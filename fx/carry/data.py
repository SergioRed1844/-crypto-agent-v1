"""Datos de la Estrategia B: velas de 1 hora bid/ask de Dukascopy (un archivo por mes), tasas de política (BIS;
respaldo OCDE vía FRED) y VIX (FRED). Corre en GitHub Actions (``fx-carry-data.yml``); el espacio de trabajo de
Claude no alcanza estas fuentes.

Formato de vela de Dukascopy: 24 bytes big-endian (tiempo, apertura, cierre, mínimo, máximo, volumen float32). En
los archivos horarios el tiempo es desde el inicio del MES (segundos; algunos en milisegundos)."""
from __future__ import annotations

import calendar
import csv
import io
import json
import lzma
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import numpy as np

from .. import data_dukascopy as D
from . import config as CC

BASE = D.BASE
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"


def url_hour(sym: str, y: int, m: int, side: str) -> str:
    return f"{BASE}/{sym}/{y:04d}/{m - 1:02d}/{side}_candles_hour_1.bi5"


def url_day(sym: str, y: int, side: str) -> str:
    return f"{BASE}/{sym}/{y:04d}/{side}_candles_day_1.bi5"


def parse(raw: bytes, base: date, span_s: int) -> np.ndarray:
    """(n, 6): minuto UTC desde 1970, o, c, l, h, volumen. ``span_s`` = duración del archivo (detecta ms)."""
    if not raw:
        return np.zeros((0, 6))
    dec = lzma.decompress(raw)
    r = np.frombuffer(dec, dtype=D.REC)
    if not len(r):
        return np.zeros((0, 6))
    t = r["t"].astype(np.int64)
    if t.max() > span_s + 86_400:
        t = t // 1000
    t0 = calendar.timegm(base.timetuple())
    out = np.empty((len(r), 6))
    out[:, 0] = (t0 + t) // 60
    out[:, 1] = r["o"]; out[:, 2] = r["c"]; out[:, 3] = r["l"]; out[:, 4] = r["h"]; out[:, 5] = r["v"]
    return out


def fetch_month(cl, sym: str, y: int, m: int) -> dict:
    span = calendar.monthrange(y, m)[1] * 86_400
    bid = parse(D._get(cl, url_hour(sym, y, m, "BID")), date(y, m, 1), span)
    ask = parse(D._get(cl, url_hour(sym, y, m, "ASK")), date(y, m, 1), span)
    return D.merge_sides(bid, ask)


def months(y0: int, until: date):
    y, m = y0, 1
    while date(y, m, 1) < date(until.year, until.month, 1):     # solo meses completos
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def download(code: str, out: str, workers: int = 4, until: date | None = None) -> dict:
    c = CC.BY_CODE[code]
    until = until or date.today()
    ms = list(months(CC.START_YEAR, until))
    parts, fails = [], []
    with D._client() as cl, ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch_month, cl, c.sym, y, m): (y, m) for y, m in ms}
        for f, (y, m) in futs.items():
            try:
                parts.append(f.result())
            except Exception as e:
                fails.append(f"{y}-{m:02d}: {e}")
    b = D.concat(parts)
    mid = (np.median(b["bc"]) + np.median(b["ac"])) / 2 * c.point if len(b["t"]) else 0
    st = {"code": code, "sym": c.sym, "months": len(ms), "failed": fails, "bars": int(len(b["t"])),
          "median_mid": round(float(mid), 5), "scale_ok": bool(c.rng[0] <= mid <= c.rng[1]),
          "first": D._ts(b["t"][0]) if len(b["t"]) else None, "last": D._ts(b["t"][-1]) if len(b["t"]) else None}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"{c.sym}_H1.npz.xz"), "wb") as fh:
        fh.write(D.encode(b))
    json.dump(st, open(os.path.join(out, f"{c.sym}_H1.json"), "w"), indent=1)
    return st


