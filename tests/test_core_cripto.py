import numpy as np
import pandas as pd

from core.cripto import adelante, medidas, pisos


def test_medidas_y_pisos():
    idx = pd.date_range("2015-01-01", periods=2500, freq="D")
    up = np.linspace(100, 1000, 1200)
    down = np.linspace(1000, 150, 400)          # cae 85%: un piso
    rec = np.linspace(150, 900, 900)
    s = pd.Series(np.concatenate([up, down, rec]), index=idx)
    df = medidas(s)
    assert abs(df["dd_ath"].min() + 0.85) < 1e-9
    p = pisos(df)
    assert len(p) == 1 and abs(p[0]["caida_desde_max"] + 0.85) < 1e-9
    a = adelante(df, df["dd_ath"] < -0.8)
    assert a["dias"] > 0 and a["episodios"] == 1 and a["d90"]["mediana"] > 0
