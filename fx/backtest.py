"""Backtest fuera de muestra del agente FX (F15-017 A): walk-forward anual expansivo, costos reales (spread
bid/ask de Dukascopy + sobreprecio OANDA + deslizamiento) y estrés ×2, portafolio con el MISMO motor de riesgo que
opera en vivo (gobernador semanal −1.5%), métricas semanales, PSR/DSR, PBO por CSCV (16 bloques) y benchmark de
signo aleatorio. Escribe ``data/fx/BACKTEST.md``, ``backtest.json`` y ``model.json`` (modelo para operar).

Uso: python -m fx backtest --bars <checkout de fx-data>/bars
"""
from __future__ import annotations

import gzip
import hashlib
import heapq
import itertools
import json
import math
import os
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

from . import calendar as K
from . import config as C
from . import data_dukascopy as D
from . import events as E
from . import model as M
from .risk import Position, RiskEngine, notional_usd

EQUITY0 = 2000.0
EULER = 0.5772156649


# ── datos y eventos ────────────────────────────────────────────────────────────────────────────────────────────────
def ny_window_mask(t: np.ndarray, start_h: float = 5.0, end_h: float = 17.5) -> np.ndarray:
    """Minutos cuyo horario de Nueva York cae en [start_h, end_h): todo lo que la estrategia usa (6:00 NY es el
    T−60 más temprano; 16:50 NY la salida forzada). Reduce memoria a la mitad sin cambiar resultados."""
    days = np.asarray(t, dtype=np.int64) // 1440
    ud, inv = np.unique(days, return_inverse=True)
    off = np.array([K.NY.utcoffset(datetime(1970, 1, 1) + timedelta(days=int(d), hours=12)).total_seconds() / 60
                    for d in ud])
    local = (np.asarray(t, dtype=np.int64) + off[inv].astype(np.int64)) % 1440
    return (local >= start_h * 60) & (local < end_h * 60)


def load_bars(bars_dir: str, syms=None) -> dict[str, E.Bars]:
    out = {}
    for s in syms or C.PAIRS:
        raw = D.load(s, bars_dir)
        if len(raw["t"]):
            keep = ny_window_mask(raw["t"])
            out[s] = E.Bars.from_raw(s, {k: np.asarray(v)[keep] for k, v in raw.items()})
    return out


def _fingerprint(bars_dir: str) -> str:
    """Huella de todo lo que determina las filas de eventos: contenido de las velas y del código que las produce."""
    h = hashlib.sha1()
    for f in sorted(os.listdir(bars_dir)):
        if f.endswith(".npz.xz"):
            h.update(f.encode())
            with open(os.path.join(bars_dir, f), "rb") as fh:
                h.update(hashlib.sha1(fh.read()).digest())
    for n in ("events.py", "config.py", "calendar.py", "backtest.py", "data_dukascopy.py"):
        with open(os.path.join(os.path.dirname(__file__), n), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:12]


def build_rows(bars: dict[str, E.Bars], cache: str | None = None, fp: str = "") -> list[dict]:
    if cache and os.path.exists(cache):
        with gzip.open(cache, "rt") as fh:
            blob = json.load(fh)
        if blob.get("fp") == fp:
            return blob["rows"]
    rows = []
    for slot in C.SLOTS:
        for sym, b in bars.items():
            if slot.pairs and sym not in slot.pairs:
                continue
            rows += E.to_rows(E.build(b, slot))
    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with gzip.open(cache, "wt") as fh:
            json.dump({"fp": fp, "rows": rows}, fh)
    return rows


def year_of(r) -> int:
    return int(r["day"][:4])


# ── walk-forward ───────────────────────────────────────────────────────────────────────────────────────────────────
def walk_forward(rows: list[dict], first: int = C.WF_FIRST_TEST_YEAR):
    years = sorted({year_of(r) for r in rows})
    cands, models = [], {}
    for y in [y for y in years if y >= first]:
        train = [r for r in rows if year_of(r) < y]
        test = [r for r in rows if year_of(r) == y]
        m = M.fit(train)
        models[y] = m
        cands += M.select(test, m)
    return cands, models


# ── portafolio con el motor de riesgo real ─────────────────────────────────────────────────────────────────────────
def early_R(bars: dict[str, E.Bars], r: dict, m: int, cost_mult: float) -> float:
    b = bars[r["sym"]]
    ie = int(np.searchsorted(b.t, r["entry_m"], "left"))
    s = E.simulate(b, ie, r["side"], r["risk_px"], m, C.PAIRS[r["sym"]], cost_mult)
    return s["R"]


