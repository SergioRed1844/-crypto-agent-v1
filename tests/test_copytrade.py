"""Pruebas sin red del análisis copy-trade (copytrade/*). Uso: python -m tests.test_copytrade"""
from __future__ import annotations

import datetime as dt
import math
import sys

import numpy as np
import pandas as pd

from copytrade import events, parse278t as P, sim
from copytrade.data import lower_of, mid
from copytrade.resolve import asset_class, bond_proxy, maturity, norm

FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def test_parse() -> None:
    lo, hi = dt.date(2026, 7, 1), dt.date(2026, 7, 31)
    check("fecha limpia", P.norm_date("7/9/2026", lo, hi) == dt.date(2026, 7, 9))
    check("fecha con / leído como 1", P.norm_date("7/812026", lo, hi) == dt.date(2026, 7, 8))
    check("fecha con espacio", P.norm_date("7/ 31/2026", lo, hi) == dt.date(2026, 7, 31))
    check("fecha fuera de ventana → None", P.norm_date("9/9/2026", lo, hi) is None)
    check("año 2028 → 2026", P.norm_date("7/10/2028", lo, hi) == dt.date(2026, 7, 10))
    check("monto con espacios", P.norm_amount("$1 000 001 - $5 000 000") == 1000001)
    check("monto con OCR o/D", P.norm_amount("s1.ooo.D01 • ss.000.000") == 1000001)
    check("monto ilegible → None", P.norm_amount("$7 - $9") is None)
    check("tipo compra garbled", P.norm_type("lourchaso") == "Purchase" and P.norm_type("IDUrchaSO") == "Purchase")
    check("tipo venta", P.norm_type("salo") == "Sale" and P.norm_type("sale") == "Sale")
    line = ("12               WEST VIRGINIA ST HSG DEV B/E 5.00 % Due Aug 1, 2027                    lourchaso"
            "              7/17/2026               No $250 001 - $500 000")
    rows = P.parse(line, lo, hi)
    check("fila completa", len(rows) == 1 and rows[0].n == 12 and rows[0].typ == "Purchase"
          and rows[0].date == dt.date(2026, 7, 17) and rows[0].lower == 250001)
    check("sello OGE", P.received("xx OGE Received 9/14/26 yy") == dt.date(2026, 9, 14))


def test_amounts() -> None:
    check("límite inferior", lower_of("$1,001-$15,000") == 1001 and lower_of("$25,000,001-$50,000,000") == 25000001)
    check("punto medio", mid(1001) == 8000.5 and mid(1000001) == 3000000.5)
    check("geo < mid", mid(1001, "geo") < mid(1001))
    check("peso igual", mid(500001, "equal") == 1.0)


def test_resolve() -> None:
    d0 = dt.date(2026, 7, 7)
    check("muni", asset_class("MIAMI DADE CNTY FL AVIATION REV RFDG SER A B/E PTC 5.00 % Due Oct 1, 2031") == "muni")
    check("vencimiento texto", maturity("X B/E 5.00 % Due Oct 1, 2031") == dt.date(2031, 10, 1))
    check("vencimiento numérico", maturity("META PLATFORMS 4.75% DUE 08/15/34") == dt.date(2034, 8, 15))
    check("muni largo → MUB", bond_proxy("muni", "X B/E 5.00 % Due Oct 1, 2031", d0) == "MUB")
    check("muni corto → SUB", bond_proxy("muni", "X B/E 5.00 % Due Jun 1, 2027", d0) == "SUB")
    check("corporativo", asset_class("META PLATFORMS 4.75% DUE 08/15/34") == "corp")
    check("perpetuo → pref", asset_class("JPMORGAN CHASE & CO PERP NN 6.8750%") == "pref")
    check("money market", asset_class("INVESCO PREMIER U.S. GOVERNMENT MONEY MARKET PORTFOLIO") == "mm")
    check("tesoro", asset_class("UNITED STATES TREAS BILL DUE 05/14/26 AGENCY PURCHASE") == "treasury")
    check("ETF es fondo", asset_class("ISHARES CORE S&P 500 ETF") == "fund")
    check("acción", asset_class("NVIDIA CORP") == "equity")
    check("normaliza ruido", norm("MICROSOFT CORP UNSOLICITED") == norm("Microsoft Corporation"))
    check("normaliza &", norm("AT&T INC") == norm("AT & T INC"))


def _px() -> pd.DataFrame:
    cal = pd.bdate_range("2025-01-21", periods=60)
    up = np.linspace(100, 160, 60)          # +60%
    flat = np.full(60, 50.0)
    cash = np.linspace(100, 100.6, 60)
    dead = np.r_[np.linspace(20, 30, 30), np.full(30, np.nan)]   # deja de cotizar a la mitad
    return pd.DataFrame({"SPY": np.linspace(100, 110, 60), "UP": up, "FLAT": flat, "BIL": cash, "DEAD": dead,
                         "AGG": np.linspace(100, 101, 60)}, index=cal)


