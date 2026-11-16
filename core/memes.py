"""Memecoins y altcoins de alto riesgo: cuáles se pueden comprar en Bitso, qué tanto han caído y qué tanto amplifican
a BTC. Datos: Bitso (libros disponibles) y CoinGecko (mercado, máximo histórico, 1 año diario).
Uso: python -m core.memes OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (rebotes-bot; research)", "accept": "application/json"}
CG = "https://api.coingecko.com/api/v3"


def get(url: str, tries: int = 5):
    import requests
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 429:
                time.sleep(20 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            print("get", url[:80], type(e).__name__, str(e)[:100])
            time.sleep(5 * (i + 1))
    return None


def serie(cid: str) -> pd.Series:
    js = get(f"{CG}/coins/{cid}/market_chart?vs_currency=usd&days=365&interval=daily")
    if not js or "prices" not in js:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(int(t), unit="ms").normalize(): float(p) for t, p in js["prices"]})
    return s[~s.index.duplicated(keep="last")].sort_index()


def main(out: str) -> int:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    res = {"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    bk = get("https://api.bitso.com/v3/available_books/") or {}
    libros = sorted({b["book"] for b in bk.get("payload", [])})
    res["bitso_libros"] = libros
    bases = {b.split("_")[0] for b in libros}
    mk = get(f"{CG}/coins/markets?vs_currency=usd&category=meme-token&order=market_cap_desc&per_page=40&page=1"
             "&price_change_percentage=7d,30d,1y") or []
    extra = get(f"{CG}/coins/markets?vs_currency=usd&ids=bitcoin,ethereum,solana,hyperliquid,ripple,cardano"
                "&price_change_percentage=7d,30d,1y") or []
    filas = []
    for x in mk + extra:
        sym = (x.get("symbol") or "").lower()
        filas.append({"id": x["id"], "sym": sym, "nombre": x.get("name"), "en_bitso": sym in bases,
                      "libros_bitso": [b for b in libros if b.split("_")[0] == sym],
                      "precio": x.get("current_price"), "cap": x.get("market_cap"), "rank": x.get("market_cap_rank"),
                      "vol24": x.get("total_volume"), "ath": x.get("ath"), "ath_fecha": (x.get("ath_date") or "")[:10],
                      "vs_ath": x.get("ath_change_percentage"), "atl": x.get("atl"),
                      "r7d": x.get("price_change_percentage_7d_in_currency"), "r30d": x.get("price_change_percentage_30d_in_currency"),
                      "r1a": x.get("price_change_percentage_1y_in_currency")})
    res["mercado"] = filas
    # Serie de 1 año para BTC y los 10 memes más grandes (más los que estén en Bitso)
    elegidos = [f for f in filas if f["id"] not in ("bitcoin",)]
    memes = [f for f in elegidos if f in filas[:len(mk)]]
    top = memes[:10] + [f for f in memes[10:] if f["en_bitso"]][:6]
    btc = serie("bitcoin")
    time.sleep(3)
    stats = {}
    for f in top:
        s = serie(f["id"])
        time.sleep(3)
        if len(s) < 120 or btc.empty:
            continue
        d = pd.concat([np.log(btc).diff(), np.log(s).diff()], axis=1).dropna()
        d.columns = ["btc", "x"]
        b = float(np.cov(d.btc, d.x)[0, 1] / d.btc.var())
        dn = d[d.btc < 0]
        stats[f["id"]] = {"dias": int(len(s)), "vol_anual": float(d.x.std() * np.sqrt(365)), "beta_btc": b,
                          "beta_dias_baja": float(np.cov(dn.btc, dn.x)[0, 1] / dn.btc.var()), "corr_btc": float(d.corr().iloc[0, 1]),
                          "peor_caida_1a": float((s / s.cummax() - 1).min()), "max_1a": float(s.max()), "min_1a": float(s.min()),
                          "vs_min_1a": float(s.iloc[-1] / s.min() - 1),
                          "mejor_30d_1a": float((s / s.shift(30) - 1).max()), "peor_30d_1a": float((s / s.shift(30) - 1).min())}
    res["estadisticas_1a"] = stats
    json.dump(res, open(o / "memes.json", "w"), indent=1, default=str)
    print(json.dumps({"libros": len(libros), "memes": len(mk), "stats": list(stats)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
