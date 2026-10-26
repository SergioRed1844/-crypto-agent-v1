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
    raw = _df(P["RawClose"], d, t) if "RawClose" in P else c          # precio al que se operó ese día
    dol = _df(P["Dollar"], d, t) if "Dollar" in P else c * v
    nbars = c.notna().cumsum()
    dollar = dol.rolling(20, min_periods=15).median()
    hi252 = c.rolling(252, min_periods=200).max()
    vmed50 = v.shift(1).rolling(50, min_periods=40).median()
    elig = (raw >= C.MIN_PRICE) & (dollar >= C.MIN_DOLLAR_VOL) & (nbars >= C.MIN_BARS)
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


def _clean_window(o, h, lo, cl, entry):
    """Velas t+1…t+HOLD sin huecos: un precio ≤ 0 es dato malo; un día sin cierre (suspensión, hueco de Yahoo) repite
    el último cierre sin máximo ni mínimo propios. Así ninguna operación desaparece por lo que pasa después de entrar."""
    o, h, lo, cl = (np.where(x > 0, x, np.nan) for x in (o, h, lo, cl))
    n, K = cl.shape
    valid = np.isfinite(cl)
    pos = np.where(valid, np.arange(K)[None, :], -1)
    last = np.maximum.accumulate(pos, axis=1)
    cl_ff = np.where(last >= 0, cl[np.arange(n)[:, None], np.maximum(last, 0)], entry[:, None])
    o = np.where(valid & np.isfinite(o), o, cl_ff)
    o[:, 0] = entry
    h = np.where(valid, np.fmax(np.fmax(h, o), cl_ff), cl_ff)
    lo = np.where(valid, np.fmin(np.fmin(lo, o), cl_ff), cl_ff)
    h[:, 0] = np.fmax(h[:, 0], entry)
    lo[:, 0] = np.fmin(lo[:, 0], entry)
    return o, h, lo, cl_ff, (~valid).sum(axis=1), np.where(valid.any(axis=1), last[:, -1], -1)


def _outcomes(P: dict, ev: list[tuple[int, int]]) -> pd.DataFrame:
    O, H, L, Cl = P["Open"], P["High"], P["Low"], P["Close"]
    ii = np.array([e[0] for e in ev])
    jj = np.array([e[1] for e in ev])
    k = np.arange(1, C.HOLD + 1)
    rows = ii[:, None] + k[None, :]                    # t+1 … t+HOLD
    cols = jj[:, None]
    entry = O[ii + 1, jj].astype(float)
    ok = np.isfinite(entry) & (entry > 0)                # solo se exige poder entrar
    entry = np.where(ok, entry, 1.0)
    o, h, lo, cl, gaps, last_valid = _clean_window(O[rows, cols].astype(float), H[rows, cols].astype(float),
                                                   L[rows, cols].astype(float), Cl[rows, cols].astype(float), entry)
    hi_r = h.max(axis=1) / entry - 1
    lo_r = lo.min(axis=1) / entry - 1
    ret21 = cl[:, -1] / entry - 1
    tp, sl = entry * (1 + C.TP), entry * (1 + C.SL)
    hit_tp = h >= tp[:, None]
    hit_sl = lo <= sl[:, None]
    BIG = C.HOLD + 5
    f_tp = np.where(hit_tp.any(axis=1), hit_tp.argmax(axis=1), BIG)
    f_sl = np.where(hit_sl.any(axis=1), hit_sl.argmax(axis=1), BIG)
    exit_px = cl[:, -1].copy()
    exit_k = np.full(len(ev), C.HOLD - 1)
    sl_first = (f_sl <= f_tp) & (f_sl < BIG)               # empate en el mismo día → stop
    tp_first = (f_tp < f_sl) & (f_tp < BIG)
    idx = np.arange(len(ev))
    o_sl = o[idx, np.minimum(f_sl, C.HOLD - 1)]
    exit_px = np.where(sl_first, np.minimum(sl, o_sl), exit_px)
    o_tp = o[idx, np.minimum(f_tp, C.HOLD - 1)]
    exit_px = np.where(tp_first, np.maximum(tp, o_tp), exit_px)
    exit_k = np.where(sl_first, f_sl, np.where(tp_first, f_tp, exit_k))
    reason = np.where(sl_first, "stop", np.where(tp_first, "toma", "tiempo"))
    gross = exit_px / entry - 1
    net = (1 + gross) * (1 - C.COST_SIDE) / (1 + C.COST_SIDE) - 1
    df = pd.DataFrame({"i": ii, "j": jj, "entry_i": ii + 1, "exit_i": ii + 1 + exit_k, "entry": entry,
                       "hit30": hi_r >= 0.30, "hit10": hi_r >= 0.10, "dd20": lo_r <= -0.20, "max_r": hi_r,
                       "min_r": lo_r, "ret21": ret21, "gross": gross, "net": net, "reason": reason,
                       "gaps": gaps, "cut": last_valid < C.HOLD - 1})
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
    """Disparos (con la misma pausa por acción que el estudio) de los últimos `days` días: aún sin resultado."""
    rows = []
    T = len(P["dates"])
    for name, s in C.SETUPS.items():
        for i, j in cooldown(raw_setup(name, F), s["cooldown"]):
            if i < T - days:
                continue
            rows.append({"setup": name, "date": str(P["dates"][i].date()), "dias": int(T - 1 - i),
                         "ticker": P["tickers"][j], "close": float(P["Close"][i, j]),
                         "operado": float(P["RawClose"][i, j]) if "RawClose" in P else float(P["Close"][i, j]),
                         "dd": float(F["dd"].iat[i, j]), "r10": float(F["r10"].iat[i, j]),
                         "r1": float(F["r1"].iat[i, j]), "vrel": float(F["vrel"].iat[i, j])})
    return pd.DataFrame(rows).sort_values(["dias", "dd"]).reset_index(drop=True) if rows else pd.DataFrame()
