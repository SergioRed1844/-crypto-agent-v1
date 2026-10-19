"""Velas de 1 minuto bid y ask de Dukascopy (datafeed público, sin llave).

URL: https://datafeed.dukascopy.com/datafeed/{SYM}/{YYYY}/{MM-1:02d}/{DD:02d}/{BID|ASK}_candles_min_1.bi5
(el mes empieza en 00). Cada archivo es LZMA (formato "alone") con registros de 24 bytes big-endian:
tiempo (segundos desde 00:00 UTC del día), apertura, cierre, mínimo, máximo (enteros × point) y volumen (float32).

Se guardan por par y año como ``{SYM}_{YYYY}.npz.xz`` con codificación delta (minutos UTC desde 1970, precios en
enteros de point). Bid y ask juntos: así el backtest cruza el spread real de cada minuto en vez de suponerlo.
Esta red no se alcanza desde el espacio de trabajo: la descarga corre en GitHub Actions (``fx-data.yml``).
"""
from __future__ import annotations

import calendar
import io
import json
import lzma
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import numpy as np

from .config import PAIRS

BASE = "https://datafeed.dukascopy.com/datafeed"
REC = np.dtype([("t", ">i4"), ("o", ">i4"), ("c", ">i4"), ("l", ">i4"), ("h", ">i4"), ("v", ">f4")])
FIELDS = ("t", "bo", "bh", "bl", "bc", "ao", "ah", "al", "ac", "bv", "av")


def url(sym: str, d: date, side: str) -> str:
    return f"{BASE}/{sym}/{d.year:04d}/{d.month - 1:02d}/{d.day:02d}/{side}_candles_min_1.bi5"


def parse_bi5(raw: bytes, d: date) -> np.ndarray:
    """Devuelve matriz (n, 6) int64/float: minuto UTC desde 1970, o, c, l, h (enteros) y volumen."""
    if not raw:
        return np.zeros((0, 6))
    dec = lzma.decompress(raw)
    if len(dec) % REC.itemsize:
        raise ValueError(f"tamaño {len(dec)} no es múltiplo de {REC.itemsize}")
    r = np.frombuffer(dec, dtype=REC)
    if not len(r):
        return np.zeros((0, 6))
    t = r["t"].astype(np.int64)
    if t.max() > 86_400:            # algunas series vienen en milisegundos
        t = t // 1000
    day0 = calendar.timegm(d.timetuple())
    out = np.empty((len(r), 6))
    out[:, 0] = (day0 + t) // 60
    out[:, 1] = r["o"]; out[:, 2] = r["c"]; out[:, 3] = r["l"]; out[:, 4] = r["h"]; out[:, 5] = r["v"]
    return out


def merge_sides(bid: np.ndarray, ask: np.ndarray) -> dict[str, np.ndarray]:
    """Une bid y ask por minuto; conserva solo minutos con operaciones (volumen > 0 en algún lado)."""
    if not len(bid) or not len(ask):
        return {k: np.zeros(0, np.int64 if k[-1] != "v" else np.float32) for k in FIELDS}
    tb, ta = bid[:, 0].astype(np.int64), ask[:, 0].astype(np.int64)
    common, ib, ia = np.intersect1d(tb, ta, return_indices=True)
    b, a = bid[ib], ask[ia]
    keep = (b[:, 5] > 0) | (a[:, 5] > 0)
    b, a, common = b[keep], a[keep], common[keep]
    return {"t": common, "bo": b[:, 1].astype(np.int64), "bc": b[:, 2].astype(np.int64),
            "bl": b[:, 3].astype(np.int64), "bh": b[:, 4].astype(np.int64),
            "ao": a[:, 1].astype(np.int64), "ac": a[:, 2].astype(np.int64),
            "al": a[:, 3].astype(np.int64), "ah": a[:, 4].astype(np.int64),
            "bv": b[:, 5].astype(np.float32), "av": a[:, 5].astype(np.float32)}


