import numpy as np
import pandas as pd

import core.spce as sp


def test_piso_y_ventanas():
    idx = pd.bdate_range("2023-01-02", periods=200)
    c = pd.Series(np.r_[np.linspace(10, 5, 100), np.linspace(5, 8, 100)], index=idx)
    m = pd.Series(True, index=idx)
    p = sp.piso_adelante(c, m, 20)
    assert p["n"] > 0 and p["mediana"] <= 0
    assert sp.ventana(c, "2023-03-01", -10, -1) < 0
    assert sp.ventana(c, "2030-01-01", -10, -1) is None
    assert 0 <= sp.rsi(c).iloc[-1] <= 100
