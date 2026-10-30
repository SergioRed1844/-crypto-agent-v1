"""Empresas en mínimos de 52 semanas y de 5 años (S&P 500 + Nasdaq-100 + extras), con fundamentales para aplicar
las reglas CORE. Corre en GitHub Actions (yfinance). Uso: python -m core.minimos OUT_DIR
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from core.fetch import INFO

EXTRAS = ["NFLX", "UBER", "NKE", "LULU", "SBUX", "TGT", "PYPL", "ADBE", "CRM", "NOW", "INTC", "PFE", "CVS", "UNH",
          "BA", "DIS", "EL", "MRNA", "ENPH", "DG", "DLTR", "LULU", "CMG", "DECK", "ONON", "BIRK", "SPCE"]
EXTRA_INFO = ["sector", "industry", "debtToEquity", "totalCash", "totalDebt", "earningsQuarterlyGrowth",
              "operatingCashflow", "returnOnEquity", "dividendYield", "currentPrice"]
UA = {"User-Agent": "Mozilla/5.0 (rebotes-bot; research)"}


def universo() -> list[str]:
    import requests
    tks: set[str] = set(EXTRAS)
    for url, col in [("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
                     ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker")]:
        try:
            html = requests.get(url, headers=UA, timeout=30).text
            for t in pd.read_html(io.StringIO(html)):
                if col in t.columns:
                    tks |= {str(x).strip().replace(".", "-") for x in t[col].dropna()}
                    break
        except Exception as e:  # noqa: BLE001
            print("universo", url, type(e).__name__, str(e)[:120])
    return sorted(t for t in tks if t and t.lower() != "nan")


def history(tks: list[str]) -> pd.DataFrame:
    import yfinance as yf
    out = []
    for i in range(0, len(tks), 100):
        chunk = tks[i:i + 100]
        for k in range(3):
            try:
                df = yf.download(chunk, start="2020-09-01", auto_adjust=True, progress=False, threads=True)["Close"]
                if df is not None and not df.empty:
                    out.append(df if isinstance(df, pd.DataFrame) else df.to_frame(chunk[0]))
                    break
            except Exception as e:  # noqa: BLE001
                print("hist", i, k, type(e).__name__, str(e)[:100])
            time.sleep(10 * (k + 1))
    return pd.concat(out, axis=1) if out else pd.DataFrame()


def metricas(s: pd.Series) -> dict:
    """Distancia a mínimos y máximos de 52 semanas y 5 años, retornos recientes y peor caída de 3 años."""
    s = s.dropna()
    s = s[s > 0]
    if len(s) < 260:
        return {}
    p, d = float(s.iloc[-1]), s.index[-1]
    y1 = s[s.index >= d - pd.Timedelta(days=365)]
    y5 = s[s.index >= d - pd.Timedelta(days=int(5 * 365.25))]
    y3 = s[s.index >= d - pd.Timedelta(days=3 * 365)]
    def r(n):
        return float(p / s.iloc[-1 - n] - 1) if len(s) > n else None
    x = s[s.index >= pd.Timestamp(f"{d.year}-01-01")]
    return {"fecha": str(d.date()), "precio": p, "anios_hist": round((s.index[-1] - s.index[0]).days / 365.25, 2),
            "min_52s": float(y1.min()), "max_52s": float(y1.max()), "vs_min_52s": float(p / y1.min() - 1),
            "vs_max_52s": float(p / y1.max() - 1), "min_5a": float(y5.min()), "max_5a": float(y5.max()),
            "vs_min_5a": float(p / y5.min() - 1), "vs_max_5a": float(p / y5.max() - 1),
            "fecha_min_5a": str(y5.idxmin().date()), "r_1d": r(1), "r_5d": r(5), "r_21d": r(21), "r_63d": r(63),
            "ytd": float(p / x.iloc[0] - 1) if len(x) else None,
            "caida_max_3a": float((y3 / y3.cummax() - 1).min()),
            "vol_anual_1a": float(np.log(y1).diff().std() * np.sqrt(252))}


def trimestres(t) -> dict:
    """Ventas y margen operativo de los últimos trimestres (para distinguir pánico de daño)."""
    try:
        q = t.quarterly_income_stmt
        if q is None or q.empty:
            return {}
        q = q.T.sort_index()
        rev = q.get("Total Revenue")
        op = q.get("Operating Income")
        if rev is None or len(rev.dropna()) < 5:
            return {}
        rev = rev.dropna()
        out = {"trim_ultimo": str(rev.index[-1].date()),
               "ventas_yoy_ult": float(rev.iloc[-1] / rev.iloc[-5] - 1),
               "ventas_yoy_prev": float(rev.iloc[-2] / rev.iloc[-6] - 1) if len(rev) >= 6 else None}
        if op is not None:
            m = (op / q["Total Revenue"]).dropna()
            if len(m) >= 5:
                out.update({"margen_op_ult": float(m.iloc[-1]), "margen_op_hace1a": float(m.iloc[-5])})
        return out
    except Exception as e:  # noqa: BLE001
        print("trim", type(e).__name__, str(e)[:80])
        return {}


def ficha(tk: str) -> dict:
    import yfinance as yf
    for i in range(3):
        try:
            t = yf.Ticker(tk)
            d = t.info or {}
            out = {k: d.get(k) for k in INFO + EXTRA_INFO}
            out.update(trimestres(t))
            return out
        except Exception as e:  # noqa: BLE001
            print("info", tk, type(e).__name__, str(e)[:80])
            time.sleep(5 * (i + 1))
    return {}


def main(out: str) -> int:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    tks = universo()
    print("universo", len(tks))
    px = history(tks)
    print("historia", px.shape)
    rows = []
    for t in px.columns:
        m = metricas(px[t])
        if m:
            rows.append({"ticker": t, **m})
    df = pd.DataFrame(rows)
    df["en_min_52s"] = df.vs_min_52s <= 0.05
    df["en_min_5a"] = df.vs_min_5a <= 0.10
    cerca = df[(df.vs_min_52s <= 0.10) | (df.vs_min_5a <= 0.15) | df.ticker.isin(["NFLX", "UBER", "NKE"])].ticker
    print("fichas", len(cerca))
    fich = {}
    for t in cerca:
        fich[t] = ficha(t)
        time.sleep(0.4)
    f = pd.DataFrame.from_dict(fich, orient="index").reset_index(names="ticker")
    full = df.merge(f, on="ticker", how="left")
    full.to_csv(o / "minimos.csv", index=False, float_format="%.6g")
    json.dump({"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "universo": len(tks),
               "con_historia": int(len(df)), "en_min_52s": int(df.en_min_52s.sum()), "en_min_5a": int(df.en_min_5a.sum()),
               "filas": full.replace({np.nan: None}).to_dict(orient="records")},
              open(o / "minimos.json", "w"), indent=1, default=str)
    print(full.sort_values("vs_min_52s").head(60)[["ticker", "precio", "vs_min_52s", "vs_min_5a", "vs_max_52s",
                                                    "revenueGrowth", "trailingPegRatio", "forwardPE"]].to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
