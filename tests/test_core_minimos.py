import numpy as np
import pandas as pd

from core.minimos import metricas


def test_metricas_minimos():
    idx = pd.bdate_range("2020-10-01", "2026-10-30")
    s = pd.Series(np.linspace(100, 50, len(idx)), index=idx)   # cae de forma continua: hoy es el mínimo de todo
    m = metricas(s)
    assert abs(m["vs_min_52s"]) < 1e-9 and abs(m["vs_min_5a"]) < 1e-9
    assert m["vs_max_52s"] < 0 and m["caida_max_3a"] < 0
    s2 = s.copy()
    s2.iloc[-1] = 60                                            # rebota 20% sobre el mínimo
    m2 = metricas(s2)
    assert 0.15 < m2["vs_min_52s"] < 0.25


def test_metricas_historia_corta_y_ceros():
    idx = pd.bdate_range("2026-01-01", periods=100)
    assert metricas(pd.Series(1.0, index=idx)) == {}
    idx = pd.bdate_range("2020-10-01", "2026-10-30")
    s = pd.Series(10.0, index=idx)
    s.iloc[5] = 0                                               # un cero no debe volverse el mínimo
    assert metricas(s)["min_5a"] == 10.0
