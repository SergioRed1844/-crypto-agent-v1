"""¿Llegó la cripto a su piso? Medidas clásicas de piso (caída desde el máximo histórico, precio contra promedio de
200 días = múltiplo de Mayer, precio contra promedio de 200 semanas, RSI semanal) y qué pasó después en el pasado
cuando estuvieron en niveles parecidos a los de hoy. Corre en GitHub Actions (yfinance). Uso: python -m core.cripto OUT
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

MONEDAS = ["BTC-USD", "ETH-USD", "DOGE-USD"]
OTROS = ["QQQ", "MXN=X"]


def history(tks: list[str]) -> pd.DataFrame:
    import yfinance as yf
    for i in range(4):
        try:
            df = yf.download(tks, start="2014-09-01", auto_adjust=True, progress=False, threads=True)["Close"]
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001
            print("reintento", i, type(e).__name__, str(e)[:120])
        time.sleep(10 * (i + 1))
    return pd.DataFrame()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def medidas(s: pd.Series) -> pd.DataFrame:
    """Serie diaria (calendario cripto, 7 días) → medidas de piso por día."""
    s = s.dropna()
    s = s[s > 0]
    df = pd.DataFrame({"p": s})
    df["ath"] = s.cummax()
    df["dd_ath"] = s / df["ath"] - 1
    df["max_365"] = s.rolling(365, min_periods=200).max()
    df["dd_365"] = s / df["max_365"] - 1
    df["mayer"] = s / s.rolling(200, min_periods=200).mean()
    df["vs_200s"] = s / s.rolling(1400, min_periods=1400).mean()
    w = s.resample("W-SUN").last()
    df["rsi_sem"] = rsi(w).reindex(df.index, method="ffill")
    return df


def adelante(df: pd.DataFrame, mask: pd.Series, hs=(30, 90, 180, 365)) -> dict:
    s = df["p"]
    idx = np.where(mask.values)[0]
    out = {"dias": int(len(idx)), "episodios": 0}
    if len(idx):
        out["episodios"] = int(1 + (np.diff(idx) > 60).sum())   # rachas separadas por >60 días
        out["primer_dia"] = str(df.index[idx[0]].date())
        out["ultimo_dia"] = str(df.index[idx[-1]].date())
    for h in hs:
        v = np.array([s.iloc[i + h] / s.iloc[i] - 1 for i in idx if i + h < len(s)])
        mn = [s.iloc[i:i + h + 1].min() / s.iloc[i] - 1 for i in idx if i + h < len(s)]
        if len(v):
            out[f"d{h}"] = {"mediana": float(np.median(v)), "pos": float((v > 0).mean()), "p10": float(np.percentile(v, 10)),
                            "p90": float(np.percentile(v, 90)), "peor_intermedio_mediana": float(np.median(mn)),
                            "peor_intermedio_p10": float(np.percentile(mn, 10)), "n": int(len(v))}
    return out


def pisos(df: pd.DataFrame) -> list[dict]:
    """Pisos históricos: mínimos de caída desde el máximo histórico ≤ −50%, separados por ≥ 365 días."""
    dd = df["dd_ath"]
    out, i = [], 0
    while i < len(dd):
        if dd.iloc[i] <= -0.5:
            j = i
            while j < len(dd) and dd.iloc[j] < -0.2:
                j += 1
            seg = dd.iloc[i:j]
            k = seg.idxmin()
            r = df.loc[k]
            out.append({"fecha": str(k.date()), "precio": float(r.p), "caida_desde_max": float(r.dd_ath),
                        "mayer": None if pd.isna(r.mayer) else float(r.mayer),
                        "vs_200s": None if pd.isna(r.vs_200s) else float(r.vs_200s),
                        "rsi_sem": None if pd.isna(r.rsi_sem) else float(r.rsi_sem),
                        "dias_desde_max": int((k - df.loc[:k, "p"].idxmax()).days)})
            i = j
        else:
            i += 1
    return out


def main(out: str) -> int:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    px = history(MONEDAS + OTROS)
    print("historia", px.shape)
    res = {"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for m in MONEDAS:
        df = medidas(px[m])
        hoy = df.iloc[-1]
        f = {"fecha": str(df.index[-1].date()), "precio": float(hoy.p), "ath": float(hoy.ath),
             "fecha_ath": str(df["p"].idxmax().date()), "dd_ath": float(hoy.dd_ath), "dd_365": float(hoy.dd_365),
             "mayer": None if pd.isna(hoy.mayer) else float(hoy.mayer),
             "vs_200s": None if pd.isna(hoy.vs_200s) else float(hoy.vs_200s),
             "media_200s": float(df["p"].rolling(1400).mean().iloc[-1]) if len(df) >= 1400 else None,
             "media_200d": float(df["p"].rolling(200).mean().iloc[-1]),
             "rsi_sem": None if pd.isna(hoy.rsi_sem) else float(hoy.rsi_sem),
             "r_7d": float(df.p.iloc[-1] / df.p.iloc[-8] - 1), "r_30d": float(df.p.iloc[-1] / df.p.iloc[-31] - 1),
             "r_90d": float(df.p.iloc[-1] / df.p.iloc[-91] - 1), "dias_desde_ath": int((df.index[-1] - df["p"].idxmax()).days)}
        # Análogos: días con múltiplo de Mayer y caída desde el máximo parecidos a hoy
        tol_m = 0.07
        tol_d = 0.07
        mk_m = (df["mayer"] - f["mayer"]).abs() <= tol_m if f["mayer"] else pd.Series(False, index=df.index)
        mk_d = (df["dd_ath"] - f["dd_ath"]).abs() <= tol_d
        f["analogos_mayer"] = adelante(df.iloc[:-1], mk_m.iloc[:-1])
        f["analogos_caida"] = adelante(df.iloc[:-1], mk_d.iloc[:-1])
        f["analogos_ambos"] = adelante(df.iloc[:-1], (mk_m & mk_d).iloc[:-1])
        f["zona_piso_mayer_lt_0_8"] = adelante(df.iloc[:-1], (df["mayer"] < 0.8).iloc[:-1])
        f["pisos_historicos"] = pisos(df)
        res[m] = f
    r = px.pct_change(fill_method=None)
    us = px["QQQ"].dropna().index
    rr = px.reindex(us).pct_change(fill_method=None).iloc[-90:]
    res["corr_90d_qqq"] = {m: float(rr[[m, "QQQ"]].dropna().corr().iloc[0, 1]) for m in MONEDAS}
    res["mxn"] = float(px["MXN=X"].dropna().iloc[-1])
    json.dump(res, open(o / "cripto.json", "w"), indent=1, default=str)
    for m in MONEDAS:
        print(m, {k: res[m][k] for k in ("precio", "dd_ath", "mayer", "vs_200s", "rsi_sem")})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