def concat(parts: list[dict]) -> dict[str, np.ndarray]:
    parts = [p for p in parts if len(p["t"])]
    if not parts:
        return {k: np.zeros(0, np.int64) for k in FIELDS}
    out = {k: np.concatenate([p[k] for p in parts]) for k in FIELDS}
    o = np.argsort(out["t"], kind="stable")
    out = {k: v[o] for k, v in out.items()}
    _, u = np.unique(out["t"], return_index=True)
    return {k: v[u] for k, v in out.items()}


def encode(b: dict[str, np.ndarray]) -> bytes:
    t = b["t"].astype(np.int64); bc = b["bc"].astype(np.int64); ac = b["ac"].astype(np.int64)
    enc = {
        "t0": np.array([t[0] if len(t) else 0]), "dt": np.diff(t, prepend=t[:1]).astype(np.int32),
        "bc0": np.array([bc[0] if len(bc) else 0]), "dbc": np.diff(bc, prepend=bc[:1]).astype(np.int32),
        "bo": (b["bo"] - bc).astype(np.int32), "bh": (b["bh"] - bc).astype(np.int32),
        "bl": (b["bl"] - bc).astype(np.int32), "sp": (ac - bc).astype(np.int32),
        "ao": (b["ao"] - ac).astype(np.int32), "ah": (b["ah"] - ac).astype(np.int32),
        "al": (b["al"] - ac).astype(np.int32), "bv": b["bv"].astype(np.float32), "av": b["av"].astype(np.float32),
    }
    buf = io.BytesIO()
    np.savez(buf, **enc)
    return lzma.compress(buf.getvalue(), preset=6)


def decode(blob: bytes) -> dict[str, np.ndarray]:
    z = np.load(io.BytesIO(lzma.decompress(blob)))
    n = len(z["dt"])
    if not n:
        return {k: np.zeros(0, np.int64) for k in FIELDS}
    dt = z["dt"].astype(np.int64); dt[0] = 0
    dbc = z["dbc"].astype(np.int64); dbc[0] = 0
    t = int(z["t0"][0]) + np.cumsum(dt)
    bc = int(z["bc0"][0]) + np.cumsum(dbc)
    ac = bc + z["sp"]
    return {"t": t, "bc": bc, "bo": bc + z["bo"], "bh": bc + z["bh"], "bl": bc + z["bl"],
            "ac": ac, "ao": ac + z["ao"], "ah": ac + z["ah"], "al": ac + z["al"],
            "bv": z["bv"], "av": z["av"]}


def _client():
    import httpx
    return httpx.Client(timeout=40, headers={"User-Agent": "Mozilla/5.0 (fx-agente research)"},
                        follow_redirects=True)


def _get(cl, u: str, tries: int = 5) -> bytes:
    last = None
    for i in range(tries):
        try:
            r = cl.get(u)
            if r.status_code == 404:
                return b""
            if r.status_code == 200:
                return r.content
            last = f"HTTP {r.status_code}"
        except Exception as e:  # red inestable: reintento con espera
            last = type(e).__name__
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{u.rsplit('/datafeed/', 1)[-1]}: {last}")


def fetch_day(cl, sym: str, d: date) -> dict[str, np.ndarray]:
    bid = parse_bi5(_get(cl, url(sym, d, "BID")), d)
    ask = parse_bi5(_get(cl, url(sym, d, "ASK")), d)
    return merge_sides(bid, ask)


def days(year: int, until: date | None = None):
    d, end = date(year, 1, 1), min(date(year, 12, 31), until or date.max)
    while d <= end:
        if d.weekday() != 5:     # sábado: mercado cerrado
            yield d
        d += timedelta(days=1)


