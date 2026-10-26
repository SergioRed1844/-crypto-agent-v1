"""Corre el estudio pre-registrado y escribe results.json, REPORT.md, events.csv y candidatos.csv.

    python -m rebotes.backtest PANEL.npz OUT_DIR
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from . import portfolio as PF
from . import signals as S
from .data import load_panel

EXAMPLES = ["META", "ZS", "SPCE", "RKLB", "SPCX", "CRWD"]


def describe(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    return {"n": int(len(df)), "p_hit30": float(df.hit30.mean()), "p_hit10": float(df.hit10.mean()),
            "p_dd20": float(df.dd20.mean()), "ret21_mean": float(df.ret21.mean()),
            "ret21_median": float(df.ret21.median()), "net_mean": float(df.net.mean()),
            "net_median": float(df.net.median()), "win": float((df.net > 0).mean()),
            "p_toma": float((df.reason == "toma").mean()), "p_stop": float((df.reason == "stop").mean()),
            "p_tiempo": float((df.reason == "tiempo").mean())}


def month_diff(setup: pd.DataFrame, base: pd.DataFrame, reps: int = 2000, seed: int = 11) -> dict:
    """Exceso del neto por operación sobre la base del mismo mes, bootstrap por meses (pre-registro)."""
    if setup.empty:
        return {"months": 0}
    s = setup.groupby("ym").net.agg(["mean", "size"])
    b = base.groupby("ym").net.mean()
    s = s[s.index.isin(b.index)]
    d = (s["mean"] - b.reindex(s.index)).to_numpy()
    w = s["size"].to_numpy(dtype=float)
    est = float((d * w).sum() / w.sum())
    rng = np.random.default_rng(seed)
    k = len(d)
    idx = rng.integers(0, k, size=(reps, k))
    bs = (d[idx] * w[idx]).sum(axis=1) / w[idx].sum(axis=1)
    sd = float(bs.std(ddof=1))
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"months": int(k), "diff": est, "lo": float(lo), "hi": float(hi), "t": est / sd if sd > 0 else 0.0}


def placebo(setup: pd.DataFrame, base: pd.DataFrame, P: dict, si: int, ei: int, reps: int) -> dict:
    counts = setup[(setup.entry_i >= si) & (setup.entry_i <= ei)].groupby("ym").size()
    pool = {m: g for m, g in base[(base.entry_i >= si) & (base.entry_i <= ei)].groupby("ym")}
    rng = np.random.default_rng(5)
    out = []
    for r in range(reps):
        parts = []
        for m, n in counts.items():
            g = pool.get(m)
            if g is not None and len(g):
                parts.append(g.iloc[rng.integers(0, len(g), size=min(n, len(g)))])
        tr = pd.concat(parts) if parts else base.iloc[:0]
        if tr.empty:
            continue
        tr = tr.assign(dd_at=rng.random(len(tr)))          # empate al azar, no por caída
        out.append(PF.stats(PF.simulate(tr, P["Close"], P["dates"], si, ei)["nav"]))
    if not out:
        return {}
    df = pd.DataFrame(out)
    return {k: float(df[k].median()) for k in df.columns} | {"cagr_p90": float(df.cagr.quantile(0.9)),
                                                              "pct_m30_p90": float(df.pct_m30.quantile(0.9))}


def run(panel: str, out: str, reps: int = C.PLACEBO_REPS) -> dict:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    P = load_panel(panel)
    F = S.features(P)
    ev = S.all_events(P, F)
    dates = P["dates"]
    si = int(dates.searchsorted(pd.Timestamp(C.TEST_START)))
    ei = len(dates) - 1
    spy_j = P["tickers"].index("SPY")
    spy = P["Close"][:, spy_j]
    spy_cagr = float((spy[ei] / spy[si]) ** (365.25 / (dates[ei] - dates[si]).days) - 1)
    for k, df in ev.items():
        if not df.empty:
            df["date"] = dates[df.i].strftime("%Y-%m-%d")
            df["ym"] = dates[df.entry_i].to_period("M").astype(str)
            df["ticker"] = [P["tickers"][j] for j in df.j]
            df["test"] = df.entry_i >= si
    base = ev["BASE"]
    res = {"meta": {"tickers": len(P["tickers"]), "days": len(dates), "first": str(dates[0].date()),
                    "last": str(dates[-1].date()), "test_start": C.TEST_START, "spy_cagr_test": spy_cagr},
           "setups": {}, "base": {"train": describe(base[~base.test]), "test": describe(base[base.test])}}
    all_setups = []
    for name in C.SETUPS:
        df = ev[name]
        r = {"train": describe(df[~df.test]) if not df.empty else {"n": 0},
             "test": describe(df[df.test]) if not df.empty else {"n": 0}}
        if not df.empty:
            tst = df[df.test]
            r["diff_vs_base_test"] = month_diff(tst, base[base.test])
            r["lift_hit30_test"] = (r["test"].get("p_hit30", 0) / res["base"]["test"]["p_hit30"]
                                    if res["base"]["test"].get("p_hit30") else None)
            sim = PF.simulate(df, P["Close"], dates, si, ei)
            r["portfolio_test"] = PF.stats(sim["nav"])
            r["portfolio_test"]["trades"] = int(len(sim["taken"]))
            r["placebo_test"] = placebo(df, base, P, si, ei, reps)
            r["by_year"] = {str(y): describe(g) for y, g in df.groupby(dates[df.entry_i].year)}
            gate = {"1_neto_vs_base": bool(r["diff_vs_base_test"].get("diff", -1) >= 0.02
                                           and r["diff_vs_base_test"].get("t", 0) >= 2
                                           and r["diff_vs_base_test"].get("months", 0) >= 30),
                    "2_lift_hit30": bool((r["lift_hit30_test"] or 0) >= 1.5),
                    "3_cartera": bool(r["portfolio_test"]["cagr"] > spy_cagr and r["portfolio_test"]["maxdd"] >= -0.35)}
            gate["pasa"] = all(gate.values())
            r["gate"] = gate
            all_setups.append(df.assign(setup=name))
        res["setups"][name] = r
    # cartera con los tres setups juntos (informativa)
    if all_setups:
        allx = pd.concat(all_setups, ignore_index=True)
        sim = PF.simulate(allx, P["Close"], dates, si, ei)
        res["portfolio_todos_test"] = PF.stats(sim["nav"]) | {"trades": int(len(sim["taken"]))}
        res["placebo_todos_test"] = placebo(allx, base, P, si, ei, reps)
        sim["nav"].to_csv(o / "nav_todos.csv", float_format="%.2f")
        cols = ["setup", "ticker", "date", "entry", "max_r", "min_r", "ret21", "net", "reason", "dd_at", "test"]
        allx[cols].to_csv(o / "events.csv", index=False, float_format="%.4f")
        ex = allx[allx.ticker.isin(EXAMPLES)][cols]
        res["examples"] = ex.to_dict(orient="records")
    cand = S.recent(P, F, days=10)
    if not cand.empty:
        cand["p_hit30_hist"] = cand.setup.map(lambda s: res["setups"][s]["test"].get("p_hit30"))
        cand["p_dd20_hist"] = cand.setup.map(lambda s: res["setups"][s]["test"].get("p_dd20"))
        cand["net_mean_hist"] = cand.setup.map(lambda s: res["setups"][s]["test"].get("net_mean"))
        cand.to_csv(o / "candidatos.csv", index=False, float_format="%.4f")
    res["candidatos"] = cand.to_dict(orient="records") if not cand.empty else []
    json.dump(res, open(o / "results.json", "w"), indent=1, default=str)
    (o / "REPORT.md").write_text(report(res))
    return res


def report(res: dict) -> str:
    pc = lambda x: "—" if x is None else f"{x*100:.1f}%"
    L = ["# Rebotes — resultados", "",
         f"{res['meta']['tickers']} acciones, {res['meta']['first']} → {res['meta']['last']}; prueba desde "
         f"{res['meta']['test_start']}. SPY en prueba: {pc(res['meta']['spy_cagr_test'])} anual.", "",
         "| setup | periodo | disparos | P(+30%) | P(+10%) | P(−20%) | neto medio (regla) | mediana | gana |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    rows = [("BASE", res["base"])] + [(k, v) for k, v in res["setups"].items()]
    for name, r in rows:
        for per in ("train", "test"):
            d = r[per]
            if d.get("n"):
                L.append(f"| {name} | {per} | {d['n']} | {pc(d['p_hit30'])} | {pc(d['p_hit10'])} | {pc(d['p_dd20'])} | "
                         f"{pc(d['net_mean'])} | {pc(d['net_median'])} | {pc(d['win'])} |")
    L += ["", "| setup | exceso vs base (IC 95%, t) | lift P(+30%) | cartera CAGR | caída máx. | meses ≥ +30% | "
          "placebo CAGR | placebo meses ≥ +30% | compuerta |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, r in res["setups"].items():
        if "gate" not in r:
            continue
        d, p, q = r["diff_vs_base_test"], r["portfolio_test"], r.get("placebo_test", {})
        L.append(f"| {name} | {pc(d.get('diff'))} [{pc(d.get('lo'))}, {pc(d.get('hi'))}], t {d.get('t', 0):.2f} | "
                 f"{(r['lift_hit30_test'] or 0):.2f}× | {pc(p['cagr'])} | {pc(p['maxdd'])} | {pc(p['pct_m30'])} | "
                 f"{pc(q.get('cagr'))} | {pc(q.get('pct_m30'))} | {'PASA' if r['gate']['pasa'] else 'no'} |")
    if "portfolio_todos_test" in res:
        p, q = res["portfolio_todos_test"], res.get("placebo_todos_test", {})
        L += ["", f"Cartera con los 3 setups (prueba): CAGR {pc(p['cagr'])}, caída máx. {pc(p['maxdd'])}, meses ≥ +30%: "
                  f"{pc(p['pct_m30'])}, meses ≤ −20%: {pc(p['pct_m_neg20'])}; placebo CAGR {pc(q.get('cagr'))}."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else C.PLACEBO_REPS)
