"""¿Suman las capas nuevas de v4.2? Mismas señales técnicas, distintos filtros, mismo simulador de portafolio.

  python tools/backtest_variants.py --csv-dir datos/ --since 2021-01-01

Variantes (todas sin LLM, sin look-ahead; el contexto usa SOLO pesos a priori y eventos con fecha < día de la señal):
  A  v4.1 reglas actuales
  B  + ganancia neta (objetivo neto ≥ MIN_NET_GAIN_PCT y R:R neto ≥ MIN_NET_RR)
  C  + derivados: veto por funding > 0.10%/8h (como en producción)
  C2 + derivados estricto: además F&G ≥ 80 o funding > 0.05% → no compra
  D  + contexto: blackout por eventos programados, sesgo por eventos recientes, tamaño y confluencia por estado
  E  + racha: 5 pérdidas seguidas → pausa de 7 días (en producción la pausa dura hasta el reset manual)
  F  v4.2 completo = B + C + D + E
Escribe data/context/backtest_v42.json y data/context/BACKTEST_V42.md.
"""
import argparse
import bisect
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import asyncio  # noqa: E402

import pandas as pd  # noqa: E402

import backtest as bt  # noqa: E402
from app import agents, config  # noqa: E402
from app.context import ctx_dir, engine, read_json, write_json  # noqa: E402
from app.context.schema import normalize  # noqa: E402
from app.risk import net_economics  # noqa: E402

R_ = config.RISK


def load_funding(csv_dir, pair):
    p = os.path.join(csv_dir, f"funding_{pair}.csv")
    if not os.path.exists(p):
        return [], []
    rows = [(int(r["ts"]), float(r["rate"])) for r in csv.DictReader(open(p))]
    return [t for t, _ in rows], [v for _, v in rows]


def funding_at(fts, fvs, t_ms):
    i = bisect.bisect_right(fts, t_ms) - 1
    return fvs[i] if i >= 0 else None


def portfolio_v42(data, sigs, fee, slip, pause_after=None, pause_days=7):
    """Igual que backtest.portfolio + tamaño por señal (sg['size']) + pausa por racha. Sin filtros = idéntico."""
    times = sorted(set().union(*[set(d["4h"].index) for d in data.values()]))
    pos, trades, streak, paused_until = {}, [], 0, None
    for t in times:
        if paused_until is not None and t >= paused_until:
            paused_until, streak = None, 0
        for pair in data:
            sg = sigs[pair].get(t)
            df = data[pair]["4h"]
            if not sg or pair in pos or len(pos) >= R_["max_open_positions"] or t not in df.index or paused_until:
                continue
            entry = float(df.loc[t, "open"]) * (1 + slip)
            sl, tp = entry - (sg["ref"] - sg["sl_ref"]), entry + (sg["tp_ref"] - sg["ref"])
            if entry <= sl or (tp - entry) / (entry - sl) < R_["min_rr"]:
                continue
            unit_risk = (entry - sl) + (entry + sl) * fee
            risk_frac = min(bt._size_mult(sg["cs"]) * R_["risk_per_trade"] * sg.get("size", 1.0),
                            R_["max_position_notional"] * unit_risk / entry)
            if risk_frac <= 0 or sum(p["risk_frac"] for p in pos.values()) + risk_frac > R_["max_correlated_risk"] + 1e-12:
                continue
            pos[pair] = {"t": t, "entry": entry, "sl": sl, "tp": tp, "cs": sg["cs"], "risk_frac": risk_frac,
                         "unit_risk": unit_risk}
        for pair in list(pos):
            df = data[pair]["4h"]
            if t not in df.index:
                continue
            bar, p = df.loc[t], pos[pair]
            o, hi, lo = bar["open"], bar["high"], bar["low"]
            exit_px = reason = None
            if p["t"] != t and o <= p["sl"]:
                exit_px, reason = o * (1 - slip), "SL_GAP"
            elif lo <= p["sl"]:
                exit_px, reason = p["sl"] * (1 - slip), "SL"
            elif hi >= p["tp"]:
                exit_px, reason = p["tp"], "TP"
            if exit_px is not None:
                r = ((exit_px - p["entry"]) - (p["entry"] + exit_px) * fee) / p["unit_risk"]
                trades.append({"pair": pair, "entry_time": str(p["t"]), "exit_time": str(t), "entry": p["entry"],
                               "exit": exit_px, "reason": reason, "R": r, "confluence": p["cs"],
                               "risk_frac": p["risk_frac"], "portfolio_pct": r * p["risk_frac"] * 100})
                del pos[pair]
                streak = streak + 1 if r <= 0 else 0
                if pause_after and streak >= pause_after:
                    paused_until = t + pd.Timedelta(days=pause_days)
    return trades


