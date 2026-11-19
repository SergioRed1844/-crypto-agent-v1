import numpy as np
import pandas as pd

import core.opis as op


def _serie(n, inicio=100.0, paso=0.001):
    idx = pd.bdate_range("2015-01-02", periods=n)
    c = inicio * (1 + paso) ** np.arange(n)
    return pd.DataFrame({"Open": c, "Close": c, "Adj Close": c, "High": c, "Low": c, "Volume": 1}, index=idx)


def test_medir_y_resumen(monkeypatch):
    monkeypatch.setattr(op, "bajar", lambda t, start, interval="1d", period=None: _serie(900))
    monkeypatch.setattr(op, "factor_split", lambda t, d: 2.0)          # un split 2:1 después de la OPI
    r = op.medir("XX", "2015-01-02", 80.0, 12.0, "arriba", True, "SPY")
    assert r["oferta_ajustada"] == 40.0 and r["tamano"] == "record" and r["grupo_precio"] == "caliente"
    assert abs(r["cierre_d1"] - 1.5) < 1e-9                              # cerró en 100 contra 40 ajustado
    assert r["desde_cierre_1a"] > 0 and abs(r["exceso_1a"]) < 1e-9       # igual que su índice
    assert r["peor_caida_1a_vs_cierre_d1"] == 0 and "lockup_ventana_-10_+10" in r
    df = pd.DataFrame([r, {**r, "ticker": "YY", "tamano": "normal", "grupo_precio": "frio", "cierre_d1": -0.1}])
    s = op.resumen(df)
    assert s["record"]["n"] == 1 and s["frio"]["n"] == 1 and s["salto_d1_<0"]["n"] == 1


def test_grupos_de_precio():
    assert op.grupo_precio("tope") == op.grupo_precio("fijo") == "esperado"
    assert op.grupo_precio("debajo") == "frio"


def test_condicion():
    c = np.array([100.0] * 70 + [60.0] * 70)           # cierre d1 en 100, cae 40% el día 70
    x = op.condicion(c, 80.0, op.pts_temperatura("arriba", True))
    assert x[0] == 2 + 4 + 0 + 0                        # caliente y agrandada, prima +25% (≤25%), sin calendario
    assert x[100] == 2 + 10 + 10 + 7                    # debajo de la oferta, −40% contra d1, silencio + reporte
