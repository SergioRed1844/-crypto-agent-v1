"""Precios diarios ajustados (dividendos + splits) de Yahoo vía yfinance, en GitHub Actions.

    python -m copytrade.prices data/copytrade/tickers.txt OUT

Escribe OUT/prices/close_adj.csv.gz (fecha × ticker), OUT/prices/close_raw.csv.gz y OUT/prices/MANIFEST.json con
lo que faltó. Un ticker sin datos se reporta; nunca se rellena con otro.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

START, CHUNK = "2024-12-01", 80


def _dl(tks: list[str], adjust: bool) -> pd.DataFrame:
    for i in range(4):
        try:
            df = yf.download(tks, start=START, auto_adjust=adjust, actions=False, progress=False,
                             threads=True, group_by="column")
            if df is not None and not df.empty:
                c = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(
                    columns={"Close": tks[0]})
                return c
        except Exception as e:  # noqa: BLE001 — la red de Actions falla de vez en cuando
            print("  reintento", i, type(e).__name__, str(e)[:120])
        time.sleep(10 * (i + 1))
    return pd.DataFrame()


def main(lst: str, out: str) -> int:
    tickers = sorted({t.strip() for t in open(lst) if t.strip() and not t.startswith("#")})
    o = Path(out) / "prices"
    o.mkdir(parents=True, exist_ok=True)
    frames = {True: [], False: []}
    for k in range(0, len(tickers), CHUNK):
        part = tickers[k:k + CHUNK]
        for adj in (True, False):
            c = _dl(part, adj)
            if not c.empty:
                frames[adj].append(c)
        print(f"{k + len(part)}/{len(tickers)}")
        time.sleep(2)
    adj = pd.concat(frames[True], axis=1) if frames[True] else pd.DataFrame()
    raw = pd.concat(frames[False], axis=1) if frames[False] else pd.DataFrame()
    adj = adj.loc[:, ~adj.columns.duplicated()].dropna(axis=1, how="all")
    missing = [t for t in tickers if t not in adj.columns]
    if missing:                                   # segundo intento, uno por uno
        for t in missing:
            c = _dl([t], True)
            if not c.empty and c.notna().any().any():
                adj[t] = c.iloc[:, 0]
            time.sleep(1)
    missing = [t for t in tickers if t not in adj.columns]
    adj.sort_index().to_csv(o / "close_adj.csv.gz", float_format="%.6g")
    raw.loc[:, ~raw.columns.duplicated()].sort_index().to_csv(o / "close_raw.csv.gz", float_format="%.6g")
    span = {t: [str(adj[t].first_valid_index())[:10], str(adj[t].last_valid_index())[:10]] for t in adj.columns}
    json.dump({"start": START, "requested": len(tickers), "got": int(adj.shape[1]), "missing": missing,
               "last_date": str(adj.index.max())[:10], "span": span}, open(o / "MANIFEST.json", "w"), indent=1)
    print("faltan", len(missing), missing[:50])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