def _trades(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", "pub", "type", "lower", "ticker", "cls"])
    df["mid"] = [mid(x) for x in df.lower]
    df["description"] = df.ticker
    return df


def test_sim() -> None:
    raw = _px()
    px, info = sim.extend(raw)
    cal = px.index
    check("serie muerta rinde como BIL", abs(px["DEAD"].iloc[-1] / px["DEAD"].iloc[29] - px["BIL"].iloc[-1]
                                             / px["BIL"].iloc[29]) < 1e-12)
    d = lambda i: str(cal[i].date())
    tr = _trades([
        (d(0), d(10), "Purchase", 1001, "UP", "equity"),
        (d(0), d(10), "Purchase", 1001, "FLAT", "equity"),
        (d(5), d(10), "Sale", 1000001, "UP", "equity"),          # vende más de lo que tiene → recorta a 0
        (d(6), d(10), "Sale", 1001, "NOPE", "equity"),           # venta de algo que nunca compró → se ignora
        (d(20), d(40), "Purchase", 1001, "UP", "equity"),
    ])
    t = sim.prepare(tr, px, info)
    check("ticker sin precio queda fuera", not t[t.ticker == "NOPE"].price_ok.any())
    h = sim.holdings(t[t.price_ok], px, "mid")
    check("venta recortada a cero", h.get("UP", 0) > 0 and abs(h["UP"] - mid(1001) / px["UP"].iloc[20]) < 1e-9)
    rE = sim.run(t, px, sim.Spec(mode="E", cost=0.0), start=cal[0])
    rR = sim.run(t, px, sim.Spec(mode="R", cost=0.0), start=cal[0])
    navR = rR["nav"]
    check("modo R en efectivo antes de publicar", abs(navR.iloc[11] / navR.iloc[0] - px["BIL"].iloc[11] /
                                                     px["BIL"].iloc[0]) < 1e-9)
    check("modo R rebalancea al día hábil siguiente a la publicación", cal[11] in rR["weights"]
          and cal[10] not in rR["weights"])
    check("modo E rebalancea el día de la operación", cal[0] in rE["weights"])
    w0 = rE["weights"][cal[0]]
    check("pesos espejo 50/50 al inicio", abs(w0["UP"] - w0["FLAT"]) < 1e-9)
    # costo: un rebalanceo de 100% en efectivo → activos = rotación 2.0
    rc = sim.run(t, px, sim.Spec(mode="E", cost=0.01), start=cal[0])
    check("costo cobrado por rotación", rc["cost"] > 0 and rc["nav"].iloc[-1] < rE["nav"].iloc[-1])
    b = sim.benchmark(px, {"SPY": 1.0}, start=cal[0], monthly=False)
    check("SPY comprar y mantener", abs(b.iloc[-1] / b.iloc[0] - 1.1) < 1e-9)
    m = sim.metrics(b, px["SPY"], px["BIL"])
    check("beta del SPY = 1", abs(m["beta"] - 1) < 1e-6)
    top = sim.run(t, px, sim.Spec(mode="E", cost=0.0, top=1), start=cal[0])
    check("top-1 tiene una sola posición", all(len(w) == 1 for w in top["weights"].values()))


def test_events() -> None:
    raw = _px()
    px, info = sim.extend(raw)
    cal = px.index
    tr = _trades([(str(cal[0].date()), str(cal[1].date()), "Purchase", 1001, "UP", "equity"),
                  (str(cal[0].date()), str(cal[1].date()), "Sale", 1001, "FLAT", "equity")])
    t = sim.prepare(tr, px, info)
    ex = events.excess(t, px, "xE", 21)
    up = ex[ex.type == "Purchase"].ex.iloc[0]
    fl = ex[ex.type == "Sale"].ex.iloc[0]
    exp_up = px["UP"].iloc[21] / px["UP"].iloc[0] - px["SPY"].iloc[21] / px["SPY"].iloc[0]
    exp_fl = -(1 - px["SPY"].iloc[21] / px["SPY"].iloc[0])
    check("exceso de compra", abs(up - exp_up) < 1e-12)
    check("venta con signo invertido (vender lo que luego rindió menos = positivo)", abs(fl - exp_fl) < 1e-12 and fl > 0)
    est, lo, hi, k = events.cluster_boot(ex[ex.type == "Purchase"], True, n=200)
    check("bootstrap con un grupo", k == 1 and math.isclose(est, exp_up) and lo == hi)


def main() -> int:
    for f in (test_parse, test_amounts, test_resolve, test_sim, test_events):
        f()
    print(f"{'OK' if not FAILS else 'FALLAS: ' + str(len(FAILS))} copytrade")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
