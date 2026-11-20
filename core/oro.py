"""Oro, metales y materias primas: estado actual, guerras, crisis de liquidez y caídas profundas (20-nov-2026).

Eventos fijados antes de ver resultados (fechas de choques geopolíticos del modelo geopolítico del 4-nov y guerras previas).
Crisis de liquidez: detectadas automáticamente (S&P −15% o peor en 20 días hábiles).
Uso: python -m core.oro OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ACTIVOS = ["GC=F", "SI=F", "HG=F", "PL=F", "GDX", "COPX", "XLE", "ITA", "BZ=F", "CL=F", "DX-Y.NYB", "^TNX", "TLT",
           "^GSPC", "BTC-USD", "MXN=X", "CF", "URA"]
GUERRAS = {"11-sep (reapertura)": "2001-09-17", "Irak 2003": "2003-03-20", "Crimea 2014": "2014-03-03",
           "Ucrania 2022": "2022-02-24", "Hamás 2023": "2023-10-09", "Irán–Israel abr-2024": "2024-04-15",
           "Irán–Israel oct-2024": "2024-10-01", "Israel–Irán jun-2025": "2025-06-13", "EUA–Irán jun-2025": "2025-06-23",
           "Guerra EUA-Israel/Irán, Ormuz (2026)": "2026-03-02"}
ALIVIOS = {"Tregua 2 semanas (abr-2026)": "2026-04-08", "MoU Islamabad (jun-2026)": "2026-06-17",
           "Oferta de reabrir Ormuz (nov-2026)": "2026-11-02"}
H = [1, 5, 20, 60, 120]


def bajar(t: str) -> pd.Series:
    import yfinance as yf
    for i in range(4):
        try:
            df = yf.Ticker(t).history(period="max", auto_adjust=True)
            if df is not None and not df.empty:
                df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                s = df["Close"].dropna()
                return s[~s.index.duplicated()]
        except Exception as e:  # noqa: BLE001
            print("reintento", t, i, str(e)[:100])
        time.sleep(4 * (i + 1))
    return pd.Series(dtype=float)


def rsi(c: pd.Series, n: int = 14) -> float:
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n).mean()
    return round(float((100 - 100 / (1 + up / dn)).iloc[-1]), 1)


def ret(c: pd.Series, fecha, h: int, base: int = -1) -> float | None:
    """Retorno de (día del evento + base) a (día del evento + h). base=-1: desde el cierre previo."""
    i = c.index.searchsorted(pd.Timestamp(fecha))
    if i >= len(c) or i + base < 0 or i + h >= len(c):
        return None
    if c.index[i] - pd.Timestamp(fecha) > pd.Timedelta(days=5):
        return None
    return round(float(c.iloc[i + h] / c.iloc[i + base] - 1), 4)


def estado(c: pd.Series) -> dict:
    mx = c.cummax()
    return {"precio": round(float(c.iloc[-1]), 4), "fecha": str(c.index[-1].date()),
            "max_hist": round(float(c.max()), 4), "fecha_max": str(c.idxmax().date()),
            "vs_max_hist": round(float(c.iloc[-1] / c.max() - 1), 4),
            "vs_max_52s": round(float(c.iloc[-1] / c.iloc[-252:].max() - 1), 4),
            "min_52s": round(float(c.iloc[-252:].min()), 4),
            "vs_sma200": round(float(c.iloc[-1] / c.rolling(200).mean().iloc[-1] - 1), 4) if len(c) > 200 else None,
            "rsi14": rsi(c), "rsi_sem": rsi(c.resample("W-FRI").last()),
            "ytd": round(float(c.iloc[-1] / c[c.index < f"{c.index[-1].year}-01-01"].iloc[-1] - 1), 4)
            if (c.index < f"{c.index[-1].year}-01-01").any() else None,
            "peor_caida_hist": round(float((c / mx - 1).min()), 4)}


def episodios_caida(c: pd.Series, umbral: float) -> list[dict]:
    """Primer día en que cae ≥umbral desde su máximo; un episodio por cada nuevo máximo."""
    mx, out, activo = c.cummax(), [], False
    for i, (d, v) in enumerate(c.items()):
        if v >= mx.iloc[i] * 0.999:
            activo = False
        if not activo and v <= mx.iloc[i] * (1 - umbral):
            activo = True
            fila = {"fecha": str(d.date()), "precio": round(float(v), 2), "max_previo": round(float(mx.iloc[i]), 2)}
            for h in (60, 120, 250, 500):
                fila[f"{h}d"] = round(float(c.iloc[i + h] / v - 1), 3) if i + h < len(c) else None
            seg = c.iloc[i:i + 750]
            fila["piso_siguiente"] = round(float(seg.min() / v - 1), 3)
            fila["dias_al_piso"] = int((seg.index.get_loc(seg.idxmin())))
            fila["caida_total_desde_max"] = round(float(seg.min() / mx.iloc[i] - 1), 3)
            out.append(fila)
    return out


def crisis_liquidez(sp: pd.Series) -> list[str]:
    r20 = sp / sp.shift(20) - 1
    fechas, ult = [], None
    for d, v in r20.items():
        if v <= -0.15 and (ult is None or (d - ult).days > 120):
            fechas.append(str(d.date()))
            ult = d
    return fechas


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    px = {t: bajar(t) for t in ACTIVOS}
    px = {t: s for t, s in px.items() if len(s)}
    r = {"generado": pd.Timestamp.utcnow().isoformat(), "estado": {t: estado(s) for t, s in px.items()}}
    g = px["GC=F"]
    r["oro_caidas_25"] = episodios_caida(g, 0.25)
    r["oro_caidas_30"] = episodios_caida(g, 0.30)
    r["oro_caidas_35"] = episodios_caida(g, 0.35)
    # Días de −3% o peor en el oro
    rd = g.pct_change()
    dias = rd[rd <= -0.03].index
    fw = {h: [] for h in (20, 60, 120)}
    for d in dias:
        i = g.index.get_loc(d)
        for h in fw:
            if i + h < len(g):
                fw[h].append(g.iloc[i + h] / g.iloc[i] - 1)
    r["oro_tras_dia_-3"] = {"n": int(len(dias)), **{f"{h}d": {"mediana": round(float(np.median(v)), 3),
                                                             "pos": round(float(np.mean(np.array(v) > 0)), 2)}
                                                  for h, v in fw.items() if v}}
    # Eventos
    for nombre, evs in (("guerras", GUERRAS), ("alivios", ALIVIOS)):
        tab = {}
        for n, f in evs.items():
            tab[n] = {"fecha": f, **{t: {f"+{h}": ret(s, f, h) for h in H} for t, s in px.items()}}
        r[nombre] = tab
        med = {}
        for t in px:
            for h in H:
                v = [tab[n][t][f"+{h}"] for n in tab if tab[n][t][f"+{h}"] is not None]
                if v:
                    med.setdefault(t, {})[f"+{h}"] = {"mediana": round(float(np.median(v)), 4),
                                                      "pos": round(float(np.mean(np.array(v) > 0)), 2), "n": len(v)}
        r[nombre + "_resumen"] = med
    # Desde el inicio de la guerra de 2026
    r["desde_inicio_guerra_2026"] = {t: ret(s, "2026-03-02", len(s) - 1 - s.index.searchsorted(pd.Timestamp("2026-03-02")))
                                     for t, s in px.items()}
    # Crisis de liquidez (S&P −15% en 20 días)
    sp = px["^GSPC"]
    cl = crisis_liquidez(sp[sp.index >= "2000-01-01"])
    r["crisis_fechas"] = cl
    tab = {}
    for f in cl:
        tab[f] = {t: {"-20a0": ret(s, f, 0, -20), "+20": ret(s, f, 20, 0), "+60": ret(s, f, 60, 0)} for t, s in px.items()}
    r["crisis"] = tab
    # Correlaciones de retornos diarios
    df = pd.DataFrame({t: s for t, s in px.items()}).ffill().pct_change()
    for n, d0 in (("1a", 252), ("90d", 90)):
        c = df.iloc[-d0:].corr()
        r[f"corr_oro_{n}"] = {t: round(float(c.loc["GC=F", t]), 2) for t in c.columns if t != "GC=F"}
    # Beta de mineras al oro (1 año)
    x = df[["GC=F", "GDX"]].iloc[-252:].dropna()
    r["beta_gdx_oro_1a"] = round(float(np.polyfit(x["GC=F"], x["GDX"], 1)[0]), 2)
    (out / "oro.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(r["estado"]["GC=F"], indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/oro")
