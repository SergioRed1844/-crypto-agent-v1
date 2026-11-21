import numpy as np
import pandas as pd

import core.velas_cripto as vc


def _d(c, freq="1D"):
    idx = pd.date_range("2024-01-01", periods=len(c), freq=freq)
    c = pd.Series(c, index=idx, dtype=float)
    return pd.DataFrame({"o": c, "h": c * 1.05, "l": c * 0.95, "c": c, "v": 1.0, "qv": c, "n": 1.0})


def test_estudios():
    c = np.r_[np.full(40, 1.0), [1.3], np.full(40, 1.2)]
    s = vc.estudio_subidas(_d(c), .2)
    assert s["n"] == 1 and s["ret_1d"]["mediana"] < 0
    h = np.r_[np.full(30, 1.0), np.linspace(1.0, 1.4, 6), np.full(40, 1.3)]
    e = vc.estudio_horas(_d(h, "1h"), .25)
    assert e["n"] >= 1
