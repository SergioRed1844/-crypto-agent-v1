"""Descarga histórica para los backtests de v4.2 (corre en GitHub Actions: Binance bloquea IPs de EE.UU. en
api.binance.com, pero data-api.binance.vision y data.binance.vision responden).

  python tools/fetch_history.py --out datos/ --pairs BTCUSDT,ETHUSDT,SOLUSDT --since 2020-03-01

Escribe <PAR>_<tf>.csv (ts,open,high,low,close,volume) para 1d/4h/1h, fear_greed.json y funding_<PAR>.csv.
"""
import argparse
import csv
import io
import json
import os
import sys
import time
import zipfile
from datetime import date, datetime, timezone

import httpx

KL = "https://data-api.binance.vision/api/v3/klines"
FR_ZIP = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{p}/{p}-fundingRate-{y}-{m:02d}.zip"
FR_API = "https://fapi.binance.com/fapi/v1/fundingRate"
TF_MS = {"1d": 86_400_000, "4h": 14_400_000, "1h": 3_600_000}
UA = {"User-Agent": "cryptoagent-backtest"}


def klines(c, pair, tf, since_ms):
    out, cur, now = [], since_ms, int(time.time() * 1000)
    while True:
        r = c.get(KL, params={"symbol": pair, "interval": tf, "startTime": cur, "limit": 1000})
        r.raise_for_status()
        rows = r.json()
        out += [[x[0], x[1], x[2], x[3], x[4], x[5]] for x in rows if x[0] + TF_MS[tf] <= now]
        if len(rows) < 1000:
            break
        cur = rows[-1][0] + TF_MS[tf]
        time.sleep(0.15)
    return out


def funding(c, pair, start: date) -> list[tuple[int, float]]:
    rows, y, m, today = [], start.year, start.month, date.today()
    while (y, m) < (today.year, today.month):
        r = c.get(FR_ZIP.format(p=pair, y=y, m=m))
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                txt = z.read(z.namelist()[0]).decode()
            rd = csv.reader(io.StringIO(txt))
            head = next(rd)
            ti = next(i for i, h in enumerate(head) if "time" in h.lower())
            ri = next(i for i, h in enumerate(head) if "rate" in h.lower())
            rows += [(int(x[ti]), float(x[ri])) for x in rd if x]
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    # mes en curso: API (puede responder 451 desde EE.UU.; entonces se queda sin el último mes)
    try:
        st = int(datetime(today.year, today.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
        r = c.get(FR_API, params={"symbol": pair, "startTime": st, "limit": 1000})
        if r.status_code == 200:
            rows += [(int(x["fundingTime"]), float(x["fundingRate"])) for x in r.json()]
    except httpx.HTTPError:
        pass
    return sorted(set(rows))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="datos")
    ap.add_argument("--pairs", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--since", default="2020-03-01")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    since = int(datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc).timestamp() * 1000)
    rep = {}
    with httpx.Client(timeout=60, headers=UA) as c:
        for p in a.pairs.split(","):
            for tf in TF_MS:
                rows = klines(c, p, tf, since)
                with open(os.path.join(a.out, f"{p}_{tf}.csv"), "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["ts", "open", "high", "low", "close", "volume"])
                    w.writerows(rows)
                rep[f"{p}_{tf}"] = len(rows)
            fr = funding(c, p, date.fromisoformat(a.since))
            with open(os.path.join(a.out, f"funding_{p}.csv"), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["ts", "rate"])
                w.writerows(fr)
            rep[f"funding_{p}"] = len(fr)
        try:
            d = c.get("https://api.alternative.me/fng/", params={"limit": 0, "format": "json"}).json()["data"]
            fg = {datetime.fromtimestamp(int(x["timestamp"]), timezone.utc).date().isoformat(): int(x["value"]) for x in d}
            json.dump(fg, open(os.path.join(a.out, "fear_greed.json"), "w"))
            rep["fear_greed"] = len(fg)
        except Exception as e:
            rep["fear_greed"] = f"error {e}"
    print(json.dumps(rep))


if __name__ == "__main__":
    sys.exit(main())
