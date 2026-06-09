"""
valuation.py — "Mr. Market" behavioral valuation (Benjamin Graham logic).

Graham's Intelligent Investor: the market is a manic-depressive partner. The crowd
under/over-estimates prices; the disciplined operator buys what's underestimated (fear,
capitulation) and avoids/sells what's overestimated (greed, euphoria).

Crypto has no earnings/book value, so we approximate "intrinsic value" with the statistical
mean and crowd-sentiment extremes. This is mean-reversion + contrarian sentiment, NOT literal
value investing — an underestimated asset can get more underestimated. So the output is a BIAS,
bounded by the bot's existing risk controls and trend regime, never a blind override.

Reads public market data (Binance klines + funding + Fear&Greed), builds behavioral features,
clusters recent states (KMeans), and outputs a mispricing score in [-1, +1]:
  -1  = deeply underestimated by the crowd  -> buy zone
  +1  = wildly overestimated (euphoria)     -> sell / avoid buying
"""
import os
import logging
import numpy as np
import httpx

log = logging.getLogger("CryptoAgent")

INTERVAL = os.environ.get("MRMARKET_INTERVAL", "4h")
LOOKBACK = int(os.environ.get("MRMARKET_LOOKBACK", "20"))
KLINES_LIMIT = 200
N_CLUSTERS = 5
_CLUSTER_NAMES = ["capitulation", "accumulation", "neutral", "markup", "euphoria"]


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _rsi(closes, period=14):
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


async def fetch_klines(pair, interval=INTERVAL, limit=KLINES_LIMIT):
    """Public OHLCV candles from Binance (no API key needed). Returns raw kline arrays."""
    symbol = pair.upper().replace("/", "")
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        log.warning(f"fetch_klines {symbol} failed: {e}")
    return []


async def fetch_funding(pair):
    """Perp funding rate: positive = crowd over-leveraged long (greed), negative = fear."""
    symbol = pair.upper().replace("/", "")
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url)
            if r.status_code == 200:
                return float(r.json().get("lastFundingRate", 0) or 0)
    except Exception:
        pass
    return 0.0


def compute_features(closes, volumes, fear_greed, funding):
    closes = np.asarray(closes, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    n = min(LOOKBACK, len(closes))
    window = closes[-n:]
    mean = window.mean()
    std = window.std() or 1e-9
    price_z = float((closes[-1] - mean) / std)
    vmean = volumes[-n:].mean() or 1e-9
    vol_ratio = float(volumes[-1] / vmean)
    rsi = _rsi(closes)
    hi = window.max()
    lo = window.min()
    drawdown_from_high = float((closes[-1] - hi) / hi) if hi else 0.0
    rally_from_low = float((closes[-1] - lo) / lo) if lo else 0.0
    ret = float((closes[-1] - closes[-2]) / closes[-2]) if len(closes) > 1 and closes[-2] else 0.0
    return {
        "price_zscore": round(price_z, 3),
        "vol_ratio": round(vol_ratio, 3),
        "rsi": round(rsi, 1),
        "fear_greed": fear_greed,
        "funding": round(funding, 6),
        "drawdown_from_high": round(drawdown_from_high, 4),
        "rally_from_low": round(rally_from_low, 4),
        "last_return": round(ret, 4),
    }


def mispricing_score(f):
    """
    Composite of interpretable behavioral signals, each in [-1,+1].
    Negative = crowd UNDER-estimates (buy); positive = crowd OVER-estimates (sell/avoid).
    """
    z = _clamp(f["price_zscore"] / 2.0)              # price stretch above/below mean
    rsi = _clamp((f["rsi"] - 50) / 30.0)             # overbought (+) / oversold (-)
    fg = _clamp((f["fear_greed"] - 50) / 50.0)       # greed (+) / fear (-)
    fund = _clamp(f["funding"] * 2000.0)             # +0.0005 funding ~ +1.0 (long-crowded)
    vol_amp = _clamp(f["vol_ratio"] - 1.0)           # above-average activity amplifies emotion
    direction = 1.0 if f["last_return"] >= 0 else -1.0
    vol_emotion = _clamp(vol_amp * direction)        # up+vol = greed, down+vol = panic
    score = 0.30 * z + 0.25 * rsi + 0.25 * fg + 0.10 * fund + 0.10 * vol_emotion
    return round(_clamp(score), 3)


def state_from_score(s):
    if s <= -0.5:
        return "DEEPLY_UNDERVALUED"
    if s <= -0.2:
        return "UNDERVALUED"
    if s < 0.2:
        return "FAIR"
    if s < 0.5:
        return "OVERVALUED"
    return "EUPHORIC"


def behavioral_cluster(closes, volumes):
    """
    KMeans over recent per-candle behavioral features -> the cluster the CURRENT candle is in,
    relabeled by centroid price-zscore so it maps onto the under/over-estimation spectrum.
    """
    try:
        from sklearn.cluster import KMeans
        closes = np.asarray(closes, dtype=float)
        volumes = np.asarray(volumes, dtype=float)
        m = min(120, len(closes) - LOOKBACK - 1)
        if m < N_CLUSTERS * 3:
            return {"cluster": -1, "label": "n/a"}
        rows = []
        for i in range(len(closes) - m, len(closes)):
            w = closes[i - LOOKBACK:i]
            std = w.std() or 1e-9
            pz = (closes[i] - w.mean()) / std
            vr = volumes[i] / (volumes[i - LOOKBACK:i].mean() or 1e-9)
            rsi = _rsi(closes[:i + 1])
            ret = (closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] else 0
            rows.append([pz, vr, (rsi - 50) / 50.0, ret * 100])
        X = np.array(rows)
        km = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10).fit(X)
        current = int(km.labels_[-1])
        order = np.argsort(km.cluster_centers_[:, 0])  # rank by price-zscore (low = undervalued)
        rank = {int(c): i for i, c in enumerate(order)}
        label = _CLUSTER_NAMES[rank[current]]
        return {"cluster": current, "label": label}
    except Exception as e:
        log.warning(f"behavioral clustering failed: {e}")
        return {"cluster": -1, "label": "n/a"}


def analyze_sync(closes, volumes, fear_greed, funding):
    """Pure (no I/O) analysis — handy for tests and reuse."""
    f = compute_features(closes, volumes, fear_greed, funding)
    score = mispricing_score(f)
    state = state_from_score(score)
    clu = behavioral_cluster(closes, volumes)
    bias = ("crowd UNDER-estimates → buy bias" if score <= -0.2 else
            "crowd OVER-estimates → avoid/sell bias" if score >= 0.2 else
            "no behavioral edge")
    rationale = (f"z={f['price_zscore']} rsi={f['rsi']} F&G={fear_greed} "
                 f"fund={funding:.4f} vol×{f['vol_ratio']} → {bias}")
    return {"valuation_state": state, "mispricing_score": score,
            "cluster": clu["label"], "cluster_id": clu["cluster"],
            "rationale": rationale, "features": f}


async def analyze(pair, fear_greed=50):
    """Fetch market data and produce the Mr. Market read for `pair`."""
    klines = await fetch_klines(pair)
    if not klines or len(klines) < LOOKBACK + 2:
        return {"valuation_state": "FAIR", "mispricing_score": 0.0, "cluster": "n/a",
                "cluster_id": -1, "rationale": "insufficient market data", "features": {}}
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    funding = await fetch_funding(pair)
    return analyze_sync(closes, volumes, fear_greed, funding)
