"""Recolección de contexto: precios multi-TF de Binance, derivados, sentimiento, noticias, calendario macro.
Nada de LLM aquí: datos crudos y deterministas."""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np

from . import config, indicators as ind

log = logging.getLogger("data")
_spot = None
_fut = None


def spot():
    global _spot
    if _spot is None:
        import ccxt
        _spot = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    return _spot


def futures():
    global _fut
    if _fut is None:
        import ccxt
        _fut = ccxt.binanceusdm({"enableRateLimit": True})
    return _fut


def ccxt_symbol(pair: str) -> str:
    pair = pair.upper().replace("/", "")
    for q in ("USDT", "USDC", "FDUSD"):
        if pair.endswith(q):
            return f"{pair[:-len(q)]}/{q}"
    raise ValueError(f"Par no soportado: {pair}")


# ── Mock para pruebas sin red ─────────────────────────────────
def _mock_ohlcv(n=300, start=60000.0, drift=0.002, seed=7):
    rng = np.random.default_rng(seed)
    ts0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    out, p = [], start
    for i in range(n):
        o = p
        p = p * (1 + drift + rng.normal(0, float(os.environ.get("MOCK_NOISE", "0.01"))))
        hi, lo = max(o, p) * 1.004, min(o, p) * 0.996
        out.append([ts0 + i * 3600_000, o, hi, lo, p, float(rng.uniform(100, 200))])
    return out


TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def fetch_ohlcv(pair: str, tf: str, limit: int = 300, since: int | None = None, closed_only: bool = True):
    """closed_only=True descarta la vela en formación: los indicadores deben ver lo mismo que Pine
    al cierre de vela (barstate.isconfirmed). Sin esto el volumen de la vela recién abierta es ~0
    y las EMAs/RSI se mueven tick a tick."""
    if config.DATA_MODE == "mock":
        return _mock_ohlcv(limit, drift={"1d": 0.003, "4h": 0.0015, "1h": 0.0005}.get(tf, 0.001))
    rows = spot().fetch_ohlcv(ccxt_symbol(pair), tf, since=since, limit=limit + 1)
    if closed_only and rows:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows = [r for r in rows if r[0] + TF_MS[tf] <= now_ms]
    return rows[-limit:]


def last_price(pair: str) -> float:
    if config.DATA_MODE == "mock":
        return float(fetch_ohlcv(pair, "1h", 300)[-1][4])
    return float(spot().fetch_ticker(ccxt_symbol(pair))["last"])


def fetch_derivatives(pair: str) -> dict:
    if config.DATA_MODE == "mock":
        return {"funding_rate": 0.0001, "open_interest": 1.0e9}
    out = {"funding_rate": None, "open_interest": None}
    sym = ccxt_symbol(pair) + ":USDT"
    try:
        out["funding_rate"] = float(futures().fetch_funding_rate(sym)["fundingRate"])
    except Exception as e:
        log.warning(f"funding: {e}")
    try:
        out["open_interest"] = float(futures().fetch_open_interest(sym).get("openInterestValue") or 0)
    except Exception as e:
        log.warning(f"OI: {e}")
    return out


async def fetch_fear_greed() -> dict:
    if config.DATA_MODE == "mock":
        return {"value": 55, "label": "Greed"}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            d = (await c.get("https://api.alternative.me/fng/?limit=1")).json()["data"][0]
            return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception as e:
        log.warning(f"F&G: {e}")
        return {"value": None, "label": "unknown"}


async def fetch_news(symbol: str) -> list[dict]:
    """Titulares recientes (CryptoPanic v2 si la key sirve, si no GDELT). Solo titulares: el LLM no navega."""
    if config.DATA_MODE == "mock":
        return [{"title": f"{symbol} ETF inflows continue for third week", "source": "mock"}]
    from .context import news as cnews
    cp = await asyncio.to_thread(cnews.cryptopanic, "hot", symbol, 1)
    items = [{"title": i["title"], "source": i["source"], "published_at": i["published_at"]} for i in cp["items"][:12]]
    if not items:
        arts = await asyncio.to_thread(cnews.gdelt, f'"{symbol}" crypto', "1d", 12)
        items = [{"title": a["title"], "source": "GDELT", "published_at": a["published_at"]} for a in arts]
    return items


def macro_events_next(hours: int) -> list[dict]:
    """Calendario macro (CPI, FOMC, NFP) desde macro_calendar.json, que se actualiza a mano cada mes.
    Formato: [{"event":"FOMC","utc":"2026-10-28T18:00:00Z"}]"""
    path = os.environ.get("MACRO_CALENDAR", "macro_calendar.json")
    try:
        with open(path) as f:
            events = json.load(f)
    except FileNotFoundError:
        return []
    now = datetime.now(timezone.utc)
    lim = now + timedelta(hours=hours)
    out = []
    for e in events:
        try:
            t = datetime.fromisoformat(e["utc"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            log.warning(f"macro_calendar: entrada inválida {e}")
            continue
        if now - timedelta(hours=1) <= t <= lim:
            out.append(e)
    return out


async def gather_market(pair: str) -> dict:
    # ccxt es síncrono: en hilos para no bloquear el event loop (si se bloquea, otro webhook pasa de 3 s)
    t = asyncio.to_thread
    d1_raw, h4_raw, h1_raw, deriv, px = await asyncio.gather(
        t(fetch_ohlcv, pair, "1d", 300), t(fetch_ohlcv, pair, "4h", 300), t(fetch_ohlcv, pair, "1h", 300),
        t(fetch_derivatives, pair), t(last_price, pair))
    d1, h4, h1 = ind.to_df(d1_raw), ind.to_df(h4_raw), ind.to_df(h1_raw)
    btc_d1 = d1 if pair.startswith("BTC") else ind.to_df(await t(fetch_ohlcv, "BTCUSDT", "1d", 300))
    vol_reg, vol_ann = ind.vol_regime(d1)
    btc_trend = ind.trend_regime(btc_d1)
    base = pair.replace("USDT", "").replace("USDC", "")
    return {
        "pair": pair,
        "price": px,  # precio vivo (ticker) para frescura y sizing; indicadores solo con velas cerradas
        "tf": {"1d": ind.snapshot(d1), "4h": ind.snapshot(h4), "1h": ind.snapshot(h1)},
        "trend_regime_1d": ind.trend_regime(d1),
        "vol_regime": vol_reg,
        "vol_annualized_pct": round(vol_ann, 1),
        "btc_trend_1d": btc_trend,
        "btc_regime": {"STRONG_UP": "GREEN", "WEAK_UP": "GREEN", "RANGE": "YELLOW",
                       "WEAK_DOWN": "YELLOW", "STRONG_DOWN": "RED"}[btc_trend],
        "derivatives": deriv,
        "fear_greed": await fetch_fear_greed(),
        "news": await fetch_news(base),
        "macro_next": macro_events_next(config.RISK["macro_blackout_hours"]),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
