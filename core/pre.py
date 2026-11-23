"""Foto del premarket: acciones de la cartera y vigiladas (con pre/post), futuros, tasas, dólar, oro, cripto en
Binance y Bitso, y pumps de ≥12% en 24 h en criptos chicas de Binance. Uso: python -m core.pre OUT_DIR
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from core.velas_cripto import get

ACCIONES = ["NVDA", "AVGO", "VRT", "HWM", "MSFT", "GOOG", "META", "UBER", "LLY", "SPCE", "AVAV", "AMD", "ANT", "CRWD", "ZS",
            "GLD", "IAU", "SMH", "QQQ", "SPY", "NU", "SE", "DASH", "AKAM", "RDDT"]
MACRO = {"S&P (ES)": "ES=F", "Nasdaq 100 (NQ)": "NQ=F", "Dow (YM)": "YM=F", "Oro (GC)": "GC=F", "WTI": "CL=F",
         "VIX": "^VIX", "Tasa 10 años": "^TNX", "Dólar (DXY)": "DX-Y.NYB", "Peso (USD/MXN)": "MXN=X"}
CRIPTO = ["BTCUSDT", "ETHUSDT", "DOGEUSDT", "PEPEUSDT", "DODOUSDT", "LISTAUSDT", "BERAUSDT", "MMTUSDT"]
BITSO = ["eth_mxn", "doge_usd", "pepe_usd", "pepe_mxn", "usd_mxn", "btc_mxn"]


def foto(t: str) -> dict:
    import yfinance as yf
    tk = yf.Ticker(t)
    d = tk.history(period="10d", interval="1d", auto_adjust=False)
    i = tk.history(period="2d", interval="1m", prepost=True, auto_adjust=False)
    if d.empty:
        return {"error": "sin datos"}
    hoy = pd.Timestamp.now("America/New_York").normalize()
    dd = d[d.index.tz_convert("America/New_York").normalize() < hoy] if d.index.tz is not None else d
    prev = float(dd.Close.iloc[-1]) if len(dd) else float(d.Close.iloc[-1])
    r = {"cierre_previo": prev, "fecha_previo": str(dd.index[-1].date()) if len(dd) else None}
    if not i.empty:
        u = i.dropna(subset=["Close"])
        r.update({"ultimo": float(u.Close.iloc[-1]), "hora_et": str(u.index[-1].tz_convert("America/New_York")),
                  "vs_previo": float(u.Close.iloc[-1] / prev - 1)})
        hoy_i = u[u.index.tz_convert("America/New_York").normalize() == hoy]
        if len(hoy_i):
            r.update({"min_hoy": float(hoy_i.Low.min()), "max_hoy": float(hoy_i.High.max()),
                      "vol_hoy": float(hoy_i.Volume.sum())})
    return r


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res: dict = {"generado": pd.Timestamp.now("UTC").isoformat(), "acciones": {}, "macro": {}, "cripto": {}, "bitso": {}}
    for t in ACCIONES:
        try:
            res["acciones"][t] = foto(t)
        except Exception as e:  # noqa: BLE001
            res["acciones"][t] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
    for k, t in MACRO.items():
        try:
            res["macro"][k] = foto(t)
        except Exception as e:  # noqa: BLE001
            res["macro"][k] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
    tick = {t["symbol"]: t for t in (get("https://data-api.binance.vision/api/v3/ticker/24hr") or [])}
    for s in CRIPTO:
        t = tick.get(s)
        if t:
            res["cripto"][s] = {k: float(t[k]) for k in ("lastPrice", "priceChangePercent", "highPrice", "lowPrice", "quoteVolume")}
    for b in BITSO:
        t = get("https://api.bitso.com/v3/ticker/", {"book": b})
        if t and t.get("payload"):
            res["bitso"][b] = {k: t["payload"].get(k) for k in ("last", "high", "low", "created_at")}
    pumps = []
    for s, t in tick.items():
        if s.endswith("USDT") and float(t.get("priceChangePercent") or 0) >= 12 and float(t.get("quoteVolume") or 0) >= 1e6:
            pumps.append({"sym": s, "cambio": float(t["priceChangePercent"]), "vol_m": round(float(t["quoteVolume"]) / 1e6, 2)})
    res["pumps_binance_12pct"] = sorted(pumps, key=lambda x: -x["cambio"])[:20]
    (out / "pre.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(len(res["acciones"]), len(res["cripto"]), len(pumps))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/pre")
