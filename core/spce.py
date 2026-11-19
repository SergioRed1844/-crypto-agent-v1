"""Estudio SPCE para una regla especulativa de acumulación (19-nov-2026).

Mide: estado actual, cuánto más suele caer desde un punto así (mínimo de los siguientes 20/40/60 días),
qué pasó antes y después de sus vuelos clave y de sus reportes, y la dilución (acciones en circulación).
Fechas de vuelos fijadas antes de ver resultados. Uso: python -m core.spce OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

VUELOS = {"Unity 21": "2021-05-22", "Unity 22 (Branson)": "2021-07-11", "Unity 25": "2023-05-25",
          "Galactic 01 (1er comercial)": "2023-06-29", "Galactic 02": "2023-08-10", "Galactic 07 (pausa)": "2024-06-08"}
INFO = ["shortName", "marketCap", "sharesOutstanding", "floatShares", "sharesShort", "shortPercentOfFloat",
        "shortRatio", "totalCash", "totalDebt", "freeCashflow", "regularMarketPrice", "regularMarketPreviousClose",
        "regularMarketDayLow", "regularMarketDayHigh", "fiftyTwoWeekLow", "fiftyTwoWeekHigh", "earningsTimestamp",
        "isEarningsDateEstimate", "averageVolume", "regularMarketVolume"]


def bajar(t: str, **kw) -> pd.DataFrame:
    import yfinance as yf
    for i in range(4):
        try:
            df = yf.Ticker(t).history(auto_adjust=True, **kw)
            if df is not None and not df.empty:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except Exception as e:  # noqa: BLE001
            print("reintento", t, i, str(e)[:100])
        time.sleep(5 * (i + 1))
    return pd.DataFrame()


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n).mean()
    return 100 - 100 / (1 + up / dn)


def ventana(c: pd.Series, fecha: str, a: int, b: int) -> float | None:
    i = c.index.searchsorted(pd.Timestamp(fecha))
    if i + b >= len(c) or i + a < 0:
        return None
    return round(float(c.iloc[i + b] / c.iloc[i + a] - 1), 4)


def piso_adelante(c: pd.Series, mask: pd.Series, h: int) -> dict:
    fut = pd.Series([c.iloc[i + 1:i + 1 + h].min() if i + h < len(c) else np.nan for i in range(len(c))], index=c.index)
    x = (fut / c - 1)[mask].dropna()
    if not len(x):
        return {"n": 0}
    return {"n": int(len(x)), "mediana": round(float(x.median()), 3), "p25": round(float(x.quantile(.25)), 3),
            "p10": round(float(x.quantile(.10)), 3), "prob_caer_20": round(float((x <= -.2).mean()), 2),
            "prob_caer_40": round(float((x <= -.4).mean()), 2)}


def adelante(c: pd.Series, mask: pd.Series, h: int) -> dict:
    x = (c.shift(-h) / c - 1)[mask].dropna()
    if not len(x):
        return {"n": 0}
    return {"n": int(len(x)), "mediana": round(float(x.median()), 3), "pos": round(float((x > 0).mean()), 2),
            "p75": round(float(x.quantile(.75)), 3), "p25": round(float(x.quantile(.25)), 3)}


def main(out_dir: str) -> None:
    import yfinance as yf
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = bajar("SPCE", period="max")
    c = df["Close"]
    tk = yf.Ticker("SPCE")
    try:
        inf = {k: (tk.info or {}).get(k) for k in INFO}
    except Exception as e:  # noqa: BLE001
        inf = {"error": str(e)[:100]}
    r = {"generado": pd.Timestamp.utcnow().isoformat(), "info": inf}
    sma50 = c.rolling(50).mean()
    dd60 = c / c.rolling(60).max() - 1
    rs = rsi(c)
    r["hoy"] = {"fecha": str(c.index[-1].date()), "precio": round(float(c.iloc[-1]), 4),
                "min_hist": round(float(c.min()), 4), "fecha_min_hist": str(c.idxmin().date()),
                "min_52s": round(float(c.iloc[-252:].min()), 4), "max_52s": round(float(c.iloc[-252:].max()), 4),
                "vs_sma50": round(float(c.iloc[-1] / sma50.iloc[-1] - 1), 3), "caida_60d": round(float(dd60.iloc[-1]), 3),
                "rsi14": round(float(rs.iloc[-1]), 1),
                "vol_20d": round(float(np.log(c).diff().iloc[-20:].std() * np.sqrt(252)), 2),
                "ultimos_15": {str(k.date()): [round(float(v), 4), int(df.Volume.loc[k])] for k, v in c.tail(15).items()}}
    # Estado parecido al de hoy: caída ≥40% en 60 días y debajo de su promedio de 50 días por ≥25%
    parecido = (dd60 <= -.40) & (c / sma50 - 1 <= -.25)
    todo = pd.Series(True, index=c.index)
    r["piso_adelante"] = {g: {f"{h}d": piso_adelante(c, m, h) for h in (20, 40, 60)}
                          for g, m in (("todos_los_dias", todo), ("parecido_a_hoy", parecido))}
    r["retorno_adelante"] = {g: {f"{h}d": adelante(c, m, h) for h in (20, 40, 60, 80)}
                             for g, m in (("todos_los_dias", todo), ("parecido_a_hoy", parecido))}
    r["dias_parecidos"] = int(parecido.sum())
    # Vuelos: carrera previa y "vender la noticia"
    r["vuelos"] = {}
    for n, f in VUELOS.items():
        i = c.index.searchsorted(pd.Timestamp(f))
        lo = c.iloc[max(i - 120, 0):max(i - 5, 1)]
        r["vuelos"][n] = {"fecha": f, "-60a-1": ventana(c, f, -60, -1), "-20a-1": ventana(c, f, -20, -1),
                          "-1a+5": ventana(c, f, -1, 5), "-1a+20": ventana(c, f, -1, 20),
                          "del_min_previo_al_-1": round(float(c.iloc[i - 1] / lo.min() - 1), 3) if len(lo) else None,
                          "dias_del_min_al_vuelo": int(i - c.index.get_loc(lo.idxmin())) if len(lo) else None}
    # Reportes (fechas de yfinance)
    try:
        ed = tk.get_earnings_dates(limit=40)
        ed.index = pd.to_datetime(ed.index).tz_localize(None)
        fechas = sorted({d.normalize() for d in ed.index if d <= c.index[-1]})
    except Exception as e:  # noqa: BLE001
        fechas, r["reportes_error"] = [], str(e)[:100]
    rep = []
    for d in fechas:
        i = c.index.searchsorted(d)
        if i - 10 < 0 or i + 5 >= len(c):
            continue
        rep.append({"fecha": str(d.date()), "-10a-1": round(float(c.iloc[i - 1] / c.iloc[i - 10] - 1), 4),
                    "-20a-1": round(float(c.iloc[i - 1] / c.iloc[max(i - 20, 0)] - 1), 4),
                    "-1a+1": round(float(c.iloc[i + 1] / c.iloc[i - 1] - 1), 4),
                    "-1a+5": round(float(c.iloc[i + 5] / c.iloc[i - 1] - 1), 4)})
    r["reportes"] = rep
    if rep:
        x = pd.DataFrame(rep)
        r["reportes_resumen"] = {k: {"mediana": round(float(x[k].median()), 3), "pos": round(float((x[k] > 0).mean()), 2),
                                     "n": int(len(x))} for k in ("-20a-1", "-10a-1", "-1a+1", "-1a+5")}
    # Dilución
    try:
        sh = tk.get_shares_full(start="2021-01-01")
        sh.index = pd.to_datetime(sh.index).tz_localize(None)
        sh = sh[~sh.index.duplicated()].sort_index()
        anual = sh.resample("YE").last()
        r["acciones"] = {str(k.date()): int(v) for k, v in anual.items()}
        r["acciones_ultimo"] = [str(sh.index[-1].date()), int(sh.iloc[-1])]
    except Exception as e:  # noqa: BLE001
        r["acciones_error"] = str(e)[:100]
    # Estacionalidad nov→mar: retorno de cada año del 19-nov al 15-mar
    est = {}
    for y in range(2019, 2026):
        a, b = c.asof(pd.Timestamp(f"{y}-11-19")), c.asof(pd.Timestamp(f"{y + 1}-03-15"))
        lo = c[(c.index >= f"{y}-11-19") & (c.index <= f"{y + 1}-03-15")]
        if pd.notna(a) and pd.notna(b) and len(lo):
            est[f"{y}-{y + 1}"] = {"19nov_a_15mar": round(float(b / a - 1), 3), "min_vs_19nov": round(float(lo.min() / a - 1), 3),
                                    "fecha_min": str(lo.idxmin().date()), "max_vs_19nov": round(float(lo.max() / a - 1), 3),
                                    "fecha_max": str(lo.idxmax().date())}
    r["nov_a_mar"] = est
    (out / "spce.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: r[k] for k in ("hoy", "vuelos", "reportes_resumen", "nov_a_mar") if k in r}, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/spce")
