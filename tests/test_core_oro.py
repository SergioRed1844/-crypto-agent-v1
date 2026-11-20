import numpy as np
import pandas as pd

import core.oro as oro


def _s(v, start="2010-01-01"):
    return pd.Series(v, index=pd.bdate_range(start, periods=len(v)), dtype=float)


def test_episodios_y_ret():
    c = _s(np.r_[np.linspace(100, 200, 100), np.linspace(200, 120, 100), np.linspace(120, 250, 600)])
    e = oro.episodios_caida(c, 0.30)
    assert len(e) == 1 and e[0]["caida_total_desde_max"] <= -0.30
    assert oro.ret(c, "2010-01-04", 5) > 0
    assert oro.ret(c, "2040-01-01", 5) is None


def test_crisis_y_estado():
    v = np.r_[np.full(50, 100.0), np.linspace(100, 80, 20), np.full(50, 80.0)]
    c = _s(v)
    assert len(oro.crisis_liquidez(c)) == 1
    e = oro.estado(c)
    assert e["vs_max_hist"] < 0 and 0 <= e["rsi14"] <= 100
