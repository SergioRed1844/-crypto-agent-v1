import numpy as np
import pandas as pd

import core.pump_alerta as pa


def _d(c, qv=None):
    idx = pd.date_range("2025-06-01", periods=len(c), freq="1D")
    c = pd.Series(np.asarray(c, dtype=float), index=idx)
    qv = pd.Series(np.ones(len(c)) if qv is None else np.asarray(qv, dtype=float), index=idx)
    return pd.DataFrame({"o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "qv": qv, "tq": qv / 2})


def test_desenlace_corto_largo():
    cae = _d(np.r_[1.0, 0.95, 0.80, np.full(10, 0.8)])
    f = pa.desenlace(cae, 0)
    assert f["corto"] == 1 and f["largo"] == -1
    sube = _d(np.r_[1.0, 1.05, 1.20, np.full(10, 1.2)])
    g = pa.desenlace(sube, 0)
    assert g["corto"] == -1 and g["largo"] == 1
    assert pa.desenlace(cae, 10) is None


def test_eventos_y_tablas():
    c = np.r_[np.full(40, 1.0), 1.25, np.full(3, 1.25), 0.9, np.full(20, 0.9)]
    qv = np.ones(len(c))
    qv[40] = 5.0
    filas = pa.filas_estudio("X", _d(c, qv))
    assert len(filas) == 1 and filas[0]["b_sube"] == "20-35%" and filas[0]["b_vol"] == "4-8x"
    assert filas[0]["corto"] == 1
    ev = pd.DataFrame(filas * 40 + [{**filas[0], "corto": -1}] * 10)
    t = pa.tablas(ev, "corto")
    p, n2, n1 = pa.prob(t, "20-35%", "4-8x", filas[0]["b_prev"])
    assert n2 == 50 and 0.7 < p < 0.8  # 40/50 encogido hacia la media
    assert pa.etiqueta(float("nan"), "prev") == "sin dato" and pa.etiqueta(.6, "prev") == "ya subió 50%+"


def test_validar_y_reporte():
    filas = []
    for i in range(60):
        filas.append({"sym": "A", "fecha": f"2025-0{1 + i % 9}-10" if i < 40 else "2026-03-10", "b_sube": "12-20%",
                      "b_vol": "2-4x", "b_prev": "0-50%", "corto": 1 if i % 4 else -1, "largo": -1})
    v = pa.validar(pd.DataFrame(filas), "corto")
    assert v["n_train"] == 40 and v["n_test"] == 20
    tit, md = pa.reporte("2026-11-23", [], {"corto": v}, {"corto": []}, None, prueba=True)
    assert tit.startswith("[PRUEBA]") and "ninguna" in tit.lower() and "Validación" in md
