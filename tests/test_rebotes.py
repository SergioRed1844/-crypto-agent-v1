"""Pruebas sin red del estudio de rebotes. Uso: python -m tests.test_rebotes"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from rebotes import backtest as B, config as C, data as D, portfolio as PF, signals as S

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
    check("costos exactos", abs(r.net - (1.30 * (1 - C.COST_SIDE) / (1 + C.COST_SIDE) - 1)) < 1e-9)
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


def flat(T=80, N=2, px=100.0):
    P = panel(T=T, N=N)
    for a in ("Open", "High", "Low", "Close"):
        P[a][:, 0] = px
    return P


def test_outcomes_extra():
    P = flat()
    P["Open"][14, 0] = 140.0
    P["High"][14, 0] = 142.0
    r = S.outcomes(P, [(10, 0)]).iloc[0]
    check("toma con hueco al alza se llena al open", r.reason == "toma" and abs(r.gross - 0.40) < 1e-6)
    P = flat()
    P["Low"][11, 0] = 80.0
    r = S.outcomes(P, [(10, 0)]).iloc[0]
    check("stop en la vela de entrada", r.reason == "stop" and abs(r.gross + 0.15) < 1e-6 and r.exit_i == 11)
    # día sin cotizar dentro de la tenencia: la operación se conserva y el hueco no inventa máximos/mínimos
    P = flat()
    for a in ("Open", "High", "Low", "Close"):
        P[a][15, 0] = np.nan
    P["Close"][10 + C.HOLD, 0] = 105.0
    d = S.outcomes(P, [(10, 0)])
    check("hueco en la tenencia no borra la operación", len(d) == 1 and int(d.gaps.iloc[0]) == 1
          and abs(d.gross.iloc[0] - 0.05) < 1e-6)
    # serie que se corta (deja de cotizar): sale al último cierre conocido
    P = flat()
    for a in ("Open", "High", "Low", "Close"):
        P[a][20:, 0] = np.nan
    P["Close"][19, 0] = 90.0
    P["Low"][19, 0] = 89.0
    d = S.outcomes(P, [(10, 0)])
    check("serie cortada sale al último cierre", len(d) == 1 and bool(d.cut.iloc[0]) and abs(d.gross.iloc[0] + 0.10) < 1e-6)
    # precio cero = dato malo, no −100%
    P = flat()
    P["Open"][16, 0] = 0.0
    P["Low"][16, 0] = 0.0
    r = S.outcomes(P, [(10, 0)]).iloc[0]
    check("precio cero no es −100%", r.reason == "tiempo" and abs(r.gross) < 1e-6)
    # lotes: mismo resultado en uno o varios
    P = panel(T=300, N=6, seed=4)
    ev = [(i, j) for i in range(0, 270, 7) for j in range(6)]
    a, b = S.outcomes(P, ev), S.outcomes(P, ev, batch=17)
    check("lotes dan lo mismo", len(a) == len(b) and np.allclose(a.net, b.net))


def test_raw_price():
    idx = pd.bdate_range("2023-01-02", periods=6)
    # Yahoo: Close ya viene ajustado por el reverse split 1:20 del día 4 (antes valía 0.80 → aparece 16)
    sub = pd.DataFrame({"Open": [16, 16, 16, 1, 1, 1.0], "High": [16, 16, 16, 1, 1, 1.0], "Low": [16, 16, 16, 1, 1, 1.0],
                        "Close": [16, 16, 16, 1, 1, 1.0], "Adj Close": [16, 16, 16, 1, 1, 1.0],
                        "Volume": [100.0] * 6, "Stock Splits": [0, 0, 0, 0.05, 0, 0]}, index=idx)
    out = D.adjust(sub)
    check("precio operado deshace el reverse split", np.allclose(out.RawClose.iloc[:3], 0.80)
          and np.allclose(out.RawClose.iloc[3:], 1.0))
    check("ajustado conserva la serie continua", np.allclose(out.Close, sub.Close))
    sub2 = sub.assign(**{"Adj Close": sub.Close * 0.5, "Stock Splits": 0.0})
    check("ajuste por dividendos a OHLC", np.allclose(D.adjust(sub2).Open, sub.Open * 0.5))
    P = panel(T=400, N=2)
    P["Volume"][:] = 1e7
    P["RawClose"] = np.full_like(P["Close"], 0.8)
    P["Dollar"] = P["Close"] * P["Volume"]
    check("filtro de US$3 usa el precio operado", not S.features(P)["elig"].values.any())


def test_setups_extra():
    P = panel(T=600, N=3, seed=5)
    P["Volume"][:] = 1e7
    c = P["Close"]
    # T0: −30% en 10 días con volumen 4× el día 420 → CAPITULACION
    c[410:421, 0] = np.linspace(c[409, 0], c[409, 0] * 0.68, 11)
    c[421:, 0] = c[420, 0]
    P["Volume"][420, 0] = 4e7
    # T1: cae 50% y luego +20% en un día con volumen 6× el día 450 → CATALIZADOR
    c[300:400, 1] = np.linspace(c[299, 1], c[299, 1] * 0.5, 100)
    c[400:450, 1] = c[399, 1]
    c[450:, 1] = c[399, 1] * 1.2
    P["Volume"][450, 1] = 6e7
    for a in ("Open", "High", "Low"):
        P[a][:] = c * (1.01 if a == "High" else 0.99 if a == "Low" else 1.0)
    F = S.features(P)
    cap = S.cooldown(S.raw_setup("CAPITULACION", F), 30)
    cat = S.cooldown(S.raw_setup("CATALIZADOR", F), 30)
    check("CAPITULACION dispara", (420, 0) in cap)
    check("CATALIZADOR dispara", (450, 1) in cat and not any(j == 0 for _, j in cat))
    b = S.base_sample(F)
    el = int(F["elig"].values.sum())
    check("base ≈ 1 de cada 10 días elegibles", abs(len(b) / el - 0.10) < 0.01)
    # recorte: los rasgos hasta t no cambian al quitar todo lo posterior
    cut = 430
    Pc = {k: (v[:cut] if isinstance(v, np.ndarray) else v) for k, v in P.items()}
    Pc["dates"] = P["dates"][:cut]
    Fc = S.features(Pc)
    same = all(np.allclose(F[k].iloc[:cut].to_numpy(dtype=float), Fc[k].to_numpy(dtype=float), equal_nan=True)
               for k in ("dd", "dd_prev", "r1", "r10", "vrel", "brk", "brk_prev", "elig"))
    check("recortar el futuro no cambia nada antes del corte", same)
    for name in C.SETUPS:
        a = S.raw_setup(name, F).iloc[:cut].to_numpy()
        check(f"{name} no mira al futuro", bool((a == S.raw_setup(name, Fc).to_numpy()).all()))


def test_mtm():
    P = panel(T=60, N=2)
    P["Close"][:, 0] = 100.0
    tr = pd.DataFrame({"j": [0], "entry_i": [10], "exit_i": [30], "net": [(1 - C.COST_SIDE) / (1 + C.COST_SIDE) - 1],
                       "entry": [100.0], "dd_at": [-0.5]})
    nav = PF.simulate(tr, P["Close"], P["dates"], 0, 59)["nav"]
    alloc = C.CAPITAL / C.MAX_POS
    v15 = C.CAPITAL - alloc + alloc * (1 - C.COST_SIDE) / (1 + C.COST_SIDE)
    check("valor diario ya descuenta el costo de vender", abs(nav.iloc[15] - v15) < 1e-6 and abs(nav.iloc[40] - v15) < 1e-6)
    P["Close"][20:25, 0] = np.nan
    nav2 = PF.simulate(tr, P["Close"], P["dates"], 0, 59)["nav"]
    check("sin cierre se usa el último conocido", abs(nav2.iloc[22] - v15) < 1e-6)
    # una salida de hoy libera el lugar hasta mañana
    P = panel(T=60, N=7)
    tr2 = pd.DataFrame({"j": [0, 1, 2, 3, 4, 5], "entry_i": [10] * 5 + [20], "exit_i": [20] * 5 + [40],
                        "net": [0.0] * 6, "entry": [100.0] * 6, "dd_at": [-0.5] * 6})
    check("no entra el día de la salida", len(PF.simulate(tr2, P["Close"], P["dates"], 0, 59)["taken"]) == 5)
    tr2.loc[5, "entry_i"] = 21
    check("entra al día siguiente de la salida", len(PF.simulate(tr2, P["Close"], P["dates"], 0, 59)["taken"]) == 6)


def test_end_to_end_setups():
    """Panel sintético con caídas y rebotes: los setups disparan y corren diferencia, placebo y compuerta."""
    T, N = 2200, 40
    P = panel(T=T, N=N, seed=21)
    P["dates"] = pd.bdate_range("2013-01-01", periods=T)
    rng = np.random.default_rng(2)
    c = P["Close"].astype(float)
    vol = np.full((T, N), 1e7, dtype=np.float32)
    for j in range(N - 1):
        for start in rng.integers(300, T - 120, size=4):
            c[start:, j] *= 0.45                      # desplome de un día con volumen
            c[start + 30:, j] *= 1.25                 # rebote con volumen
            vol[start, j] = vol[start + 30, j] = 6e7
    c = c.astype(np.float32)
    P["Close"], P["Open"], P["High"], P["Low"] = c, c.copy(), c * 1.02, c * 0.98
    P["Volume"] = vol
    with tempfile.TemporaryDirectory() as d:
        np.savez_compressed(Path(d) / "panel.npz", data=np.stack([P[f] for f in ("Open", "High", "Low", "Close", "Volume")]),
                            dates=np.array(P["dates"].strftime("%Y-%m-%d"), dtype="U10"), tickers=np.array(P["tickers"]),
                            fields=np.array(["Open", "High", "Low", "Close", "Volume"]))
        res = B.run(str(Path(d) / "panel.npz"), str(Path(d) / "out"), reps=3)
        n_test = {k: v["test"].get("n", 0) for k, v in res["setups"].items()}
        check(f"setups con disparos en prueba {n_test}", min(n_test.values()) > 0)
        ok = all("gate" in v and v["diff_vs_base_test"].get("months", 0) > 0 and v.get("placebo_test")
                 for v in res["setups"].values())
        check("diferencia, placebo y compuerta corren", ok)
        end = pd.Timestamp(res["meta"]["portfolio_end"])
        check("la cartera termina en fin de mes con 21 velas detrás",
              (P["dates"] > end).sum() >= C.HOLD and P["dates"][P["dates"].searchsorted(end) + 1].month != end.month)


def main():
    for f in (test_outcomes, test_outcomes_extra, test_raw_price, test_setups, test_setups_extra, test_portfolio,
              test_mtm, test_end_to_end, test_end_to_end_setups):
        f()
    print(("OK" if not FAILS else f"FALLAS: {len(FAILS)}") + " rebotes")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
