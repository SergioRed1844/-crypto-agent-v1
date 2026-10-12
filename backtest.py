"""Backtest de las REGLAS del bot (technical + regime + niveles por defecto), sin LLM.
Usa exactamente las mismas funciones que producción (app.indicators, app.agents).

Sin look-ahead:
  - en cada cierre de vela 4H solo se usan velas 1D/4H/1H ya cerradas a esa hora
  - la entrada es al OPEN de la vela 4H siguiente
  - si en una vela se tocan stop y take-profit, cuenta el stop
  - si la vela abre por debajo del stop (gap), sale al open, no al stop
  - comisión 0.1% por lado (FEE_RATE)

Uso (en tu Mac, Binance es accesible desde México):
  pip install -r requirements.txt
  python backtest.py --pairs BTCUSDT,ETHUSDT,SOLUSDT --since 2022-01-01
  python backtest.py --csv-dir datos/   # alternativa con CSV propios: <PAR>_<tf>.csv (ts,open,high,low,close,volume)
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import numpy as np
import pandas as pd

from app import agents, config, indicators as ind
from app.data import TF_MS

TFS = ("1d", "4h", "1h")
WARMUP = 210  # velas diarias necesarias para EMA200


def download(pair, tf, since_ms):
    import ccxt
    ex = ccxt.binance({"enableRateLimit": True})
    sym = pair.replace("USDT", "/USDT")
    out, cur = [], since_ms
    while True:
        rows = ex.fetch_ohlcv(sym, tf, since=cur, limit=1000)
        if not rows:
            break
        out += rows
        cur = rows[-1][0] + TF_MS[tf]
        if len(rows) < 1000:
            break
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return [r for r in out if r[0] + TF_MS[tf] <= now_ms]  # solo velas cerradas


def load(pair, since_ms, csv_dir):
    res = {}
    for tf in TFS:
        if csv_dir:
            df = pd.read_csv(os.path.join(csv_dir, f"{pair}_{tf}.csv"))
            rows = df[["ts", "open", "high", "low", "close", "volume"]].values.tolist()
        else:
            # el diario empieza 260 días antes para tener EMA200 desde el inicio
            pre = WARMUP * 86_400_000 + 50 * 86_400_000 if tf == "1d" else 400 * TF_MS[tf]
            rows = download(pair, tf, since_ms - pre)
            print(f"  {pair} {tf}: {len(rows)} velas", file=sys.stderr)
        res[tf] = ind.to_df(rows)
    return res


def market_at(dfs, btc_d1, t_close, pair):
    """Contexto tal como lo vería el servidor al cierre de la vela 4H que termina en t_close."""
    cut = {tf: dfs[tf][dfs[tf].index + pd.Timedelta(milliseconds=TF_MS[tf]) <= t_close].tail(300) for tf in TFS}
    if len(cut["1d"]) < WARMUP or len(cut["4h"]) < 60 or len(cut["1h"]) < 60:
        return None
    b = btc_d1[btc_d1.index + pd.Timedelta(days=1) <= t_close].tail(300)
    vol_reg, vol_ann = ind.vol_regime(cut["1d"])
    bt = ind.trend_regime(b)
    return {"pair": pair, "price": float(cut["4h"]["close"].iloc[-1]),
            "tf": {tf: ind.snapshot(cut[tf]) for tf in TFS},
            "trend_regime_1d": ind.trend_regime(cut["1d"]), "vol_regime": vol_reg,
            "vol_annualized_pct": round(vol_ann, 1), "btc_trend_1d": bt,
            "btc_regime": {"STRONG_UP": "GREEN", "WEAK_UP": "GREEN", "RANGE": "YELLOW",
                           "WEAK_DOWN": "YELLOW", "STRONG_DOWN": "RED"}[bt],
            "derivatives": {"funding_rate": None}, "fear_greed": {"value": None}, "macro_next": []}


async def decide(m, pair):
    s = {"signal": {}, "pair": pair, "market": m, "reports": []}
    tech = (await agents.technical(s))["reports"][0]
    reg = (await agents.regime(s))["reports"][0]
    ok = tech["vote"] == "LONG" and not reg["veto"] and reg["vote"] == "LONG"
    return ok, tech.get("confluence", 0)


def signals(pair, dfs, btc_d1, start_ts):
    """Paso 1 (lo caro): decisión de las reglas en cada cierre de vela 4H, sin posiciones."""
    h4 = dfs["4h"]
    out = {}
    loop = asyncio.new_event_loop()
    for i in range(len(h4.index) - 1):
        t_open = h4.index[i]
        if t_open < start_ts:
            continue
        m = market_at(dfs, btc_d1, t_open + pd.Timedelta(hours=4), pair)
        if m is None:
            continue
        ok, cs = loop.run_until_complete(decide(m, pair))
        if ok:
            sl_ref, tp_ref = agents._default_levels(m)
            out[h4.index[i + 1]] = {"ref": m["price"], "sl_ref": sl_ref, "tp_ref": tp_ref, "cs": cs}
    loop.close()
    return out


def _size_mult(cs):
    from app.risk import _size_mult as f
    return f(cs)


def portfolio(data, sigs, fee, slip):
    """Paso 2: un solo reloj para todos los pares, con los límites de producción (risk.py):
    1 posición por par, MAX_OPEN_POSITIONS, riesgo correlacionado total, factor por confluencia y
    tope de nocional (25% del equity). Orden sin look-ahead en cada vela t:
      a) entradas al OPEN de t (con la señal del cierre anterior) usando los cupos ocupados al open,
      b) salidas con el rango de t para TODAS las posiciones, incluidas las que entraron en t (stop primero)."""
    R_ = config.RISK
    times = sorted(set().union(*[set(d["4h"].index) for d in data.values()]))
    pos, trades = {}, []
    for t in times:
        for pair in data:  # a) entradas
            sg = sigs[pair].get(t)
            df = data[pair]["4h"]
            if not sg or pair in pos or len(pos) >= R_["max_open_positions"] or t not in df.index:
                continue
            entry = float(df.loc[t, "open"]) * (1 + slip)  # compra a mercado: paga slippage
            sl, tp = entry - (sg["ref"] - sg["sl_ref"]), entry + (sg["tp_ref"] - sg["ref"])
            if entry <= sl or (tp - entry) / (entry - sl) < R_["min_rr"]:
                continue
            unit_risk = (entry - sl) + (entry + sl) * fee
            # riesgo como fracción del equity: el menor entre el objetivo y lo que permite el tope de nocional
            risk_frac = min(_size_mult(sg["cs"]) * R_["risk_per_trade"], R_["max_position_notional"] * unit_risk / entry)
            if sum(p["risk_frac"] for p in pos.values()) + risk_frac > R_["max_correlated_risk"] + 1e-12:
                continue
            pos[pair] = {"t": t, "entry": entry, "sl": sl, "tp": tp, "cs": sg["cs"], "risk_frac": risk_frac,
                         "unit_risk": unit_risk}
        for pair in list(pos):  # b) salidas con la vela t
            df = data[pair]["4h"]
            if t not in df.index:
                continue
            bar, p = df.loc[t], pos[pair]
            o, hi, lo = bar["open"], bar["high"], bar["low"]
            exit_px = reason = None
            if p["t"] != t and o <= p["sl"]:
                exit_px, reason = o * (1 - slip), "SL_GAP"
            elif lo <= p["sl"]:
                exit_px, reason = p["sl"] * (1 - slip), "SL"   # el stop sale a mercado: paga slippage
            elif hi >= p["tp"]:
                exit_px, reason = p["tp"], "TP"                 # límite en reposo: llena a su precio
            if exit_px is not None:
                r = ((exit_px - p["entry"]) - (p["entry"] + exit_px) * fee) / p["unit_risk"]
                trades.append({"pair": pair, "entry_time": str(p["t"]), "exit_time": str(t), "entry": p["entry"],
                               "exit": exit_px, "reason": reason, "R": r, "confluence": p["cs"],
                               "risk_frac": p["risk_frac"], "portfolio_pct": r * p["risk_frac"] * 100})
                del pos[pair]
    return trades


def _boot(R, n=2000, seed=1):
    """Intervalo de confianza 95% de la expectativa por bootstrap. Si el límite inferior es <= 0,
    la ventaja no está demostrada aunque el promedio sea positivo."""
    rng = np.random.default_rng(seed)
    means = rng.choice(R, size=(n, len(R)), replace=True).mean(axis=1)
    return [round(float(np.percentile(means, 2.5)), 3), round(float(np.percentile(means, 97.5)), 3)]


def metrics(tr):
    if not tr:
        return {"trades": 0}
    R = np.array([t["R"] for t in tr])
    wins, losses = R[R > 0], R[R <= 0]
    eq = np.cumsum(R)
    dd = float((eq - np.maximum.accumulate(np.concatenate([[0], eq]))[1:]).min())
    return {"trades": int(len(R)), "win_rate": round(float((R > 0).mean()), 3),
            "expectancy_R": round(float(R.mean()), 3),
            "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else None,
            "total_R": round(float(R.sum()), 2), "max_drawdown_R": round(dd, 2),
            "retorno_portafolio_%": round(float(sum(t["portfolio_pct"] for t in tr)), 2),
            "expectancy_IC95_R": _boot(R),
            "worst_streak": int(max((len(s) for s in "".join("L" if x <= 0 else "W" for x in R).split("W")), default=0))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--since", default="2022-01-01")
    ap.add_argument("--csv-dir", default="")
    ap.add_argument("--oos-frac", type=float, default=0.4, help="fracción final reservada fuera de muestra")
    ap.add_argument("--slippage", type=float, default=0.0005, help="slippage por lado en entradas y stops")
    ap.add_argument("--out", default="backtest_trades.csv")
    a = ap.parse_args()
    since = pd.Timestamp(a.since, tz="UTC")
    since_ms = int(since.timestamp() * 1000)
    pairs = [p.strip().upper() for p in a.pairs.split(",")]
    data = {p: load(p, since_ms, a.csv_dir) for p in pairs}
    btc_d1 = data["BTCUSDT"]["1d"] if "BTCUSDT" in data else load("BTCUSDT", since_ms, a.csv_dir)["1d"]
    sigs = {p: signals(p, data[p], btc_d1, since) for p in pairs}
    all_tr = portfolio(data, sigs, config.FEE_RATE, a.slippage)
    all_tr.sort(key=lambda t: t["exit_time"])
    if not all_tr:
        print(json.dumps({"resultado": "0 trades: las reglas nunca dispararon"}, indent=2))
        return
    cut = int(len(all_tr) * (1 - a.oos_frac))
    first_ts = data[pairs[0]]["4h"].index
    report = {
        "periodo": f"{since.date()} a {first_ts[-1].date()}",
        "comision_por_lado": config.FEE_RATE,
        "slippage_por_lado": a.slippage,
        "limites": {k: config.RISK[k] for k in ("risk_per_trade", "max_open_positions", "max_correlated_risk", "min_rr")},
        "total": metrics(all_tr),
        "en_muestra (primer 60%)": metrics(all_tr[:cut]),
        "fuera_de_muestra (ultimo 40%)": metrics(all_tr[cut:]),
        "por_par": {p: metrics([t for t in all_tr if t["pair"] == p]) for p in pairs},
        "por_confluencia": {k: metrics([t for t in all_tr if (t["confluence"] >= 6) == (k == ">=6")])
                            for k in (">=6", "5")},
        "buy_and_hold_%": {p: round(float(data[p]["4h"]["close"].iloc[-1] /
                                          data[p]["4h"][data[p]["4h"].index >= since]["close"].iloc[0] - 1) * 100, 1)
                           for p in pairs},
        "criterio_gate_B": ("FUERA de muestra: 100+ trades, expectancy_R >= 0.3, profit_factor >= 1.5 y "
                            "límite inferior de expectancy_IC95_R > 0"),
    }
    pd.DataFrame(all_tr).to_csv(a.out, index=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
