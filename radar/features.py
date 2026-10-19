"""Indicadores diarios vectorizados (solo información disponible al cierre de cada barra: sin mirar al futuro)."""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv


def log_ret(close: np.ndarray) -> np.ndarray:
    r = np.full(len(close), np.nan)
    r[1:] = np.log(close[1:] / close[:-1])
    return r


def pct_change(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[k:] / x[:-k] - 1
    return out


def roll_mean(x: np.ndarray, w: int, shift: int = 0) -> np.ndarray:
    """Media móvil de x[t-w+1-shift .. t-shift]; NaN hasta tener w datos válidos."""
    out = np.full(len(x), np.nan)
    if len(x) < w + shift:
        return out
    v = swv(x, w)
    m = np.nanmean(v, axis=1) if np.isnan(x).any() else v.mean(axis=1)
    cnt = (~np.isnan(v)).sum(axis=1)
    m[cnt < max(2, int(0.8 * w))] = np.nan
    out[w - 1 + shift:] = m[: len(m) - shift] if shift else m
    return out


def roll_std(x: np.ndarray, w: int, shift: int = 1) -> np.ndarray:
    """Desviación estándar de x en la ventana previa (shift=1 excluye el día t: el choque no infla su propia σ)."""
    out = np.full(len(x), np.nan)
    if len(x) < w + shift:
        return out
    v = swv(x, w)
    with np.errstate(all="ignore"):
        s = np.nanstd(v, axis=1, ddof=1)
    cnt = (~np.isnan(v)).sum(axis=1)
    s[cnt < max(2, int(0.8 * w))] = np.nan
    out[w - 1 + shift:] = s[: len(s) - shift] if shift else s
    return out


def roll_max(x: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) == 0:
        return out
    # ventana creciente al inicio (máximo desde el inicio) para no perder los primeros años
    head = np.maximum.accumulate(x[: min(w, len(x))])
    out[: len(head)] = head
    if len(x) >= w:
        out[w - 1:] = swv(x, w).max(axis=1)
    return out


def rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    """RSI de Wilder."""
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return out
    d = np.diff(close)
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = up[:n].mean(), dn[:n].mean()
    for i in range(n, len(d)):
        au = (au * (n - 1) + up[i]) / n
        ad = (ad * (n - 1) + dn[i]) / n
        out[i + 1] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def zscore_prev(x: np.ndarray, w: int) -> np.ndarray:
    """z de x[t] contra la media/σ de x[t-w .. t-1]."""
    mu = roll_mean(x, w, shift=1)
    sd = roll_std(x, w, shift=1)
    with np.errstate(all="ignore"):
        return (x - mu) / sd


def align(dates: list[str], mapping: dict[str, float], ffill_days: int = 0) -> np.ndarray:
    """Valores de un dict fecha→valor alineados a `dates`. ffill_days>0 rellena huecos (fines de semana)."""
    out = np.full(len(dates), np.nan)
    last, last_i = np.nan, -10**9
    for i, d in enumerate(dates):
        v = mapping.get(d)
        if v is not None and np.isfinite(v):
            out[i] = v
            last, last_i = v, i
        elif ffill_days and i - last_i <= ffill_days:
            out[i] = last
    return out


def align_series(dates: list[str], s_dates: list[str], values: np.ndarray, ffill_days: int = 4) -> np.ndarray:
    return align(dates, dict(zip(s_dates, values.tolist())), ffill_days)