def portfolio(cands: list[dict], bars: dict[str, E.Bars] | None = None, cost_mult: float = 1.0,
              equity0: float = EQUITY0, risk: C.Risk = C.RISK):
    eng = RiskEngine(equity0, risk)
    cands = sorted(cands, key=lambda r: (r["entry_m"], r["sym"]))
    n_event = defaultdict(int)
    for r in cands:
        n_event[(r["slot"], r["t0"])] += 1
    heap, trades, skipped = [], [], defaultdict(int)
    seq = itertools.count()

    def close(r, pos, m, R):
        pnl = R * pos.risk_usd
        acts = eng.on_close(r["sym"], pnl, m)
        trades.append({**{k: r[k] for k in ("sym", "slot", "day", "dir", "hold", "z", "why")}, "R": R,
                       "pnl": pnl, "exit_m": m, "risk_usd": pos.risk_usd, "equity": eng.equity})
        return acts

    def flatten(m):
        while heap:
            _, _, r, pos = heapq.heappop(heap)
            R = early_R(bars, r, m, cost_mult) if bars else _R(r, cost_mult)
            close(r, pos, m, R)

    for r in cands:
        while heap and heap[0][0] <= r["entry_m"]:
            xm, _, rr, pos = heapq.heappop(heap)
            acts = close(rr, pos, xm, _R(rr, cost_mult))
            if any(a.startswith("flatten") for a in acts):
                flatten(xm + 1)      # el resto sale al minuto siguiente del stop que disparó el tope
        if eng.off:
            skipped["apagado"] += 1
            continue
        price = r.get("entry") or 1.0
        dec = eng.size(r["entry_m"], r["sym"], r["side"], price, r["risk_px"], n_event[(r["slot"], r["t0"])],
                       r["blackout"])
        if not dec.ok:
            skipped[(dec.reasons or ["?"])[0].split(":")[0]] += 1
            continue
        pos = Position(r["sym"], r["side"], dec.units, price, price - r["side"] * r["risk_px"], dec.risk_usd,
                       r["entry_m"], r["exit_m"], notional_usd(r["sym"], dec.units, price),
                       r["side"] * C.PAIRS[r["sym"]].usd_sign)
        eng.on_open(pos)
        heapq.heappush(heap, (r["exit_m"], next(seq), r, pos))
    while heap:
        xm, _, rr, pos = heapq.heappop(heap)
        close(rr, pos, xm, _R(rr, cost_mult))
    return trades, eng, dict(skipped)


def _R(r: dict, cost_mult: float) -> float:
    return r["R"] - (cost_mult - 1.0) * r["R_cost"]


# ── métricas ───────────────────────────────────────────────────────────────────────────────────────────────────────
def weekly(trades: list[dict], start_m: int, end_m: int, equity0: float = EQUITY0):
    by = defaultdict(float)
    for t in trades:
        by[K.fx_week(t["exit_m"])] += t["pnl"]
    weeks, m = [], K.week_open_min(start_m)
    while m <= end_m:
        weeks.append(K.fx_week(m + 60))
        m += 7 * 24 * 60
    eq, out = equity0, []
    for w in weeks:
        p = by.get(w, 0.0)
        out.append({"week": w, "pnl": p, "ret": p / eq, "traded": w in by})
        eq += p
    return out


def _moments(x: np.ndarray):
    sd = x.std(ddof=1)
    if sd == 0 or len(x) < 3:
        return 0.0, 0.0, 3.0
    z = (x - x.mean()) / sd
    return float(x.mean() / sd), float((z ** 3).mean()), float((z ** 4).mean())


def psr(x: np.ndarray, sr0: float = 0.0) -> float:
    sr, sk, ku = _moments(x)
    den = math.sqrt(max(1 - sk * sr + (ku - 1) / 4 * sr ** 2, 1e-9))
    return M._phi((sr - sr0) * math.sqrt(len(x) - 1) / den)


def dsr(x: np.ndarray, sr_trials: list[float], n_trials: int) -> float:
    v = float(np.var(sr_trials, ddof=1)) if len(sr_trials) > 1 else 0.0
    from statistics import NormalDist
    nd = NormalDist()
    n = max(n_trials, 2)
    sr0 = math.sqrt(v) * ((1 - EULER) * nd.inv_cdf(1 - 1 / n) + EULER * nd.inv_cdf(1 - 1 / (n * math.e)))
    return psr(x, sr0)


