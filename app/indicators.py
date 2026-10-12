"""Indicadores y régimen calculados en el servidor (no dependemos solo de Pine)."""
import numpy as np
import pandas as pd


def to_df(ohlcv: list) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts")


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def trend_regime(df: pd.DataFrame) -> str:
    """Methodology 8.1 STEP_2 (sobre diario)."""
    c = df["close"]
    e21, e50, e200 = ema(c, 21), ema(c, 50), ema(c, 200)
    p, a, b, g = c.iloc[-1], e21.iloc[-1], e50.iloc[-1], e200.iloc[-1]
    rising = e21.iloc[-1] > e21.iloc[-5] and e50.iloc[-1] > e50.iloc[-5]
    falling = e21.iloc[-1] < e21.iloc[-5] and e50.iloc[-1] < e50.iloc[-5]
    if p > a > b > g and rising:
        return "STRONG_UP"
    if p < a < b < g and falling:
        return "STRONG_DOWN"
    if p > g:
        return "WEAK_UP"
    if p < g:
        return "WEAK_DOWN"
    return "RANGE"


def vol_regime(df_daily: pd.DataFrame) -> tuple[str, float]:
    """Methodology 8.1 STEP_1: vol realizada 30d anualizada."""
    r = np.log(df_daily["close"]).diff().dropna().tail(30)
    v = float(r.std() * np.sqrt(365) * 100)
    if v < 40:
        return "LOW", v
    if v < 70:
        return "NORMAL", v
    if v < 100:
        return "HIGH", v
    return "EXTREME", v


def snapshot(df: pd.DataFrame) -> dict:
    c = df["close"]
    return {
        "close": float(c.iloc[-1]),
        "ema21": float(ema(c, 21).iloc[-1]),
        "ema50": float(ema(c, 50).iloc[-1]),
        "ema200": float(ema(c, 200).iloc[-1]),
        "rsi": float(rsi(c).iloc[-1]),
        "atr": float(atr(df).iloc[-1]),
        "vol_ratio": float(df["volume"].iloc[-1] / max(df["volume"].tail(20).mean(), 1e-9)),
        "swing_low_20": float(df["low"].tail(20).min()),
        "swing_high_20": float(df["high"].tail(20).max()),
        # máximo de las 20 velas ANTERIORES (= ta.highest(high, 20)[1] en Pine)
        "prior_high_20": float(df["high"].iloc[-21:-1].max()),
        "chg_5": float(c.iloc[-1] / c.iloc[-6] - 1),
    }
