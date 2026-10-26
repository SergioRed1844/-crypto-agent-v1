"""Universo (iShares Russell 3000, respaldo listas Nasdaq/NYSE) y velas diarias ajustadas de Yahoo. Corre en Actions.

    python -m rebotes.data universe OUT_DIR
    python -m rebotes.data prices OUT_DIR          # usa OUT_DIR/universe.txt; guarda OUT_DIR/panel.npz
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C

IWV = ("https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/1467271812596.ajax"
       "?fileType=csv&fileName=IWV_holdings&dataType=fund")
LISTS = {"nasdaqlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
         "otherlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"}
UA = {"User-Agent": "Mozilla/5.0 (rebotes research; github-actions)"}
FIELDS = ("Open", "High", "Low", "Close", "Volume")


def _get(url: str) -> str | None:
    import httpx
    for i in range(3):
        try:
            r = httpx.get(url, headers=UA, timeout=60, follow_redirects=True)
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text
            print("  http", r.status_code, url[:80])
        except Exception as e:  # noqa: BLE001
            print("  error", type(e).__name__, url[:80])
        time.sleep(5 * (i + 1))
    return None


def parse_iwv(text: str) -> list[str]:
    """CSV de holdings de iShares: unas líneas de encabezado y luego Ticker,Name,Sector,Asset Class,..."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("Ticker,")), None)
    if start is None:
        return []
    out = []
    for r in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        tk = (r.get("Ticker") or "").strip().strip('"')
        if (r.get("Asset Class") or "").strip() == "Equity" and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", tk):
            out.append(tk.replace(".", "-").replace("/", "-"))
    return out


def parse_lists(nasdaq: str, other: str) -> list[str]:
    out = []
    bad = re.compile(r"warrant|unit|right|preferred|depositary|notes|debenture|%|acquisition corp", re.I)
    for text, sym_col in ((nasdaq, "Symbol"), (other, "ACT Symbol")):
        rows = list(csv.DictReader(io.StringIO(text), delimiter="|"))
        for r in rows:
            s = (r.get(sym_col) or "").strip()
            if not s or r.get("Test Issue") == "Y" or r.get("ETF") == "Y" or bad.search(r.get("Security Name", "")):
                continue
            if re.fullmatch(r"[A-Z]{1,5}", s):
                out.append(s)
    return out


def universe(out: str) -> int:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    src = "iwv"
    tk = []
    t = _get(IWV)
    if t:
        tk = parse_iwv(t)
    if len(tk) < 1500:
        src = "listas"
        a, b = _get(LISTS["nasdaqlisted"]), _get(LISTS["otherlisted"])
        tk = parse_lists(a or "", b or "")
    tk = sorted(set(tk) | set(C.EXTRA))
    (o / "universe.txt").write_text("\n".join(tk) + "\n")
    json.dump({"source": src, "n": len(tk), "date": time.strftime("%Y-%m-%d")}, open(o / "universe.json", "w"))
    print(src, len(tk))
    return 0


def _dl(tks: list[str]) -> pd.DataFrame:
    import yfinance as yf
    for i in range(4):
        try:
            df = yf.download(tks, start=C.START, auto_adjust=True, actions=False, progress=False, threads=True,
                             group_by="ticker")
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001
            print("  reintento", i, type(e).__name__, str(e)[:100])
        time.sleep(10 * (i + 1))
    return pd.DataFrame()


def prices(out: str, chunk: int = 100) -> int:
    o = Path(out)
    tks = [x.strip() for x in open(o / "universe.txt") if x.strip()]
    frames: dict[str, pd.DataFrame] = {}
    for k in range(0, len(tks), chunk):
        part = tks[k:k + chunk]
        df = _dl(part)
        for t in part:
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
            except KeyError:
                continue
            sub = sub[[f for f in FIELDS if f in sub.columns]].dropna(how="all")
            if len(sub) >= 50 and set(FIELDS) <= set(sub.columns):
                frames[t] = sub
        print(f"{min(k + chunk, len(tks))}/{len(tks)} con datos: {len(frames)}", flush=True)
        time.sleep(1)
    cal = frames["SPY"].index if "SPY" in frames else sorted(set().union(*[f.index for f in frames.values()]))
    cal = pd.DatetimeIndex(cal)
    names = sorted(frames)
    arr = np.full((len(FIELDS), len(cal), len(names)), np.nan, dtype=np.float32)
    for j, t in enumerate(names):
        f = frames[t].reindex(cal)
        for i, fld in enumerate(FIELDS):
            arr[i, :, j] = f[fld].to_numpy(dtype=np.float32)
    np.savez_compressed(o / "panel.npz", data=arr, dates=np.array(cal.strftime("%Y-%m-%d"), dtype="U10"),
                        tickers=np.array(names), fields=np.array(FIELDS))
    missing = [t for t in tks if t not in frames]
    json.dump({"requested": len(tks), "got": len(names), "days": len(cal), "first": str(cal[0].date()),
               "last": str(cal[-1].date()), "missing": missing[:500]}, open(o / "prices.json", "w"), indent=1)
    print("panel", arr.shape, "faltan", len(missing))
    return 0


def load_panel(path: str) -> dict:
    z = np.load(path, allow_pickle=False)
    d = {f: z["data"][i] for i, f in enumerate(z["fields"])}
    d["dates"] = pd.DatetimeIndex(z["dates"])
    d["tickers"] = list(z["tickers"])
    return d


if __name__ == "__main__":
    cmd, out = sys.argv[1], sys.argv[2]
    sys.exit(universe(out) if cmd == "universe" else prices(out))
