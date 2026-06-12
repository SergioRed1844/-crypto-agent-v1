"""
market_context.py — unified multi-source market read (Phase 3).

Aggregates SIX public APIs into one timestamped object that is injected into the Gemini prompt
on every signal (see the market-data-pipeline skill):

  1. CoinGecko   /simple/price          → price, 24h change, volume
  2. CoinPaprika /v1/tickers/{id}        → SECOND price source (cross-validation, anti-bias #6)
  3. alternative.me /fng/?limit=30       → Fear & Greed 30-day SERIES (detect sentiment turns)
  4. CryptoPanic /v1/posts               → news headlines + votes → sentiment score (optional key)
  5. Binance public fapi                 → funding rate + open interest (leverage/squeeze risk)
  6. CoinGecko   /global                 → BTC dominance + total market cap (rotation context)

Principles (never violated): APIs only (no HTML scraping); never invent data; each source fails
independently (graceful degradation); a 5-minute TTL cache respects rate limits; if >=2 CRITICAL
sources fail the agent enters SOLO-OBSERVATION (log, do not open new trades).

The fetching (`build_context`) is kept separate from the pure aggregation (`assemble`) so the
scoring / cross-validation / degradation logic is unit-testable without network.
"""
import os
import time
import logging
import statistics
from datetime import datetime, timezone

import httpx

log = logging.getLogger("CryptoAgent")

CRYPTOPANIC_API_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "")
CACHE_TTL = int(os.environ.get("MARKET_CTX_TTL_SEC", "300"))  # 5 min default

# Assets we track, keyed by their canonical USDT pair.
ASSETS = {
    "BTCUSDT": {"coingecko": "bitcoin", "coinpaprika": "btc-bitcoin", "binance": "BTCUSDT", "key": "btc_price"},
    "ETHUSDT": {"coingecko": "ethereum", "coinpaprika": "eth-ethereum", "binance": "ETHUSDT", "key": "eth_price"},
    "SOLUSDT": {"coingecko": "solana", "coinpaprika": "sol-solana", "binance": "SOLUSDT", "key": "sol_price"},
}
# Sources whose loss degrades trust in the whole read. >=2 down → SOLO-OBSERVATION.
CRITICAL_SOURCES = ["coingecko", "coinpaprika", "fear_greed", "binance"]
PRICE_DISAGREEMENT_LIMIT = 0.01  # 1% between CoinGecko and CoinPaprika → unreliable price

_cache = {}  # pair -> (expires_at, context)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ─────────────────────────── pure aggregation (testable) ───────────────────────────
def cross_validate_prices(assets_prices: dict) -> dict:
    """
    assets_prices: {pair: {"coingecko": x|None, "coinpaprika": y|None, "binance": z|None}}
    Returns {pair: {"consensus": float, "reliable": bool, "disagreement_pct": float, "sources": [...]}}.
    Reliability is judged on the two independent primary sources (CoinGecko vs CoinPaprika);
    Binance is a tie-breaker/fallback for the consensus only.
    """
    out = {}
    for pair, src in assets_prices.items():
        vals = {k: float(v) for k, v in src.items() if v and float(v) > 0}
        consensus = statistics.median(vals.values()) if vals else 0.0
        cg, cp = vals.get("coingecko"), vals.get("coinpaprika")
        if cg and cp:
            disagreement = abs(cg - cp) / ((cg + cp) / 2)
            reliable = disagreement <= PRICE_DISAGREEMENT_LIMIT
        else:
            # Only one primary source (or none): usable but flagged as not cross-validated.
            disagreement = 0.0
            reliable = bool(vals)  # at least one price exists
        out[pair] = {"consensus": round(consensus, 6), "reliable": reliable,
                     "disagreement_pct": round(disagreement * 100, 3),
                     "sources": sorted(vals.keys())}
    return out


def fear_greed_trend(series) -> str:
    """RISING / FALLING / FLAT from the 30-day F&G series (series[0] = most recent)."""
    vals = [int(x) for x in series if str(x).strip() != ""]
    if len(vals) < 5:
        return "UNKNOWN"
    recent = statistics.mean(vals[:5])
    older = statistics.mean(vals[-5:])
    if recent - older >= 5:
        return "RISING"
    if older - recent >= 5:
        return "FALLING"
    return "FLAT"


