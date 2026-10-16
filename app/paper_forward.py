"""Prueba en papel v4.2 hacia adelante — swing BTC/ETH/SOL (1D/4H/1H). Corre cada hora en GitHub Actions.

Dos portafolios hipotéticos de 1,000 USDT con las MISMAS señales técnicas, decididas al cierre de cada vela de 4H:
  A · reglas v4.1 (technical + regime, niveles por defecto, límites de riesgo de producción)
  B · v4.2 completo: A + derivados estricto (F&G/funding) + contexto en vivo (calendario, noticias, on-chain)
      + ganancia neta mínima + pausa por racha de 5 pérdidas
La diferencia B − A mide en vivo si las capas nuevas suman o restan.

Sin look-ahead: cada vela se decide con datos cerrados hasta su cierre y con el contexto de ESE momento (la corrida
llega ≤ 2 h después; si llega más tarde, la señal se registra pero no se opera, igual que un webhook vencido).
Entradas a mercado al cierre + slippage; salidas con velas de 1H (stop primero, gap al open).
Meta: ≥ 30 trades cerrados en B y ≥ 14 días → deja de abrir y reporta contra el gate de papel.
Uso: python -m app.paper_forward [--state data/paper/state.json]
"""
import os

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
import pandas as pd  # noqa: E402

from app import agents, config, indicators as ind  # noqa: E402
from app.risk import _size_mult, net_economics  # noqa: E402

log = logging.getLogger("paper")
ROOT = Path(__file__).resolve().parents[1]
PAIRS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
EQ, FEE, SLIP = 1000.0, config.FEE_RATE, config.SLIPPAGE
R = config.RISK
H4 = pd.Timedelta(hours=4)
MAX_LAG = pd.Timedelta(hours=2)
GOAL_TRADES, MIN_DAYS, PAUSE_DAYS = 30, 14, 7
KL = "https://data-api.binance.vision/api/v3/klines"
UA = {"User-Agent": "cryptoagent-paper-v42"}


