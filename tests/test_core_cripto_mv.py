import numpy as np
import pandas as pd

from core.cripto_mv import analogos, betas, episodios_miedo, escenarios, objetivos, variables_moneda


def test_objetivos_y_analogos():
    idx = pd.date_range("2016-01-01", periods=2200, freq="D")
    rng = np.random.default_rng(1)
    p = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.03, len(idx)))), index=idx)
    ob = objetivos(p)
    i = 100
    assert abs(ob["min30"].iloc[i] - (p.iloc[i + 1:i + 31].min() / p.iloc[i] - 1)) < 1e-12
    assert ob["ret90"].iloc[-1] != ob["ret90"].iloc[-1]          # NaN al final: no mira hacia adelante
    df = variables_moneda(p, "").join(ob)
    a = analogos(df, ["mayer", "dd_ath", "vol30", "r30"], k=50)
    assert a["k"] == 50 and 0 <= a["h90"]["p_caer_20"] <= 1


def test_betas_escenarios_miedo():
    idx = pd.date_range("2023-01-01", periods=900, freq="D")
    rng = np.random.default_rng(2)
    b = np.cumsum(rng.normal(0, 0.02, len(idx)))
    px = pd.DataFrame({"BTC-USD": 100 * np.exp(b), "ETH-USD": 50 * np.exp(1.5 * b), "DOGE-USD": np.exp(2 * b)}, index=idx)
    bt = betas(px)
    assert 1.3 < bt["ETH-USD"]["1a"]["beta_diaria"] < 1.7
    esc = escenarios(px, bt, float(px["BTC-USD"].max()))
    assert len(esc) == 5 and all(e["ETH-USD"] > 0 for e in esc)
    df = pd.DataFrame({"fg": [50, 15, 10, 30, 18, 19], "dd_ath": -0.5, "min90": -0.1, "ret90": 0.2, "ret180": 0.3},
                      index=pd.date_range("2020-01-01", periods=6))
    r = episodios_miedo(df)
    assert r["rachas"] == 2 and r["dias_seguidos_fg_le_25"] == 2
