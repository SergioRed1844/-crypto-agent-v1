"""Foto de los candidatos CORE (precio, valuación, crecimiento) y desempeño de las tesis de enero 2026 desde su fecha.

Corre en GitHub Actions (yfinance). Uso: python -m core.fetch OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PILARES = {
    "infra_ia": ["NVDA", "ASML", "MSFT", "TSM", "AVGO"],
    "ciberseguridad": ["ZS", "CRWD", "PANW", "NET", "FTNT", "CIBR"],
    "energia_redes": ["CEG", "VST", "GEV", "ANET", "ETN"],
    "salud_metabolica": ["LLY", "NVO"],
    "defensa_robotica": ["ITA", "BOTZ"],
    "cobertura": ["IBIT", "GLD", "BTC-USD"],
    "china": ["MCHI", "KWEB", "0981.HK", "0763.HK", "002415.SZ", "300024.SZ", "601985.SS"],
    "base": ["SPY", "VT", "QQQ", "ACWI"],
    "plan_b_ene26": ["CRM", "AMZN", "GOOGL", "NBIS"],
    "tesis_gpt_oct26": ["AXON", "PWR", "VRT", "PLTR", "OKTA"],
    "espacio": ["SPCE", "SPCX", "RKLB", "ASTS", "UFO"],
    "cartera": ["SPCE", "LLY", "ETH-USD", "DOGE-USD", "BTC-USD"],
    "mercado": ["^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX", "^TNX", "DX-Y.NYB", "MXN=X", "SOXX", "XLK", "XLV", "XLE", "XLF", "MSFT", "GOOGL", "AMZN", "META", "AAPL"],
}
# Tesis recuperadas por el GPT de Sergio (registros de enero 2026): se miden desde su fecha, sin elegir nada después.
TESIS = {
    "Plan A infra IA (16-ene-2026)": ("2026-01-16", {"NVDA": 1, "MSFT": 1, "ASML": 1}),
    "Plan B diversificado (16-ene-2026)": ("2026-01-16", {"CRM": 1, "AMZN": 1, "GOOGL": 1, "NVO": 1, "NBIS": 1}),
    "60/40 Occidente-China (26-ene-2026)": ("2026-01-26", {"NVDA": .12, "MSFT": .12, "GOOGL": .12, "AMZN": .12, "ASML": .12,
                                                         "0981.HK": .08, "0763.HK": .08, "002415.SZ": .08,
                                                         "300024.SZ": .08, "601985.SS": .08}),
    "SPY (16-ene-2026)": ("2026-01-16", {"SPY": 1}),
    "SPY (26-ene-2026)": ("2026-01-26", {"SPY": 1}),
    "ZS (16-ene-2026)": ("2026-01-16", {"ZS": 1}),
    "LLY (16-ene-2026)": ("2026-01-16", {"LLY": 1}),
}
INFO = ["shortName", "currency", "marketCap", "trailingPE", "forwardPE", "priceToSalesTrailing12Months",
        "revenueGrowth", "earningsGrowth", "grossMargins", "operatingMargins", "profitMargins", "freeCashflow",
        "totalRevenue", "pegRatio", "trailingPegRatio", "beta", "recommendationMean", "targetMeanPrice",
        "numberOfAnalystOpinions", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
        "regularMarketPrice", "regularMarketPreviousClose", "regularMarketChangePercent",
        "postMarketPrice", "postMarketChangePercent", "preMarketPrice", "preMarketChangePercent",
        "earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd", "isEarningsDateEstimate"]


def history(tks: list[str]) -> pd.DataFrame:
    import yfinance as yf
    for i in range(4):
        try:
            df = yf.download(tks, start="2021-01-01", auto_adjust=True, progress=False, threads=True)["Close"]
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001
            print("reintento", i, type(e).__name__, str(e)[:120])
        time.sleep(10 * (i + 1))
    return pd.DataFrame()


def info(t: str) -> dict:
    import yfinance as yf
    for i in range(3):
        try:
            d = yf.Ticker(t).info or {}
            return {k: d.get(k) for k in INFO}
        except Exception as e:  # noqa: BLE001
            print("info", t, type(e).__name__, str(e)[:80])
            time.sleep(5 * (i + 1))
    return {}


def stats(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) < 30:
        return {}
    last, d = float(s.iloc[-1]), s.index[-1]
    def ret_since(date):
        x = s[s.index >= pd.Timestamp(date)]
        return float(last / x.iloc[0] - 1) if len(x) else None
    y1 = s[s.index >= d - pd.Timedelta(days=365)]
    y3 = s[s.index >= d - pd.Timedelta(days=3 * 365)]
    dd3 = float((y3 / y3.cummax() - 1).min()) if len(y3) else None
    yrs = (y3.index[-1] - y3.index[0]).days / 365.25 if len(y3) > 1 else None
    def ret_n(n):
        return float(last / s.iloc[-1 - n] - 1) if len(s) > n else None
    return {"fecha": str(d.date()), "precio": last, "r_1d": ret_n(1), "r_5d": ret_n(5), "r_21d": ret_n(21), "ytd": ret_since(f"{d.year}-01-01"), "r_1a": ret_since(d - pd.Timedelta(days=365)),
            "r_desde_16ene26": ret_since("2026-01-16"), "cagr_3a": float((y3.iloc[-1] / y3.iloc[0]) ** (1 / yrs) - 1) if yrs else None,
            "max_52s": float(y1.max()), "caida_vs_max52s": float(last / y1.max() - 1), "caida_max_3a": dd3,
            "vol_anual_1a": float(np.log(y1).diff().std() * np.sqrt(252))}


def tesis(px: pd.DataFrame) -> dict:
    out = {}
    for name, (start, w) in TESIS.items():
        cols = [c for c in w if c in px.columns and px[c].loc[pd.Timestamp(start):].notna().any()]
        if not cols:
            out[name] = {"error": "sin datos"}
            continue
        p = px[cols].loc[pd.Timestamp(start):].dropna(how="all").ffill()
        base = p.bfill().iloc[0]                          # primer precio de cada activo desde la fecha (calendarios distintos)
        ww = np.array([w[c] for c in p.columns], dtype=float)
        ww = ww / ww.sum()
        rel = p.bfill() / base
        nav = (rel * ww).sum(axis=1)                     # compra y mantén con los pesos de la fecha de la tesis
        out[name] = {"desde": str(p.index[0].date()), "hasta": str(p.index[-1].date()), "retorno": float(nav.iloc[-1] - 1),
                     "caida_max": float((nav / nav.cummax() - 1).min()), "activos": list(p.columns),
                     "faltan": [c for c in w if c not in p.columns],
                     "por_activo": {c: float(rel[c].iloc[-1] - 1) for c in p.columns}}
    return out


def main(out: str) -> int:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    tks = sorted({t for v in PILARES.values() for t in v})
    px = history(tks)
    print("historia", px.shape)
    rows = []
    for pil, lst in PILARES.items():
        for t in lst:
            r = {"pilar": pil, "ticker": t}
            r.update(stats(px[t]) if t in px.columns else {})
            r.update(info(t))
            rows.append(r)
            time.sleep(0.5)
    df = pd.DataFrame(rows)
    df.to_csv(o / "snapshot.csv", index=False, float_format="%.6g")
    th = tesis(px)
    json.dump({"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tesis": th,
               "snapshot": df.replace({np.nan: None}).to_dict(orient="records")},
              open(o / "snapshot.json", "w"), indent=1, default=str)
    print(df[["pilar", "ticker", "precio", "ytd", "r_desde_16ene26", "caida_vs_max52s", "forwardPE",
              "priceToSalesTrailing12Months", "revenueGrowth"]].to_string())
    print(json.dumps(th, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