def summarize(trades, weeks, eng, equity0=EQUITY0) -> dict:
    rets = np.array([w["ret"] for w in weeks]) if weeks else np.zeros(1)
    traded = [w for w in weeks if w["traded"]]
    eq = np.array([equity0] + [t["equity"] for t in trades])
    peak = np.maximum.accumulate(eq)
    years = max(len(weeks) / 52.18, 1e-9)
    total = eq[-1] / equity0 - 1
    Rs = np.array([t["R"] for t in trades]) if trades else np.zeros(0)
    streak = worst_streak = 0
    for w in weeks:
        streak = streak + 1 if w["pnl"] < 0 else 0
        worst_streak = max(worst_streak, streak)
    return {
        "trades": len(trades), "hit": float((Rs > 0).mean()) if len(Rs) else 0.0,
        "avg_R": float(Rs.mean()) if len(Rs) else 0.0, "total_ret": float(total),
        "cagr": float((1 + total) ** (1 / years) - 1) if total > -1 else -1.0,
        "max_dd": float((1 - eq / peak).max()), "weeks": len(weeks), "weeks_traded": len(traded),
        "weeks_pos": int(sum(w["pnl"] > 0 for w in weeks)), "weeks_neg": int(sum(w["pnl"] < 0 for w in weeks)),
        "pct_pos_of_traded": float(sum(w["pnl"] > 0 for w in traded) / len(traded)) if traded else 0.0,
        "worst_week": float(rets.min()), "best_week": float(rets.max()),
        "weeks_below_cap": int((rets < -C.RISK.weekly_loss_cap - 1e-9).sum()),
        "max_losing_weeks_row": worst_streak,
        "sharpe_ann": float(rets.mean() / rets.std(ddof=1) * math.sqrt(52)) if rets.std() > 0 else 0.0,
        "psr0": psr(rets) if len(rets) > 3 else 0.5, "final_equity": float(eq[-1]),
        "off": eng.off,
    }


# ── PBO (CSCV) y DSR sobre TODAS las pruebas: cada (par, slot, variante) es un ensayo ───────────────────────────────
def trial_matrix(rows: list[dict], min_n: int = C.EB_MIN_N):
    """Matriz semanas × ensayos con la suma semanal de R neto de cada (par, slot, dirección, horizonte, z).
    Es lo que el EB elige por grupo: N = número de columnas es el número honesto de ensayos para DSR/PBO."""
    cols = defaultdict(lambda: defaultdict(float))
    counts = defaultdict(int)
    for r in rows:
        for z in C.Z_GRID:
            if M.eligible(r, z):
                k = (r["sym"], r["slot"], r["dir"], r["hold"], z)
                cols[k][K.fx_week(r["exit_m"])] += r["R"]
                counts[k] += 1
    keys = sorted(k for k in cols if counts[k] >= min_n)
    if not keys:
        return np.zeros((0, 0)), []
    weeks = sorted({w for k in keys for w in cols[k]})
    X = np.array([[cols[k].get(w, 0.0) for k in keys] for w in weeks])
    return X, keys


def weekly_sr(X: np.ndarray) -> list[float]:
    sd = X.std(axis=0, ddof=1)
    return [float(m / s) if s > 0 else 0.0 for m, s in zip(X.mean(axis=0), sd)]


