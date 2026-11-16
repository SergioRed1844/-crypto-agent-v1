"""Precios de Bitso en MXN contra el precio en dólares × tipo de cambio (prima o descuento de Bitso).
Corre en GitHub Actions. Uso: python -m core.bitso OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (rebotes-bot; research)"}
LIBROS = {"eth_mxn": "ETH-USD", "doge_mxn": "DOGE-USD", "btc_mxn": "BTC-USD"}


def main(out: str) -> int:
    import requests
    import yfinance as yf
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    res = {"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    px = yf.download(list(LIBROS.values()) + ["MXN=X"], period="5d", interval="1m", progress=False, auto_adjust=True)["Close"].ffill().iloc[-1]
    res["mxn"] = float(px["MXN=X"])
    for libro, tk in LIBROS.items():
        try:
            js = requests.get(f"https://api.bitso.com/v3/ticker/?book={libro}", headers=UA, timeout=20).json()["payload"]
            ref = float(px[tk]) * res["mxn"]
            res[libro] = {k: js.get(k) for k in ("last", "bid", "ask", "high", "low", "vwap", "created_at")}
            res[libro].update({"usd": float(px[tk]), "ref_mxn": ref, "prima": float(js["last"]) / ref - 1})
        except Exception as e:  # noqa: BLE001
            res[libro] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    json.dump(res, open(o / "bitso.json", "w"), indent=1)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
