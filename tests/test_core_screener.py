import numpy as np
import pandas as pd

import core.screener_cripto as sc


def _d(c, qv=None):
    idx = pd.date_range("2024-01-01", periods=len(c), freq="1D")
    c = pd.Series(np.asarray(c, dtype=float), index=idx)
    qv = pd.Series(np.ones(len(c)) if qv is None else np.asarray(qv, dtype=float), index=idx)
    return pd.DataFrame({"o": c, "h": c * 1.02, "l": c * 0.98, "c": c, "v": 1.0, "qv": qv})


def test_senal_despertar():
    c = np.r_[np.full(100, 10.0), np.full(170, 1.0), np.linspace(1.0, 1.3, 31)[1:]]
    qv = np.ones(len(c))
    qv[-10:] = 5.0
    x = sc.senales(_d(c, qv))
    u = x.iloc[-1]
    assert bool(u.rompe90) and u.vol_ratio >= 2 and abs(u.ret30 - .3) < 1e-9 and u.vs_max <= -.8
    assert bool(u.despertar)
    # sin volumen no hay señal
    assert not bool(sc.senales(_d(c)).despertar.iloc[-1])
    # si ya subió más de 60% en 30 días, tampoco (ya explotó)
    c2 = np.r_[np.full(100, 10.0), np.full(170, 1.0), np.linspace(1.0, 1.8, 31)[1:]]
    assert not bool(sc.senales(_d(c2, qv)).despertar.iloc[-1])


def test_adelante_y_resumen():
    gana = _d(np.r_[1.0, 1.1, 1.3, 1.6, np.full(40, 1.4)])
    f = sc.adelante(gana, 0)
    assert f["primero"] == "gana" and f["max_30d"] > .5
    pierde = _d(np.r_[1.0, 0.9, 0.75, 2.0, np.full(40, 1.0)])
    assert sc.adelante(pierde, 0)["primero"] == "pierde"
    assert sc.adelante(gana, 30) is None
    r = sc.resumen([{"sym": "A", **f}, {"sym": "B", **sc.adelante(pierde, 0)}])
    assert r["n"] == 2 and r["P_+50_antes_-20"] == .5 and r["P_-20_antes_+50"] == .5
    assert sc.resumen([]) == {"n": 0}


def test_eventos_separados():
    c = np.r_[np.full(100, 10.0), np.full(170, 1.0), np.linspace(1.0, 1.3, 31)[1:], np.full(40, 1.3)]
    qv = np.ones(len(c))
    qv[290:300] = 5.0
    d = _d(c, qv)
    ev = sc.eventos("X", d, sc.senales(d))
    assert 1 <= len(ev) and all("primero" in e for e in ev)
    fechas = pd.to_datetime([e["fecha"] for e in ev])
    assert all((b - a).days >= 30 for a, b in zip(fechas, fechas[1:]))
