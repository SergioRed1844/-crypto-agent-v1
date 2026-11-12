"""Estudio de NVDA: caídas previas y lo que siguió, reacciones a reportes, movimiento implícito en opciones,
ETF apalancados (desgaste por volatilidad y peores caídas), empresas de alta beta ligadas a NVDA y salidas de CEO.
Corre en GitHub Actions (yfinance). Uso: python -m core.nvda OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

APALANCADOS = {"NVDL": ("NVDA", 2), "NVDU": ("NVDA", 2), "NVD": ("NVDA", -2), "SOXL": ("SOXX", 3), "TQQQ": ("QQQ", 3)}
LIGADAS = ["CRWV", "NBIS", "SMCI", "AMD", "AVGO", "TSM", "MU", "ARM", "VRT", "ORCL", "ANET", "DELL", "CLS", "IREN"]
BASE = ["NVDA", "SPY", "QQQ", "SOXX"]
# Salidas o crisis de CEO con fecha conocida (día 0 = primera sesión con la noticia).
CEO = {
    "Apple: renuncia Steve Jobs (24-ago-2011, tras el cierre)": ("AAPL", "2011-08-25"),
    "Intel: renuncia Krzanich por relación (21-jun-2018)": ("INTC", "2018-06-21"),
    "Tesla: demanda de la SEC a Musk (27-sep-2018, tras el cierre)": ("TSLA", "2018-09-28"),
    "McDonald's: despido de Easterbrook por relación (3-nov-2019, domingo)": ("MCD", "2019-11-04"),
    "Intel: sale Gelsinger (1-dic-2024, domingo)": ("INTC", "2024-12-02"),
}


def history(tks: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf
    for i in range(4):
        try:
            df = yf.download(tks, start=start, auto_adjust=True, progress=False, threads=True)["Close"]
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001
            print("reintento", i, type(e).__name__, str(e)[:120])
        time.sleep(10 * (i + 1))
    return pd.DataFrame()


def max_dd(s: pd.Series) -> float:
    s = s.dropna()
    return float((s / s.cummax() - 1).min()) if len(s) else float("nan")


def sintetico(r: pd.Series, lev: float) -> pd.Series:
    """Precio de un producto que rebalancea a diario con apalancamiento `lev` (sin comisiones ni costo de deuda)."""
    return (1 + (lev * r).clip(lower=-0.999)).cumprod()


def caidas_nvda(px: pd.Series, umbral: float = -0.08, sep: int = 20) -> dict:
    """Días en que NVDA cae ≥8% en 2 sesiones (separados ≥20 sesiones): qué pasó después, en NVDA y en un 2x diario."""
    r = px.pct_change(fill_method=None)
    r2 = px / px.shift(2) - 1
    x2 = sintetico(r.fillna(0), 2)
    dias, ult = [], -10_000
    for i, v in enumerate(r2.values):
        if pd.notna(v) and v <= umbral and i - ult >= sep:
            dias.append(i)
            ult = i
    filas = []
    for i in dias:
        f = {"fecha": str(px.index[i].date()), "caida_2d": float(r2.iloc[i]),
             "vs_max_52s": float(px.iloc[i] / px.iloc[max(0, i - 252):i + 1].max() - 1)}
        for h in (5, 20, 60, 120, 252):
            if i + h < len(px):
                f[f"d{h}"] = float(px.iloc[i + h] / px.iloc[i] - 1)
                f[f"x2_d{h}"] = float(x2.iloc[i + h] / x2.iloc[i] - 1)
        w = px.iloc[i:i + 61]
        f["peor_60d"] = float(w.min() / px.iloc[i] - 1)
        f["x2_peor_60d"] = float(x2.iloc[i:i + 61].min() / x2.iloc[i] - 1)
        filas.append(f)
    df = pd.DataFrame(filas)
    res = {"n": len(df), "eventos": filas}
    for h in (5, 20, 60, 120, 252):
        for p in ("", "x2_"):
            c = f"{p}d{h}"
            if c in df and df[c].notna().any():
                v = df[c].dropna()
                res[f"{c}_mediana"] = float(v.median())
                res[f"{c}_pos"] = float((v > 0).mean())
                res[f"{c}_peor"] = float(v.min())
    for c in ("peor_60d", "x2_peor_60d"):
        if c in df:
            res[f"{c}_mediana"] = float(df[c].median())
            res[f"{c}_peor"] = float(df[c].min())
    return res


def desde_maximo(px: pd.Series, lo=-0.35, hi=-0.20) -> dict:
    """Cuando NVDA estuvo entre -20% y -35% de su máximo de 52 semanas: retorno a 60/120/252 sesiones (días traslapados)."""
    m = px.rolling(252, min_periods=120).max()
    dd = px / m - 1
    idx = np.where((dd >= lo) & (dd <= hi))[0]
    out = {"dias": int(len(idx))}
    for h in (60, 120, 252):
        v = [px.iloc[i + h] / px.iloc[i] - 1 for i in idx if i + h < len(px)]
        if v:
            out[f"d{h}_mediana"] = float(np.median(v))
            out[f"d{h}_pos"] = float(np.mean(np.array(v) > 0))
            out[f"d{h}_p10"] = float(np.percentile(v, 10))
            out[f"d{h}_p90"] = float(np.percentile(v, 90))
    return out


def reportes(px: pd.Series) -> dict:
    import yfinance as yf
    try:
        ed = yf.Ticker("NVDA").get_earnings_dates(limit=40)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}
    if ed is None or ed.empty:
        return {"error": "sin fechas"}
    filas = []
    for ts in ed.index:
        d = pd.Timestamp(ts).tz_localize(None) if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts)
        if d > px.index[-1]:
            continue
        # NVDA reporta después del cierre: la reacción es la sesión siguiente.
        pos = px.index.searchsorted(d.normalize(), side="right")
        if pos >= len(px) or pos < 1:
            continue
        r1 = float(px.iloc[pos] / px.iloc[pos - 1] - 1)
        r5 = float(px.iloc[min(pos + 4, len(px) - 1)] / px.iloc[pos - 1] - 1)
        filas.append({"reporte": str(d.date()), "reaccion_1d": r1, "reaccion_5d": r5})
    df = pd.DataFrame(filas).drop_duplicates("reporte").sort_values("reporte")
    ult = df.tail(16)
    return {"ultimos": ult.to_dict(orient="records"), "n": int(len(ult)),
            "baja_1d": int((ult.reaccion_1d < 0).sum()), "mov_abs_medio": float(ult.reaccion_1d.abs().mean()),
            "mayor_baja": float(ult.reaccion_1d.min()), "mayor_alza": float(ult.reaccion_1d.max())}


def opciones(spot: float) -> dict:
    """Movimiento implícito: straddle ATM del primer vencimiento después del reporte del 17-nov."""
    import yfinance as yf
    t = yf.Ticker("NVDA")
    try:
        exps = list(t.options)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}
    out = {"vencimientos": exps[:8]}
    for e in exps:
        if e < "2026-11-18":
            continue
        try:
            ch = t.option_chain(e)
        except Exception as ex:  # noqa: BLE001
            out["error"] = str(ex)[:200]
            break
        c, p = ch.calls, ch.puts
        k = c.iloc[(c.strike - spot).abs().argsort()[:1]].strike.iloc[0]
        cr, pr = c[c.strike == k].iloc[0], p[p.strike == k].iloc[0]
        mid = lambda row: float((row.bid + row.ask) / 2) if row.bid > 0 and row.ask > 0 else float(row.lastPrice)
        st = mid(cr) + mid(pr)
        out.update({"vencimiento": e, "strike": float(k), "call": mid(cr), "put": mid(pr), "straddle": st,
                    "mov_implicito": st / spot, "iv_call": float(cr.impliedVolatility), "iv_put": float(pr.impliedVolatility),
                    "oi_put_call": float(p.openInterest.sum() / max(c.openInterest.sum(), 1)),
                    "vol_put_call": float(p.volume.fillna(0).sum() / max(c.volume.fillna(0).sum(), 1))})
        break
    return out


def main(out: str) -> int:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    tks = sorted(set(BASE + LIGADAS + list(APALANCADOS) + [v[0] for v in CEO.values()]))
    px = history(tks, "2010-01-01")
    print("historia", px.shape, "faltan", [t for t in tks if t not in px.columns or px[t].dropna().empty])
    nv = px["NVDA"].dropna()
    r = px.pct_change(fill_method=None)
    hoy = nv.index[-1]
    res = {"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ultimo_dia": str(hoy.date()),
           "nvda_precio": float(nv.iloc[-1])}
    # Volatilidad, beta a NVDA, correlación, peor caída 3 años y retornos recientes
    y1 = r.loc[hoy - pd.Timedelta(days=365):]
    perf = {}
    for t in tks:
        s = px[t].dropna()
        if len(s) < 30:
            continue
        a = y1[["NVDA", t]].dropna()
        b = float(np.cov(a["NVDA"], a[t])[0, 1] / a["NVDA"].var()) if len(a) > 60 and t != "NVDA" else None
        perf[t] = {"precio": float(s.iloc[-1]), "vol_1a": float(y1[t].std() * np.sqrt(252)),
                   "beta_nvda_1a": b, "corr_nvda_1a": float(a.corr().iloc[0, 1]) if len(a) > 60 else None,
                   "peor_caida_3a": max_dd(s.loc[hoy - pd.Timedelta(days=3 * 365):]),
                   "peor_caida_hist": max_dd(s), "inicio": str(s.index[0].date()),
                   "r_5d": float(s.iloc[-1] / s.iloc[-6] - 1) if len(s) > 6 else None,
                   "r_21d": float(s.iloc[-1] / s.iloc[-22] - 1) if len(s) > 22 else None,
                   "vs_max_52s": float(s.iloc[-1] / s.loc[hoy - pd.Timedelta(days=365):].max() - 1)}
    res["perf"] = perf
    # ETF apalancados: real contra L × subyacente en varias ventanas
    ap = {}
    for t, (u, lev) in APALANCADOS.items():
        if t not in px or px[t].dropna().empty:
            continue
        s, su = px[t].dropna(), px[u].dropna()
        f = {"subyacente": u, "lev": lev, "inicio": str(s.index[0].date())}
        for n in (21, 63, 126, 252, 504):
            if len(s) > n:
                ru = float(su.loc[s.index[-1 - n]:].iloc[-1] / su.loc[s.index[-1 - n]:].iloc[0] - 1)
                f[f"{n}d"] = {"etf": float(s.iloc[-1] / s.iloc[-1 - n] - 1), "subyacente": ru, "lev_x_sub": lev * ru}
        ap[t] = f
    res["apalancados"] = ap
    # 2x diario sintético de NVDA desde 2010: peores caídas por año y global
    x2 = sintetico(r["NVDA"].fillna(0), 2)
    x3s = sintetico(r["SOXX"].fillna(0), 3)
    res["sintetico"] = {"nvda_2x_peor_caida": max_dd(x2), "nvda_peor_caida": max_dd(nv),
                        "soxx_3x_peor_caida": max_dd(x3s),
                        "nvda_2x_peor_caida_3a": max_dd(x2.loc[hoy - pd.Timedelta(days=3 * 365):]),
                        "por_anio": {str(y): {"nvda": float(nv[nv.index.year == y].iloc[-1] / nv[nv.index.year == y].iloc[0] - 1),
                                               "nvda_2x": float(x2[x2.index.year == y].iloc[-1] / x2[x2.index.year == y].iloc[0] - 1),
                                               "nvda_dd": max_dd(nv[nv.index.year == y]), "nvda_2x_dd": max_dd(x2[x2.index.year == y])}
                                      for y in range(2015, hoy.year + 1)}}
    res["caidas_2d"] = caidas_nvda(nv)
    res["desde_maximo_20_35"] = desde_maximo(nv)
    res["soxl_desde_max_70_85"] = desde_maximo(px["SOXL"].dropna(), -0.85, -0.70)
    sx = px["SOXL"].dropna()
    res["soxl_dd_2022"] = {"max": float(sx.loc["2021-06":"2022-12"].max()), "min": float(sx.loc["2021-06":"2022-12"].min()),
                           "caida": float(sx.loc["2021-06":"2022-12"].min() / sx.loc["2021-06":"2022-12"].max() - 1)}
    res["reportes"] = reportes(nv)
    res["opciones"] = opciones(float(nv.iloc[-1]))
    # Salidas de CEO
    ceo = {}
    us = px["SPY"].dropna().index
    p = px.reindex(us).ffill(limit=3)
    for nombre, (t, f) in CEO.items():
        d = p.index[p.index >= pd.Timestamp(f)]
        if not len(d) or t not in p:
            continue
        i = p.index.get_loc(d[0])
        fila = {"ticker": t, "dia0": str(d[0].date())}
        for h in (0, 5, 20, 60, 252):
            if i + h < len(p):
                fila[f"d{h}"] = float(p[t].iloc[i + h] / p[t].iloc[i - 1] - 1)
                fila[f"spy_d{h}"] = float(p["SPY"].iloc[i + h] / p["SPY"].iloc[i - 1] - 1)
        fila["peor_60d"] = float(p[t].iloc[i:i + 61].min() / p[t].iloc[i - 1] - 1)
        ceo[nombre] = fila
    res["ceo"] = ceo
    json.dump(res, open(o / "nvda.json", "w"), indent=1, default=str)
    print(json.dumps({k: res[k] for k in ("ultimo_dia", "nvda_precio", "opciones")}, indent=1, default=str)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
