"""Semana que viene: ¿el dinero sale de tecnología hacia oro/otros?, futuros del domingo, y qué tanto más pueden bajar
BTC/ETH/DOGE (estados parecidos al de hoy y probabilidad de tocar cada precio en 7 y 30 días).
Datos: yfinance. Uso: python -m core.semana OUT_DIR
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROTACION = {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "Chips (SMH)": "SMH", "Tecnología (XLK)": "XLK",
            "Pequeñas (IWM)": "IWM", "Consumo básico (XLP)": "XLP", "Salud (XLV)": "XLV", "Servicios públicos (XLU)": "XLU",
            "Energía (XLE)": "XLE", "Oro (GLD)": "GLD", "Mineras de oro (GDX)": "GDX", "Plata (SLV)": "SLV",
            "Bonos largos (TLT)": "TLT", "Cetes de EUA (SGOV)": "SGOV", "Dólar (DXY)": "DX-Y.NYB", "Tasa 10 años": "^TNX",
            "VIX": "^VIX", "BTC": "BTC-USD", "ETH": "ETH-USD", "DOGE": "DOGE-USD", "Peso (USD/MXN)": "MXN=X"}
FUTUROS = {"S&P (ES)": "ES=F", "Nasdaq 100 (NQ)": "NQ=F", "Oro (GC)": "GC=F", "Petróleo WTI": "CL=F", "BTC": "BTC-USD",
           "ETH": "ETH-USD", "Nikkei": "^N225"}
NIVELES = {"BTC-USD": [58400, 56000, 55130, 52500, 50000, 45000],
           "ETH-USD": [1700, 1650, 1600, 1565, 1538, 1500, 1450, 1400, 1300],
           "DOGE-USD": [0.053, 0.051, 0.050, 0.048, 0.0465, 0.045, 0.040, 0.035]}


def bajar(tks, **kw) -> pd.DataFrame:
    import yfinance as yf
    return yf.download(tks, progress=False, auto_adjust=True, **kw)


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n).mean()
    return 100 - 100 / (1 + up / dn)


def rendimientos(c: pd.Series, v: pd.Series | None) -> dict:
    c = c.dropna()
    if len(c) < 25:
        return {}
    r = {"ultimo": float(c.iloc[-1]), "fecha": str(c.index[-1].date()),
         "1d": float(c.iloc[-1] / c.iloc[-2] - 1), "5d": float(c.iloc[-1] / c.iloc[-6] - 1),
         "20d": float(c.iloc[-1] / c.iloc[-21] - 1)}
    oct1 = c[c.index >= "2026-10-01"]
    if len(oct1):
        r["desde_1oct"] = float(c.iloc[-1] / oct1.iloc[0] - 1)
    if v is not None:
        v = v.reindex(c.index).fillna(0) * c
        if v.iloc[-60:].mean() > 0:
            r["vol_5d_vs_60d"] = float(v.iloc[-5:].mean() / v.iloc[-65:-5].mean())
    return r


def prob_tocar(d: pd.DataFrame, niveles: list[float], dias: int, precio: float, vol_banda: float = .25) -> dict:
    """P(el mínimo de los siguientes `dias` toque cada nivel), en días con volatilidad de 20 días parecida a la de hoy.
    El nivel se expresa como distancia relativa al cierre, así que sirve para cualquier precio."""
    c, lo = d.Close, d.Low
    ret = np.log(c).diff()
    vol = ret.rolling(20).std() * np.sqrt(365)
    hoy = float(vol.iloc[-1])
    fut_min = pd.Series([lo.iloc[i + 1:i + dias + 1].min() if i + dias < len(c) else np.nan for i in range(len(c))], index=c.index)
    caida = (fut_min / c - 1)
    ok = caida.notna() & vol.between(hoy * (1 - vol_banda), hoy * (1 + vol_banda))
    x = caida[ok]
    res = {"vol20_hoy": round(hoy, 3), "n_dias": int(ok.sum()), "precio": precio,
           "caida_min_mediana": round(float(x.median()), 3), "p25": round(float(x.quantile(.25)), 3),
           "p10": round(float(x.quantile(.10)), 3)}
    res["niveles"] = {str(n): round(float((x <= n / precio - 1).mean()), 3) for n in niveles}
    return res


def analogos_btc(w: pd.DataFrame) -> dict:
    """Semanas con BTC ≥45% debajo de su máximo y RSI semanal 30–40 (como hoy). Qué pasó después."""
    c, lo = w.Close, w.Low
    dd = c / c.cummax() - 1
    rw = rsi(c)
    m = (dd <= -.45) & (dd >= -.70) & rw.between(30, 40)
    filas, ult = [], None
    for t in c.index[m]:
        i = c.index.get_loc(t)
        if i + 13 >= len(c):
            continue
        f = {"semana": str(t.date()), "rsi": round(float(rw.iloc[i]), 1), "dd": round(float(dd.iloc[i]), 3),
             "ret_1s": float(c.iloc[i + 1] / c.iloc[i] - 1), "ret_4s": float(c.iloc[i + 4] / c.iloc[i] - 1),
             "ret_13s": float(c.iloc[i + 13] / c.iloc[i] - 1),
             "min_4s": float(lo.iloc[i + 1:i + 5].min() / c.iloc[i] - 1), "min_13s": float(lo.iloc[i + 1:i + 14].min() / c.iloc[i] - 1)}
        f["episodio"] = str(t.year) if ult is None or (t - ult).days > 120 else filas[-1]["episodio"]
        ult = t
        filas.append(f)
    if not filas:
        return {"n": 0}
    x = pd.DataFrame(filas)
    res = {"n_semanas": int(len(x)), "episodios": sorted(x.episodio.unique().tolist())}
    for k in ("ret_1s", "ret_4s", "ret_13s", "min_4s", "min_13s"):
        res[k] = {"mediana": round(float(x[k].median()), 3), "p25": round(float(x[k].quantile(.25)), 3),
                  "p75": round(float(x[k].quantile(.75)), 3), "pos": round(float((x[k] > 0).mean()), 2)}
    res["P_otro_-10_en_4s"] = round(float((x.min_4s <= -.10).mean()), 2)
    res["P_otro_-20_en_13s"] = round(float((x.min_13s <= -.20).mean()), 2)
    res["por_episodio"] = {e: {"semanas": int(len(g)), "ret_13s_med": round(float(g.ret_13s.median()), 3),
                               "min_13s_med": round(float(g.min_13s.median()), 3)} for e, g in x.groupby("episodio")}
    return res


def tech_y_cripto(dd: pd.DataFrame) -> dict:
    """Semanas en que el Nasdaq cayó ≥3%: qué hizo BTC esa semana y la siguiente; correlación de 90 días."""
    q, b = dd["^IXIC"].dropna(), dd["BTC-USD"].dropna()
    idx = q.index.intersection(b.index)
    q, b = q.loc[idx], b.loc[idx]
    rq, rb = q.pct_change(), b.pct_change()
    res = {"corr_90d": round(float(rq.iloc[-90:].corr(rb.iloc[-90:])), 2),
           "beta_90d": round(float(rq.iloc[-90:].cov(rb.iloc[-90:]) / rq.iloc[-90:].var()), 2)}
    qw, bw = q.resample("W-FRI").last(), b.resample("W-FRI").last()
    wq, wb = qw.pct_change(), bw.pct_change()
    m = wq <= -.03
    sig = wb.shift(-1)
    res["semanas_nasdaq_-3"] = int(m.sum())
    res["btc_misma_semana_med"] = round(float(wb[m].median()), 3)
    res["btc_semana_sig_med"] = round(float(sig[m].dropna().median()), 3)
    res["btc_semana_sig_pos"] = round(float((sig[m].dropna() > 0).mean()), 2)
    return res


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res: dict = {"generado": pd.Timestamp.now("UTC").isoformat()}
    tks = list(ROTACION.values())
    d = bajar(tks, period="2y", interval="1d")
    res["rotacion"] = {k: rendimientos(d["Close"][t], d["Volume"][t] if t in d["Volume"] else None) for k, t in ROTACION.items()}
    # futuros del domingo en la noche contra el cierre del viernes
    fut = {}
    for k, t in FUTUROS.items():
        try:
            h = bajar(t, period="5d", interval="1h")["Close"].squeeze().dropna()
            dly = bajar(t, period="10d", interval="1d")["Close"].squeeze().dropna()
            vie = dly[dly.index.dayofweek == 4]
            fut[k] = {"ultimo": float(h.iloc[-1]), "hora_utc": str(h.index[-1]),
                      "cierre_viernes": float(vie.iloc[-1]) if len(vie) else None,
                      "vs_viernes": float(h.iloc[-1] / vie.iloc[-1] - 1) if len(vie) else None}
        except Exception as e:  # noqa: BLE001
            fut[k] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    res["futuros"] = fut
    largo = bajar(list(NIVELES) + ["^IXIC"], period="max", interval="1d")
    res["prob_tocar"] = {}
    for t, nv in NIVELES.items():
        x = pd.DataFrame({k: largo[k][t] for k in ("Close", "Low")}).dropna()
        x = x[x.index >= "2018-01-01"]
        p = float(x.Close.iloc[-1])
        res["prob_tocar"][t] = {"7d": prob_tocar(x, nv, 7, p), "30d": prob_tocar(x, nv, 30, p)}
    w = bajar("BTC-USD", period="max", interval="1wk")
    w = pd.DataFrame({k: w[k].squeeze() for k in ("Close", "Low")}).dropna()
    res["btc_hoy"] = {"rsi_sem": round(float(rsi(w.Close).iloc[-1]), 1), "dd": round(float(w.Close.iloc[-1] / w.Close.max() - 1), 3),
                      "sma200s": float(w.Close.rolling(200).mean().iloc[-1])}
    res["analogos_btc"] = analogos_btc(w)
    res["tech_y_cripto"] = tech_y_cripto(largo["Close"])
    (out / "semana.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(res["futuros"], default=str)[:1500])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/semana")