def context_eval(hist_sched, hist_all, priors, t: pd.Timestamp, fg):
    now = t.to_pydatetime()
    day = now.date().isoformat()
    cal = [e for e in hist_sched if abs((datetime.fromisoformat(e["date"]).date() - now.date()).days) <= 3]
    recent = [e for e in hist_all if e["date"] < day and e["date"] >= (now - timedelta(days=60)).date().isoformat()]
    # weights={} → SOLO priors: los pesos de weights.json se estimaron con toda la muestra (sería look-ahead).
    # btc_regime GREEN no es un supuesto: las señales de reglas solo existen cuando el régimen de BTC vota LONG (GREEN).
    return engine.compute(now, cal, recent, [], {}, {"btc_regime": "GREEN", "fear_greed": fg}, priors, {}, 1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", default="datos")
    ap.add_argument("--pairs", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--since", default="2021-01-01")
    ap.add_argument("--slippage", type=float, default=config.SLIPPAGE)
    ap.add_argument("--oos-frac", type=float, default=0.4)
    a = ap.parse_args(argv)
    since = pd.Timestamp(a.since, tz="UTC")
    pairs = a.pairs.split(",")
    data = {p: bt.load(p, int(since.timestamp() * 1000), a.csv_dir) for p in pairs}
    btc_d1 = data["BTCUSDT"]["1d"]
    print("señales…", file=sys.stderr)
    base = {p: bt.signals(p, data[p], btc_d1, since) for p in pairs}
    fg = json.load(open(os.path.join(a.csv_dir, "fear_greed.json"))) if os.path.exists(
        os.path.join(a.csv_dir, "fear_greed.json")) else {}
    fund = {p: load_funding(a.csv_dir, p) for p in pairs}
    priors = read_json("priors.json")
    hist = []
    for e in read_json("sources/history_events.json", []):
        try:
            hist.append(normalize(e, "happened"))
        except ValueError:
            pass
    sched = [dict(e, status="confirmed") for e in hist if e.get("scheduled")]
    loop = asyncio.new_event_loop()
    feats = {}
    for p in pairs:
        for t, sg in base[p].items():
            dprev = (t - pd.Timedelta(days=1)).date().isoformat()
            fgv = fg.get(dprev)
            fr = funding_at(*fund[p], int(t.timestamp() * 1000)) if fund[p][0] else None
            m = {"derivatives": {"funding_rate": fr}, "fear_greed": {"value": fgv}}
            der = loop.run_until_complete(agents.derivatives({"market": m}))["reports"][0]
            ne = net_economics(sg["ref"], sg["sl_ref"], sg["tp_ref"])
            ctx = context_eval(sched, hist, priors, t, fgv)
            feats[(p, t)] = {"fg": fgv, "funding": fr, "der_veto": der["veto"], "der_score": der["score"], **ne,
                             "ctx_state": ctx["state"], "ctx_veto": ctx["veto_entries"], "ctx_size": ctx["size_mult"],
                             "ctx_extra": ctx["extra_confluence"], "ctx_bias": ctx["bias"]}
    loop.close()

    def build(net=False, der=False, der_strict=False, ctx=False):
        out = {}
        for p in pairs:
            out[p] = {}
            for t, sg in base[p].items():
                f = feats[(p, t)]
                if net and (f["net_gain_pct"] < R_["min_net_gain_pct"] or f["net_rr"] < R_["min_net_rr"]):
                    continue
                if (der or der_strict) and f["der_veto"]:
                    continue
                if der_strict and ((f["fg"] or 0) >= 80 or (f["funding"] or 0) > 0.0005):
                    continue
                size = 1.0
                if ctx:
                    if f["ctx_veto"] or sg["cs"] < R_["min_confluence"] + f["ctx_extra"]:
                        continue
                    size = f["ctx_size"]
                out[p][t] = {**sg, "size": size}
        return out

    fee = config.FEE_RATE
    V = {"A · v4.1 reglas actuales": build(),
         "B · + ganancia neta": build(net=True),
         "C · + derivados (veto funding)": build(der=True),
         "C2 · + derivados estricto (F&G/funding)": build(der_strict=True),
         "D · + contexto (calendario y eventos)": build(ctx=True),
         "E · + racha (pausa tras 5 pérdidas)": build(),
         "F · v4.2 completo (B+C+D+E)": build(net=True, der=True, ctx=True)}
    pause = {"E · + racha (pausa tras 5 pérdidas)": 5, "F · v4.2 completo (B+C+D+E)": 5}
    ref_tr = bt.portfolio(data, base, fee, a.slippage)
    # corte fuera de muestra por FECHA, igual para todas las variantes (comparan el mismo periodo)
    t0, t1 = since, max(d["4h"].index[-1] for d in data.values())
    oos_from = str(t0 + (t1 - t0) * (1 - a.oos_frac))
    res = {}
    for name, sigs in V.items():
        tr = portfolio_v42(data, sigs, fee, a.slippage, pause.get(name))
        tr.sort(key=lambda x: x["exit_time"])
        if name.startswith("A ·"):
            assert [x["R"] for x in sorted(ref_tr, key=lambda x: x["exit_time"])] == [x["R"] for x in tr], \
                "el simulador v4.2 sin filtros debe ser idéntico al de backtest.py"
        res[name] = {"señales": sum(len(s) for s in sigs.values()), "total": bt.metrics(tr),
                     "en_muestra": bt.metrics([x for x in tr if x["entry_time"] < oos_from]),
                     "fuera_de_muestra": bt.metrics([x for x in tr if x["entry_time"] >= oos_from]),
                     "por_par": {p: bt.metrics([x for x in tr if x["pair"] == p]) for p in pairs}}
    grid = {}
    for g, r in ((0.0, 0.0), (0.01, 1.5), (0.015, 1.8), (0.025, 2.0), (0.04, 2.0)):
        sigs = {p: {t: sg for t, sg in base[p].items() if feats[(p, t)]["net_gain_pct"] >= g and feats[(p, t)]["net_rr"] >= r}
                for p in pairs}
        tr = portfolio_v42(data, sigs, fee, a.slippage)
        grid[f"neta≥{g:.1%} y R:R neto≥{r}"] = bt.metrics(tr)
    states = {}
    for f in feats.values():
        states[f["ctx_state"]] = states.get(f["ctx_state"], 0) + 1
    out = {"generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "periodo": f"{since.date()} → {data[pairs[0]]['4h'].index[-1].date()}", "pares": pairs,
           "fuera_de_muestra_desde": oos_from[:10],
           "comision": fee, "slippage": a.slippage, "limites": {k: R_[k] for k in (
               "risk_per_trade", "max_open_positions", "max_correlated_risk", "min_rr", "min_net_gain_pct", "min_net_rr")},
           "variantes": res, "rejilla_ganancia_neta": grid, "estados_contexto_en_señales": states,
           "cobertura": {"fear_greed_dias": len(fg), "funding": {p: len(fund[p][0]) for p in pairs}},
           "criterio": "Una capa SUMA si mejora la expectativa FUERA de muestra sin dejar < 30 trades, y el límite inferior "
                       "del IC95 sube. Si solo mejora en muestra, es sobreajuste."}
    write_json("backtest_v42.json", out)
    (ctx_dir() / "BACKTEST_V42.md").write_text(render(out), encoding="utf-8")
    print(json.dumps({k: v["fuera_de_muestra"] for k, v in res.items()}, ensure_ascii=False)[:3000])


def render(o):
    f = lambda m, k: "—" if not m.get("trades") else m.get(k)
    L = ["# Backtest de variantes v4.2 — ¿suman las capas nuevas?", "",
         f"Periodo {o['periodo']} · pares {', '.join(o['pares'])} · comisión {o['comision']:.2%}/lado · slippage "
         f"{o['slippage']:.2%} · generado {o['generado_utc']}. Sin LLM; el contexto usa pesos a priori y solo eventos "
         "con fecha anterior a la señal (sin look-ahead).", "",
         f"Fuera de muestra = entradas desde {o['fuera_de_muestra_desde']} (mismo corte para todas las variantes).", "",
         "| Variante | Señales | Trades | Ganadas | Expectativa R | PF | Máx DD R | Retorno % | IC95 R | Fuera de muestra: trades / exp. R / IC95 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in o["variantes"].items():
        t, oo = v["total"], v["fuera_de_muestra"]
        L.append(f"| {k} | {v['señales']} | {t.get('trades', 0)} | {f(t, 'win_rate')} | {f(t, 'expectancy_R')} | "
                 f"{f(t, 'profit_factor')} | {f(t, 'max_drawdown_R')} | {f(t, 'retorno_portafolio_%')} | "
                 f"{f(t, 'expectancy_IC95_R')} | {oo.get('trades', 0)} / {f(oo, 'expectancy_R')} / {f(oo, 'expectancy_IC95_R')} |")
    L += ["", "## Rejilla del filtro de ganancia neta", "", "| Umbral | Trades | Ganadas | Expectativa R | PF | IC95 R |",
          "|---|---|---|---|---|---|"]
    for k, m in o["rejilla_ganancia_neta"].items():
        L.append(f"| {k} | {m.get('trades', 0)} | {f(m, 'win_rate')} | {f(m, 'expectancy_R')} | {f(m, 'profit_factor')} | "
                 f"{f(m, 'expectancy_IC95_R')} |")
    L += ["", f"Estados de contexto al momento de las señales: {o['estados_contexto_en_señales']}",
          f"Cobertura de datos: {o['cobertura']}", "", f"**Criterio:** {o['criterio']}"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
