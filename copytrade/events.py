"""¿Hay información en lo que compra/vende? Exceso sobre SPY a h días hábiles por operación (pre-registro).

Base (a): cierre del día de la operación. Base (b): cierre del primer día hábil después de la publicación.
Ventas con signo invertido (positivo = lo vendido luego lo hizo peor que el índice). IC 95% por bootstrap
agrupado por la fecha base (las operaciones del mismo día no son independientes).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

H = (21, 63, 126)


def excess(t: pd.DataFrame, px: pd.DataFrame, base_col: str, h: int) -> pd.DataFrame:
    cal = px.index
    pos = {d: i for i, d in enumerate(cal)}
    spy = px["SPY"]
    rows = []
    for r in t.itertuples():
        b = getattr(r, base_col)
        if b is None or pd.isna(b) or b not in pos:
            continue
        i = pos[b]
        if i + h >= len(cal):
            continue
        p0, p1 = px.at[b, r.ticker], px.iat[i + h, px.columns.get_loc(r.ticker)]
        if not (p0 > 0 and p1 > 0):
            continue
        e = p1 / p0 - spy.iat[i + h] / spy.iat[i]
        sign = 1.0 if r.type == "Purchase" else -1.0
        rows.append((b, r.type, sign * e, r.mid, r.ticker))
    return pd.DataFrame(rows, columns=["base", "type", "ex", "w", "ticker"])


def cluster_boot(df: pd.DataFrame, weighted: bool, n: int = 2000, seed: int = 7) -> tuple[float, float, float, int]:
    if df.empty:
        return (float("nan"),) * 3 + (0,)
    g = df.groupby("base")
    sums = g.apply(lambda x: ((x.ex * x.w).sum() if weighted else x.ex.sum()), include_groups=False).values
    wts = g.apply(lambda x: (x.w.sum() if weighted else len(x)), include_groups=False).values
    est = sums.sum() / wts.sum()
    rng = np.random.default_rng(seed)
    k = len(sums)
    idx = rng.integers(0, k, size=(n, k))
    bs = sums[idx].sum(axis=1) / wts[idx].sum(axis=1)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return float(est), float(lo), float(hi), int(k)


def study(t: pd.DataFrame, px: pd.DataFrame) -> pd.DataFrame:
    t = t[t.cls.isin(["equity", "fund"]) & t.price_ok]
    out = []
    for base_col, label in (("xE", "desde la operación"), ("xR", "desde la publicación")):
        for h in H:
            ex = excess(t, px, base_col, h)
            for side in ("Purchase", "Sale"):
                d = ex[ex.type == side]
                for weighted in (True, False):
                    est, lo, hi, k = cluster_boot(d, weighted)
                    out.append({"base": label, "h": h, "side": "compras" if side == "Purchase" else "ventas",
                                "peso": "por monto" if weighted else "por operación", "n": len(d), "clusters": k,
                                "exceso": est, "ic_lo": lo, "ic_hi": hi,
                                "acierto": float((d.ex > 0).mean()) if len(d) else float("nan")})
    return pd.DataFrame(out)


def calendar_time(t: pd.DataFrame, px: pd.DataFrame, base_col: str, h: int, side: str = "Purchase",
                  lags: int = 10) -> dict:
    """Prueba en tiempo calendario (cambio declarado 25-oct-2026 tras la revisión independiente): cada día, la
    cartera de las operaciones cuya fecha base cayó en los h días hábiles previos, ponderada por monto y con
    deriva de precio (comprar y mantener h días), menos SPY. Media diaria anualizada y t de Newey-West. Las
    ventas entran con signo invertido. Evita tratar como independientes cientos de operaciones del mismo lote."""
    t = t[t.cls.isin(["equity", "fund"]) & t.price_ok & (t.type == side)]
    cal = px.index
    pos = {d: i for i, d in enumerate(cal)}
    rets = px.pct_change(fill_method=None)
    spy = rets["SPY"]
    n = len(cal)
    num = np.zeros(n)
    den = np.zeros(n)
    arr = {c: px[c].values for c in set(t.ticker)}
    for r in t.itertuples():
        b = getattr(r, base_col)
        if b is None or pd.isna(b) or b not in pos:
            continue
        i0 = pos[b]
        i1 = min(n - 1, i0 + h)
        if i1 <= i0:
            continue
        p = arr[r.ticker]
        base = p[i0]
        if not base > 0:
            continue
        seg = slice(i0 + 1, i1 + 1)
        wprev = r.mid * p[i0:i1] / base                    # valor al cierre previo de cada día
        rr = p[i0 + 1:i1 + 1] / p[i0:i1] - 1
        ok = np.isfinite(wprev) & np.isfinite(rr)
        num[seg] += np.where(ok, wprev * rr, 0.0)
        den[seg] += np.where(ok, wprev, 0.0)
    act = den > 0
    if act.sum() < 20:
        return {"days": int(act.sum()), "ann": float("nan"), "t": float("nan"), "per_h": float("nan")}
    port = num[act] / den[act]
    ex = port - spy.values[act]
    ex = np.nan_to_num(ex)
    if side == "Sale":
        ex = -ex
    m = ex.mean()
    # t de Newey-West para la media (regresión sobre constante)
    e = ex - m
    S = (e * e).sum()
    for L in range(1, lags + 1):
        S += 2 * (1 - L / (lags + 1)) * (e[L:] * e[:-L]).sum()
    se_m = np.sqrt(S) / len(ex)
    return {"days": int(act.sum()), "ann": float(m * 252), "t": float(m / se_m) if se_m > 0 else 0.0,
            "per_h": float(m * h), "lo_h": float((m - 1.96 * se_m) * h), "hi_h": float((m + 1.96 * se_m) * h),
            "first": str(cal[np.argmax(act)].date())}


def calendar_study(t: pd.DataFrame, px: pd.DataFrame) -> pd.DataFrame:
    out = []
    for base_col, label in (("xE", "desde la operación"), ("xR", "desde la publicación")):
        for h in H:
            for side in ("Purchase", "Sale"):
                d = calendar_time(t, px, base_col, h, side)
                out.append({"base": label, "h": h, "side": "compras" if side == "Purchase" else "ventas", **d})
    return pd.DataFrame(out)
