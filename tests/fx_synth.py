"""Velas sintéticas de 1 minuto bid/ask para probar el agente FX sin red."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from fx import calendar as K
from fx import config as C


def bars(sym="EURUSD", start=date(2019, 1, 1), years=3, seed=0, event_p=0.12, jump_sd=8.0, drift=0.6,
         slot_name="US_0830", base_vol=1.2e-5, spread_pips=0.3):
    """Paseo aleatorio + en ~event_p de los días un salto en el slot (|salto| ≈ jump_sd·σ15) seguido de un drift
    en la MISMA dirección de ``drift``×salto durante las 2 h siguientes (drift=0 → sin ventaja)."""
    rng = np.random.default_rng(seed)
    p = C.PAIRS[sym]
    slot = next(s for s in C.SLOTS if s.name == slot_name)
    end = start + timedelta(days=int(365.25 * years))
    t_all, r_all = [], []
    d = start
    while d < end:
        if d.weekday() < 5:
            m0 = K.to_min(K.datetime.combine(d, K.time(0, 0), K.UTC))
            t = np.arange(m0, m0 + 1440)
            r = rng.standard_normal(1440) * base_vol
            if rng.random() < event_p:
                tm = K.slot_min(slot, d) - m0
                if 0 <= tm < 1440 - 200:
                    j = rng.choice([-1, 1]) * jump_sd * base_vol * np.sqrt(15) * (1 + rng.random())
                    r[tm:tm + 3] += j / 3
                    r[tm:tm + 30] += rng.standard_normal(30) * base_vol * 3
                    r[tm + 15:tm + 135] += drift * j / 120
            t_all.append(t); r_all.append(r)
        d += timedelta(days=1)
    t = np.concatenate(t_all)
    lp = np.log(1.10) + np.cumsum(np.concatenate(r_all))
    mid_c = np.exp(lp)
    mid_o = np.concatenate([[mid_c[0]], mid_c[:-1]])
    wig = np.abs(rng.standard_normal(len(t))) * base_vol * mid_c
    hi = np.maximum(mid_o, mid_c) + wig
    lo = np.minimum(mid_o, mid_c) - wig
    half = spread_pips * p.pip / 2
    q = lambda x: np.round(x / p.point).astype(np.int64)  # noqa: E731
    return {"t": t, "bo": q(mid_o - half), "bh": q(hi - half), "bl": q(lo - half), "bc": q(mid_c - half),
            "ao": q(mid_o + half), "ah": q(hi + half), "al": q(lo + half), "ac": q(mid_c + half),
            "bv": np.ones(len(t), np.float32), "av": np.ones(len(t), np.float32)}
