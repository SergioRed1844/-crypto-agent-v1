"""Arma la tabla final de operaciones (una fila por operación) con fecha de publicación, clase de activo y ticker.

    python -m copytrade.build [FILINGS_DIR] OUT_CSV

FILINGS_DIR (opcional) = carpeta `filings/` de la rama copytrade-data: MANIFEST.json (Last-Modified) y text/*.txt
(sello "OGE Received" y firmas digitales). La publicación de cada reporte es la fecha más tardía entre la que da
Open Cabinet, el sello de recepción, la última firma digital de OGE y el Last-Modified del PDF en el servidor:
nunca se le atribuye al copiador información antes de que existiera.
"""
from __future__ import annotations

import csv
import datetime as dt
import email.utils
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

from . import parse278t as P
from .data import ROOT, filings, mid
from .resolve import resolve

TERM_START = dt.date(2025, 1, 20)
OC = ROOT / "data" / "copytrade" / "oc_trump_rows.csv.gz"
MANUAL = ROOT / "data" / "copytrade" / "manual_2026-09-17.csv"


def publication_dates(fdir: Path | None) -> dict[str, dict]:
    man = {}
    if fdir and (fdir / "MANIFEST.json").exists():
        man = {m["key"]: m for m in json.load(open(fdir / "MANIFEST.json"))}
    out = {}
    for f in filings():
        k = f["key"]
        cand = {}
        if f["oc_posted"]:
            cand["open_cabinet"] = dt.date.fromisoformat(f["oc_posted"])
        lm = man.get(k, {}).get("last_modified")
        if lm:
            cand["last_modified"] = email.utils.parsedate_to_datetime(lm).date()
        txt = fdir / "text" / f"{k}.txt" if fdir else None
        if txt and txt.exists():
            t = txt.read_text(errors="replace")
            if (r := P.received(t)):
                cand["oge_received"] = r
            sig = [dt.date(int(a), int(b), int(c)) for a, b, c in re.findall(r"Date: (20\d\d)\.(\d\d)\.(\d\d)", t)]
            if sig:
                cand["ultima_firma"] = max(sig)
        pub = max(cand.values()) if cand else None
        out[k] = {"pub": pub, **{a: str(b) for a, b in cand.items()}}
    return out


def rows_oc() -> list[dict]:
    with gzip.open(OC, "rt", newline="") as fh:
        return list(csv.DictReader(fh))


def rows_manual() -> list[dict]:
    out = []
    for r in csv.DictReader(open(MANUAL)):
        out.append({"recordId": f"m0917-{int(r['n']):03d}", "filing_key": "2026-09-17", "source_kind": "278-T",
                    "periodic_status": "reported", "date_scope": "", "description": r["description"],
                    "type": r["type"], "date": r["date"], "lower": r["lower"], "instrument_type": "",
                    "resolved_ticker": "", "oc_rt": "", "oc_rule": "", "oc_cands": "",
                    "verificationState": "transcripción visual", "source_page": r["page"], "source_row": r["n"],
                    "account_label": ""})
    return out


def build(fdir: Path | None) -> tuple[list[dict], dict]:
    pubs = publication_dates(fdir)
    out, drop = [], Counter()
    for r in rows_oc() + rows_manual():
        d = dt.date.fromisoformat(r["date"])
        if d < TERM_START or r.get("periodic_status") == "pre-service":
            drop["antes del mandato"] += 1
            continue
        lower = int(float(r["lower"])) if r["lower"] else None
        if not lower:
            drop["monto ilegible"] += 1
            continue
        res = resolve(r["description"], d, r)
        pub = pubs.get(r["filing_key"], {}).get("pub")
        out.append({"id": r["recordId"], "filing": r["filing_key"], "kind": r["source_kind"],
                    "status": r["periodic_status"], "date": str(d), "pub": str(pub) if pub else "",
                    "type": r["type"], "lower": lower, "mid": mid(lower), "description": r["description"],
                    "cls": res["cls"], "ticker": res["ticker"] or "", "how": res["how"], "proxy": int(res["proxy"]),
                    "account": r.get("account_label", ""), "verif": r.get("verificationState", "")})
    return out, {"dropped": dict(drop), "publication": {k: {a: str(b) for a, b in v.items()} for k, v in pubs.items()}}


def main(argv: list[str]) -> int:
    fdir = Path(argv[0]) if len(argv) > 1 else None
    out_csv = Path(argv[-1])
    rows, meta = build(fdir)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    json.dump(meta, open(out_csv.with_suffix(".meta.json"), "w"), indent=1, default=str)
    usd = Counter()
    for r in rows:
        usd[(r["cls"], bool(r["ticker"]))] += r["mid"]
    for k, v in sorted(usd.items(), key=lambda x: -x[1]):
        print(f"{k[0]:9s} {'con ticker' if k[1] else 'SIN':10s} ${v/1e6:10.1f} M")
    print(len(rows), meta["dropped"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
