"""Variables de mercado (independientes cuantitativas y moderadoras) para el contexto.

Gratis y sin key: Fear & Greed (alternative.me), oferta de stablecoins (DefiLlama), Polymarket (probabilidades
ex-ante de eventos). Con FRED_API_KEY (gratis): dólar amplio, VIX, 10 años, Nasdaq. Todo es opcional: si una
fuente falla, su variable queda en None y la señal la ignora (nunca se inventa un valor).
"""
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx

log = logging.getLogger("macro")
UA = {"User-Agent": "cryptoagent-context/4.2"}
FRED_SERIES = {"dxy": "DTWEXBGS", "vix": "VIXCLS", "us10y": "DGS10", "nasdaq": "NASDAQCOM"}


def _get(url, **kw):
    r = httpx.get(url, timeout=30, headers=UA, **kw)
    r.raise_for_status()
    return r.json()


def fear_greed(limit: int = 31) -> dict:
    try:
        d = _get("https://api.alternative.me/fng/", params={"limit": limit, "format": "json"})["data"]
        vals = [int(x["value"]) for x in d]
        return {"value": vals[0], "label": d[0]["value_classification"], "avg_7d": round(sum(vals[:7]) / 7, 1),
                "avg_30d": round(sum(vals[:30]) / min(30, len(vals)), 1)}
    except Exception as e:
        log.warning(f"F&G: {e}")
        return {"value": None}


def fear_greed_history() -> dict[str, int]:
    """Histórico completo (desde 2018-02) para backtests: {YYYY-MM-DD: valor}."""
    d = _get("https://api.alternative.me/fng/", params={"limit": 0, "format": "json"})["data"]
    return {datetime.fromtimestamp(int(x["timestamp"]), timezone.utc).date().isoformat(): int(x["value"]) for x in d}


def stablecoins() -> dict:
    try:
        rows = _get("https://stablecoins.llama.fi/stablecoincharts/all")
        s = [(int(r["date"]), float((r.get("totalCirculatingUSD") or {}).get("peggedUSD") or 0)) for r in rows]
        s = [x for x in s if x[1] > 0]
        last_t, last = s[-1]
        def ago(days):
            t = last_t - days * 86400
            return min(s, key=lambda x: abs(x[0] - t))[1]
        return {"total_usd": round(last), "chg_7d_pct": round((last / ago(7) - 1) * 100, 2),
                "chg_30d_pct": round((last / ago(30) - 1) * 100, 2)}
    except Exception as e:
        log.warning(f"DefiLlama: {e}")
        return {"total_usd": None}


def fred(series: str, days: int = 90) -> list[tuple[str, float]]:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        return []
    start = (date.today() - timedelta(days=days)).isoformat()
    try:
        j = _get("https://api.stlouisfed.org/fred/series/observations",
                 params={"series_id": series, "api_key": key, "file_type": "json", "observation_start": start})
        return [(o["date"], float(o["value"])) for o in j.get("observations", []) if o["value"] not in (".", "")]
    except Exception as e:
        log.warning(f"FRED {series}: {type(e).__name__}")  # nunca imprime la URL (lleva la key)
        return []


def _chg(obs, n=20, pct=True):
    if len(obs) <= n:
        return None
    a, b = obs[-n - 1][1], obs[-1][1]
    return round((b / a - 1) * 100, 2) if pct else round((b - a) * 100, 1)


def fred_moderators() -> dict:
    if not os.environ.get("FRED_API_KEY"):
        return {"status": "sin FRED_API_KEY"}
    o = {k: fred(s) for k, s in FRED_SERIES.items()}
    return {"status": "ok", "dxy_20d_pct": _chg(o["dxy"]), "vix": o["vix"][-1][1] if o["vix"] else None,
            "us10y_20d_bps": _chg(o["us10y"], pct=False), "nasdaq_20d_pct": _chg(o["nasdaq"]),
            "as_of": {k: (v[-1][0] if v else None) for k, v in o.items()}}


def polymarket_prob(url_or_slug: str) -> dict | None:
    """Probabilidad del 'Sí' de un mercado de Polymarket (para elecciones y eventos binarios)."""
    if not url_or_slug:
        return None
    slug = url_or_slug.rstrip("/").split("/")[-1].split("?")[0]
    try:
        m = _get(f"https://gamma-api.polymarket.com/markets/slug/{slug}")
    except Exception:
        try:
            ev = _get(f"https://gamma-api.polymarket.com/events/slug/{slug}")
            m = max(ev.get("markets", []), key=lambda x: float(x.get("volume") or 0))
        except Exception as e:
            log.warning(f"Polymarket {slug}: {e}")
            return None
    try:
        prices = json.loads(m.get("outcomePrices") or "[]")
        outs = json.loads(m.get("outcomes") or "[]")
        return {"question": m.get("question"), "outcomes": dict(zip(outs, [float(p) for p in prices])),
                "volume": float(m.get("volume") or 0), "slug": slug}
    except Exception:
        return None


def snapshot(calendar: list[dict] | None = None) -> dict:
    out = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "fear_greed": fear_greed(), "stablecoins": stablecoins(), "fred": fred_moderators(), "polymarket": {}}
    for e in (calendar or []):
        if e.get("prediction_market_url") and e["utc"] >= out["generated_utc"] and e["prior_tier"] >= 3:
            p = polymarket_prob(e["prediction_market_url"])
            if p:
                out["polymarket"][e["id"]] = p
    return out