def repair(code: str, src: str, out: str, workers: int = 2, rounds: int = 3) -> dict:
    """Vuelve a pedir los meses que faltan (Dukascopy responde 503 bajo carga) y fusiona con lo que ya había."""
    c = CC.BY_CODE[code]
    have = load(code, src) if os.path.exists(os.path.join(src, f"{c.sym}_H1.npz.xz")) else D.concat([])
    present = {(K_ym(m)) for m in np.unique(np.asarray(have["t"]) // 1440 * 1440)} if len(have["t"]) else set()
    want = [ym for ym in months(CC.START_YEAR, date.today()) if ym not in present]
    parts, fails = [have], []
    with D._client() as cl:
        for _ in range(rounds):
            fails = []
            with ThreadPoolExecutor(workers) as ex:
                futs = {ex.submit(fetch_month, cl, c.sym, y, m): (y, m) for y, m in want}
                for f, (y, m) in futs.items():
                    try:
                        parts.append(f.result())
                    except Exception as e:
                        fails.append(((y, m), str(e)[:80]))
            want = [ym for ym, _ in fails]
            if not want:
                break
            time.sleep(20)
    b = D.concat(parts)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"{c.sym}_H1.npz.xz"), "wb") as fh:
        fh.write(D.encode(b))
    mid = (np.median(b["bc"]) + np.median(b["ac"])) / 2 * c.point if len(b["t"]) else 0
    st = {"code": code, "sym": c.sym, "months": len(list(months(CC.START_YEAR, date.today()))),
          "failed": [f"{y}-{m:02d}: {e}" for (y, m), e in fails], "bars": int(len(b["t"])),
          "median_mid": round(float(mid), 5), "scale_ok": bool(c.rng[0] <= mid <= c.rng[1]),
          "first": D._ts(b["t"][0]) if len(b["t"]) else None, "last": D._ts(b["t"][-1]) if len(b["t"]) else None}
    json.dump(st, open(os.path.join(out, f"{c.sym}_H1.json"), "w"), indent=1)
    return st


