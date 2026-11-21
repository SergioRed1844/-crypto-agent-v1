"""Velas de una cripto (Binance vía data-api.binance.vision; respaldo CoinGecko) y qué pasó después de subidas fuertes.
Uso: python -m core.velas_cripto OUT_DIR SIMBOLO_BINANCE COINGECKO_ID   (ej. DODOUSDT dodo)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BV = "https://data-api.binance.vision/api/v3/klines"


def get(url: str, params: dict | None = None, tries: int = 4):
    import requests
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "Mozilla/5.0 (rebotes-bot)"})
            if r.status_code == 429:
                time.sleep(15 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            print("get", url[:70], type(e).__name__, str(e)[:120])
            time.sleep(4 * (i + 1))
    return None


def klines(sym: str, interval: str, limit: int = 1000, start: int | None = None) -> pd.DataFrame:
    p = {"symbol": sym, "interval": interval, "limit": limit}
    if start:
        p["startTime"] = start
    js = get(BV, p)
    if not js:
        return pd.DataFrame()
    df = pd.DataFrame(js, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tb", "tq", "x"])
    df.index = pd.to_datetime(df.t, unit="ms")
    return df[["o", "h", "l", "c", "v", "qv", "n"]].astype(float)


def diario_completo(sym: str) -> pd.DataFrame:
    partes, start = [], 1_500_000_000_000
    for _ in range(6):
        d = klines(sym, "1d", 1000, start)
        if d.empty:
            break
        partes.append(d)
        start = int(d.index[-1].value // 1_000_000) + 86_400_000
        if len(d) < 1000:
            break
    return pd.concat(partes).sort_index() if partes else pd.DataFrame()


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n).mean()
    return 100 - 100 / (1 + up / dn)


def estudio_subidas(d: pd.DataFrame, umbral: float, cond30: float | None = None) -> dict:
    c, h, lo = d.c, d.h, d.l
    r1 = c / c.shift(1) - 1
    r30 = c / c.shift(30) - 1
    m = r1 >= umbral
    if cond30 is not None:
        m &= r30 >= cond30
    filas = []
    for t in d.index[m]:
        i = d.index.get_loc(t)
        if i + 30 >= len(d):
            continue
        f = {"fecha": str(t.date()), "dia": round(float(r1.iloc[i]), 3)}
        for k in (1, 3, 7, 30):
            f[f"ret_{k}d"] = round(float(c.iloc[i + k] / c.iloc[i] - 1), 3)
        f["max_alto_1d"] = round(float(h.iloc[i + 1] / c.iloc[i] - 1), 3)
        f["max_alto_7d"] = round(float(h.iloc[i + 1:i + 8].max() / c.iloc[i] - 1), 3)
        f["min_bajo_7d"] = round(float(lo.iloc[i + 1:i + 8].min() / c.iloc[i] - 1), 3)
        f["min_bajo_30d"] = round(float(lo.iloc[i + 1:i + 31].min() / c.iloc[i] - 1), 3)
        filas.append(f)
    if not filas:
        return {"n": 0}
    x = pd.DataFrame(filas)
    res = {"n": int(len(x)), "eventos": filas[-12:]}
    for k in ["ret_1d", "ret_3d", "ret_7d", "ret_30d", "max_alto_1d", "max_alto_7d", "min_bajo_7d", "min_bajo_30d"]:
        res[k] = {"mediana": round(float(x[k].median()), 3), "pos": round(float((x[k] > 0).mean()), 2),
                  "p75": round(float(x[k].quantile(.75)), 3), "p25": round(float(x[k].quantile(.25)), 3)}
    res["prob_+50_en_7d"] = round(float((x.max_alto_7d >= .5).mean()), 2)
    res["prob_+300_en_30d"] = None
    return res


def estudio_horas(hh: pd.DataFrame, umbral: float) -> dict:
    c, h, lo = hh.c, hh.h, hh.l
    r24 = c / c.shift(24) - 1
    sel, ult = [], None
    for t, v in r24.items():
        if v >= umbral and (ult is None or (t - ult) > pd.Timedelta(hours=24)):
            sel.append(t)
            ult = t
    filas = []
    for t in sel:
        i = hh.index.get_loc(t)
        if i + 24 >= len(hh):
            continue
        filas.append({"hora": str(t), "sube_24h": round(float(r24.loc[t]), 3),
                      "max_12h": round(float(h.iloc[i + 1:i + 13].max() / c.iloc[i] - 1), 3),
                      "min_12h": round(float(lo.iloc[i + 1:i + 13].min() / c.iloc[i] - 1), 3),
                      "ret_24h": round(float(c.iloc[i + 24] / c.iloc[i] - 1), 3)})
    if not filas:
        return {"n": 0}
    x = pd.DataFrame(filas)
    return {"n": int(len(x)), "eventos": filas[-10:],
            **{k: {"mediana": round(float(x[k].median()), 3), "pos": round(float((x[k] > 0).mean()), 2)}
               for k in ("max_12h", "min_12h", "ret_24h")},
            "prob_max12h_+50": round(float((x.max_12h >= .5).mean()), 2),
            "prob_max12h_+20": round(float((x.max_12h >= .2).mean()), 2)}


def main(out_dir: str, sym: str, cg: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    r = {"generado": pd.Timestamp.utcnow().isoformat(), "simbolo": sym}
    h1 = klines(sym, "1h", 1000)
    m15 = klines(sym, "15m", 200)
    d = diario_completo(sym)
    r["fuente"] = "binance" if not h1.empty else "sin datos de binance"
    if not h1.empty:
        c = h1.c
        u24 = h1.iloc[-24:]
        vwap24 = float((u24.qv.sum()) / u24.v.sum())
        tr = pd.concat([h1.h - h1.l, (h1.h - c.shift()).abs(), (h1.l - c.shift()).abs()], axis=1).max(axis=1)
        r["hora"] = {"ultimo": float(c.iloc[-1]), "hora": str(h1.index[-1]), "max_24h": float(u24.h.max()),
                     "min_24h": float(u24.l.min()), "vwap_24h": vwap24, "rsi14_1h": round(float(rsi(c).iloc[-1]), 1),
                     "atr14_1h": float(tr.rolling(14).mean().iloc[-1]),
                     "vol_24h_usdt": float(u24.qv.sum()),
                     "vol_vs_prom_30d": round(float(u24.qv.sum() / (h1.qv.iloc[-24 * 31:-24].sum() / 30)), 2)
                     if len(h1) > 24 * 31 else None,
                     "sma24": float(c.rolling(24).mean().iloc[-1]), "sma72": float(c.rolling(72).mean().iloc[-1]),
                     "ultimas_24": [{"h": str(t)[5:16], "o": round(float(x.o), 5), "h_": round(float(x.h), 5),
                                     "l": round(float(x.l), 5), "c": round(float(x.c), 5), "qv": int(x.qv)}
                                    for t, x in h1.iloc[-24:].iterrows()]}
        r["subidas_24h_+25"] = estudio_horas(h1, .25)
    if not m15.empty:
        r["m15_ultimas_16"] = [{"h": str(t)[5:16], "c": round(float(x.c), 5), "qv": int(x.qv)} for t, x in m15.iloc[-16:].iterrows()]
    if not d.empty:
        c = d.c
        r["diario"] = {"desde": str(d.index[0].date()), "dias": int(len(d)), "max_hist_cierre": float(c.max()),
                       "fecha_max": str(c.idxmax().date()), "ret_30d": round(float(c.iloc[-1] / c.iloc[-31] - 1), 3),
                       "rsi14_d": round(float(rsi(c).iloc[-1]), 1),
                       "max_365": float(d.h.iloc[-365:].max()), "min_365": float(d.l.iloc[-365:].min()),
                       "ultimos_10": {str(t.date()): [round(float(x.o), 5), round(float(x.h), 5), round(float(x.l), 5),
                                                      round(float(x.c), 5), int(x.qv)] for t, x in d.iloc[-10:].iterrows()}}
        r["dias_+20"] = estudio_subidas(d, .20)
        r["dias_+20_tras_30d_+60"] = estudio_subidas(d, .20, .60)
        r["dias_+25"] = estudio_subidas(d, .25)
        # ¿Cuántas veces subió +300% en 30 días desde cualquier día?
        fut_max = pd.Series([d.h.iloc[i + 1:i + 31].max() if i + 30 < len(d) else np.nan for i in range(len(d))], index=d.index)
        x = (fut_max / c - 1).dropna()
        r["prob_cualquier_dia_+50_en_30d"] = round(float((x >= .5).mean()), 3)
        r["prob_cualquier_dia_+300_en_30d"] = round(float((x >= 3).mean()), 4)
    (out / "velas.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: r[k] for k in r if k in ("hora", "diario")}, default=str)[:3000])


if __name__ == "__main__":
    a = sys.argv
    main(a[1] if len(a) > 1 else "out/velas", a[2] if len(a) > 2 else "DODOUSDT", a[3] if len(a) > 3 else "dodo")