def composite_score(fear_greed, funding, news_score, btc_24h_change) -> float:
    """
    Crowd positioning in [-100, +100]. POSITIVE = crowd over-optimistic (greed/euphoria → avoid);
    NEGATIVE = crowd over-pessimistic (fear/capitulation → potential Graham buy zone).
    Weighted mean of the available interpretable components (missing ones are skipped, weights
    renormalized).
    """
    comps, weights = [], []
    if fear_greed is not None:
        comps.append(_clamp((fear_greed - 50) * 2.0, -100, 100)); weights.append(0.40)
    if funding is not None:
        comps.append(_clamp(funding * 200000.0, -100, 100)); weights.append(0.20)
    if news_score is not None:
        comps.append(_clamp(news_score * 100.0, -100, 100)); weights.append(0.20)
    if btc_24h_change is not None:
        comps.append(_clamp(btc_24h_change * 5.0, -100, 100)); weights.append(0.20)
    if not comps:
        return 0.0
    tot = sum(weights)
    return round(sum(c * w for c, w in zip(comps, weights)) / tot, 1)


def news_sentiment(posts) -> tuple:
    """CryptoPanic posts → (score in [-1,1], n_used). Uses bullish/bearish/positive/negative votes."""
    if not posts:
        return None, 0
    pos = neg = 0
    for p in posts:
        v = p.get("votes", {}) or {}
        pos += int(v.get("positive", 0)) + int(v.get("bullish", 0))
        neg += int(v.get("negative", 0)) + int(v.get("bearish", 0))
    total = pos + neg
    if total == 0:
        return 0.0, len(posts)
    return round((pos - neg) / total, 3), len(posts)


def assemble(sources: dict, pair: str = "BTCUSDT") -> dict:
    """
    Pure aggregation: takes whatever each source returned (or None on failure) and produces the
    unified context object with composite score, data-quality flags and the SOLO-OBSERVATION
    decision. No network here — fully unit-testable.

    `sources` shape (any value may be None = that source failed):
      {
        "coingecko":  {"BTCUSDT": {"price":x,"change_24h":c}, ...} | None,
        "coinpaprika":{"BTCUSDT": {"price":y,"change_24h":c}, ...} | None,
        "binance":    {"BTCUSDT": z, ...} | None,        # spot price fallback
        "fear_greed": {"value":int,"label":str,"series":[...]} | None,
        "cryptopanic":[posts...] | None,
        "funding":    float | None,
        "open_interest": float | None,
        "global":     {"btc_dominance":d,"total_mcap_usd":m} | None,
      }
    """
    sources_ok = {
        "coingecko": sources.get("coingecko") is not None,
        "coinpaprika": sources.get("coinpaprika") is not None,
        "fear_greed": sources.get("fear_greed") is not None,
        "cryptopanic": sources.get("cryptopanic") is not None,
        "binance": sources.get("funding") is not None or sources.get("binance") is not None,
        "coingecko_global": sources.get("global") is not None,
    }

    # Per-asset prices from each source → cross-validation.
    assets_prices = {}
    for p in ASSETS:
        cg = (sources.get("coingecko") or {}).get(p, {}).get("price")
        cp = (sources.get("coinpaprika") or {}).get(p, {}).get("price")
        bn = (sources.get("binance") or {}).get(p)
        assets_prices[p] = {"coingecko": cg, "coinpaprika": cp, "binance": bn}
    prices = cross_validate_prices(assets_prices)

    # 24h change (prefer CoinGecko, fall back to CoinPaprika).
    def _chg(p):
        return ((sources.get("coingecko") or {}).get(p, {}).get("change_24h")
                if (sources.get("coingecko") or {}).get(p, {}).get("change_24h") is not None
                else (sources.get("coinpaprika") or {}).get(p, {}).get("change_24h"))
    btc_24h = _chg("BTCUSDT")

    fg = sources.get("fear_greed") or {}
    fg_value = fg.get("value")
    funding = sources.get("funding")
    news_score, news_n = news_sentiment(sources.get("cryptopanic"))

    comp = composite_score(fg_value, funding, news_score, btc_24h)

    critical_down = [s for s in CRITICAL_SOURCES if not sources_ok.get(s, False)]
    solo = len(critical_down) >= 2
    degradation = []
    if critical_down:
        degradation.append("critical sources down: " + ",".join(critical_down))
    for p, info in prices.items():
        if not info["reliable"]:
            degradation.append(f"{p} price not cross-validated (Δ{info['disagreement_pct']}%)")

    glob = sources.get("global") or {}
    ctx = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pair": pair,
        # legacy keys consumed elsewhere in server.py
        "fear_greed": fg_value if fg_value is not None else 50,
        "fear_greed_label": fg.get("label", "Neutral"),
        "btc_price": prices.get("BTCUSDT", {}).get("consensus", 0),
        "eth_price": prices.get("ETHUSDT", {}).get("consensus", 0),
        "sol_price": prices.get("SOLUSDT", {}).get("consensus", 0),
        "btc_24h_change": btc_24h if btc_24h is not None else 0,
        "btc_funding": funding if funding is not None else 0,
        # rich Phase-3 fields
        "fear_greed_trend": fear_greed_trend(fg.get("series", [])),
        "prices": prices,
        "open_interest": sources.get("open_interest"),
        "btc_dominance": glob.get("btc_dominance"),
        "total_mcap_usd": glob.get("total_mcap_usd"),
        "news_score": news_score,
        "news_count": news_n,
        "composite_score": comp,
        "sources_ok": sources_ok,
        "price_reliable": {p: prices[p]["reliable"] for p in prices},
        "critical_down": critical_down,
        "solo_observation": solo,
        "degradation": degradation,
    }
    return ctx