def K_ym(minute: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(int(minute) * 60, timezone.utc)
    return d.year, d.month


def load(code: str, d: str) -> dict:
    c = CC.BY_CODE[code]
    with open(os.path.join(d, f"{c.sym}_H1.npz.xz"), "rb") as fh:
        return D.decode(fh.read())


# ── tasas y VIX ────────────────────────────────────────────────────────────────────────────────────────────────────
BIS_URLS = (
    "https://stats.bis.org/api/v1/data/WS_CBPOL/D.{codes}/all?detail=dataonly&format=csv",
    "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{codes}?format=csv",
    "https://data.bis.org/static/bulk/WS_CBPOL_csv_flat.zip",
)


def _http(url: str, timeout: int = 60):
    import httpx
    return httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0 (fx-agente research)"})


def bis_rates() -> tuple[list[tuple[str, str, float]], str]:
    """[(fecha, moneda, tasa %)] diarios de BIS y la URL que funcionó."""
    codes = ["US"] + [c.bis for c in CC.UNIVERSE]
    to_ccy = {"US": "USD", **{c.bis: c.code for c in CC.UNIVERSE}}
    for u in BIS_URLS:
        url = u.format(codes="+".join(codes))
        try:
            r = _http(url, 120)
        except Exception:
            continue
        if r.status_code != 200 or len(r.content) < 1000:
            continue
        text = r.text
        if url.endswith(".zip"):
            z = zipfile.ZipFile(io.BytesIO(r.content))
            text = z.read(z.namelist()[0]).decode("utf-8", "replace")
        rows = _parse_bis_csv(text, to_ccy)
        if len(rows) > 1000:
            return rows, url
    return [], ""


def _parse_bis_csv(text: str, to_ccy: dict) -> list:
    rd = csv.DictReader(io.StringIO(text))
    out = []
    for row in rd:
        keys = {k.upper(): v for k, v in row.items() if k}
        area = keys.get("REF_AREA") or keys.get("REF_AREA:REFERENCE AREA", "")
        area = area.split(":")[0].strip()
        freq = (keys.get("FREQ") or "D").split(":")[0].strip()
        tp = keys.get("TIME_PERIOD") or keys.get("TIME_PERIOD:TIME PERIOD") or ""
        val = keys.get("OBS_VALUE") or keys.get("OBS_VALUE:OBSERVATION VALUE") or ""
        if freq != "D" or area not in to_ccy or not tp or val in ("", "NaN"):
            continue
        try:
            if tp >= "2013":
                out.append((tp[:10], to_ccy[area], float(val)))
        except ValueError:
            continue
    return out


def fred_series(sid: str) -> list[tuple[str, float]]:
    r = _http(FRED.format(sid), 60)
    if r.status_code != 200:
        return []
    out = []
    for line in r.text.splitlines()[1:]:
        p = line.split(",")
        if len(p) == 2 and p[1] not in (".", ""):
            try:
                out.append((p[0], float(p[1])))
            except ValueError:
                pass
    return out


def oecd_rates() -> list[tuple[str, str, float]]:
    out = []
    for code, cc in [("USD", "US")] + [(c.code, c.oecd) for c in CC.UNIVERSE]:
        for d, v in fred_series(f"IR3TIB01{cc}M156N"):
            if d >= "2013":
                out.append((d, code, v))
    return out


def fetch_aux(out: str) -> dict:
    os.makedirs(out, exist_ok=True)
    rows, src = bis_rates()
    kind = "BIS política (diaria)"
    if not rows:
        rows, src, kind = oecd_rates(), "FRED IR3TIB01*M156N", "OCDE interbancaria 3M (mensual)"
    with open(os.path.join(out, "rates.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "ccy", "rate"])
        w.writerows(sorted(rows))
    vix = fred_series("VIXCLS")
    with open(os.path.join(out, "vix.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "vix"])
        w.writerows(vix)
    cov = {}
    for d, c, v in rows:
        cov.setdefault(c, [d, d, 0])
        cov[c][0] = min(cov[c][0], d); cov[c][1] = max(cov[c][1], d); cov[c][2] += 1
    st = {"rates_source": src, "rates_kind": kind, "rates_rows": len(rows), "coverage": cov,
          "vix_rows": len(vix), "vix_first": vix[0][0] if vix else None, "vix_last": vix[-1][0] if vix else None}
    json.dump(st, open(os.path.join(out, "aux.json"), "w"), indent=1)
    return st


def load_rates(d: str) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list] = {}
    with open(os.path.join(d, "rates.csv")) as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["ccy"], []).append((row["date"], float(row["rate"])))
    for v in out.values():
        v.sort()
    return out


def load_vix(d: str) -> list[tuple[str, float]]:
    with open(os.path.join(d, "vix.csv")) as fh:
        return [(r["date"], float(r["vix"])) for r in csv.DictReader(fh)]


def probe(out: str) -> int:
    lines = ["# Sonda Estrategia B", ""]
    bad = 0
    with D._client() as cl:
        for code in ("EUR", "HUF", "ZAR", "NOK"):
            c = CC.BY_CODE[code]
            try:
                b = fetch_month(cl, c.sym, 2024, 1)
                hrs = sorted({int(m % 1440 // 60) for m in b["t"]})
                mid = (np.median(b["bc"]) + np.median(b["ac"])) / 2 * c.point
                lines.append(f"- {c.sym} 2024-01 horario: {len(b['t'])} velas, {D._ts(b['t'][0])} → "
                             f"{D._ts(b['t'][-1])}, mid {mid:.5f}, horas UTC {hrs[:3]}…{hrs[-3:]}, "
                             f"escala {'ok' if c.rng[0] <= mid <= c.rng[1] else 'MAL'}")
                if not (c.rng[0] <= mid <= c.rng[1]) or len(b["t"]) < 400:
                    bad += 1
            except Exception as e:
                bad += 1
                lines.append(f"- {c.sym}: error {str(e)[:120]}")
    for u in BIS_URLS:
        url = u.format(codes="US+XM+MX")
        try:
            r = _http(url, 60)
            lines.append(f"- BIS {url[:80]} → HTTP {r.status_code}, {len(r.content)} bytes, "
                         f"{r.headers.get('content-type', '')[:40]}")
            if r.status_code == 200 and not url.endswith(".zip"):
                lines.append("  " + " | ".join(r.text.splitlines()[:2])[:300])
        except Exception as e:
            lines.append(f"- BIS {url[:80]} → {type(e).__name__}")
    for sid in ("VIXCLS", "IR3TIB01MXM156N", "IR3TIB01EZM156N", "IR3TIB01ZAM156N", "DFF"):
        try:
            s = fred_series(sid)
            lines.append(f"- FRED {sid}: {len(s)} obs, {s[0] if s else ''} → {s[-1] if s else ''}")
        except Exception as e:
            lines.append(f"- FRED {sid}: {type(e).__name__}")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "PROBE_CARRY.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return bad


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "probe":
        sys.exit(1 if probe(sys.argv[2]) else 0)
    if cmd == "pair":
        st = download(sys.argv[2], sys.argv[3])
        print(json.dumps({k: v for k, v in st.items() if k != "failed"}), len(st["failed"]), "meses fallidos")
        sys.exit(0 if st["scale_ok"] and len(st["failed"]) <= 2 else 1)
    if cmd == "repair":
        st = repair(sys.argv[2], sys.argv[3], sys.argv[4])
        print(json.dumps({k: v for k, v in st.items() if k != "failed"}), st["failed"])
        sys.exit(0)
    if cmd == "aux":
        print(json.dumps(fetch_aux(sys.argv[2]), indent=1))
        sys.exit(0)
    raise SystemExit(f"comando desconocido: {cmd}")
