import numpy as np
import pandas as pd

from core.nvda import caidas_nvda, desde_maximo, max_dd, sintetico


def test_sintetico_y_caida():
    r = pd.Series([0.10, -0.10] * 50)
    x1, x2 = sintetico(r, 1), sintetico(r, 2)
    assert x2.iloc[-1] < x1.iloc[-1] < 1          # el 2x se desgasta más en un mercado que va y viene
    assert abs(max_dd(pd.Series([100, 50, 75])) + 0.5) < 1e-12


def test_caidas_y_desde_maximo():
    idx = pd.bdate_range("2015-01-01", periods=800)
    px = pd.Series(np.linspace(100, 200, 800), index=idx)
    px.iloc[400:] *= 0.7                            # una caída de 30% en un día
    res = caidas_nvda(px)
    assert res["n"] == 1 and res["eventos"][0]["caida_2d"] <= -0.08
    assert desde_maximo(px)["dias"] > 0
