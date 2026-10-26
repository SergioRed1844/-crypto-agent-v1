"""Parser propio del texto OCR (pdftotext -layout o tesseract) de un 278-T de OGE. Sirve para VERIFICAR las filas
de Open Cabinet y para leer los reportes que Open Cabinet todavía no tiene. El OCR es ruidoso ("ourchaso",
"2/10/2028", "3,2312026"): cada campo se normaliza con reglas explícitas y lo que no se puede leer queda en None.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

LOWER = [1001, 15001, 50001, 100001, 250001, 500001, 1000001, 5000001, 25000001, 50000001]
UPPER = {1001: 15000, 15001: 50000, 50001: 100000, 100001: 250000, 250001: 500000, 500001: 1000000,
         1000001: 5000000, 5000001: 25000000, 25000001: 50000000, 50000001: None}
YN = r"(?:y\S{1,2}|v\S{1,2}|n\S{0,1}|n0|ne)"
ROW = re.compile(
    rf"^\s*(?P<n>[0-9IlO]{{1,4}})\s+(?P<desc>.+?)\s{{2,}}(?P<typ>\S(?:.{{0,16}}?\S)?)\s{{2,}}"
    rf"(?P<date>[0-9.,'\"](?:.{{0,14}}?\S)?)\s{{1,}}(?P<yn>{YN})\s+(?P<amt>[^\s].*\d.*)$", re.I)


@dataclass
class Row:
    n: int | None
    desc: str
    typ: str | None          # Purchase | Sale | None
    date: dt.date | None
    lower: int | None
    line: str


def norm_type(tok: str) -> str | None:
    t = tok.lower().replace(" ", "")
    if re.search(r"sa[l1i]|s[a@]le|^sal|sell", t):
        return "Sale"
    if re.search(r"rch|un:h|urc|chas|cha[aeos]|rcl|ch[ao]s|hase|ha[os][eo]|ourc|urch|n:h|oun|ra>a|uta|^[il|\\\[]?[dp]u|^[il|]?ou", t):
        return "Purchase"
    return None


def norm_amount(s: str) -> int | None:
    s = s.replace("O", "0").replace("o", "0").replace("D", "0").replace("S", "$").replace("s", "$")
    parts = re.split(r"[-•–—]|\s-\s", s, maxsplit=1)
    digits = re.sub(r"[^0-9]", "", parts[0])
    if not digits:
        return None
    v = int(digits)
    if v in UPPER:
        return v
    # "$1 000 001" leído como "1000001"; "$5o0,001" ya corregido; si sobra un dígito al frente ($→5), quitarlo
    if digits.startswith("5") and int(digits[1:] or 0) in UPPER:
        return int(digits[1:])
    return None


def _valid(m: int, d: int, y: int, lo: dt.date, hi: dt.date) -> dt.date | None:
    try:
        x = dt.date(y, m, d)
    except ValueError:
        return None
    return x if lo <= x <= hi else None


def norm_date(tok: str, lo: dt.date, hi: dt.date) -> dt.date | None:
    """Fecha m/d/aaaa con OCR ruidoso. Solo acepta fechas dentro de [lo, hi] (inicio del mandato … sello de OGE)."""
    t = re.sub(r"[,.lI|]", "/", re.sub(r"\s+", "", tok))
    cands: set[dt.date] = set()
    for yfix in (None, "6", "5"):
        u = t
        if yfix:
            if not re.search(r"202[0-9]$", u) or u[-1] in "56":
                continue
            u = u[:-1] + yfix                              # 2028 → 2026, 2023 → 2025 (OCR de 6/5)
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", u)
        if m:
            if (x := _valid(int(m[1]), int(m[2]), int(m[3]), lo, hi)):
                cands.add(x)
            continue
        dig = re.sub(r"\D", "", u)
        # el "/" se leyó como "1": probar todas las posiciones
        for i in range(1, 3):
            for j in range(i + 1, i + 4):
                for drop_i in (0, 1):
                    for drop_j in (0, 1):
                        mm, rest = dig[:i], dig[i + drop_i:]
                        k = j - i
                        dd, yy = rest[:k], rest[k + drop_j:]
                        if len(yy) == 4 and mm and dd and len(dd) <= 2:
                            if (x := _valid(int(mm), int(dd), int(yy), lo, hi)):
                                if drop_i and dig[i] != "1" or drop_j and rest[k] != "1":
                                    continue
                                cands.add(x)
        if cands:
            break
    return cands.pop() if len(cands) == 1 else None


def parse(text: str, lo: dt.date, hi: dt.date) -> list[Row]:
    out = []
    for line in text.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        n = m["n"].replace("I", "1").replace("l", "1").replace("O", "0")
        out.append(Row(int(n) if n.isdigit() else None, re.sub(r"\s+", " ", m["desc"]).strip(),
                       norm_type(m["typ"]), norm_date(m["date"], lo, hi), norm_amount(m["amt"]), line))
    return out


def received(text: str) -> dt.date | None:
    """Sello 'OGE Received 9/14/26' de la portada."""
    m = re.search(r"OGE\s+Rec\S*\s+(\d{1,2})/(\d{1,2})/(\d{2,4})", text, re.I)
    if not m:
        return None
    y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
    try:
        return dt.date(y, int(m[1]), int(m[2]))
    except ValueError:
        return None
