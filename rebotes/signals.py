"""Elegibilidad, setups, muestra base y resultados por disparo (todo vectorizado sobre el panel T × N).

Convención: la señal se evalúa con datos hasta el cierre del día t; la entrada es al open de t+1; la tenencia son las
velas t+1 … t+HOLD. Nada usa datos posteriores a t para decidir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def _df(a: np.ndarray, dates, tickers) -> pd.DataFrame:
    return pd.DataFrame(a, index=dates, columns=tickers)


def features(P: dict) -> dict[str, pd.DataFrame]:
    d, t = P["dates"], P["tickers"]
    c = _df(P["Close"], d, t)
    v = _df(P["Volume"], d, t)
    nbars = c.notna().cumsum()
    dollar = (c * v).rolling(20, min_periods=15).median()
    hi252 = c.rolling(252, min_periods=200).max()
    vmed50 = v.shift(1).rolling(50, min_periods=40).median()
    elig = (c >= C.MIN_PRICE) & (dollar >= C.MIN_DOLLAR_VOL) & (nbars >= C.MIN_BARS)
    return {"close": c, "vol": v, "elig": elig, "dd": c / hi252 - 1, "dd_prev": c.shift(1) / hi252.shift(1) - 1,
            "r1": c / c.shift(1) - 1, "r10": c / c.shift(10) - 1, "vrel": v / vmed50,
            "brk": c > c.shift(1).rolling(C.SETUPS["CAIDA_GIRO"]["breakout"]).max(),
            "brk_prev": c.shift(1) > c.shift(2).rolling(C.SETUPS["CAIDA_GIRO"]["breakout"]).max()}


def raw_setup(name: str, F: dict) -> pd.DataFrame:
    s = C.SETUPS[name]
    if name == "CAIDA_GIRO":
        m = (F["dd"] <= s["dd"]) & F["brk"] & ~F["brk_prev"]
    elif name == "CAPITULACION":
        m = (F["r10"] <= s["r10"]) & (F["vrel"] >= s["vol_mult"])
    elif name == "CATALIZADOR":
        m = (F["r1"] >= s["r1"]) & (F["vrel"] >= s["vol_mult"]) & (F["dd_prev"] <= s["dd_prev"])
    else:
        raise KeyError(name)
    return m & F["elig"]


def cooldown(mask: pd.DataFrame, bars: int) -> list[tuple[int, int]]:
    """(fila t, columna j) de los disparos, dejando `bars` velas de pausa por acción."""
    out = []
    a = mask.to_numpy(dtype=bool)
    for j in range(a.shape[1]):
        last = -10**9
        for i in np.flatnonzero(a[:, j]):
            if i - last >= bars:
                out.append((int(i), j))
                last = i
    return out


def base_sample(F: dict) -> list[tuple[int, int]]:
    a = F["elig"].to_numpy(dtype=bool)
    T, N = a.shape
    rows = np.arange(T)[:, None]
    cols = np.arange(N)[None, :]
    pick = a & (((rows + cols * 7) % C.BASE_EVERY) == 0)
    i, j = np.nonzero(pick)
    return list(zip(i.tolist(), j.tolist()))


def outcomes(P: dict, ev: list[tuple[int, int]], batch: int = 150_000) -> pd.DataFrame:
    """Resultados de cada disparo: entrada al open de t+1; 21 velas; regla TP/SL/tiempo con costos."""
    T = P["Open"].shape[0]
    ev = [(i, j) for i, j in ev if i + C.HOLD < T]       # la última vela de la tenencia (t+HOLD) ya existe
    if not ev:
        return pd.DataFrame()
    if len(ev) > batch:
        return pd.concat([_outcomes(P, ev[k:k + batch]) for k in range(0, len(ev), batch)], ignore_index=True)
    return _outcomes(P, ev)


def _outcomes(P: dict, ev: list[tuple[int, int]]) -> pd.DataFrame:
    O, H, L, Cl = P["Open"], P["High"], P["Low"], P["Close"]
    ii = np.array([e[0] for e in ev])
    jj = np.array([e[1] for e in ev])
    k = np.arange(1, C.HOLD + 1)
    rows = ii[:, None] + k[None, :]                    # t+1 … t+HOLD
    cols = jj[:, None]
    o, h, lo, cl = O[rows, cols], H[rows, cols], L[rows, cols], Cl[rows, cols]
    entry = o[:, 0]
    ok = np.isfinite(entry) & (entry > 0) & np.isfinite(cl).all(axis=1) & np.isfinite(h).all(axis=1) \
        & np.isfinite(lo).all(axis=1)
    hi_r = np.nanmax(h, axis=1) / entry - 1
    lo_r = np.nanmin(lo, axis=1) / entry - 1
    ret21 = cl[:, -1] / entry - 1
    tp, sl = entry * (1 + C.TP), entry * (1 + C.SL)
    hit_tp = h >= tp[:, None]
    hit_sl = lo <= sl[:, None]
    BIG = C.HOLD + 5
    f_tp = np.where(hit_tp.any(axis=1), hit_tp.argmax(axis=1), BIG)
    f_sl = np.where(hit_sl.any(axis=1), hit_sl.argmax(axis=1), BIG)
    exit_px = cl[:, -1].copy()
    exit_k = np.full(len(ev), C.HOLD - 1)
    reason = np.array(["tiempo"] * len(ev), dtype=object)
    sl_first = (f_sl <= f_tp) & (f_sl < BIG)               # empate en el mismo día → stop
    tp_first = (f_tp < f_sl) & (f_tp < BIG)
    idx = np.arange(len(ev))
    o_sl = o[idx, np.minimum(f_sl, C.HOLD - 1)]
    exit_px = np.where(sl_first, np.minimum(sl, np.where(np.isfinite(o_sl), o_sl, sl)), exit_px)
    o_tp = o[idx, np.minimum(f_tp, C.HOLD - 1)]
    exit_px = np.where(tp_first, np.maximum(tp, np.where(np.isfinite(o_tp), o_tp, tp)), exit_px)
    exit_k = np.where(sl_first, f_sl, np.where(tp_first, f_tp, exit_k))
    reason = np.where(sl_first, "stop", np.where(tp_first, "toma", reason))
    gross = exit_px / entry - 1
    net = (1 + gross) * (1 - C.COST_SIDE) / (1 + C.COST_SIDE) - 1
    df = pd.DataFrame({"i": ii, "j": jj, "entry_i": ii + 1, "exit_i": ii + 1 + exit_k, "entry": entry,
                       "hit30": hi_r >= 0.30, "hit10": hi_r >= 0.10, "dd20": lo_r <= -0.20, "max_r": hi_r,
                       "min_r": lo_r, "ret21": ret21, "gross": gross, "net": net, "reason": reason})
    return df[ok].reset_index(drop=True)


def all_events(P: dict, F: dict | None = None) -> dict[str, pd.DataFrame]:
    F = F or features(P)
    out = {}
    for name, s in C.SETUPS.items():
        ev = cooldown(raw_setup(name, F), s["cooldown"])
        df = outcomes(P, ev)
        if not df.empty:
            df["dd_at"] = F["dd"].to_numpy()[df.i, df.j]
        out[name] = df
    b = outcomes(P, base_sample(F))
    if not b.empty:
        b["dd_at"] = F["dd"].to_numpy()[b.i, b.j]
    out["BASE"] = b
    return out


def recent(P: dict, F: dict, days: int = 10) -> pd.DataFrame:
    """Disparos de los últimos `days` días (aún sin resultado): los candidatos vigentes."""
    rows = []
    T = len(P["dates"])
    for name, s in C.SETUPS.items():
        m = raw_setup(name, F).to_numpy(dtype=bool)
        for i in range(max(0, T - days), T):
            for j in np.flatnonzero(m[i]):
                rows.append({"setup": name, "date": str(P["dates"][i].date()), "ticker": P["tickers"][j],
                             "close": float(P["Close"][i, j]), "dd": float(F["dd"].iat[i, j]),
                             "r10": float(F["r10"].iat[i, j]), "r1": float(F["r1"].iat[i, j]),
                             "vrel": float(F["vrel"].iat[i, j])})
    return pd.DataFrame(rows)
