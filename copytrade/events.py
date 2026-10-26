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
