"""Grafo LangGraph del comité de inversión. Los LLM solo se consultan si las reglas en código pasan.

 cola → gather ─┬─ technical ─┐
                ├─ regime ────┤
                ├─ derivatives┼─→ rules_gate ─(técnico FLAT o veto)──────────────→ aggregate → journal
                └─ context ───┘        │ pasa      (context = calendario + eventos + on-chain, v4.2)
                              ┌────────┴────────┐
                          sentiment        methodology        (LLM, en paralelo)
                              └────────┬────────┘
                                   aggregate ─(VETO/INSUFFICIENT)→ journal
                                       │PASS
                                 bull ∥ bear → judge → risk_gate ─(rechazo)→ journal
                                                           │aprobado
                                                        execute → journal
"""
import asyncio
import logging
import uuid

from langgraph.graph import END, START, StateGraph

from . import agents, config, data, execution, risk, store
from .state import AgentState

log = logging.getLogger("graph")


async def gather(s: AgentState):
    did = s.get("decision_id") or (s["signal"].get("signal_id") or uuid.uuid4().hex)[:12]
    return {"market": await data.gather_market(s["pair"]), "decision_id": did}


async def risk_gate(s: AgentState):
    eq, free = await asyncio.to_thread(execution.equity)
    upnl = await asyncio.to_thread(execution.unrealized_pnl)
    # precio del venue de ejecución: la frescura y el sizing se miden donde se va a llenar la orden
    px = await asyncio.to_thread(execution.exec_price, s["pair"])
    s = {**s, "market": {**s["market"], "price": px}}
    return {"risk": await asyncio.to_thread(risk.evaluate, s, eq, free, upnl)}


async def execute(s: AgentState):
    res = await asyncio.to_thread(execution.buy_with_oco, s["risk"]["order"], s["decision_id"],
                                  s["signal"].get("signal_id", s["decision_id"]))
    return {"execution": res, "final_action": "BUY" if res.get("ok") else "BUY_FAILED"}


async def journal(s: AgentState):
    cons = s.get("portfolio", {}).get("consensus", {})
    if s.get("final_action") is None:
        if cons.get("gate") != "PASS":
            action, reason = "NO_TRADE", f"consenso {cons.get('gate')}: vetos={cons.get('vetoes')}"
        else:
            action, reason = "REJECTED", f"risk_gate: {s.get('risk', {}).get('failed')}"
    else:
        action = s["final_action"]
        reason = s.get("execution", {}).get("error", "ok")
    payload = {k: s.get(k) for k in ("signal", "reports", "bull_case", "bear_case", "judge", "risk", "execution")}
    payload["market_summary"] = {k: s["market"].get(k) for k in
                                 ("price", "trend_regime_1d", "vol_regime", "btc_regime", "fear_greed", "derivatives")}
    payload["context"] = next((r.get("context") for r in s.get("reports", []) if r["agent"] == "context"), None)
    shadow = _maybe_shadow(s, action)
    if shadow:
        payload["shadow_position"] = shadow
    payload["versions"] = {"release": config.RELEASE_ID, "llm": f"{config.LLM_PROVIDER}:{config.GEMINI_MODEL}"}
    sid = s["signal"].get("signal_id") or s["decision_id"]
    if not store.signal_seen(sid):  # llamada directa a run() sin pasar por el webhook (tests)
        store.claim_signal(sid, s["pair"])
    store.finish_decision(sid, action, reason, payload)
    log.info(f"[{s['decision_id']}] {s['pair']} → {action} | {reason}")
    return {"final_action": action}


def _rules_only_long(s: AgentState) -> bool:
    """La misma condición que usa backtest.py: técnico LONG + régimen sin veto y votando LONG."""
    reps = {r["agent"]: r for r in s.get("reports", [])}
    t, g = reps.get("technical"), reps.get("regime")
    return bool(t and g and t["vote"] == "LONG" and g["vote"] == "LONG" and not g["veto"])


def _maybe_shadow(s: AgentState, action: str):
    """Si las reglas solas habrían comprado y el bot no compró, abre una posición 'sombra' (sin dinero).
    Sirve para medir si los agentes LLM y los vetos suman o restan valor."""
    if action == "BUY" or not _rules_only_long(s):
        return None
    if any(p["pair"] == s["pair"] for p in store.shadow_positions() + store.open_positions()):
        return None  # las reglas también estarían ya dentro: no es un bloqueo del comité
    m = s["market"]
    sl, tp = agents._default_levels(m)
    if m["price"] <= sl:
        return None
    pid = f"S-{s['decision_id']}"
    unit = (m["price"] - sl) + (m["price"] + sl) * config.FEE_RATE
    qty = 1.0 / unit  # riesgo nominal = 1 USDT → pnl_usdt ≈ R
    store.open_position(id=pid, decision_id=s["decision_id"], pair=s["pair"], mode="shadow", qty=qty,
                        entry=m["price"], stop=sl, tp=tp, risk_usdt=1.0, entry_order_id="shadow", oco_id="shadow")
    return pid


async def rules_gate(s: AgentState):
    return {}


def route_after_rules(s: AgentState):
    reps = {r["agent"]: r for r in s.get("reports", [])}
    ok = reps["technical"]["vote"] == "LONG" and not any(r["veto"] for r in reps.values())
    return ["sentiment", "methodology"] if ok else "aggregate"


def route_after_aggregate(s: AgentState):
    return ["bull", "bear"] if s["portfolio"]["consensus"]["gate"] == "PASS" else "journal"


def route_after_risk(s: AgentState):
    return "execute" if s["risk"]["approved"] else "journal"


def build():
    g = StateGraph(AgentState)
    g.add_node("gather", gather)
    for name in ("technical", "regime", "derivatives", "context", "sentiment", "methodology", "aggregate", "bull", "bear",
                 "judge"):
        g.add_node(name, getattr(agents, name))
    g.add_node("rules_gate", rules_gate)
    g.add_node("risk_gate", risk_gate)
    g.add_node("execute", execute)
    g.add_node("journal", journal)

    g.add_edge(START, "gather")
    code_analysts = ["technical", "regime", "derivatives", "context"]
    for a in code_analysts:                               # fan-out en paralelo (sin LLM)
        g.add_edge("gather", a)
    g.add_edge(code_analysts, "rules_gate")               # fan-in: espera a los 4
    g.add_conditional_edges("rules_gate", route_after_rules, ["sentiment", "methodology", "aggregate"])
    g.add_edge(["sentiment", "methodology"], "aggregate")  # fan-in de los LLM
    g.add_conditional_edges("aggregate", route_after_aggregate, ["bull", "bear", "journal"])
    g.add_edge(["bull", "bear"], "judge")
    g.add_edge("judge", "risk_gate")
    g.add_conditional_edges("risk_gate", route_after_risk, ["execute", "journal"])
    g.add_edge("execute", "journal")
    g.add_edge("journal", END)
    return g.compile()


graph = build()


async def run(signal: dict) -> dict:
    pair = str(signal.get("pair", "")).upper().replace("BINANCE:", "")
    return await graph.ainvoke({"signal": signal, "pair": pair, "reports": [], "errors": []})