# ─────────────────────────── async fetchers ───────────────────────────
async def _coingecko(client):
    ids = ",".join(a["coingecko"] for a in ASSETS.values())
    r = await client.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"})
    r.raise_for_status()
    d = r.json()
    out = {}
    for pair, a in ASSETS.items():
        row = d.get(a["coingecko"], {})
        if row:
            out[pair] = {"price": row.get("usd"), "change_24h": row.get("usd_24h_change")}
    return out


async def _coinpaprika(client):
    out = {}
    for pair, a in ASSETS.items():
        r = await client.get(f"https://api.coinpaprika.com/v1/tickers/{a['coinpaprika']}")
        if r.status_code == 200:
            usd = r.json().get("quotes", {}).get("USD", {})
            out[pair] = {"price": usd.get("price"), "change_24h": usd.get("percent_change_24h")}
    return out or None


async def _binance_prices(client):
    out = {}
    for pair in ASSETS:
        r = await client.get(f"https://api.binance.com/api/v3/ticker/price?symbol={pair}")
        if r.status_code == 200:
            out[pair] = float(r.json().get("price", 0))
    return out or None


async def _fear_greed(client):
    r = await client.get("https://api.alternative.me/fng/?limit=30")
    r.raise_for_status()
    data = r.json().get("data", [])
    return {"value": int(data[0]["value"]), "label": data[0]["value_classification"],
            "series": [int(x["value"]) for x in data]}


async def _funding(client, pair="BTCUSDT"):
    r = await client.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={pair}")
    r.raise_for_status()
    return float(r.json().get("lastFundingRate", 0) or 0)


async def _open_interest(client, pair="BTCUSDT"):
    r = await client.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={pair}")
    r.raise_for_status()
    return float(r.json().get("openInterest", 0) or 0)


async def _cryptopanic(client):
    if not CRYPTOPANIC_API_KEY:
        return None
    r = await client.get("https://cryptopanic.com/api/v1/posts/",
                         params={"auth_token": CRYPTOPANIC_API_KEY, "currencies": "BTC,ETH,SOL",
                                 "kind": "news", "public": "true"})
    r.raise_for_status()
    return r.json().get("results", [])


async def _global(client):
    r = await client.get("https://api.coingecko.com/api/v3/global")
    r.raise_for_status()
    d = r.json().get("data", {})
    return {"btc_dominance": d.get("market_cap_percentage", {}).get("btc"),
            "total_mcap_usd": d.get("total_market_cap", {}).get("usd")}


async def _safe(coro, name):
    try:
        return await coro
    except Exception as e:
        log.warning(f"market_context source '{name}' failed: {e}")
        return None


async def build_context(pair: str = "BTCUSDT", funding_pair: str = "BTCUSDT") -> dict:
    """Fetch all six sources (each guarded), assemble, and cache for CACHE_TTL seconds."""
    now = time.time()
    hit = _cache.get(pair)
    if hit and hit[0] > now:
        return hit[1]

    async with httpx.AsyncClient(timeout=10) as client:
        sources = {
            "coingecko": await _safe(_coingecko(client), "coingecko"),
            "coinpaprika": await _safe(_coinpaprika(client), "coinpaprika"),
            "fear_greed": await _safe(_fear_greed(client), "fear_greed"),
            "cryptopanic": await _safe(_cryptopanic(client), "cryptopanic"),
            "funding": await _safe(_funding(client, funding_pair), "binance_funding"),
            "open_interest": await _safe(_open_interest(client, funding_pair), "binance_oi"),
            "global": await _safe(_global(client), "coingecko_global"),
        }
        # Binance spot prices only needed as a fallback when a primary price source is missing.
        if sources["coingecko"] is None or sources["coinpaprika"] is None:
            sources["binance"] = await _safe(_binance_prices(client), "binance_prices")
        else:
            sources["binance"] = None

    ctx = assemble(sources, pair=pair)
    if ctx["solo_observation"]:
        log.warning(f"SOLO-OBSERVATION: {ctx['degradation']}")
    _cache[pair] = (now + CACHE_TTL, ctx)
    return ctx


def clear_cache():
    _cache.clear()
