"""Clase de activo y ticker (o proxy) para cada operación.

Orden de resolución para acciones/ETF/fondos (la primera que responde gana; se guarda cuál fue):
  1. `data/copytrade/overrides.csv` (revisión manual, con motivo)
  2. ticker impreso en la descripción, p. ej. "Republic Airways Holdings Inc. (RJET)"
  3. resolución de Open Cabinet (`resolved_ticker` o `oc_rt`; candidatos únicos o clases de la misma empresa)
  4. nombre normalizado igual a uno de las listas Nasdaq/NYSE/SEC (exacto, luego prefijo único ≥ 10 letras)
Bonos y efectivo van a un ETF proxy del mismo segmento según el vencimiento (pre-registro).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "copytrade" / "ref"
OVERRIDES = ROOT / "data" / "copytrade" / "overrides.csv"

MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                       "DEC"], 1)}
NOISE = r"\b(UNSOLICITED|SOLICITED|DISCRETIONARY|ORDER|DISCRETION|EXERCISED|COMMON STOCK|COMMON|COM NEW|COM|NEW|" \
        r"ORD SHS|ORDINARY SHARES|SHS|ADR|SPONSORED|AMERICAN DEPOSITARY SHARES?|REIT|CL [A-C]|CLASS [A-C]|" \
        r"INC|INCORPORATED|CORPORATION|CORP|CO|COMPANY|LTD|LIMITED|PLC|LLC|L P|LP|N V|NV|S A|SA|AG|SE|THE|F|" \
        r"HOLDINGS|HLDGS|HOLDING|GROUP|GRP|DEL|OH|OHIO|IRELAND)\b"
ABBR = {"INTL": "INTERNATIONAL", "TECHNOLOGIES": "TECH", "TECHNOLOGY": "TECH", "TECHNOL": "TECH", "TECHNOLO": "TECH",
        "TECHN": "TECH", "FINL": "FINANCIAL", "SVCS": "SERVICES", "SVC": "SERVICE", "MGMT": "MANAGEMENT",
        "PPTYS": "PROPERTIES", "PPTY": "PROPERTY", "TR": "TRUST", "INDS": "INDUSTRIES", "MATLS": "MATERIALS",
        "PHARMACEUTICALS": "PHARMA", "PHARMACEUTICAL": "PHARMA", "SYS": "SYSTEMS", "BANCORPORATION": "BANCORP",
        "COMMUNICATIONS": "COMM", "COMMUNICATION": "COMM", "ENTMT": "ENTERTAINMENT", "MFG": "MANUFACTURING",
        "AMERN": "AMERICAN", "NATL": "NATIONAL", "ELEC": "ELECTRIC", "INVT": "INVESTMENT", "PMTS": "PAYMENTS",
        "WHSL": "WHOLESALE", "MTRS": "MOTORS", "PETE": "PETROLEUM", "RLTY": "REALTY", "MTG": "MORTGAGE",
        "AUTOMOTIVE": "AUTO", "LABS": "LABORATORIES", "LAB": "LABORATORIES", "CAP": "CAPITAL", "BK": "BANK",
        "SOLUTIONS": "SOLUTION", "SEC": "SECURITY", "&": "AND", "SCIENCES": "SCIENCE", "MACHS": "MACHINES",
        "PROD": "PRODUCTS", "CHEMICAL": "CHEMICALS", "PROCESSNG": "PROCESSING", "DEVICES": "DEVICE"}


def norm(name: str) -> str:
    s = name.upper()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\bDISCRETIONARY ORDER.*$|\bJ\.?P\.? MORGAN SECURITIES.*$|\bSOLICITED ORDER.*$", " ", s)
    s = s.replace(".COM", " COM").replace("-", " ").replace("/", " ").replace("&", " & ")
    s = re.sub(r"[^A-Z0-9& ]", " ", s)
    toks = [ABBR.get(t, t) for t in s.split()]
    s = " ".join(toks)
    for _ in range(2):
        s = re.sub(NOISE, " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def listings() -> tuple[dict[str, set[str]], dict[str, str], set[str]]:
    """nombre normalizado → tickers; ticker → nombre; tickers que son ETF."""
    by: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    etfs: set[str] = set()

    def add(nm: str, tk: str, etf: bool = False) -> None:
        tk = tk.strip().replace(".", "-").replace("$", "-P")
        if not tk or " " in tk or "-P" in tk:
            return
        if not etf and re.search(r"\b(Notes?|Debentures?|Preferred|Depositary Shares|Warrants?|Units?|Rights?|"
                                 r"Subordinated|Senior|Due \d{4}|Fixed|Floating|Perpetual)\b|%", nm, re.I):
            return                                          # solo acciones comunes (y ETF) entran al mapa
        nm = re.sub(r"\s+-\s+.*$", "", nm)               # "Apple Inc. - Common Stock" → "Apple Inc."
        nm = re.sub(r"\b(Common Stock|Class [A-C] Common Stock|Ordinary Shares|Common Shares)\b.*$", "", nm, flags=re.I)
        k = norm(nm)
        if k:
            by.setdefault(k, set()).add(tk)
            names.setdefault(tk, nm)
        if etf:
            etfs.add(tk)
    for fn in ("nasdaqlisted.txt", "otherlisted.txt"):
        p = REF / fn
        if not p.exists():
            continue
        rows = list(csv.reader(open(p), delimiter="|"))
        head = rows[0]
        si, ni = 0, head.index("Security Name")
        ei = head.index("ETF")
        ti = head.index("Test Issue")
        for r in rows[1:]:
            if len(r) < len(head) or r[ti] == "Y":
                continue
            add(r[ni], r[si], r[ei] == "Y")
    p = REF / "sec-company-tickers-exchange.json"
    if p.exists():
        d = json.load(open(p))
        for cik, nm, tk, ex in d["data"]:
            if ex in ("Nasdaq", "NYSE", "CBOE", "NYSE American", "NYSE Arca"):
                add(nm, tk)
    return by, names, etfs


@lru_cache(maxsize=1)
def overrides() -> dict[str, tuple[str, str]]:
    if not OVERRIDES.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(OVERRIDES)):
        out[norm(r["name"])] = (r["ticker"].strip(), r["reason"].strip())
    return out


# ----------------------------------------------------------------------------------------------- clase de activo
MUNI = re.compile(r"\b(CNTY|COUNTY|AUTH|SCH|SCHS|DIST|ISD|INDPT|RFDG|REF|B/E|BE/R|MUN|MUNI|TWP|HSG|HOSP|PSF|GTD|"
                  r"BDS|COMMN|BRD|BLDG|IMPT|PUB|UTIL|UTILS|WTR|SWR|TPK|TRAN|REV|RV|CTF|PARTN|COPS|GO|OBLIG|"
                  r"TEX|FLA|CALIF|MASS|STATE|ST|CITY|VLY|ENERGY AUTH|DEV|FING|FIN AUTH|HLTH|EDL|FACS|BAM|AGM|"
                  r"VAR|IDR|SYST|PURP|UNLT|UNLTD|UNIV|EDUC|TOB)\b")
BOND = re.compile(r"(\d+(\.\d+)?\s?%|\bDUE\b|\bDue\b|\bDTD\b|\bYTM\b|\bB/E\b|\bNOTES?\b|\bNTS\b|\bREGS?\b)", re.I)
PREF = re.compile(r"\b(PERP|ALT TIER|TIER I|PER \d|PFD|PREFERRED|DEP SHS|DEPOSITARY SH)\b|\bPER\s+\d", re.I)
MM = re.compile(r"MONEY MARKET|MONEY FUND|GOVERNMENT OBLIGATIONS|TREASURY OBLIGATIONS|GOVT OBLIG|CASH RESERVE|"
                r"LIQUIDITY FUND|TREASURY PORTFOLIO|GOVERNMENT PORTFOLIO|SWEEP", re.I)
TREAS = re.compile(r"\b(UNITED STATES TREAS|US TREAS|U S TREAS|TREASURY BILL|TREAS BILL|TREASURY NOTE|T-BILL)\b",
                   re.I)
FUND = re.compile(r"\b(ETF|ISHARES|VANGUARD|SPDR|INVESCO|SCHWAB|FIDELITY|PROSHARES|DIREXION|WISDOMTREE|"
                  r"STATE STREET|SELECT SECTOR|INDEX FUND|INDEX FDS|FUND|FD TR|TRUST ETF|GOLD TRUST)\b", re.I)


def maturity(desc: str) -> dt.date | None:
    d = desc.upper()
    m = re.search(r"DUE\s+([A-Z]{3})[A-Z]*\.?\s+(\d{1,2}),?\s+(\d{4})", d)
    if m and m[1][:3] in MONTHS:
        try:
            return dt.date(int(m[3]), MONTHS[m[1][:3]], int(m[2]))
        except ValueError:
            pass
    m = re.search(r"DUE\s+(\d{1,2})/(\d{1,2})/(\d{2,4})", d) or re.search(r"\b(\d{2})/(\d{2})/(\d{2,4})\b", d)
    if m:
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        try:
            return dt.date(y, int(m[1]), int(m[2]))
        except ValueError:
            pass
    m = re.search(r"DUE\s+(\d{2})(\d{2})(\d{2})\b", d)
    if m:
        try:
            return dt.date(2000 + int(m[3]), int(m[1]), int(m[2]))
        except ValueError:
            pass
    m = re.search(r"DUE\s+(\d{4})\b", d)
    if m and 2025 <= int(m[1]) <= 2080:
        return dt.date(int(m[1]), 6, 30)
    return None


def asset_class(desc: str, oc_type: str = "") -> str:
    d = desc.upper()
    if MM.search(d):
        return "mm"
    if TREAS.search(d):
        return "treasury"
    if PREF.search(d) and not re.search(r"\bETF\b", d):
        return "pref"
    if BOND.search(d) and (maturity(d) or re.search(r"\d\s?%", d)) and not re.search(r"\bETF\b|ISHARES|VANGUARD", d):
        return "muni" if MUNI.search(d) or oc_type == "municipal_bond" else "corp"
    if oc_type in ("etf", "mutual_fund") or FUND.search(d):
        return "fund"
    if oc_type == "option" or re.search(r"\b(CALL|PUT)\b.*\d", d):
        return "option"
    return "equity"


def bond_proxy(cls: str, desc: str, trade: dt.date) -> str:
    mat = maturity(desc)
    yrs = (mat - trade).days / 365.25 if mat else None
    if cls == "mm":
        return "BIL"
    if cls == "pref":
        return "PFF"
    if cls == "treasury":
        if yrs is None or yrs <= 1:
            return "BIL"
        return "SHY" if yrs <= 3 else "IEF" if yrs <= 10 else "TLT"
    if cls == "muni":
        return "SUB" if yrs is not None and yrs <= 3 else "MUB"
    if cls == "corp":
        if re.search(r"\bPERP\b", desc.upper()):
            return "PFF"
        if yrs is None:
            return "VCIT"
        return "VCSH" if yrs <= 3 else "VCIT" if yrs <= 10 else "VCLT"
    raise ValueError(cls)


def _same_company(cands: list[str]) -> str | None:
    """GOOG/GOOGL, BRK-A/BRK-B, FOX/FOXA…: si todos comparten raíz de nombre, la clase más líquida (la primera
    en orden alfabético con sufijo A/L, o la más corta)."""
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    _, names, _ = listings()
    ks = {norm(names.get(c, c)) for c in cands}
    if len(ks) == 1 or all(c[:3] == cands[0][:3] for c in cands):
        pref = {"GOOG": "GOOGL", "BRK-A": "BRK-B", "FOX": "FOXA", "NWS": "NWSA", "LEN-B": "LEN", "UA": "UAA",
                "HEI-A": "HEI", "BF-A": "BF-B"}
        c = sorted(cands, key=len)[0]
        return pref.get(c, c)
    return None


def ticker(desc: str, row: dict | None = None) -> tuple[str | None, str]:
    row = row or {}
    return _ticker(desc, row.get("resolved_ticker", ""), row.get("oc_rt", ""), row.get("oc_rule", ""),
                   row.get("oc_cands", ""))


@lru_cache(maxsize=None)
def _ticker(desc: str, resolved_ticker: str, oc_rt: str, oc_rule: str, oc_cands: str) -> tuple[str | None, str]:
    row = {"resolved_ticker": resolved_ticker, "oc_rt": oc_rt, "oc_rule": oc_rule, "oc_cands": oc_cands}
    k = norm(desc)
    ov = overrides()
    if k in ov:
        t, why = ov[k]
        return (t or None), "manual: " + why
    m = re.search(r"\(([A-Z]{1,5}(?:[.-][A-Z])?)\)", desc)
    by, names, _ = listings()
    known = {t for s in by.values() for t in s}
    if m and m.group(1).replace(".", "-") in known:
        return m.group(1).replace(".", "-"), "ticker impreso"
    for f in ("resolved_ticker", "oc_rt"):
        if row.get(f):
            return row[f].replace(".", "-"), "open cabinet " + (row.get("oc_rule") or f)
    if row.get("oc_cands"):
        c = _same_company([x.replace(".", "-") for x in row["oc_cands"].split("|")])
        if c:
            return c, "open cabinet candidatos"
    if k in by:
        c = _same_company(sorted(by[k]))
        if c:
            return c, "nombre exacto"
    if len(k) >= 10:
        hits = {kk for kk in by if kk.startswith(k)}
        if len(hits) == 1:
            c = _same_company(sorted(by[hits.pop()]))
            if c:
                return c, "prefijo único"
    return None, "sin mapeo"


def resolve(desc: str, trade: dt.date, row: dict | None = None) -> dict:
    row = row or {}
    cls = asset_class(desc, row.get("instrument_type", ""))
    if cls in ("mm", "treasury", "pref", "muni", "corp"):
        return {"cls": cls, "ticker": bond_proxy(cls, desc, trade), "how": "proxy " + cls, "proxy": True}
    if cls == "option":
        return {"cls": cls, "ticker": None, "how": "opción (fuera)", "proxy": False}
    t, how = ticker(desc, row)
    if cls == "fund" and t is None and MM.search(desc):
        return {"cls": "mm", "ticker": "BIL", "how": "proxy mm", "proxy": True}
    _, _, etfs = listings()
    if t:   # con ticker, la clase la decide la lista (ETF o no), no la palabra "FIDELITY"/"SCHWAB" del nombre
        cls = "fund" if (t in etfs or re.search(r"\b(ETF|ETN|FUND|FD|FDS|FDS TR|PORTFOLIO|GOLD TRUST)\b", desc.upper())) \
            else "equity"
    return {"cls": cls, "ticker": t, "how": how, "proxy": False}
