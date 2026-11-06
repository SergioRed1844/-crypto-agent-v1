"""Correlaciones y estudio de eventos geopolíticos para la cartera de Sergio y los temas del día (petróleo/Irán,
centros de datos, robots humanoides, defensa, oro, solar, salud). Corre en GitHub Actions (yfinance).
Uso: python -m core.correl OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

GRUPOS = {
    "cartera": ["LLY", "SPCE", "HWM", "UBER", "GOOG", "VRT", "NVDA", "ETH-USD", "DOGE-USD"],
    "mercado": ["SPY", "QQQ", "VT", "^VIX", "TLT", "GLD", "MXN=X"],
    "petroleo_guerra": ["BZ=F", "CL=F", "XLE", "ITA", "LMT", "NOC", "RTX"],
    "centros_datos": ["SOXX", "NVDA", "AVGO", "VRT", "GEV", "PWR", "CEG"],
    "robots_humanoides": ["BOTZ", "APH", "TEL", "TSLA", "6324.T", "6268.T"],
    "solar_salud": ["ICLN", "FSLR", "XLV", "UNH"],
    "cripto": ["BTC-USD"],
    "coberturas": ["CF", "NTR", "MOS", "XOM", "CVX", "COP", "OXY", "XOP", "BNO"],
}
# Choques geopolíticos con fecha conocida (día 0 = primer día hábil de EUA después del hecho).
EVENTOS = {
    "Rusia invade Ucrania (24-feb-2022)": "2022-02-24",
    "Ataque de Hamás a Israel (7-oct-2023)": "2023-10-09",
    "Irán ataca Israel con drones (13-abr-2024)": "2024-04-15",
    "Irán lanza misiles a Israel (1-oct-2024)": "2024-10-01",
    "Israel ataca Irán (13-jun-2025)": "2025-06-13",
    "EUA bombardea sitios nucleares de Irán (22-jun-2025)": "2025-06-23",
    "EUA e Israel atacan Irán; inicia crisis de Ormuz (28-feb-2026)": "2026-03-02",
}
# Días de alivio (tregua o apertura de Ormuz), para medir cuánto pierde una cobertura si hay acuerdo.
ALIVIOS = {
    "Tregua Israel–Irán (anuncio 23-jun-2025 por la noche)": "2025-06-24",
    "Tregua de 2 semanas y paso por Ormuz (7-abr-2026, 18:32 ET)": "2026-04-08",
    "Irán ofrece reabrir Ormuz en 2 días (1 y 2-nov-2026)": "2026-11-02",
}


def history(tks: list[str]) -> pd.DataFrame:
    import yfinance as yf
    for i in range(4):
        try:
            df = yf.download(tks, start="2021-06-01", auto_adjust=True, progress=False, threads=True)["Close"]
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001
            print("reintento", i, type(e).__name__, str(e)[:120])
        time.sleep(10 * (i + 1))
    return pd.DataFrame()


def rets(px: pd.DataFrame) -> pd.DataFrame:
    """Retornos diarios en días hábiles de EUA (las cripto y el yen se alinean al calendario de SPY)."""
    us = px["SPY"].dropna().index
    p = px.reindex(us).ffill(limit=3)
    return p.pct_change(fill_method=None)


def betas(r: pd.DataFrame, factor: str, desde: str) -> dict:
    x = r[factor].loc[desde:]
    out = {}
    for c in r.columns:
        if c == factor:
            continue
        y = r[c].loc[desde:]
        d = pd.concat([x, y], axis=1).dropna()
        if len(d) < 120:
            continue
        cov = np.cov(d.iloc[:, 0], d.iloc[:, 1])
        out[c] = {"beta": float(cov[0, 1] / cov[0, 0]), "corr": float(d.corr().iloc[0, 1]), "n": int(len(d))}
    return out


def condicional(r: pd.DataFrame, px: pd.DataFrame, mask: pd.Series, horizontes=(0, 5, 20)) -> dict:
    """Retorno medio de cada activo el día del choque y en los h días hábiles siguientes."""
    us = px["SPY"].dropna().index
    p = px.reindex(us).ffill(limit=3)
    dias = mask[mask].index
    out = {}
    for c in p.columns:
        s = p[c]
        res = {}
        for h in horizontes:
            vals = []
            for d in dias:
                i = s.index.get_loc(d)
                if i - 1 < 0 or i + h >= len(s):
                    continue
                a, b = s.iloc[i - 1], s.iloc[i + h]
                if pd.notna(a) and pd.notna(b) and a > 0:
                    vals.append(b / a - 1)
            res[f"d{h}"] = float(np.mean(vals)) if vals else None
            res[f"d{h}_pos"] = float(np.mean([v > 0 for v in vals])) if vals else None
        res["n"] = int(len(dias))
        out[c] = res
    return out


def eventos(px: pd.DataFrame, lista: dict | None = None) -> dict:
    us = px["SPY"].dropna().index
    p = px.reindex(us).ffill(limit=3)
    out = {}
    for nombre, f in (lista or EVENTOS).items():
        d = p.index[p.index >= pd.Timestamp(f)]
        if not len(d):
            continue
        i = p.index.get_loc(d[0])
        fila = {}
        for c in p.columns:
            s = p[c]
            base = s.iloc[i - 1] if i >= 1 else np.nan
            if pd.isna(base) or base <= 0:
                continue
            r = {}
            for h in (0, 5, 20, 60):
                if i + h < len(s) and pd.notna(s.iloc[i + h]):
                    r[f"d{h}"] = float(s.iloc[i + h] / base - 1)
            w = s.iloc[i:min(i + 21, len(s))]
            r["peor_20d"] = float(w.min() / base - 1) if len(w) else None
            fila[c] = r
        out[nombre] = {"dia0": str(p.index[i].date()), "activos": fila}
    return out


def main(out: str) -> int:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    tks = sorted({t for v in GRUPOS.values() for t in v})
    px = history(tks)
    print("historia", px.shape, "faltan", [t for t in tks if t not in px.columns or px[t].dropna().empty])
    r = rets(px)
    hoy = r.index[-1]
    c1 = r.loc[hoy - pd.Timedelta(days=365):].corr()
    c3 = r.loc[hoy - pd.Timedelta(days=3 * 365):].corr()
    res = {"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "grupos": GRUPOS,
           "corr_1a": c1.round(3).replace({np.nan: None}).to_dict(), "corr_3a": c3.round(3).replace({np.nan: None}).to_dict(),
           "beta_brent_1a": betas(r, "BZ=F", str((hoy - pd.Timedelta(days=365)).date())),
           "beta_spy_1a": betas(r, "SPY", str((hoy - pd.Timedelta(days=365)).date())),
           "beta_vix_1a": betas(r, "^VIX", str((hoy - pd.Timedelta(days=365)).date()))}
    brent = r["BZ=F"]
    vix = r["^VIX"]
    res["choque_petroleo"] = condicional(r, px, (brent >= 0.04).fillna(False))
    res["choque_vix"] = condicional(r, px, (vix >= 0.20).fillna(False))
    res["alivio_petroleo"] = condicional(r, px, (brent <= -0.04).fillna(False))
    res["eventos"] = eventos(px)
    res["alivios"] = eventos(px, ALIVIOS)
    # desempeño desde el inicio de la crisis de Ormuz y en el último mes
    us = px["SPY"].dropna().index
    p = px.reindex(us).ffill(limit=3)
    def ret(a, b=None):
        s = p.loc[a:b] if b else p.loc[a:]
        return (s.iloc[-1] / s.iloc[0] - 1).round(4).replace({np.nan: None}).to_dict()
    res["desde_27feb26"] = ret("2026-02-27")
    res["ultimo_mes"] = ret(str((hoy - pd.Timedelta(days=31)).date()))
    json.dump(res, open(o / "correl.json", "w"), indent=1, default=str)
    c1.round(3).to_csv(o / "corr_1a.csv")
    r.loc["2024-01-01":].round(5).to_csv(o / "rets_diarios.csv")
    print(json.dumps({k: res[k] for k in ("desde_27feb26",)}, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