def check_scale(sym: str, b: dict) -> dict:
    p = PAIRS[sym]
    if not len(b["t"]):
        return {"ok": False, "why": "sin datos"}
    mid = (np.median(b["bc"]) + np.median(b["ac"])) / 2 * p.point
    spread_pips = float(np.median(b["ac"] - b["bc"]) * p.point / p.pip)
    ok = p.rng[0] <= mid <= p.rng[1] and 0 <= spread_pips < (200 if p.em else 20)
    return {"ok": bool(ok), "median_mid": round(float(mid), 5), "median_spread_pips": round(spread_pips, 3)}


def download_year(sym: str, year: int, out_dir: str, workers: int = 8, until: date | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    ds = list(days(year, until))
    fails, parts = [], []
    with _client() as cl, ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch_day, cl, sym, d): d for d in ds}
        for f, d in futs.items():
            try:
                parts.append(f.result())
            except Exception as e:
                fails.append(f"{d}: {e}")
    b = concat(parts)
    stats = {"sym": sym, "year": year, "days_requested": len(ds), "days_failed": len(fails), "fails": fails[:400],
             "minutes": int(len(b["t"])), "scale": check_scale(sym, b),
             "first_utc": _ts(b["t"][0]) if len(b["t"]) else None,
             "last_utc": _ts(b["t"][-1]) if len(b["t"]) else None}
    blob = encode(b)
    with open(os.path.join(out_dir, f"{sym}_{year}.npz.xz"), "wb") as fh:
        fh.write(blob)
    stats["bytes"] = len(blob)
    with open(os.path.join(out_dir, f"{sym}_{year}.json"), "w") as fh:
        json.dump(stats, fh, indent=1)
    return stats


def repair(sym: str, year: int, bars_dir: str, out_dir: str, workers: int = 3, until: date | None = None) -> dict:
    """Vuelve a pedir los días hábiles que faltan en el archivo de un par-año (fallas por saturación del servidor)
    y fusiona. Los festivos devuelven archivo vacío y simplemente siguen faltando."""
    path = os.path.join(bars_dir, f"{sym}_{year}.npz.xz")
    have = decode(open(path, "rb").read()) if os.path.exists(path) else concat([])
    present = _dates(have["t"])
    want = [d for d in days(year, until) if d.weekday() < 5 and d not in present and (d.month, d.day) not in
            ((12, 25), (1, 1))]
    fails, parts = [], [have]
    with _client() as cl, ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch_day, cl, sym, d): d for d in want}
        for f, d in futs.items():
            try:
                parts.append(f.result())
            except Exception as e:
                fails.append(f"{d}: {e}")
    b = concat(parts)
    os.makedirs(out_dir, exist_ok=True)
    blob = encode(b)
    with open(os.path.join(out_dir, f"{sym}_{year}.npz.xz"), "wb") as fh:
        fh.write(blob)
    stats = {"sym": sym, "year": year, "repaired_days": len(want) - len(fails), "days_requested": len(want),
             "days_failed": len(fails), "fails": fails[:400], "minutes": int(len(b["t"])), "scale": check_scale(sym, b),
             "first_utc": _ts(b["t"][0]) if len(b["t"]) else None, "last_utc": _ts(b["t"][-1]) if len(b["t"]) else None,
             "bytes": len(blob)}
    with open(os.path.join(out_dir, f"{sym}_{year}.json"), "w") as fh:
        json.dump(stats, fh, indent=1)
    return stats