# ── datos ─────────────────────────────────────────────────────
def klines(c: httpx.Client, pair: str, tf: str, limit: int = 300, start_ms: int | None = None) -> list:
    out, now = [], int(time.time() * 1000)
    step = {"1d": 86_400_000, "4h": 14_400_000, "1h": 3_600_000}[tf]
    params = {"symbol": pair, "interval": tf, "limit": min(limit, 1000)}
    if start_ms:
        params["startTime"] = start_ms
    while True:
        rows = c.get(KL, params=params).raise_for_status().json()
        out += [[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows if r[0] + step <= now]
        if not start_ms or len(rows) < params["limit"]:
            break
        params["startTime"] = rows[-1][0] + step
    return out


def funding_now(c: httpx.Client, pair: str) -> tuple[float | None, str]:
    try:  # Binance futuros responde 451 a IPs de EE.UU. (GitHub Actions); entonces OKX
        r = c.get("https://fapi.binance.com/fapi/v1/premiumIndex", params={"symbol": pair})
        if r.status_code == 200:
            return float(r.json()["lastFundingRate"]), "binance"
    except Exception:
        pass
    try:
        r = c.get("https://www.okx.com/api/v5/public/funding-rate", params={"instId": pair.replace("USDT", "-USDT-SWAP")})
        if r.status_code == 200 and r.json().get("data"):
            return float(r.json()["data"][0]["fundingRate"]), "okx"
    except Exception:
        pass
    return None, "sin dato"


def fear_greed_now(c: httpx.Client) -> int | None:
    try:
        return int(c.get("https://api.alternative.me/fng/", params={"limit": 1}).json()["data"][0]["value"])
    except Exception:
        return None


def fetch_live(state: dict) -> dict:
    with httpx.Client(timeout=30, headers=UA) as c:
        start_1h = min([pd.Timestamp(p["last_checked"]).value // 1_000_000
                        for pf in state["portfolios"].values() for p in pf["positions"].values()] or [0])
        dfs = {}
        for p in PAIRS:
            dfs[p] = {"1d": ind.to_df(klines(c, p, "1d", 300)), "4h": ind.to_df(klines(c, p, "4h", 300)),
                      "1h": ind.to_df(klines(c, p, "1h", 300) if not start_1h
                                      else klines(c, p, "1h", 1000, min(start_1h, int(time.time() * 1000) - 300 * 3_600_000)))}
        fund = {p: funding_now(c, p) for p in PAIRS}
        fg = fear_greed_now(c)
    return {"dfs": dfs, "funding": fund, "fg": fg}


def context_now(now: datetime, market: dict) -> dict:
    try:
        from app.context import pipeline
        return pipeline.build_signal(now, market)
    except Exception as e:  # sin contexto no hay luz verde: precaución
        log.warning(f"contexto: {e}")
        from app.context.live import mock_signal
        s = mock_signal("CAUTION")
        s["reasons"] = [f"contexto no disponible ({type(e).__name__})"]
        return s


# ── estado ────────────────────────────────────────────────────
def new_state(now: datetime) -> dict:
    t0 = pd.Timestamp(now).floor("4h") - H4
    return {"started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "pairs": list(PAIRS), "goal_trades": GOAL_TRADES,
            "min_days": MIN_DAYS, "status": "corriendo", "last_bar": {p: str(t0) for p in PAIRS},
            "portfolios": {k: {"positions": {}, "trades": [], "streak": 0, "pause_until": None} for k in ("A", "B")},
            "decisions": [], "notified": [], "runs": 0}


def _iso(t) -> str:
    return pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ")


def _close(pf: dict, pair: str, px: float, t, why: str) -> dict:
    p = pf["positions"].pop(pair)
    r = ((px - p["entry"]) - (p["entry"] + px) * FEE) / p["unit"]
    tr = {"pair": pair, "entry_time": p["entry_time"], "exit_time": _iso(t), "entry": round(p["entry"], 6),
          "exit": round(px, 6), "why": why, "R": round(r, 3), "pct": round(r * p["risk_frac"] * 100, 4),
          "usdt": round(r * p["risk_frac"] * EQ, 2), "cs": p["cs"], "ctx_state": p.get("ctx_state")}
    pf["trades"].append(tr)
    pf["streak"] = pf["streak"] + 1 if r <= 0 else 0
    return tr


def manage_exits(state: dict, dfs: dict, now: datetime, ctx: dict | None) -> list:
    out = []
    for name, pf in state["portfolios"].items():
        for pair in list(pf["positions"]):
            p = pf["positions"][pair]
            h1 = dfs[pair]["1h"]
            bars = h1[(h1.index >= pd.Timestamp(p["entry_time"])) & (h1.index > pd.Timestamp(p["last_checked"]))]
            for t, b in bars.iterrows():
                first = t == pd.Timestamp(p["entry_time"])
                if not first and b["open"] <= p["sl"]:
                    out.append((name, _close(pf, pair, b["open"] * (1 - SLIP), t + pd.Timedelta(hours=1), "SL_GAP")))
                    break
                if b["low"] <= p["sl"]:
                    out.append((name, _close(pf, pair, p["sl"] * (1 - SLIP), t + pd.Timedelta(hours=1), "SL")))
                    break
                if b["high"] >= p["tp"]:
                    out.append((name, _close(pf, pair, p["tp"], t + pd.Timedelta(hours=1), "TP")))
                    break
                p["last_checked"] = _iso(t)
        if name == "B" and ctx and ctx.get("exit_all"):
            for pair in list(pf["positions"]):
                last = dfs[pair]["1h"]["close"].iloc[-1]
                out.append((name, _close(pf, pair, last * (1 - SLIP), now, "CONTEXTO_SALIDA")))
        if name == "B" and pf["streak"] >= R["max_consecutive_losses"] and not pf["pause_until"]:
            pf["pause_until"] = _iso(now + timedelta(days=PAUSE_DAYS))
            state.setdefault("events", []).append(f"{_iso(now)}: B en pausa {PAUSE_DAYS} días por 5 pérdidas seguidas")
    return out


def _try_enter(pf: dict, pair: str, m: dict, cs: int, t_close, size: float = 1.0) -> tuple[bool, str, dict | None]:
    if pair in pf["positions"]:
        return False, "ya hay posición en el par", None
    if len(pf["positions"]) >= R["max_open_positions"]:
        return False, f"máx {R['max_open_positions']} posiciones", None
    ref = m["price"]
    sl_ref, tp_ref = agents._default_levels(m)
    entry = ref * (1 + SLIP)
    sl, tp = entry - (ref - sl_ref), entry + (tp_ref - ref)
    if entry <= sl:
        return False, "stop inválido", None
    unit = (entry - sl) + (entry + sl) * FEE
    rf = min(_size_mult(cs) * R["risk_per_trade"] * size, R["max_position_notional"] * unit / entry)
    if rf <= 0:
        return False, "tamaño 0", None
    if sum(p["risk_frac"] for p in pf["positions"].values()) + rf > R["max_correlated_risk"] + 1e-12:
        return False, "riesgo correlacionado", None
    pos = {"pair": pair, "entry_time": _iso(t_close), "entry": entry, "sl": sl, "tp": tp, "unit": unit,
           "risk_frac": rf, "cs": cs, "last_checked": _iso(t_close - pd.Timedelta(hours=1))}
    pf["positions"][pair] = pos
    return True, "entra", pos


def process_bars(state: dict, live: dict, now: datetime, ctx_fn=context_now) -> list:
    """Decide cada vela 4H cerrada desde la última procesada. Devuelve las decisiones nuevas."""
    from backtest import decide, market_at
    dfs, out = live["dfs"], []
    btc_d1 = dfs["BTCUSDT"]["1d"]
    loop = asyncio.new_event_loop()
    try:
        for pair in PAIRS:
            h4 = dfs[pair]["4h"]
            last = pd.Timestamp(state["last_bar"][pair])
            for t_open in h4.index:
                t_close = t_open + H4
                if t_close <= last or t_close > pd.Timestamp(now):
                    continue
                state["last_bar"][pair] = str(t_close)
                m = market_at(dfs[pair], btc_d1, t_close, pair)
                if m is None:
                    continue
                ok, cs = loop.run_until_complete(decide(m, pair))
                if not ok:
                    continue
                d = {"t": _iso(t_close), "pair": pair, "cs": cs, "precio": round(m["price"], 6)}
                if pd.Timestamp(now) - t_close > MAX_LAG:
                    d.update(A="señal vieja (corrida atrasada)", B="señal vieja (corrida atrasada)")
                    out.append(d)
                    continue
                if state["status"] != "corriendo":
                    d.update(A="meta alcanzada: no abre", B="meta alcanzada: no abre")
                    out.append(d)
                    continue
                okA, whyA, _ = _try_enter(state["portfolios"]["A"], pair, m, cs, t_close)
                d["A"] = whyA
                # B: capas v4.2
                pfB = state["portfolios"]["B"]
                fr, fsrc = live["funding"].get(pair, (None, "sin dato"))
                mk = {"derivatives": {"funding_rate": fr}, "fear_greed": {"value": live["fg"]}}
                der = loop.run_until_complete(agents.derivatives({"market": mk}))["reports"][0]
                ctx = ctx_fn(now, {"btc_regime": m["btc_regime"], "vol_regime": m["vol_regime"], "fear_greed": live["fg"]})
                ne = net_economics(m["price"], *agents._default_levels(m))
                d.update(ctx=ctx["state"], fg=live["fg"], funding=fr, funding_src=fsrc,
                         neta=round(ne["net_gain_pct"], 4), rr_neto=round(ne["net_rr"], 2))
                if pfB["pause_until"] and pd.Timestamp(now) < pd.Timestamp(pfB["pause_until"]):
                    d["B"] = "pausa por racha de 5 pérdidas"
                elif der["veto"]:
                    d["B"] = "derivados: " + "; ".join(der["reasons"][-1:])[:80]
                elif ctx["veto_entries"]:
                    d["B"] = f"contexto {ctx['state']}: {(ctx['reasons'] or [''])[0][:70]}"
                elif cs < R["min_confluence"] + int(ctx.get("extra_confluence") or 0):
                    d["B"] = f"contexto {ctx['state']} pide confluencia {R['min_confluence'] + ctx['extra_confluence']} (tiene {cs})"
                elif ne["net_gain_pct"] < R["min_net_gain_pct"] or ne["net_rr"] < R["min_net_rr"]:
                    d["B"] = f"ganancia neta {ne['net_gain_pct']:.2%} / R:R neto {ne['net_rr']:.2f} insuficiente"
                else:
                    if pfB["pause_until"]:
                        pfB["pause_until"], pfB["streak"] = None, 0
                    okB, whyB, pos = _try_enter(pfB, pair, m, cs, t_close, ctx["size_mult"])
                    d["B"] = whyB
                    if pos:
                        pos["ctx_state"] = ctx["state"]
                out.append(d)
    finally:
        loop.close()
    state["decisions"] = (state["decisions"] + out)[-300:]
    return out


# ── métricas y reporte ────────────────────────────────────────
def metrics(trades: list) -> dict:
    if not trades:
        return {"trades": 0}
    Rs = [t["R"] for t in trades]
    w = [r for r in Rs if r > 0]
    lo = [r for r in Rs if r <= 0]
    eq = pk = dd = 0.0
    for t in trades:
        eq += t["usdt"]
        pk = max(pk, eq)
        dd = min(dd, eq - pk)
    return {"trades": len(Rs), "win_rate": round(len(w) / len(Rs), 3), "expectancy_R": round(sum(Rs) / len(Rs), 3),
            "profit_factor": round(sum(w) / -sum(lo), 2) if lo and sum(lo) < 0 else None,
            "rr_promedio": round((sum(w) / len(w)) / (-sum(lo) / len(lo)), 2) if w and lo else None,
            "usdt": round(sum(t["usdt"] for t in trades), 2), "max_dd_usdt": round(dd, 2)}


def floating(pf: dict, dfs: dict) -> float:
    tot = 0.0
    for pair, p in pf["positions"].items():
        last = dfs[pair]["1h"]["close"].iloc[-1] if pair in dfs else p["entry"]
        r = ((last - p["entry"]) - (p["entry"] + last) * FEE) / p["unit"]
        tot += r * p["risk_frac"] * EQ
    return round(tot, 2)


def gate(state: dict, now: datetime) -> dict:
    mB = metrics(state["portfolios"]["B"]["trades"])
    days = (pd.Timestamp(now) - pd.Timestamp(state["started_utc"])).total_seconds() / 86400
    g = {"≥30 trades": mB.get("trades", 0) >= GOAL_TRADES, "≥14 días": days >= MIN_DAYS,
         "ganadas >50%": (mB.get("win_rate") or 0) > 0.5, "R:R promedio ≥2.0": (mB.get("rr_promedio") or 0) >= 2.0,
         "drawdown <10%": (mB.get("max_dd_usdt") or 0) > -0.10 * EQ}
    return {"dias": round(days, 1), "checks": g, "aprobado": all(g.values())}


def render(state: dict, dfs: dict, now: datetime) -> str:
    MTY = -6
    f = lambda s: (pd.Timestamp(s) + pd.Timedelta(hours=MTY)).strftime("%d-%b %H:%M")
    g = gate(state, now)
    L = ["# Prueba en papel v4.2 — swing BTC/ETH/SOL", "",
         "> Dinero hipotético (1,000 USDT por portafolio). Ninguna orden real. Mismas señales técnicas para los dos "
         "portafolios: **A** = reglas v4.1, **B** = v4.2 completo (derivados estricto + contexto + ganancia neta + racha).", "",
         f"**Inicio:** {f(state['started_utc'])} (Monterrey) · **Actualizado:** {f(_iso(now))} · **Día {g['dias']}** · "
         f"**Estado:** {state['status']}", "",
         "| Portafolio | Trades | Ganadas | Expectativa R | PF | R:R promedio | Cerrado USDT | Flotante USDT | Máx DD USDT | Abiertas |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for k, name in (("A", "A · reglas v4.1"), ("B", "B · v4.2 completo")):
        pf = state["portfolios"][k]
        m = metrics(pf["trades"])
        L.append(f"| {name} | {m.get('trades', 0)} | {m.get('win_rate', '—')} | {m.get('expectancy_R', '—')} | "
                 f"{m.get('profit_factor') or '—'} | {m.get('rr_promedio') or '—'} | {m.get('usdt', 0):+.2f} | "
                 f"{floating(pf, dfs):+.2f} | {m.get('max_dd_usdt', 0)} | {len(pf['positions'])} |")
    L += ["", "**Gate de papel (portafolio B):** " + " · ".join(f"{'✅' if v else '⬜'} {k}" for k, v in g["checks"].items()), ""]
    for k in ("A", "B"):
        pf = state["portfolios"][k]
        if pf["positions"]:
            L += [f"### Posiciones abiertas {k}", "", "| Par | Entrada (MTY) | Precio | Stop | Objetivo | Contexto |",
                  "|---|---|---|---|---|---|"]
            L += [f"| {p['pair'][:-4]} | {f(p['entry_time'])} | {p['entry']:.6g} | {p['sl']:.6g} | {p['tp']:.6g} | "
                  f"{p.get('ctx_state', '—')} |" for p in pf["positions"].values()]
            L.append("")
    tr = sorted([dict(t, pf=k) for k in ("A", "B") for t in state["portfolios"][k]["trades"]],
                key=lambda x: x["exit_time"], reverse=True)[:20]
    if tr:
        L += ["### Últimas operaciones cerradas", "", "| Port. | Par | Entrada | Salida | Motivo | R | USDT |",
              "|---|---|---|---|---|---|---|"]
        L += [f"| {t['pf']} | {t['pair'][:-4]} | {f(t['entry_time'])} | {f(t['exit_time'])} | {t['why']} | {t['R']:+.2f} | "
              f"{t['usdt']:+.2f} |" for t in tr]
        L.append("")
    dec = state["decisions"][-15:][::-1]
    if dec:
        L += ["### Últimas señales técnicas y qué hizo cada portafolio", "",
              "| Vela 4H (MTY) | Par | Conf. | A | B | Contexto | F&G |", "|---|---|---|---|---|---|---|"]
        L += [f"| {f(d['t'])} | {d['pair'][:-4]} | {d['cs']} | {d.get('A', '')} | {d.get('B', '')} | {d.get('ctx', '—')} | "
              f"{d.get('fg', '—')} |" for d in dec]
    for e in state.get("events", [])[-5:]:
        L.append(f"- {e}")
    L += ["", "Gate completo (CLAUDE.md): ≥30 trades, ≥2 semanas, ganadas >50%, R:R promedio ≥2.0, drawdown <10%. "
          "Pasarlo NO activa dinero real: esa decisión es tuya y manual."]
    return "\n".join(L) + "\n"


def notify(state: dict, now: datetime) -> dict | None:
    nB = len(state["portfolios"]["B"]["trades"])
    msgs = []
    for ms in (1, 10, 20, 30):
        if nB >= ms and f"trades_{ms}" not in state["notified"]:
            state["notified"].append(f"trades_{ms}")
            mA, mB = metrics(state["portfolios"]["A"]["trades"]), metrics(state["portfolios"]["B"]["trades"])
            msgs.append(f"Prueba v4.2: {nB} trades cerrados en B ({mB.get('usdt', 0):+.2f} USDT, expectativa "
                        f"{mB.get('expectancy_R')}R) vs A {mA.get('trades', 0)} trades ({mA.get('usdt', 0):+.2f} USDT).")
    for e in state.get("events", []):
        if e not in state["notified"]:
            state["notified"].append(e)
            msgs.append(e)
    if not msgs:
        return None
    return {"title": f"[CryptoAgent papel v4.2] {nB} trades — {_iso(now)}",
            "body": "\n\n".join(msgs) + "\n\nTablero: data/paper/README.md (rama v4.2-contexto). Solo papel."}


def run(state_path: Path, now: datetime | None = None, live: dict | None = None, ctx_fn=context_now) -> dict:
    now = now or datetime.now(timezone.utc)
    state = json.loads(state_path.read_text()) if state_path.exists() else new_state(now)
    live = live or fetch_live(state)
    first_ctx = None
    if state["portfolios"]["B"]["positions"]:
        m = {"btc_regime": None, "vol_regime": None, "fear_greed": live["fg"]}
        first_ctx = ctx_fn(now, m)
    exits = manage_exits(state, live["dfs"], now, first_ctx)
    decs = process_bars(state, live, now, ctx_fn)
    if state["status"] == "corriendo" and len(state["portfolios"]["B"]["trades"]) >= GOAL_TRADES and \
            gate(state, now)["dias"] >= MIN_DAYS:
        state["status"] = "meta alcanzada"
        state.setdefault("events", []).append(f"{_iso(now)}: meta de {GOAL_TRADES} trades y {MIN_DAYS} días alcanzada; "
                                              "ya no abre posiciones nuevas")
    state["runs"] += 1
    state["updated_utc"] = _iso(now)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str))
    (state_path.parent / "README.md").write_text(render(state, live["dfs"], now), encoding="utf-8")
    n = notify(state, now)
    note = state_path.parent / "notify.json"
    if n:
        note.write_text(json.dumps(n, ensure_ascii=False))
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str))
    elif note.exists():
        note.unlink()
    return {"salidas": len(exits), "señales": len(decs), "entradas_A": sum(d.get("A") == "entra" for d in decs),
            "entradas_B": sum(d.get("B") == "entra" for d in decs), "estado": state["status"],
            "trades_B": len(state["portfolios"]["B"]["trades"])}


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=str(ROOT / "data" / "paper" / "state.json"))
    a = ap.parse_args(argv)
    print(json.dumps(run(Path(a.state)), ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
