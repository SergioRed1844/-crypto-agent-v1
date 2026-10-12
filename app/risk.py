"""Risk gate 100% determinista. Ningún LLM puede saltarse esto.
Implementa el Pre-Trade Checklist (§9.2) y el sizing por riesgo (no por % del saldo como el v3)."""
from . import config, store
from .state import AgentState

R = config.RISK


def _size_mult(confluence: int) -> float:
    # Methodology §7: CS 8+ = full, 5-7 = 50-75%
    if confluence >= 8:
        return 1.0
    if confluence >= 6:
        return 0.75
    return 0.5


def net_economics(price: float, sl: float, tp: float, fee: float | None = None, slip: float | None = None) -> dict:
    """Economía REAL del trade: compra a mercado con slippage, comisión de ida y vuelta, stop a mercado con slippage.
    Ejemplo real (scalp BTC 12-oct-2026): precio 83,773, stop 83,598, objetivo 84,358 → 2.5:1 bruto, 0.88:1 neto.
    Por eso se filtra en neto, no en bruto."""
    fee = config.FEE_RATE if fee is None else fee
    slip = config.SLIPPAGE if slip is None else slip
    entry = price * (1 + slip)
    stop_fill = sl * (1 - slip)
    gain = (tp - entry) - (entry + tp) * fee
    loss = (entry - stop_fill) + (entry + stop_fill) * fee
    return {"net_gain_pct": gain / entry if entry > 0 else 0.0, "net_loss_pct": loss / entry if entry > 0 else 0.0,
            "net_rr": gain / loss if loss > 0 else 0.0}


def _context(s: AgentState) -> dict:
    rep = next((r for r in s.get("reports", []) if r["agent"] == "context"), None)
    c = (rep or {}).get("context") or {}
    return {"veto": bool(rep and rep["veto"]), "state": c.get("state", "SIN_CONTEXTO"),
            "size_mult": float(c.get("size_mult", 1.0))}


def evaluate(s: AgentState, equity: float, usdt_free: float, unrealized: float = 0.0) -> dict:
    m, j, cons = s["market"], s["judge"], s["portfolio"]["consensus"]
    pair, price, atr = s["pair"], m["price"], m["tf"]["4h"]["atr"]
    checks = []

    def chk(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    base = pair.replace("USDT", "").replace("USDC", "")
    chk("par_permitido", pair in config.ALLOWED_PAIRS and base not in config.PROTECTED_ASSETS, pair)
    chk("consenso_multiagente", cons["gate"] == "PASS", f"{cons['gate']} votos={cons['long_votes']} vetos={cons['vetoes']}")
    chk("juez_compra", j.get("action") == "BUY", j.get("action"))
    chk("confianza_juez", j.get("confidence", 0) >= R["min_judge_confidence"], str(j.get("confidence")))
    chk("edge_articulado", len(str(j.get("edge", ""))) >= 20, "")
    chk("kill_switch_manual", not store.get("kill_switch", False), "")

    # Drawdown = realizado + flotante de lo abierto (el v4.0 solo veía lo realizado)
    d_pnl = (store.realized_pnl_since(24) + unrealized) / equity if equity else 0
    w_pnl = (store.realized_pnl_since(24 * 7) + unrealized) / equity if equity else 0
    chk("drawdown_diario", d_pnl > R["daily_dd_kill"], f"{d_pnl:.2%}")
    chk("drawdown_semanal", w_pnl > R["weekly_dd_kill"], f"{w_pnl:.2%}")

    opens = store.open_positions()
    chk("sin_posicion_en_par", all(p["pair"] != pair for p in opens), "")
    chk("max_posiciones", len(opens) < R["max_open_positions"], str(len(opens)))

    chk("sizing_valido", equity > 0 and atr > 0, f"equity={equity:.2f} atr={atr:.4f}")
    sig_price = float(s["signal"].get("price") or price)
    drift = abs(price - sig_price)
    chk("senal_fresca", drift <= R["max_entry_drift_atr"] * atr, f"drift={drift:.4f} atr={atr:.4f}")

    # Niveles SIEMPRE deterministas (los mismos que valida backtest.py). Los del LLM solo se registran:
    # un stop que no se backtesteó no debe mover dinero.
    from .agents import _default_levels
    sl, tp = _default_levels(m)
    rr = (tp - price) / (price - sl) if price > sl else 0
    chk("rr_minimo", rr >= R["min_rr"], f"{rr:.2f}")
    ne = net_economics(price, sl, tp) if price > sl else {"net_gain_pct": 0, "net_loss_pct": 0, "net_rr": 0}
    chk("ganancia_neta_minima", ne["net_gain_pct"] >= R["min_net_gain_pct"],
        f"{ne['net_gain_pct']:.2%} neto (mín {R['min_net_gain_pct']:.1%})")
    chk("rr_neto_minimo", ne["net_rr"] >= R["min_net_rr"], f"{ne['net_rr']:.2f} neto (mín {R['min_net_rr']})")
    streak = store.consecutive_losses()
    chk("racha_perdidas", streak < R["max_consecutive_losses"], f"{streak} seguidas (máx {R['max_consecutive_losses'] - 1})")
    ctx = _context(s)
    chk("contexto_sin_veto", not ctx["veto"], ctx["state"])

    # Riesgo por unidad = lo que de verdad se pierde en el stop: entrada con slippage, stop a mercado con slippage
    # y comisiones de ida y vuelta (así el 0.5% es un techo real, no nominal)
    _e, _s = price * (1 + config.SLIPPAGE), sl * (1 - config.SLIPPAGE)
    unit_risk = (_e - _s) + (_e + _s) * config.FEE_RATE if price > sl else 0
    risk_usdt = equity * R["risk_per_trade"] * _size_mult(cons.get("confluence", 5)) * max(0.0, min(1.0, ctx["size_mult"]))
    qty = risk_usdt / unit_risk if unit_risk > 0 else 0
    notional = qty * price
    cap = min(equity * R["max_position_notional"], usdt_free * 0.98)
    if notional > cap and price > 0:
        qty, notional = cap / price, cap
        risk_usdt = qty * unit_risk
    chk("nocional_minimo", notional >= R["min_notional_usdt"], f"{notional:.2f} USDT")
    open_risk = sum(p["risk_usdt"] or 0 for p in opens) + risk_usdt
    chk("riesgo_total_abierto", open_risk <= equity * R["max_open_risk"], f"{open_risk:.2f} USDT")
    chk("riesgo_correlacionado", open_risk <= equity * R["max_correlated_risk"],
        f"{open_risk:.2f} de {equity * R['max_correlated_risk']:.2f} USDT")

    approved = all(c["ok"] for c in checks)
    return {"approved": approved, "checks": checks,
            "failed": [c["check"] for c in checks if not c["ok"]],
            "order": {"pair": pair, "qty": qty, "entry_ref": price, "stop": sl, "tp": tp,
                      "risk_usdt": round(risk_usdt, 4), "notional": round(notional, 2), "rr": round(rr, 2),
                      "net_gain_pct": round(ne["net_gain_pct"], 5), "net_rr": round(ne["net_rr"], 3),
                      "context_state": ctx["state"], "context_size_mult": ctx["size_mult"]},
            "llm_levels_ignored": {"stop_loss": j.get("stop_loss"), "take_profit": j.get("take_profit")}}
