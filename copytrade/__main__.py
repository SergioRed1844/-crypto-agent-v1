"""python -m copytrade run --prices DIR --rates CSV [--filings DIR] --out DIR

Corre la variante principal, las 36 combinaciones de sensibilidad, los comparativos y el estudio por operación, y
escribe results.json, nav.csv, events.csv, contrib.csv y REPORT.md en --out.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import pandas as pd

from . import events, sim
from .build import build
from .resolve import listings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--prices", required=True)
    ap.add_argument("--rates", required=True)
    ap.add_argument("--filings", default=None)
    ap.add_argument("--trades", default=None, help="trades.csv ya armado (si no, se arma)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--quick", action="store_true", help="solo la principal y comparativos")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if a.trades:
        trades = pd.read_csv(a.trades, dtype={"ticker": str})
    else:
        rows, meta = build(Path(a.filings) if a.filings else None)
        trades = pd.DataFrame(rows)
        trades.to_csv(out / "trades.csv", index=False)
        json.dump(meta, open(out / "trades.meta.json", "w"), indent=1, default=str)
    trades["ticker"] = trades["ticker"].fillna("")
    raw = sim.load_prices(str(Path(a.prices) / "close_adj.csv.gz"))
    px, info = sim.extend(raw)
    t = sim.prepare(trades, px, info)
    _, names, _ = listings()
    t["eq"] = sim.equity_sleeve(t, names)

    # ---- cobertura
    allt = trades.copy()
    cov = {
        "rows": int(len(allt)), "usd_buys": float(allt[allt.type == "Purchase"].mid.sum()),
        "usd_sales": float(allt[allt.type == "Sale"].mid.sum()),
        "rows_mapped": int((allt.ticker != "").sum()),
        "usd_buys_mapped_priced": float(t[(t.type == "Purchase") & t.price_ok].mid.sum()),
        "usd_buys_unmapped": float(allt[(allt.type == "Purchase") & (allt.ticker == "")].mid.sum()),
        "usd_buys_no_price": float(t[(t.type == "Purchase") & ~t.price_ok].mid.sum()),
        "tickers_no_price": sorted(set(t[~t.price_ok].ticker))[:200],
        "price_last": str(px.index[-1].date()),
        "by_class_buys": allt[allt.type == "Purchase"].groupby("cls").mid.sum().round(0).to_dict(),
    }

    # ---- variantes
    principal = sim.Spec()
    specs = [principal, sim.Spec(mode="E")]
    if not a.quick:
        for mode, sleeve, amount, cost in itertools.product(["E", "R"], ["full", "equity"],
                                                            ["mid", "lower", "geo", "equal"], [0.0029, 0.0005]):
            s = sim.Spec(mode=mode, sleeve=sleeve, amount=amount, cost=cost)
            if s not in specs:
                specs.append(s)
        specs += [sim.Spec(mode="R", lag=5), sim.Spec(mode="E", top=30), sim.Spec(mode="R", top=30),
                  sim.Spec(mode="R", sleeve="equity", top=30), sim.Spec(mode="E", sleeve="equity", top=30)]
    spy = px["SPY"]
    bil = px[sim.CASH]
    res, navs = [], {}
    for s in specs:
        tt = t[t.eq] if s.sleeve == "equity" else t
        r = sim.run(tt, px, s)
        m = sim.metrics(r["nav"], spy, bil)
        m.update(name=s.name(), mode=s.mode, lag=s.lag, sleeve=s.sleeve, amount=s.amount, cost=s.cost, top=s.top,
                 cost_paid=r["cost"], turnover=r["turnover"], rebalances=r["rebalances"])
        res.append(m)
        navs[s.name()] = r["nav"]
        if s == principal:
            r_main = r
        if s == sim.Spec(mode="E"):
            r_e = r
        print(f"{s.name():32s} final {m['final']:>10,.0f}  total {m['total']*100:6.1f}%  maxdd {m['maxdd']*100:6.1f}%"
              f"  beta {m['beta']:.2f}  alfa {m['alpha_ann']*100:5.1f}% (t {m['alpha_t']:.2f})", flush=True)

    # ---- comparativos
    bm = {"SPY": sim.benchmark(px, {"SPY": 1.0}, monthly=False),
          "60/40 SPY/AGG": sim.benchmark(px, {"SPY": 0.6, "AGG": 0.4}),
          "MUB": sim.benchmark(px, {"MUB": 1.0}, monthly=False),
          "BIL": sim.benchmark(px, {"BIL": 1.0}, monthly=False)}
    if "QQQ" in px:
        bm["QQQ"] = sim.benchmark(px, {"QQQ": 1.0}, monthly=False)
    bres = []
    for k, v in bm.items():
        m = sim.metrics(v, spy, bil)
        m["name"] = k
        bres.append(m)
        navs["bench:" + k] = v
    cal = navs[principal.name()].index
    fx = raw["MXN=X"].reindex(cal).ffill() if "MXN=X" in raw else None
    mxn = {}
    if fx is not None:
        f = fx / fx.iloc[0]
        for k in [principal.name(), sim.Spec(mode="E").name(), "bench:SPY"]:
            mxn[k] = float(navs[k].iloc[-1] * f.iloc[-1])
        cet = sim.cetes_mxn(a.rates, cal)
        mxn["CETES (aprox. tasa Banxico)"] = float(cet.iloc[-1])
        navs["bench:CETES_MXN"] = cet
        navs["fx:USDMXN"] = fx

    # ---- contribución, pesos y operaciones
    contrib = r_main["contrib"].sort_values()
    cls_of = t.drop_duplicates("ticker").set_index("ticker")["cls"]
    contrib_cls = r_main["contrib"].groupby(lambda k: cls_of.get(k, "efectivo")).sum()
    contrib_e = r_e["contrib"].sort_values()
    last_w = list(r_main["weights"].items())[-1][1].sort_values(ascending=False)
    ev = events.study(t, px)

    pd.DataFrame(navs).to_csv(out / "nav.csv", float_format="%.2f")
    ev.to_csv(out / "events.csv", index=False, float_format="%.5f")
    pd.DataFrame({"R": r_main["contrib"], "E": r_e["contrib"]}).to_csv(out / "contrib.csv", float_format="%.2f")
    last_w.to_csv(out / "weights_last.csv", float_format="%.5f")
    json.dump({"coverage": cov, "variants": res, "benchmarks": bres, "mxn_final": mxn,
               "contrib_class_R": contrib_cls.round(2).to_dict(),
               "top_contrib_R": contrib.tail(10).round(2).to_dict(), "worst_contrib_R": contrib.head(10).round(2).to_dict(),
               "top_contrib_E": contrib_e.tail(10).round(2).to_dict(), "worst_contrib_E": contrib_e.head(10).round(2).to_dict(),
               "weights_last_R_top15": last_w.head(15).round(4).to_dict(),
               "events": ev.to_dict(orient="records")}, open(out / "results.json", "w"), indent=1, default=str)
    print(json.dumps(cov, indent=1, default=str)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
