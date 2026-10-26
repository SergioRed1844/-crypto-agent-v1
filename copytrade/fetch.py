"""Descarga (en GitHub Actions) los PDF de OGE de la lista `data/copytrade/filings.csv`, el índice de reportes del
Presidente y las listas de tickers de la SEC/Nasdaq. Escribe en OUT/ (luego se publica en la rama `copytrade-data`).

    python -m copytrade.fetch OUT

Todo lo descargado es dato no confiable: solo se guarda, se extrae texto con pdftotext y se calcula su hash.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

UA = "CryptoAgent copytrade research (github-actions; 41898282+github-actions[bot]@users.noreply.github.com)"
MAX_PDF = 90 * 1024 * 1024          # límite de GitHub: 100 MB por archivo
INDEX_URLS = [
    "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index?OpenView&Start=1&Count=1000",
    "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index?ReadViewEntries&Start=1&Count=1000",
    "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index?ReadViewEntries&OutputFormat=JSON&Start=1&Count=1000",
    "https://extapps2.oge.gov/201/Presiden.nsf/President%20and%20Vice%20President%20Index?OpenView",
]
LISTS = {
    "sec_company_tickers_exchange.json": "https://www.sec.gov/files/company_tickers_exchange.json",
    "nasdaqlisted.txt": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "otherlisted.txt": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}


def get(cli: httpx.Client, url: str, tries: int = 4) -> httpx.Response | None:
    for i in range(tries):
        try:
            r = cli.get(url)
            if r.status_code == 200:
                return r
            print(f"  {r.status_code} {url}")
        except httpx.HTTPError as e:
            print(f"  error {type(e).__name__} {url}")
        time.sleep(3 * (i + 1))
    return None


def pdftext(pdf: Path, txt: Path) -> dict:
    subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], check=False)
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    pages = int(m.group(1)) if (m := re.search(r"^Pages:\s+(\d+)", info, re.M)) else 0
    words = len(txt.read_text(errors="replace").split()) if txt.exists() else 0
    return {"pages": pages, "words": words, "needs_ocr": pages > 0 and words < 60 * pages}


def main(out: str) -> int:
    out_p = Path(out)
    (out_p / "pdfs").mkdir(parents=True, exist_ok=True)
    (out_p / "text").mkdir(parents=True, exist_ok=True)
    (out_p / "index").mkdir(parents=True, exist_ok=True)
    (out_p / "lists").mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open("data/copytrade/filings.csv")))
    manifest = []
    with httpx.Client(headers={"User-Agent": UA}, timeout=120, follow_redirects=True) as cli:
        for name, url in LISTS.items():
            r = get(cli, url)
            if r is not None:
                (out_p / "lists" / name).write_bytes(r.content)
                print("lista", name, len(r.content))
        found = set()
        for i, url in enumerate(INDEX_URLS):
            r = get(cli, url, tries=2)
            if r is None:
                continue
            (out_p / "index" / f"index_{i}.html").write_bytes(r.content)
            for m in re.finditer(r'["\']([^"\']*\$FILE/[^"\']*Trump[^"\']*\.pdf)["\']', r.text, re.I):
                found.add(m.group(1))
        known = {r["url"].split("/PAS+Index/")[-1] for r in rows}
        extra = sorted(u for u in found if u.split("/PAS+Index/")[-1] not in known and "278" in u)
        for j, u in enumerate(extra):
            full = u if u.startswith("http") else "https://extapps2.oge.gov" + ("" if u.startswith("/") else "/") + u
            rows.append({"key": f"extra-{j}", "kind": "unknown", "url": full, "oc_posted": "", "label": u.split("/")[-1]})
        for r in rows:
            key = r["key"]
            resp = get(cli, r["url"])
            rec = {**r, "ok": resp is not None}
            if resp is not None:
                blob = resp.content
                rec.update(bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(),
                           last_modified=resp.headers.get("last-modified", ""))
                tmp = out_p / "pdfs" / f"{key}.pdf"
                tmp.write_bytes(blob)
                rec.update(pdftext(tmp, out_p / "text" / f"{key}.txt"))
                if len(blob) > MAX_PDF:
                    tmp.unlink()
                    rec["pdf_stored"] = False
                else:
                    rec["pdf_stored"] = True
            manifest.append(rec)
            print(key, rec.get("ok"), rec.get("bytes"), rec.get("pages"), rec.get("words"), rec.get("needs_ocr"))
            time.sleep(1.0)
    (out_p / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    return 0 if all(m["ok"] for m in manifest if not m["key"].startswith("extra")) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out/ct"))
