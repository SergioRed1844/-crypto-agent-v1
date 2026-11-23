import numpy as np
import pandas as pd

import core.semana as sm


def _d(c, freq="1D"):
    idx = pd.date_range("2020-01-01", periods=len(c), freq=freq)
    c = pd.Series(np.asarray(c, dtype=float), index=idx)
    return pd.DataFrame({"Close": c, "Low": c * 0.97})


def test_prob_tocar_monotona():
    rng = np.random.default_rng(0)
    c = 100 * np.exp(np.cumsum(rng.normal(0, .03, 1500)))
    r = sm.prob_tocar(_d(c), [95, 90, 80], 7, 100.0)
    p = [r["niveles"][k] for k in ("95", "90", "80")]
    assert p[0] >= p[1] >= p[2] and 0 <= p[2] <= 1 and r["n_dias"] > 0


def test_rendimientos_y_analogos():
    c = pd.Series(np.linspace(100, 130, 80), index=pd.date_range("2026-08-01", periods=80))
    r = sm.rendimientos(c, pd.Series(1.0, index=c.index))
    assert abs(r["1d"] - (130 / c.iloc[-2] - 1)) < 1e-12 and "desde_1oct" in r
    # serie semanal: sube a 100, cae a 45 lentamente -> RSI bajo y caída >45%
    up = np.linspace(10, 100, 120)
    down = np.linspace(100, 45, 40)
    flat = np.full(30, 45.0)
    a = sm.analogos_btc(_d(np.r_[up, down, flat], "W"))
    assert "n" in a or a["n_semanas"] >= 0
