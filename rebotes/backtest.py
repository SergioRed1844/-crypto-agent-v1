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
    """Exceso del neto por operación sobre la base del mismo mes (ponderado por disparos del setup).

    Error estándar por bootstrap de meses (pre-registro) y por bloques de 3 meses calendario (cambio posterior: las
    tenencias de 21 velas cruzan de mes y los meses de pánico se parecen entre sí). La compuerta usa el t más bajo."""
    if setup.empty:
        return {"months": 0}
    s = setup.groupby("ym").net.agg(["mean", "size"])
    b = base.groupby("ym").net.mean()
    s = s[s.index.isin(b.index)]
    if s.empty:
        return {"months": 0}
    d = (s["mean"] - b.reindex(s.index)).to_numpy()
    w = s["size"].to_numpy(dtype=float)
    est = float((d * w).sum() / w.sum())
    rng = np.random.default_rng(seed)
    k = len(d)
    idx = rng.integers(0, k, size=(reps, k))
    bs = (d[idx] * w[idx]).sum(axis=1) / w[idx].sum(axis=1)
    sd = float(bs.std(ddof=1))
    lo, hi = np.percentile(bs, [2.5, 97.5])
    per = pd.PeriodIndex(s.index, freq="M")
    blk = pd.Series(d * w).groupby((per.year * 12 + per.month - 1) // 3).sum().to_numpy()
    blw = pd.Series(w).groupby((per.year * 12 + per.month - 1) // 3).sum().to_numpy()
    kb = len(blk)
    bi = rng.integers(0, kb, size=(reps, kb))
    bb = blk[bi].sum(axis=1) / blw[bi].sum(axis=1)
    sdb = float(bb.std(ddof=1))
    lob, hib = np.percentile(bb, [2.5, 97.5])
    t1 = est / sd if sd > 0 else 0.0
    t3 = est / sdb if sdb > 0 else 0.0
    return {"months": int(k), "eff_months": float(w.sum() ** 2 / (w ** 2).sum()), "diff": est,
            "lo": float(lo), "hi": float(hi), "t_mes": t1, "lo_bloque": float(lob), "hi_bloque": float(hib),
            "t_bloque": t3, "t": min(t1, t3) if est > 0 else max(t1, t3) if est < 0 else 0.0}


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
    # fin de la cartera: último cierre de mes con al menos HOLD velas después (las últimas entradas ya tienen
    # resultado completo; no hay mes parcial). El SPY se mide en la misma ventana.
    last_ok = len(dates) - 1 - C.HOLD
    month_end = np.flatnonzero(dates[1:].month != dates[:-1].month)
    ei = int(month_end[month_end <= last_ok].max())
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
    hit = base[base.dd_at <= -0.40]                        # descriptivo: acción ya golpeada, día cualquiera
    res = {"meta": {"tickers": len(P["tickers"]), "days": len(dates), "first": str(dates[0].date()),
                    "last": str(dates[-1].date()), "test_start": C.TEST_START, "portfolio_end": str(dates[ei].date()),
                    "spy_cagr_test": spy_cagr,
                    "gaps": {k: {"con_huecos": int((df.gaps > 0).sum()), "cortadas": int(df.cut.sum()),
                                 "n": int(len(df))} for k, df in ev.items() if not df.empty}},
           "setups": {}, "base": {"train": describe(base[~base.test]), "test": describe(base[base.test])},
           "base_golpeada": {"train": describe(hit[~hit.test]), "test": describe(hit[hit.test])}}
    all_setups = []
    for name in C.SETUPS:
        df = ev[name]
        r = {"train": describe(df[~df.test]) if not df.empty else {"n": 0},
             "test": describe(df[df.test]) if not df.empty else {"n": 0}}
        if not df.empty:
            tst = df[df.test]
            r["diff_vs_base_test"] = month_diff(tst, base[base.test])
            r["diff_vs_golpeada_test"] = month_diff(tst, hit[hit.test])
            r["lift_hit30_test"] = (r["test"].get("p_hit30", 0) / res["base"]["test"]["p_hit30"]
                                    if res["base"]["test"].get("p_hit30") else None)
            sim = PF.simulate(df, P["Close"], dates, si, ei)
            r["portfolio_test"] = PF.stats(sim["nav"])
            r["portfolio_test"]["trades"] = int(len(sim["taken"]))
            r["placebo_test"] = placebo(df, base, P, si, ei, reps)
            r["by_year"] = {str(y): describe(g) for y, g in df.groupby(dates[df.entry_i].year)}
            r["lift_dd20_test"] = (r["test"].get("p_dd20", 0) / res["base"]["test"]["p_dd20"]
                                   if res["base"]["test"].get("p_dd20") else None)
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
        cols = ["setup", "ticker", "date", "entry", "max_r", "min_r", "ret21", "net", "reason", "dd_at", "gaps", "test"]
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
    m = res["meta"]
    L = ["# Rebotes — resultados", "",
         f"{m['tickers']} acciones, {m['first']} → {m['last']}; prueba desde {m['test_start']} (cartera hasta "
         f"{m['portfolio_end']}). SPY en la misma ventana: {pc(m['spy_cagr_test'])} anual.", "",
         "Por disparo (21 velas desde la entrada al open siguiente; neto = regla +30% / −15% / 21 velas con 0.39% por lado).",
         "", "| setup | periodo | disparos | P(+30%) | P(+10%) | P(−20%) | neto medio | mediana | gana |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    rows = [("BASE", res["base"]), ("BASE golpeada (≤ −40%)", res["base_golpeada"])] + list(res["setups"].items())
    for name, r in rows:
        for per in ("train", "test"):
            d = r[per]
            if d.get("n"):
                L.append(f"| {name} | {per} | {d['n']} | {pc(d['p_hit30'])} | {pc(d['p_hit10'])} | {pc(d['p_dd20'])} | "
                         f"{pc(d['net_mean'])} | {pc(d['net_median'])} | {pc(d['win'])} |")
    L += ["", "Compuerta (prueba). Exceso = neto medio del setup menos la base del mismo mes; t = el más bajo entre "
          "bootstrap por mes y por bloques de 3 meses.", "",
          "| setup | exceso vs base [IC 95% bloques] | t mes / bloque | meses (efectivos) | exceso vs golpeada | "
          "lift P(+30%) | lift P(−20%) | cartera CAGR | caída máx. | meses ≥ +30% | placebo CAGR | placebo meses ≥ +30% | "
          "compuerta |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, r in res["setups"].items():
        if "gate" not in r:
            continue
        d, g, p, q = r["diff_vs_base_test"], r.get("diff_vs_golpeada_test", {}), r["portfolio_test"], r.get("placebo_test", {})
        L.append(f"| {name} | {pc(d.get('diff'))} [{pc(d.get('lo_bloque'))}, {pc(d.get('hi_bloque'))}] | "
                 f"{d.get('t_mes', 0):.2f} / {d.get('t_bloque', 0):.2f} | {d.get('months', 0)} ({d.get('eff_months', 0):.0f}) | "
                 f"{pc(g.get('diff'))} | {(r['lift_hit30_test'] or 0):.2f}× | {(r.get('lift_dd20_test') or 0):.2f}× | "
                 f"{pc(p['cagr'])} | {pc(p['maxdd'])} | {pc(p['pct_m30'])} | {pc(q.get('cagr'))} | {pc(q.get('pct_m30'))} | "
                 f"{'PASA' if r['gate']['pasa'] else 'no'} ({sum(bool(v) for k, v in r['gate'].items() if k != 'pasa')}/3) |")
    if "portfolio_todos_test" in res:
        p, q = res["portfolio_todos_test"], res.get("placebo_todos_test", {})
        L += ["", f"Cartera con los 3 setups (prueba): CAGR {pc(p['cagr'])}, caída máx. {pc(p['maxdd'])}, meses ≥ +30%: "
                  f"{pc(p['pct_m30'])}, meses ≥ +10%: {pc(p['pct_m10'])}, meses ≤ −20%: {pc(p['pct_m_neg20'])}, "
                  f"mediana mensual {pc(p['median_m'])}; placebo CAGR {pc(q.get('cagr'))}."]
    gp = m.get("gaps", {})
    if gp:
        L += ["", "Operaciones con días sin cotizar dentro de la tenencia (se conservan; el día faltante repite el último "
                  "cierre): " + "; ".join(f"{k} {v['con_huecos']}/{v['n']} (serie cortada {v['cortadas']})"
                                         for k, v in gp.items())]
    if res.get("examples"):
        L += ["", "## Ejemplos pedidos", "", "| setup | ticker | señal | entrada | máx. | mín. | día 21 | neto | salida |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for e in sorted(res["examples"], key=lambda e: (e["ticker"], e["date"])):
            L.append(f"| {e['setup']} | {e['ticker']} | {e['date']} | {e['entry']:.2f} | {pc(e['max_r'])} | {pc(e['min_r'])} | "
                     f"{pc(e['ret21'])} | {pc(e['net'])} | {e['reason']} |")
    if res.get("candidatos"):
        L += ["", "## Disparos recientes (sin resultado aún)", "",
              "| setup | ticker | fecha | precio | caída vs máx. 252d | P(+30%) hist. | P(−20%) hist. | neto medio hist. |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for c in res["candidatos"]:
            L.append(f"| {c['setup']} | {c['ticker']} | {c['date']} | {c['operado']:.2f} | {pc(c['dd'])} | "
                     f"{pc(c.get('p_hit30_hist'))} | {pc(c.get('p_dd20_hist'))} | {pc(c.get('net_mean_hist'))} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else C.PLACEBO_REPS)
