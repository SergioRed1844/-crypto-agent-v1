"""Niveles técnicos diarios (velas): promedios 20/50/200, ATR 14, mínimos/máximos recientes, pivotes clásicos y las
últimas velas. Uso: python -m core.niveles OUT_DIR TICKER [TICKER...]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


def niveles(df: pd.DataFrame) -> dict:
    df = df.dropna()
    c, h, l, o = df["Close"], df["High"], df["Low"], df["Open"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    last = df.iloc[-1]
    prev = df.iloc[-2]
    P = (prev.High + prev.Low + prev.Close) / 3
    velas = [{"fecha": str(i.date()), "o": float(r.Open), "h": float(r.High), "l": float(r.Low), "c": float(r.Close),
              "vol": float(r.Volume), "cuerpo": float(r.Close - r.Open), "mecha_inf": float(min(r.Open, r.Close) - r.Low),
              "mecha_sup": float(r.High - max(r.Open, r.Close))} for i, r in df.iloc[-10:].iterrows()]
    return {"fecha": str(df.index[-1].date()), "precio": float(c.iloc[-1]), "sma20": float(c.rolling(20).mean().iloc[-1]),
            "sma50": float(c.rolling(50).mean().iloc[-1]), "sma200": float(c.rolling(200).mean().iloc[-1]), "atr14": atr,
            "min_10d": float(l.iloc[-10:].min()), "max_10d": float(h.iloc[-10:].max()),
            "min_20d": float(l.iloc[-20:].min()), "max_20d": float(h.iloc[-20:].max()),
            "min_52s": float(l.iloc[-252:].min()), "fecha_min_52s": str(l.iloc[-252:].idxmin().date()),
            "max_52s": float(h.iloc[-252:].max()), "fecha_max_52s": str(h.iloc[-252:].idxmax().date()),
            "pivote_hoy": {"P": float(P), "S1": float(2 * P - prev.High), "S2": float(P - (prev.High - prev.Low)),
                           "R1": float(2 * P - prev.Low), "R2": float(P + (prev.High - prev.Low))},
            "vol_rel_hoy": float(last.Volume / df["Volume"].iloc[-21:-1].mean()), "velas": velas}


def main(out: str, tks: list[str]) -> int:
    import yfinance as yf
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    res = {"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for t in tks:
        try:
            df = yf.Ticker(t).history(period="2y", interval="1d", auto_adjust=True)
            res[t] = niveles(df) if len(df.dropna()) >= 3 else {"nota": f"solo {len(df)} días de historia"}
            if len(df.dropna()) >= 2:
                res[t]["cambio_dia"] = float(df.Close.iloc[-1] / df.Close.iloc[-2] - 1)
            ih = yf.Ticker(t).history(period="2d", interval="15m", auto_adjust=True)
            if len(ih):
                d = ih[ih.index.date == ih.index[-1].date()]
                vw = float((d.Close * d.Volume).sum() / max(d.Volume.sum(), 1))
                res[t]["intradia"] = {"apertura": float(d.Open.iloc[0]), "max": float(d.High.max()), "min": float(d.Low.min()),
                                      "ultimo": float(d.Close.iloc[-1]), "vwap": vw, "hora_ultima": str(d.index[-1])}
        except Exception as e:  # noqa: BLE001
            res[t] = {"error": f"{type(e).__name__}: {str(e)[:150]}"}
    json.dump(res, open(o / "niveles.json", "w"), indent=1, default=str)
    print(json.dumps({t: {k: res[t].get(k) for k in ("precio", "sma20", "sma50", "sma200", "atr14", "min_20d")} for t in tks}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:] or ["NVDA"]))
