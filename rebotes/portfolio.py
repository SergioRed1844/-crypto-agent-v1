"""Cartera de hasta MAX_POS posiciones con la regla fija (toma +30%, stop −15%, 21 velas) y costos.

Cada operación ya trae su vela de entrada/salida y su retorno neto (signals.outcomes). La cartera solo decide cuáles
caben: entra por fecha; en empate, la de mayor caída desde su máximo; no repite una acción abierta; 1/MAX_POS del
valor al entrar. El valor diario se marca con el cierre menos el costo de vender.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def simulate(trades: pd.DataFrame, close: np.ndarray, dates: pd.DatetimeIndex, start_i: int, end_i: int
             ) -> dict:
    tr = trades[(trades.entry_i >= start_i) & (trades.entry_i <= end_i)].copy()
    tr = tr.sort_values(["entry_i", "dd_at"], kind="stable")
    by_day: dict[int, list] = {}
    for r in tr.itertuples():
        by_day.setdefault(int(r.entry_i), []).append(r)
    cash = C.CAPITAL
    open_pos: list[dict] = []
    nav = np.full(end_i - start_i + 1, np.nan)
    taken = []
    for t in range(start_i, end_i + 1):
        # salidas de ayer o antes: el lugar se libera hasta hoy (una salida de hoy ocurre durante el día)
        still = []
        for p in open_pos:
            if p["exit_i"] < t:
                cash += p["alloc"] * (1 + p["net"])
            else:
                still.append(p)
        open_pos = still
        # entradas al open de hoy
        held = {p["j"] for p in open_pos}
        for r in by_day.get(t, []):
            if len(open_pos) >= C.MAX_POS or r.j in held:
                continue
            eq = cash + sum(p["alloc"] * _mtm(p, close, t - 1) for p in open_pos)   # valor al cierre previo
            alloc = min(cash, eq / C.MAX_POS)
            if alloc <= 0:
                break
            cash -= alloc
            open_pos.append({"j": r.j, "alloc": alloc, "net": r.net, "exit_i": int(r.exit_i), "entry": r.entry,
                             "entry_i": t})
            held.add(r.j)
            taken.append(r)
        nav[t - start_i] = cash + sum(p["alloc"] * ((1 + p["net"]) if p["exit_i"] <= t else _mtm(p, close, t))
                                      for p in open_pos)
    s = pd.Series(nav, index=dates[start_i:end_i + 1])
    return {"nav": s, "taken": pd.DataFrame([r._asdict() for r in taken]) if taken else pd.DataFrame()}


def _mtm(p: dict, close: np.ndarray, t: int) -> float:
    """Valor relativo de la posición si se vendiera al cierre de t, ya con el costo de salida (la de entrada ya está
    en `net`). Si ese día no hay cierre, vale el último cierre conocido."""
    if t < p["entry_i"]:
        return 1.0
    col = close[p["entry_i"]:t + 1, p["j"]]
    fin = np.flatnonzero(np.isfinite(col) & (col > 0))
    c = float(col[fin[-1]]) if len(fin) else p["entry"]
    return c / p["entry"] * (1 - C.COST_SIDE) / (1 + C.COST_SIDE)


def monthly(nav: pd.Series) -> pd.Series:
    m = nav.resample("ME").last()
    first = nav.iloc[0]
    return m.pct_change().fillna(m.iloc[0] / first - 1)


def stats(nav: pd.Series) -> dict:
    m = monthly(nav)
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    dd = nav / nav.cummax() - 1
    return {"final": float(nav.iloc[-1]), "cagr": float((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1),
            "maxdd": float(dd.min()), "months": int(len(m)), "pct_m30": float((m >= 0.30).mean()),
            "pct_m10": float((m >= 0.10).mean()), "pct_m_neg20": float((m <= -0.20).mean()),
            "pct_m_pos": float((m > 0).mean()), "median_m": float(m.median()), "best_m": float(m.max()),
            "worst_m": float(m.min())}
