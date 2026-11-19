"""Estudio de OPIs grandes: cómo se comportan según tamaño (récord vs normal) y precio contra su rango.

Muestra fija, escrita antes de ver resultados (precio de oferta nominal; los splits se ajustan con yfinance).
Mide desde el precio de oferta y desde el primer cierre (lo que paga quien compra en bolsa), a 1 sem, 1, 3, 6 meses,
1, 2 y 3 años; peor caída del primer año; ventana del lock-up (día 180) y entradas escalonadas
(día 1, después del primer reporte ~día 63, después del lock-up ~día 135).
Además: SPCX, ANT y TSLA en vivo, razón TSLA/SPCX (precio implícito de una fusión sin prima) y el antecedente
SolarCity (2016).

Uso: python -m core.opis OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ticker, primer día de cotización, precio de oferta nominal (moneda local), US$ mil M levantados (sin greenshoe),
# precio contra el rango ORIGINAL (arriba / tope / medio / bajo / debajo / fijo), agrandada (más acciones), índice local
OPIS = [
    ("V", "2008-03-19", 44.0, 17.9, "arriba", True, "SPY"),
    ("GM", "2010-11-18", 33.0, 20.1, "arriba", True, "SPY"),
    ("META", "2012-05-18", 38.0, 16.0, "arriba", True, "SPY"),
    ("BABA", "2014-09-19", 68.0, 21.8, "arriba", False, "SPY"),
    ("9434.T", "2018-12-19", 1500.0, 23.5, "fijo", False, "^N225"),
    ("2222.SR", "2019-12-11", 32.0, 25.6, "tope", False, "^TASI.SR"),
    ("RIVN", "2021-11-10", 78.0, 11.9, "arriba", True, "SPY"),
    ("P911.DE", "2022-09-29", 82.5, 9.1, "tope", False, "^GDAXI"),
    ("UBER", "2019-05-10", 45.0, 8.1, "bajo", False, "SPY"),
    ("LYFT", "2019-03-29", 72.0, 2.3, "arriba", False, "SPY"),
    ("SNOW", "2020-09-16", 120.0, 3.4, "arriba", False, "SPY"),
    ("DASH", "2020-12-09", 102.0, 3.4, "arriba", False, "SPY"),
    ("ABNB", "2020-12-10", 68.0, 3.5, "arriba", False, "SPY"),
    ("KVUE", "2023-05-04", 22.0, 3.8, "medio", True, "SPY"),
    ("ARM", "2023-09-14", 51.0, 4.9, "tope", False, "SPY"),
    ("BIRK", "2023-10-11", 46.0, 1.5, "medio", False, "SPY"),
    ("RDDT", "2024-03-21", 34.0, 0.75, "tope", False, "SPY"),
    ("LINE", "2024-07-25", 78.0, 4.4, "medio", False, "SPY"),
    ("VG", "2025-01-24", 25.0, 1.75, "debajo", False, "SPY"),
    ("CRWV", "2025-03-28", 40.0, 1.5, "debajo", False, "SPY"),
    ("CRCL", "2025-06-05", 31.0, 1.05, "arriba", True, "SPY"),
    ("CHYM", "2025-06-12", 27.0, 0.86, "arriba", False, "SPY"),
    ("FIG", "2025-07-31", 33.0, 1.2, "arriba", False, "SPY"),
    ("KLAR", "2025-09-10", 40.0, 1.37, "arriba", False, "SPY"),
    ("SPCX", "2026-06-12", 135.0, 75.0, "fijo", False, "SPY"),
    ("ANT", "2026-11-19", 83.0, 81.3, "arriba", True, "SPY"),
]
HORIZ = {"1s": 5, "1m": 21, "3m": 63, "6m": 126, "1a": 252, "2a": 504, "3a": 756}
ENTRADAS = {"dia1": 0, "post_reporte_d63": 63, "post_lockup_d135": 135}
INFO = ["shortName", "currency", "marketCap", "trailingPE", "forwardPE", "priceToSalesTrailing12Months",
        "revenueGrowth", "earningsGrowth", "grossMargins", "operatingMargins", "profitMargins", "freeCashflow",
        "totalRevenue", "sharesOutstanding", "beta", "recommendationMean", "targetMeanPrice",
        "numberOfAnalystOpinions", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "regularMarketPrice",
        "regularMarketOpen", "regularMarketDayHigh", "regularMarketDayLow", "regularMarketPreviousClose",
        "regularMarketChangePercent", "regularMarketVolume", "earningsTimestamp", "isEarningsDateEstimate"]


def bajar(t: str, start: str, interval: str = "1d", period: str | None = None) -> pd.DataFrame:
    import yfinance as yf
    for i in range(4):
        try:
            tk = yf.Ticker(t)
            df = tk.history(period=period, interval=interval, auto_adjust=False) if period else \
                tk.history(start=start, interval=interval, auto_adjust=False)
            if df is not None and not df.empty:
                df.index = pd.to_datetime(df.index).tz_localize(None) if interval == "1d" else df.index
                return df
        except Exception as e:  # noqa: BLE001
            print("reintento", t, i, type(e).__name__, str(e)[:120])
        time.sleep(5 * (i + 1))
    return pd.DataFrame()


def factor_split(t: str, desde: str) -> float:
    import yfinance as yf
    try:
        s = yf.Ticker(t).splits
        if s is None or s.empty:
            return 1.0
        s.index = pd.to_datetime(s.index).tz_localize(None)
        s = s[s.index > pd.Timestamp(desde)]
        return float(np.prod(s.values)) if len(s) else 1.0
    except Exception:  # noqa: BLE001
        return 1.0


def info(t: str) -> dict:
    import yfinance as yf
    try:
        d = yf.Ticker(t).info or {}
        return {k: d.get(k) for k in INFO}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}


def grupo_precio(p: str) -> str:
    return {"arriba": "caliente", "tope": "esperado", "medio": "esperado", "fijo": "esperado",
            "bajo": "frio", "debajo": "frio"}[p]


def medir(t, fecha, oferta, mm, precio, agrandada, bench) -> dict:
    df = bajar(t, fecha)
    r = {"ticker": t, "fecha": fecha, "oferta_nominal": oferta, "levantado_mm_usd": mm, "vs_rango": precio,
         "grupo_precio": grupo_precio(precio), "agrandada": agrandada,
         "tamano": "record" if mm >= 10 else "normal", "benchmark": bench}
    if df.empty:
        r["error"] = "sin datos"
        return r
    df = df[df.index >= pd.Timestamp(fecha)]
    if df.empty:
        r["error"] = "sin datos desde la fecha"
        return r
    f = factor_split(t, fecha)
    of = oferta / f
    c, a = df["Close"].values, df["Adj Close"].values if "Adj Close" in df else df["Close"].values
    r.update({"factor_split": f, "oferta_ajustada": round(of, 4), "primer_dia": str(df.index[0].date()),
              "apertura_d1": round(float(df["Open"].iloc[0]) / of - 1, 4),
              "cierre_d1": round(float(c[0]) / of - 1, 4), "dias": len(df),
              "hoy_vs_oferta": round(float(c[-1]) / of - 1, 4), "hoy_vs_cierre_d1": round(float(a[-1]) / a[0] - 1, 4),
              "ultimo": round(float(c[-1]), 4), "ultima_fecha": str(df.index[-1].date())})
    b = bajar(bench, fecha)
    bc = b["Adj Close"] if not b.empty and "Adj Close" in b else (b["Close"] if not b.empty else None)
    for k, h in HORIZ.items():
        if len(df) > h:
            r[f"desde_cierre_{k}"] = round(float(a[h]) / a[0] - 1, 4)
            r[f"desde_oferta_{k}"] = round(float(c[h]) / of - 1, 4)
            if bc is not None:
                try:
                    b0 = float(bc.asof(df.index[0]))
                    bh = float(bc.asof(df.index[h]))
                    r[f"exceso_{k}"] = round((a[h] / a[0]) / (bh / b0) - 1, 4)
                except Exception:  # noqa: BLE001
                    pass
    n = min(len(df), 252)
    seg = c[:n]
    r["peor_caida_1a_vs_cierre_d1"] = round(float(seg.min()) / c[0] - 1, 4)
    r["peor_caida_1a_vs_oferta"] = round(float(seg.min()) / of - 1, 4)
    r["dia_del_minimo_1a"] = int(seg.argmin())
    r["dias_debajo_oferta_1a_pct"] = round(float((seg < of).mean()), 3)
    m = min(len(df), 21)
    r["max_primer_mes_vs_cierre_d1"] = round(float(c[:m].max()) / c[0] - 1, 4)
    r["dia_max_primer_mes"] = int(c[:m].argmax())
    pico = np.maximum.accumulate(c[:n])
    r["peor_caida_desde_pico_1a"] = round(float((c[:n] / pico - 1).min()), 4)
    # lock-up: 180 días naturales
    lk = df.index.searchsorted(pd.Timestamp(fecha) + pd.Timedelta(days=180))
    if lk + 10 < len(df) and lk - 10 >= 0:
        r["lockup_ventana_-10_+10"] = round(float(a[lk + 10]) / a[lk - 10] - 1, 4)
        r["lockup_-20_a_0"] = round(float(a[lk]) / a[max(lk - 20, 0)] - 1, 4)
    for k, d in ENTRADAS.items():
        for fin, hz in (("2a", 504), ("3a", 756)):
            if len(df) > hz:
                r[f"entrada_{k}_a_{fin}"] = round(float(a[hz]) / a[d] - 1, 4)
    return r


def resumen(df: pd.DataFrame) -> dict:
    cols = [c for c in df.columns if c.startswith(("cierre_d1", "apertura_d1", "desde_cierre_", "desde_oferta_",
                                                   "exceso_", "peor_caida", "lockup", "entrada_",
                                                   "max_primer_mes", "dias_debajo"))]
    out = {}
    hist = df[~df["ticker"].isin(["SPCX", "ANT"])]
    grupos = {"todas": hist, "record": hist[hist.tamano == "record"], "normal": hist[hist.tamano == "normal"],
              "caliente": hist[hist.grupo_precio == "caliente"], "esperado": hist[hist.grupo_precio == "esperado"],
              "frio": hist[hist.grupo_precio == "frio"],
              "record_caliente": hist[(hist.tamano == "record") & (hist.grupo_precio == "caliente")],
              "record_esperado": hist[(hist.tamano == "record") & (hist.grupo_precio != "caliente")],
              "salto_d1_>25%": hist[hist.cierre_d1 > .25], "salto_d1_0-25%": hist[hist.cierre_d1.between(0, .25)],
              "salto_d1_<0": hist[hist.cierre_d1 < 0]}
    for g, d in grupos.items():
        e = {"n": int(len(d)), "tickers": list(d.ticker)}
        for c in cols:
            v = pd.to_numeric(d[c], errors="coerce").dropna()
            if len(v):
                e[c] = {"mediana": round(float(v.median()), 4), "n": int(len(v)),
                        "pos_pct": round(float((v > 0).mean()), 2)}
        out[g] = e
    return out


def vivos(out: Path) -> dict:
    r = {}
    for t in ["SPCX", "ANT", "TSLA"]:
        r[t] = info(t)
    s = bajar("SPCX", "2026-06-12")
    tz = bajar("TSLA", "2026-01-01")
    if not s.empty:
        c = s["Close"]
        r["SPCX_serie"] = {"max": round(float(c.max()), 2), "fecha_max": str(c.idxmax().date()),
                           "min": round(float(c.min()), 2), "fecha_min": str(c.idxmin().date()),
                           "ultimo": round(float(c.iloc[-1]), 2), "vs_max": round(float(c.iloc[-1] / c.max() - 1), 4),
                           "vol_anual": round(float(np.log(c).diff().std() * np.sqrt(252)), 3),
                           "cierres_mensuales": {str(k.date()): round(float(v), 2)
                                                 for k, v in c.resample("ME").last().items()},
                           "ultimos_15": {str(k.date()): round(float(v), 2) for k, v in c.tail(15).items()}}
    if not s.empty and not tz.empty:
        j = pd.concat([tz["Close"].rename("TSLA"), s["Close"].rename("SPCX")], axis=1).dropna()
        j["razon"] = j.TSLA / j.SPCX
        rt = np.log(j[["TSLA", "SPCX"]]).diff().dropna()
        r["TSLA_SPCX"] = {"corr_diaria": round(float(rt.corr().iloc[0, 1]), 3),
                          "beta_tsla_a_spcx": round(float(np.polyfit(rt.SPCX, rt.TSLA, 1)[0]), 3),
                          "razon_hoy": round(float(j.razon.iloc[-1]), 4),
                          "razon_rango": [round(float(j.razon.min()), 4), round(float(j.razon.max()), 4)],
                          "razon_ultimos_15": {str(k.date()): round(float(v), 4) for k, v in j.razon.tail(15).items()},
                          "ret_ultimos_15": {str(k.date()): [round(float(x), 4) for x in v]
                                             for k, v in rt.tail(15).iterrows()}}
        j.to_csv(out / "tsla_spcx.csv")
    if not tz.empty:
        c = tz["Close"]
        r["TSLA_serie"] = {"ultimo": round(float(c.iloc[-1]), 2), "max_2026": round(float(c.max()), 2),
                           "min_2026": round(float(c.min()), 2), "ytd": round(float(c.iloc[-1] / c.iloc[0] - 1), 4),
                           "vol_anual": round(float(np.log(c).diff().std() * np.sqrt(252)), 3)}
    # Antecedente: Tesla-SolarCity (oferta anunciada 21-jun-2016 tras el cierre)
    sc = bajar("TSLA", "2016-06-01")
    if not sc.empty:
        c = sc["Close"]
        w = c[(c.index >= "2016-06-15") & (c.index <= "2016-07-15")]
        r["solarcity_2016"] = {str(k.date()): round(float(v), 3) for k, v in w.items()}
        r["solarcity_dia_anuncio"] = round(float(c.asof(pd.Timestamp("2016-06-22")) / c.asof(pd.Timestamp("2016-06-21")) - 1), 4)
        r["solarcity_a_1a"] = round(float(c.asof(pd.Timestamp("2017-06-22")) / c.asof(pd.Timestamp("2016-06-21")) - 1), 4)
    # ANT intradía de hoy (si ya cotiza)
    try:
        m = bajar("ANT", "", interval="5m", period="1d")
        if not m.empty:
            r["ANT_intradia"] = {"primer": round(float(m["Open"].iloc[0]), 2), "hora_primer": str(m.index[0]),
                                 "max": round(float(m["High"].max()), 2), "min": round(float(m["Low"].min()), 2),
                                 "ultimo": round(float(m["Close"].iloc[-1]), 2), "hora_ultimo": str(m.index[-1]),
                                 "volumen": int(m["Volume"].sum())}
    except Exception as e:  # noqa: BLE001
        r["ANT_intradia_error"] = str(e)[:120]
    return r


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    filas = [medir(*o) for o in OPIS]
    df = pd.DataFrame(filas)
    df.to_csv(out / "opis.csv", index=False)
    res = {"generado": pd.Timestamp.utcnow().isoformat(), "resumen": resumen(df), "vivos": vivos(out),
           "filas": filas}
    (out / "opis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(df[["ticker", "tamano", "grupo_precio", "cierre_d1", "desde_cierre_1a", "exceso_1a", "desde_cierre_3a",
              "exceso_3a", "peor_caida_1a_vs_cierre_d1"]].to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/opis")
