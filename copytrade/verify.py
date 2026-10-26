"""Verifica las filas de Open Cabinet contra nuestro parser del texto de cada PDF de OGE (por reporte).

    python -m copytrade.verify OC_CSV TEXT_DIR OUT_JSON

Métricas por reporte: filas de OC, filas leídas por nosotros, suma de montos, y % de filas de OC cuyo
(fecha, tipo, rango) aparece en nuestra lectura (multiconjunto) — y la similitud del nombre en las que casan.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import difflib
import json
import re
import sys
from pathlib import Path

from . import parse278t as P
from .data import filings, oc_rows, filing_key_of

TERM = dt.date(2025, 1, 20)


def _key(desc: str) -> str:
    return re.sub(r"[^A-Z0-9 ]", "", desc.upper())[:40]


def verify_filing(text: str, oc: list[dict], hi: dt.date) -> dict:
    lo = dt.date(2024, 12, 1)
    mine = P.parse(text, lo, hi)
    ours = collections.defaultdict(list)
    for r in mine:
        if r.date and r.typ and r.lower:
            ours[(r.date, r.typ, r.lower)].append(r)
    matched, sims, full = 0, [], 0
    for o in oc:
        k = (dt.date.fromisoformat(o["date"]), o["type"], int(o["lower"]))
        if ours.get(k):
            cand = ours[k]
            best = max(cand, key=lambda r: difflib.SequenceMatcher(None, _key(r.desc), _key(o["description"])).ratio())
            s = difflib.SequenceMatcher(None, _key(best.desc), _key(o["description"])).ratio()
            cand.remove(best)
            matched += 1
            sims.append(s)
            full += s >= 0.6
    nums = [r.n for r in mine if r.n]
    return {"oc_rows": len(oc), "parsed_rows": len(mine), "parsed_complete": sum(1 for r in mine if r.date and r.typ and r.lower),
            "max_row_no": max(nums) if nums else 0,
            "match_date_type_amount": round(matched / max(1, len(oc)), 4),
            "match_plus_name": round(full / max(1, len(oc)), 4),
            "median_name_sim": round(sorted(sims)[len(sims) // 2], 3) if sims else None,
            "oc_usd_mid": sum(float(o["mid"]) for o in oc),
            "parsed_usd_mid": sum((r.lower + (P.UPPER[r.lower] or r.lower)) / 2 for r in mine if r.lower),
            "received": str(P.received(text) or "")}


def main(oc_csv: str, text_dir: str, out: str) -> int:
    rows = oc_rows(oc_csv)
    by = collections.defaultdict(list)
    for r in rows:
        by[filing_key_of(r["source_filing_url"])].append(r)
    res = {}
    for f in filings():
        if f["kind"] != "278T":
            continue
        txt = Path(text_dir) / f"{f['key']}.txt"
        if not txt.exists():
            res[f["key"]] = {"oc_rows": len(by.get(f["key"], [])), "error": "sin texto"}
            continue
        hi = dt.date.fromisoformat(f["oc_posted"]) if f["oc_posted"] else dt.date.today()
        res[f["key"]] = verify_filing(txt.read_text(errors="replace"), by.get(f["key"], []), hi)
        print(f["key"], res[f["key"]])
    json.dump(res, open(out, "w"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