def pbo_cscv(X: np.ndarray, S: int = 16) -> dict:
    T, N = X.shape
    if T < S * 4 or N < 2:
        return {"pbo": None, "why": "muestra insuficiente"}
    blocks = np.array_split(np.arange(T), S)
    lams = []

    def sr(a):
        sd = a.std(axis=0, ddof=1)
        return np.where(sd > 0, a.mean(axis=0) / np.where(sd > 0, sd, 1), 0.0)

    for comb in itertools.combinations(range(S), S // 2):
        IS = np.concatenate([blocks[i] for i in comb])
        OS = np.concatenate([blocks[i] for i in range(S) if i not in comb])
        best = int(np.argmax(sr(X[IS])))
        oos = sr(X[OS])
        rank = (oos < oos[best]).sum() + 0.5 * ((oos == oos[best]).sum() - 1) + 1
        w = rank / (N + 1)
        lams.append(math.log(w / (1 - w)))
    lams = np.array(lams)
    return {"pbo": float((lams <= 0).mean()), "combos": len(lams), "S": S, "N": N}


# ── benchmark de signo aleatorio ───────────────────────────────────────────────────────────────────────────────────
def random_sign(cands: list[dict], rows: list[dict], n: int = 2000, seed: int = 7) -> dict:
    opp = {}
    for r in rows:
        opp[(r["sym"], r["slot"], r["day"], r["dir"], r["hold"])] = r["R"]
    pairs = []
    for c in cands:
        o = opp.get((c["sym"], c["slot"], c["day"], "rev" if c["dir"] == "mom" else "mom", c["hold"]))
        if o is not None:
            pairs.append((c["R"], o))
    if not pairs:
        return {"n": 0}
    a = np.array(pairs)
    real = a[:, 0].mean()
    rng = np.random.default_rng(seed)
    sims = np.array([np.where(rng.random(len(a)) < 0.5, a[:, 0], a[:, 1]).mean() for _ in range(n)])
    return {"n": len(a), "avg_R": float(real), "rand_avg_R": float(sims.mean()), "p_value": float((sims >= real).mean())}


# ── reporte ────────────────────────────────────────────────────────────────────────────────────────────────────────
def scales_now(bars: dict[str, E.Bars]) -> dict:
    out = {}
    for slot in C.SLOTS:
        for sym, b in bars.items():
            if slot.pairs and sym not in slot.pairs:
                continue
            rows = E.slot_series(b, slot)
            if len(rows) < C.MIN_SCALE_OBS:
                continue
            rets = np.array([r[2] for r in rows[-C.SCALE_WINDOW_DAYS:]])
            spreads = np.array([r[3] for r in rows[-60:]])
            out[f"{sym}|{slot.name}"] = {"sigma_slot": E.robust_scale(rets), "spread_typ": float(np.median(spreads)),
                                         "last_day": rows[-1][0].isoformat(),
                                         "abs_hist": [round(abs(float(x)), 8) for x in rets]}
    return out


def run(bars_dir: str, out_dir: str = C.DATA_DIR, cache_dir: str = C.CACHE_DIR) -> dict:
    bars = load_bars(bars_dir)
    fp = _fingerprint(bars_dir)
    rows = build_rows(bars, os.path.join(cache_dir, "events.json.gz"), fp)
    cands, models = walk_forward(rows)
    if not cands:
        res = {"error": "sin candidatos fuera de muestra", "rows": len(rows)}
    else:
        start_m = min(c["entry_m"] for c in cands)
        end_m = max(c["exit_m"] for c in cands)
        res = {"rows": len(rows), "fingerprint": fp, "generated": datetime.now(timezone.utc).isoformat()}
        for name, cm in (("base", 1.0), ("estres_x2", C.COST_STRESS)):
            tr, eng, sk = portfolio(cands, bars, cm)
            wk = weekly(tr, start_m, end_m)
            res[name] = summarize(tr, wk, eng) | {"skipped": sk, "risk_log": eng.log[-15:]}
            if name == "base":
                res["weeks_base"] = wk
                res["trades_base"] = tr
        X, keys = trial_matrix(rows)
        srs = weekly_sr(X) if len(keys) else [0.0]
        rets = np.array([w["ret"] for w in res["weeks_base"]])
        res["n_trials"] = len(keys)
        res["dsr"] = dsr(rets, srs, max(len(keys), 2))
        res["pbo"] = pbo_cscv(X) if len(keys) >= 2 else {"pbo": None, "why": "menos de 2 ensayos"}
        res["random_sign"] = random_sign(cands, rows)
        res["by_group"] = _by_group(res["trades_base"])
        res["by_era"] = _by_era(res["weeks_base"])
        res["models"] = {y: {f"{s}|{sl}": {k: g[k] for k in ("dir", "hold", "z", "p_pos", "post_mean", "n")}
                             for (s, sl), g in m["active"].items()} for y, m in models.items()}
    os.makedirs(out_dir, exist_ok=True)
    if "error" not in res:
        final = M.fit(rows)
        last_day = max(date.fromisoformat(r["day"]) for r in rows)
        model_json = M.serializable(final, last_day, {"scales": scales_now(bars), "fingerprint": fp,
                                                      "risk": vars(C.RISK), "version": 2})
        json.dump(model_json, open(os.path.join(out_dir, "model.json"), "w"), indent=1, default=str)
    else:
        model_json = None       # sin validación fuera de muestra no se publica modelo
    slim = {k: v for k, v in res.items() if k not in ("trades_base",)}
    json.dump(slim, open(os.path.join(out_dir, "backtest.json"), "w"), indent=1, default=str)
    open(os.path.join(out_dir, "BACKTEST.md"), "w").write(report(res, model_json))
    return res


def _by_group(trades):
    g = defaultdict(list)
    for t in trades:
        g[(t["sym"], t["slot"])].append(t["R"])
    return {f"{s}|{sl}": {"n": len(v), "avg_R": float(np.mean(v)), "hit": float(np.mean(np.array(v) > 0))}
            for (s, sl), v in sorted(g.items())}


def _by_era(weeks):
    eras = {"2018-2021": (2018, 2021), "2022-2024": (2022, 2024), "2025-2026": (2025, 2026)}
    out = {}
    for name, (a, b) in eras.items():
        w = [x for x in weeks if a <= int(x["week"][:4]) <= b]
        if w:
            r = np.array([x["ret"] for x in w])
            out[name] = {"weeks": len(w), "ret": float(np.prod(1 + r) - 1), "pos": int((r > 0).sum()),
                         "neg": int((r < 0).sum()), "worst": float(r.min())}
    return out


def _pct(x, d=1):
    return f"{100 * x:+.{d}f}%"


def report(res: dict, model_json: dict) -> str:
    L = ["# Backtest del agente FX — Estrategia A (reacción intradía a datos macro)", "",
         f"Generado {res.get('generated', '')} · filas de eventos {res.get('rows')} · huella `{res.get('fingerprint')}`",
         ""]
    if "error" in res:
        return "\n".join(L + [f"**{res['error']}**"]) + "\n"
    b, s = res["base"], res["estres_x2"]
    L += ["## Fuera de muestra (walk-forward anual, 2018 → hoy, capital inicial US$2,000)", "",
          "| métrica | costos base | costos ×2 |", "|---|---|---|"]
    for k, lab, f in (("trades", "operaciones", str), ("hit", "aciertos", _pct), ("avg_R", "R medio por operación",
                      lambda x: f"{x:+.3f}"), ("total_ret", "retorno total", _pct), ("cagr", "anualizado", _pct),
                      ("max_dd", "drawdown máximo", lambda x: f"{100 * x:.1f}%"),
                      ("sharpe_ann", "Sharpe anual (semanal)", lambda x: f"{x:.2f}"),
                      ("psr0", "PSR (Sharpe>0)", lambda x: f"{x:.2f}"),
                      ("weeks_traded", "semanas con operaciones", str),
                      ("pct_pos_of_traded", "% de esas semanas en positivo", _pct),
                      ("worst_week", "peor semana", _pct), ("weeks_below_cap", "semanas peores que −1.5%", str),
                      ("max_losing_weeks_row", "racha máx. de semanas negativas", str)):
        L.append(f"| {lab} | {f(b[k])} | {f(s[k])} |")
    rs = res["random_sign"]
    L += ["", f"**DSR** (N = {res['n_trials']} ensayos par×slot×variante): {res['dsr']:.2f} · "
              f"**PBO** (CSCV {res['pbo'].get('S')} bloques sobre esos ensayos): {res['pbo'].get('pbo')}",
          f"**Signo aleatorio**: R medio real {rs.get('avg_R', 0):+.3f} vs aleatorio {rs.get('rand_avg_R', 0):+.3f}"
          f" (p = {rs.get('p_value', float('nan')):.3f}, n = {rs.get('n')})", "",
          "## Por era", "", "| era | semanas | retorno | + | − | peor semana |", "|---|---|---|---|---|---|"]
    for k, v in res["by_era"].items():
        L.append(f"| {k} | {v['weeks']} | {_pct(v['ret'])} | {v['pos']} | {v['neg']} | {_pct(v['worst'])} |")
    L += ["", "## Por (par, slot) fuera de muestra", "", "| grupo | n | R medio | aciertos |", "|---|---|---|---|"]
    for k, v in res["by_group"].items():
        L.append(f"| {k} | {v['n']} | {v['avg_R']:+.3f} | {_pct(v['hit'], 0)} |")
    L += ["", "## Modelo vigente (entrenado con todo hasta " + model_json["trained_until"] + ")", "",
          f"Umbral P(ventaja>0) ajustado por variantes: {model_json['p_adj']:.3f}", "",
          "| grupo | dirección | horizonte | z mín | P(ventaja>0) | R medio a posteriori | n |", "|---|---|---|---|---|---|---|"]
    for k, g in sorted(model_json["active"].items()):
        L.append(f"| {k} | {g['dir']} | {g['hold']} min | {g['z']} | {g['p_pos']:.3f} | {g['post_mean']:+.3f} | {g['n']} |")
    if not model_json["active"]:
        L.append("| — ningún grupo pasa el umbral: el agente no opera | | | | | | |")
    L += ["", "Bloqueos del motor de riesgo (base): " + json.dumps(b["skipped"], ensure_ascii=False),
          "", "Notas: costos = spread real cruzado + sobreprecio OANDA estimado + deslizamiento; el estrés ×2 los duplica."
          " Los resultados históricos se descuentan ~50% para planear (F14-017). Nada aquí es garantía."]
    return "\n".join(L) + "\n"
