"""Carga de la lista de reportes y de las filas (Open Cabinet + nuestro parser), con montos normalizados."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .parse278t import LOWER, UPPER

ROOT = Path(__file__).resolve().parent.parent
FILINGS = ROOT / "data" / "copytrade" / "filings.csv"


def filings() -> list[dict]:
    return list(csv.DictReader(open(FILINGS)))


def _oid(url: str) -> str:
    m = re.search(r"PAS\+Index/([0-9A-F]{32})/", url)
    return m.group(1) if m else url


def filing_key_of(url: str) -> str | None:
    want = _oid(url)
    for f in filings():
        if _oid(f["url"]) == want:
            return f["key"]
    return None


def lower_of(amount: str) -> int | None:
    m = re.match(r"\s*\$?([\d,]+)", amount or "")
    if not m:
        return None
    v = int(m.group(1).replace(",", ""))
    return v if v in UPPER else None


def mid(lower: int, how: str = "mid") -> float:
    up = UPPER[lower] or lower * 2
    if how == "lower":
        return float(lower)
    if how == "geo":
        return (lower * up) ** 0.5
    if how == "equal":
        return 1.0
    return (lower + up) / 2


def oc_rows(path: str) -> list[dict]:
    """Filas de Trump del CSV público de Open Cabinet (la primera línea es un comentario)."""
    with open(path, newline="") as fh:
        first = fh.readline()
        if not first.startswith("#"):
            fh.seek(0)
        out = []
        for r in csv.DictReader(fh):
            if not r["official_name"].startswith("Trump, Donald"):
                continue
            r["lower"] = lower_of(r["amount_range"])
            r["mid"] = mid(r["lower"]) if r["lower"] else 0.0
            r["description"] = r["description"]
            out.append(r)
    return out