def _dates(t) -> set:
    e = date(1970, 1, 1)
    return {e + timedelta(days=int(k)) for k in np.unique(np.asarray(t, dtype=np.int64) // 1440)}


def coverage(bars_dir: str) -> list[dict]:
    """Días hábiles con datos por par-año (para el manifiesto y para decidir si hace falta reparar)."""
    out = []
    for f in sorted(os.listdir(bars_dir)):
        if not f.endswith(".npz.xz"):
            continue
        sym, y = f[:-7].split("_")
        b = decode(open(os.path.join(bars_dir, f), "rb").read())
        ds = _dates(b["t"])
        wk = [d for d in days(int(y), date.today() - timedelta(days=1)) if d.weekday() < 5]
        out.append({"sym": sym, "year": int(y), "weekdays": len(wk), "with_data": sum(d in ds for d in wk),
                    "minutes": int(len(b["t"]))})
    return out


def _ts(m) -> str:
    return datetime.fromtimestamp(int(m) * 60, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def load(sym: str, bars_dir: str, years=None) -> dict[str, np.ndarray]:
    """Carga los años disponibles de un par (``bars_dir`` = checkout de la rama ``fx-data``)."""
    files = sorted(f for f in os.listdir(bars_dir) if f.startswith(sym + "_") and f.endswith(".npz.xz"))
    parts = []
    for f in files:
        y = int(f[len(sym) + 1:len(sym) + 5])
        if years is None or y in years:
            with open(os.path.join(bars_dir, f), "rb") as fh:
                parts.append(decode(fh.read()))
    return concat(parts)


def probe(out: str) -> int:
    """Descarga pocos días por par y escribe un informe: valida URL, formato, escala y spreads."""
    test_days = [date(2015, 1, 15), date(2020, 3, 9), date(2024, 1, 5), date.today() - timedelta(days=3)]
    lines = ["# Sonda Dukascopy", "", "| par | día | minutos | mid mediano | spread mediano (pips) | escala ok |",
             "|---|---|---|---|---|---|"]
    bad = 0
    with _client() as cl:
        for sym in PAIRS:
            for d in test_days:
                try:
                    b = fetch_day(cl, sym, d)
                    sc = check_scale(sym, b)
                    lines.append(f"| {sym} | {d} | {len(b['t'])} | {sc.get('median_mid')} | "
                                 f"{sc.get('median_spread_pips')} | {sc['ok']} |")
                    if d.weekday() < 5 and len(b["t"]) and not sc["ok"]:
                        bad += 1
                except Exception as e:
                    bad += 1
                    lines.append(f"| {sym} | {d} | error | {str(e)[:80]} | | |")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "PROBE.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return bad


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "probe":
        sys.exit(1 if probe(sys.argv[2] if len(sys.argv) > 2 else "out") else 0)
    if cmd == "year":
        sym, year, out = sys.argv[2], int(sys.argv[3]), sys.argv[4]
        until = date.today() - timedelta(days=1)
        st = download_year(sym, year, out, until=until)
        print(json.dumps(st))
        sys.exit(0 if st["scale"]["ok"] and st["days_failed"] <= max(3, st["days_requested"] // 50) else 1)
    if cmd == "repair":
        sym, year, src, out = sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
        st = repair(sym, year, src, out, until=date.today() - timedelta(days=1))
        print(json.dumps({k: v for k, v in st.items() if k != "fails"}))
        sys.exit(0)
    if cmd == "merge":
        # merge OLD_DIR NEW_DIR OUT_DIR: une minuto a minuto lo publicado con lo recién bajado (nunca se pierde un
        # día que ya estaba bien porque la descarga nueva haya fallado ese día).
        old_d, new_d, out_d = sys.argv[2], sys.argv[3], sys.argv[4]
        os.makedirs(out_d, exist_ok=True)
        for f in sorted(os.listdir(new_d)):
            if not f.endswith(".npz.xz"):
                continue
            parts = [decode(open(os.path.join(new_d, f), "rb").read())]
            if os.path.exists(os.path.join(old_d, f)):
                parts.insert(0, decode(open(os.path.join(old_d, f), "rb").read()))
            b = concat(parts)
            with open(os.path.join(out_d, f), "wb") as fh:
                fh.write(encode(b))
            print(f, "minutos:", [len(p["t"]) for p in parts], "→", len(b["t"]))
        sys.exit(0)
    if cmd == "coverage":
        rows = coverage(sys.argv[2])
        for r in rows:
            print(f"{r['sym']} {r['year']}: {r['with_data']}/{r['weekdays']} días hábiles, {r['minutes']} min")
        sys.exit(0)
    raise SystemExit(f"comando desconocido: {cmd}")
