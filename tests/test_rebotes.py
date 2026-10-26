"""Pruebas sin red del estudio de rebotes. Uso: python -m tests.test_rebotes"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from rebotes import backtest as B, config as C, portfolio as PF, signals as S

FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def panel(T=400, N=3, seed=1):
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2017-01-02", periods=T)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (T, N)), axis=0)).astype(np.float32)
    P = {"Open": c.copy(), "High": c * 1.01, "Low": c * 0.99, "Close": c.copy(),
         "Volume": np.full((T, N), 1e6, dtype=np.float32), "dates": d, "tickers": [f"T{k}" for k in range(N - 1)] + ["SPY"]}
    return P


def test_outcomes():
    P = panel(T=60, N=2)
    O, H, L, Cl = P["Open"], P["High"], P["Low"], P["Close"]
    O[:, 0] = H[:, 0] = L[:, 0] = Cl[:, 0] = 100.0
    # día t=10: señal; entrada al open de 11 = 100; vela 13 toca +30% → toma
    H[13, 0] = 131.0
    r = S.outcomes(P, [(10, 0)]).iloc[0]
    check("toma +30% al tocar", r.reason == "toma" and abs(r.gross - 0.30) < 1e-6 and r.hit30)
    check("costos restan", r.net < r.gross)
    # mismo día toca toma y stop → stop
    L[13, 0] = 84.0
    r = S.outcomes(P, [(10, 0)]).iloc[0]
    check("empate toma/stop → stop", r.reason == "stop" and abs(r.gross + 0.15) < 1e-6)
    # gap a la baja: abre en 70 → se llena al open
    P2 = panel(T=60, N=2)
    for a in ("Open", "High", "Low", "Close"):
        P2[a][:, 0] = 100.0
    P2["Open"][15, 0] = P2["Low"][15, 0] = 70.0
    r = S.outcomes(P2, [(10, 0)]).iloc[0]
    check("stop con hueco se llena al open", r.reason == "stop" and abs(r.gross + 0.30) < 1e-6)
    # sin tocar nada → salida por tiempo al cierre de la vela 21
    P3 = panel(T=60, N=2)
    for a in ("Open", "High", "Low", "Close"):
        P3[a][:, 0] = 100.0
    P3["Close"][10 + C.HOLD, 0] = 110.0
    r = S.outcomes(P3, [(10, 0)]).iloc[0]
    check("salida por tiempo en la vela 21", r.reason == "tiempo" and abs(r.gross - 0.10) < 1e-6
          and r.exit_i == 10 + C.HOLD)
    check("sin futuro suficiente → fuera", S.outcomes(P3, [(50, 0)]).empty)


def test_setups():
    P = panel(T=600, N=3, seed=3)
    c = P["Close"]
    # T0: cae 60% entre 300 y 400 y luego rompe el máximo de 20 días en 420
    c[300:400, 0] = np.linspace(c[299, 0], c[299, 0] * 0.4, 100)
    c[400:420, 0] = c[399, 0]
    c[420:, 0] = c[399, 0] * 1.2
    for a in ("Open", "High", "Low"):
        P[a][:, 0] = c[:, 0] * (1.01 if a == "High" else 0.99 if a == "Low" else 1.0)
    P["Volume"][:, :] = 1e7
    F = S.features(P)
    m = S.raw_setup("CAIDA_GIRO", F)
    ev = S.cooldown(m, 60)
    check("CAIDA_GIRO dispara en el giro", any(i == 420 and j == 0 for i, j in ev))
    check("pausa de 60 velas", len([e for e in ev if e[1] == 0]) == 1)
    # sin mirar al futuro: cambiar precios posteriores a 420 no cambia el disparo de 420
    P["Close"][421:, 0] *= 3
    F2 = S.features(P)
    check("la señal no usa el futuro", bool(S.raw_setup("CAIDA_GIRO", F2).iat[420, 0]) == bool(m.iat[420, 0]))
    check("elegibilidad exige 260 velas", not F["elig"].iloc[:250, 0].any())


def test_portfolio():
    P = panel(T=120, N=8)
    dates = P["dates"]
    tr = pd.DataFrame({"j": list(range(7)), "entry_i": [10] * 7, "exit_i": [20] * 7, "net": [0.1] * 7,
                       "entry": P["Open"][10, :7], "dd_at": [-0.9, -0.8, -0.7, -0.6, -0.5, -0.4, -0.3]})
    sim = PF.simulate(tr, P["Close"], dates, 0, 119)
    check("máximo 5 posiciones", len(sim["taken"]) == 5)
    check("entra primero la de mayor caída", list(sim["taken"].j) == [0, 1, 2, 3, 4])
    check("resultado neto: +10% en el 100% invertido", abs(sim["nav"].iloc[-1] - C.CAPITAL * 1.1) < 1e-6)
    tr2 = pd.DataFrame({"j": [0, 1], "entry_i": [10, 20], "exit_i": [20, 30], "net": [0.1, 0.1],
                        "entry": [P["Open"][10, 0], P["Open"][20, 1]], "dd_at": [-0.5, -0.5]})
    s2 = PF.simulate(tr2, P["Close"], dates, 0, 119)
    check("reinvierte después de salir", len(s2["taken"]) == 2)
    st = PF.stats(sim["nav"])
    check("estadísticas mensuales", 0 <= st["pct_m30"] <= 1 and st["months"] >= 5)


def test_end_to_end():
    P = panel(T=1500, N=12, seed=9)
    P["dates"] = pd.bdate_range("2014-01-01", periods=1500)
    P["Volume"][:] = 1e7
    with tempfile.TemporaryDirectory() as d:
        np.savez_compressed(Path(d) / "panel.npz", data=np.stack([P[f] for f in ("Open", "High", "Low", "Close", "Volume")]),
                            dates=np.array(P["dates"].strftime("%Y-%m-%d"), dtype="U10"), tickers=np.array(P["tickers"]),
                            fields=np.array(["Open", "High", "Low", "Close", "Volume"]))
        res = B.run(str(Path(d) / "panel.npz"), str(Path(d) / "out"), reps=3)
        check("corre de punta a punta", "base" in res and (Path(d) / "out" / "REPORT.md").exists())
        check("base con muestra", res["base"]["test"]["n"] > 100)


def main():
    for f in (test_outcomes, test_setups, test_portfolio, test_end_to_end):
        f()
    print(("OK" if not FAILS else f"FALLAS: {len(FAILS)}") + " rebotes")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
