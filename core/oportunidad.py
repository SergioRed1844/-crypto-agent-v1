"""Oportunidades fuera del factor IA: empresas de crecimiento castigadas aun con el rebote, con datos para pre-auditar
(crecimiento, flujo libre, múltiplos, próximo reporte por la regla 3) + foto en vivo de la cartera.
Uso: python -m core.oportunidad OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

from core.pre import ACCIONES, MACRO, foto

UNIVERSO = {
    "ciber": ["CRWD", "PANW", "FTNT", "NET", "ZS", "S", "OKTA", "CYBR", "QLYS", "RBRK"],
    "software": ["NOW", "CRM", "ADBE", "DDOG", "SNOW", "MDB", "TEAM", "HUBS", "SHOP", "INTU", "TTD", "APP", "PLTR"],
    "fintech": ["NU", "MELI", "SE", "HOOD", "SOFI", "COIN", "AFRM", "TOST", "V", "MA"],
    "salud": ["ISRG", "VRTX", "REGN", "NVO", "DXCM", "BSX", "HIMS", "ARGX", "ALNY", "TMDX"],
    "consumo": ["NFLX", "SPOT", "DUOL", "RDDT", "ONON", "DECK", "CMG", "CAVA", "ABNB", "BKNG", "DASH", "COST", "AXON"],
}


def ficha(t: str) -> dict:
    import yfinance as yf
    tk = yf.Ticker(t)
    r = foto(t)
    h = tk.history(period="1y", interval="1d", auto_adjust=True)
    if not h.empty:
        p = r.get("ultimo") or float(h.Close.iloc[-1])
        r["max_52s"] = float(h.High.max())
        r["vs_max"] = p / r["max_52s"] - 1
        r["vs_min"] = p / float(h.Low.min()) - 1
        r["ret_5d_previo"] = float(h.Close.iloc[-2] / h.Close.iloc[-7] - 1) if len(h) > 8 else None
        r["sma200"] = float(h.Close.rolling(200).mean().iloc[-1]) if len(h) >= 200 else None
    try:
        i = tk.info
    except Exception:  # noqa: BLE001
        i = {}
    mc = i.get("marketCap") or 0
    r.update({"nombre": i.get("shortName"), "cap_mm": round(mc / 1e9, 1) if mc else None,
              "crec_ventas": i.get("revenueGrowth"), "crec_utilidad": i.get("earningsGrowth"),
              "margen_bruto": i.get("grossMargins"), "margen_oper": i.get("operatingMargins"),
              "pe_adelantado": i.get("forwardPE"), "peg": i.get("trailingPegRatio") or i.get("pegRatio"),
              "fcf_yield": (i.get("freeCashflow") / mc) if i.get("freeCashflow") and mc else None,
              "deuda_neta_mm": round(((i.get("totalDebt") or 0) - (i.get("totalCash") or 0)) / 1e9, 1),
              "recomendacion": i.get("recommendationKey"), "objetivo_medio": i.get("targetMeanPrice")})
    try:
        cal = tk.calendar
        ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if ed:
            r["proximo_reporte"] = str(ed[0])
    except Exception:  # noqa: BLE001
        pass
    return r


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res: dict = {"generado": pd.Timestamp.now("UTC").isoformat(), "cartera": {}, "macro": {}, "filtro": {}}
    for t in ACCIONES:
        try:
            res["cartera"][t] = foto(t)
        except Exception as e:  # noqa: BLE001
            res["cartera"][t] = {"error": str(e)[:80]}
    for k, t in MACRO.items():
        try:
            res["macro"][k] = foto(t)
        except Exception as e:  # noqa: BLE001
            res["macro"][k] = {"error": str(e)[:80]}
    for sector, tks in UNIVERSO.items():
        for t in tks:
            try:
                res["filtro"][t] = {"sector": sector, **ficha(t)}
            except Exception as e:  # noqa: BLE001
                res["filtro"][t] = {"sector": sector, "error": str(e)[:80]}
            time.sleep(.3)
    (out / "oportunidad.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(len(res["filtro"]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/oportunidad")
