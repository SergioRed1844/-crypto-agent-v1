"""Busca una cripto por nombre en CoinGecko y trae su ficha: precio, capitalización, volumen, máximo histórico,
cambios, liquidez, contrato y si existe en Bitso. Para tokens con nombres repetidos devuelve todos los candidatos.
Uso: python -m core.buscar_cripto OUT_DIR consulta [consulta...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from core.memes import CG, get, serie


def ficha(cid: str) -> dict:
    js = get(f"{CG}/coins/{cid}?localization=false&tickers=true&market_data=true&community_data=false"
             "&developer_data=false&sparkline=false") or {}
    md = js.get("market_data") or {}
    u = lambda k: (md.get(k) or {}).get("usd") if isinstance(md.get(k), dict) else md.get(k)  # noqa: E731
    tick = js.get("tickers") or []
    mercados = sorted(({"exchange": (t.get("market") or {}).get("name"), "par": f"{t.get('base')}/{t.get('target')}",
                        "vol_usd": (t.get("converted_volume") or {}).get("usd"), "confianza": t.get("trust_score")}
                       for t in tick), key=lambda x: -(x["vol_usd"] or 0))[:10]
    s = serie(cid)
    hist = {}
    if len(s) > 5:
        hist = {"dias": int(len(s)), "primer_dato": str(s.index[0].date()), "min_365": float(s.min()),
                "max_365": float(s.max()), "fecha_max_365": str(s.idxmax().date()),
                "ret_7d": float(s.iloc[-1] / s.iloc[-8] - 1) if len(s) > 8 else None,
                "ret_30d": float(s.iloc[-1] / s.iloc[-31] - 1) if len(s) > 31 else None,
                "ultimos_10": {str(k.date()): float(v) for k, v in s.tail(10).items()}}
    return {"id": cid, "nombre": js.get("name"), "simbolo": js.get("symbol"), "categorias": js.get("categories"),
            "plataformas": js.get("platforms"), "fecha_genesis": js.get("genesis_date"),
            "precio": u("current_price"), "cap": u("market_cap"), "rank": js.get("market_cap_rank"),
            "fdv": u("fully_diluted_valuation"), "vol_24h": u("total_volume"),
            "ath": u("ath"), "ath_fecha": (md.get("ath_date") or {}).get("usd"), "vs_ath": (md.get("ath_change_percentage") or {}).get("usd"),
            "atl": u("atl"), "cambio_24h": md.get("price_change_percentage_24h"), "cambio_7d": md.get("price_change_percentage_7d"),
            "cambio_30d": md.get("price_change_percentage_30d"), "cambio_1a": md.get("price_change_percentage_1y"),
            "circulante": md.get("circulating_supply"), "total": md.get("total_supply"), "max": md.get("max_supply"),
            "mercados": mercados, "historia": hist}


def main(out_dir: str, consultas: list[str]) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    libros = get("https://api.bitso.com/v3/available_books/") or {}
    en_bitso = sorted({b["book"] for b in libros.get("payload", [])})
    res = {"generado": pd.Timestamp.utcnow().isoformat(), "bitso_libros": en_bitso, "consultas": {}}
    for q in consultas:
        js = get(f"{CG}/search?query={q}") or {}
        cands = (js.get("coins") or [])[:8]
        res["consultas"][q] = {"candidatos": [{k: c.get(k) for k in ("id", "name", "symbol", "market_cap_rank")} for c in cands],
                               "fichas": [ficha(c["id"]) for c in cands[:5]],
                               "en_bitso": [b for b in en_bitso if b.split("_")[0] == q.lower()]}
    (out / "buscar.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    for q, r in res["consultas"].items():
        for f in r["fichas"]:
            print(q, f["id"], f["simbolo"], f["precio"], f["cap"], f["vol_24h"], f["ath"], f["ath_fecha"], f["vs_ath"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/buscar", sys.argv[2:] or ["dodo"])
