"""
CryptoAgent v1.0 — Webhook Server
Receives TradingView alerts → Consults RAG → Calls Gemini → Returns trade decision
Deploy on Railway.app
"""
import os
import json
import time
import csv
import logging
from datetime import datetime, timedelta
from io import StringIO

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

# ── Config ──────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "crypto-agent-v1-secret")
SHEETS_WEBAPP_URL = os.environ.get("SHEETS_WEBAPP_URL", "")  # Google Apps Script URL
PAPER_TRADING = os.environ.get("PAPER_TRADING", "true").lower() == "true"

# ── Logging ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("CryptoAgent")

# ── App ─────────────────────────────────────────────────
app = FastAPI(title="CryptoAgent v1.0", version="1.0.0")

# ── In-memory state ─────────────────────────────────────
trade_log = []          # List of all trades this session
daily_pnl = 0.0         # Running daily P&L
weekly_pnl = 0.0        # Running weekly P&L
open_positions = []      # Currently open positions
last_daily_reset = datetime.utcnow().date()
last_weekly_reset = datetime.utcnow().isocalendar()[1]
satellite_pct = 20.0     # Dynamic satellite allocation %
trade_counter = 0

# ── OCEAN Personality Constants ─────────────────────────
PERSONALITY = {
    "openness": 75,          # Adapts strategy, doesn't invent new risk rules
    "conscientiousness": 95, # Always follows checklist
    "extraversion": 15,      # Zero FOMO, contrarian at extremes
    "agreeableness": 10,     # Cuts losses without mercy
    "neuroticism": 5,        # Zero panic, zero euphoria
}

# ── Risk Parameters (dynamically adjustable) ────────────
RISK_PARAMS = {
    "max_risk_per_trade": 0.005,   # 0.5%
    "max_total_exposure": 0.05,     # 5%
    "daily_drawdown_kill": -0.03,   # -3%
    "weekly_drawdown_kill": -0.05,  # -5%
    "min_confluence": 5,
    "min_confidence": 65,
    "min_rr": 2.0,
    "atr_multiplier": 2.0,
    "satellite_min": 10,
    "satellite_max": 30,
    "time_stop_swing_days": 5,
    "time_stop_meme_hours": 48,
    "protected_assets": ["BNB", "BNBUSDT", "BNBBUSD"],  # NEVER trade these
}


# ══════════════════════════════════════════════════════════
# RAG MODULE
# ══════════════════════════════════════════════════════════
import pickle
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

class RAGSearch:
    def __init__(self):
        self.loaded = False
        try:
            with open("rag/tfidf_vectorizer.pkl", "rb") as f:
                self.vectorizer = pickle.load(f)
            with open("rag/tfidf_matrix.pkl", "rb") as f:
                self.tfidf_matrix = pickle.load(f)
            with open("rag/chunks_metadata.json", "r") as f:
                self.metadata = json.load(f)
            self.loaded = True
            log.info(f"RAG loaded: {len(self.metadata)} chunks")
        except Exception as e:
            log.error(f"RAG load failed: {e}")

    def search(self, query, k=5):
        if not self.loaded:
            return []
        q_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self.tfidf_matrix).flatten()
        top_idx = scores.argsort()[-k:][::-1]
        results = []
        for idx in top_idx:
            if scores[idx] < 0.03:
                continue
            chunk = self.metadata[idx]
            results.append({
                "score": float(scores[idx]),
                "doc": chunk["doc_source"],
                "section": chunk["section"],
                "text": chunk["text"][:1500]  # Limit context size
            })
        return results

    def build_context(self, query, k=5, max_words=2000):
        results = self.search(query, k=k)
        parts = []
        total = 0
        for r in results:
            words = len(r["text"].split())
            if total + words > max_words:
                break
            parts.append(f'[{r["doc"]} | {r["section"]}]\n{r["text"]}')
            total += words
        return "\n\n---\n\n".join(parts)

rag = RAGSearch()


# ══════════════════════════════════════════════════════════
# MARKET CONTEXT MODULE
# ══════════════════════════════════════════════════════════
async def get_market_context():
    """Fetch free market data: Fear&Greed, BTC price, funding rates."""
    context = {}
    async with httpx.AsyncClient(timeout=10) as client:
        # Fear & Greed Index
        try:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            data = r.json()
            context["fear_greed"] = int(data["data"][0]["value"])
            context["fear_greed_label"] = data["data"][0]["value_classification"]
        except:
            context["fear_greed"] = 50
            context["fear_greed_label"] = "Neutral"

        # BTC Price from Binance public API (no key needed, more reliable than CoinGecko)
        for symbol, key in [("BTCUSDT", "btc_price"), ("ETHUSDT", "eth_price"), ("SOLUSDT", "sol_price")]:
            try:
                r = await client.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}")
                data = r.json()
                context[key] = float(data.get("lastPrice", 0))
                if key == "btc_price":
                    context["btc_24h_change"] = float(data.get("priceChangePercent", 0))
            except:
                context[key] = 0

        # Funding rate - use Binance global API (not fapi which has geo restrictions)
        try:
            r = await client.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
            context["btc_funding"] = 0  # Funding rate requires futures API, default to 0
        except:
            context["btc_funding"] = 0

    return context


# ══════════════════════════════════════════════════════════
# GEMINI LLM MODULE
# ══════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are an institutional-grade crypto trading agent with an OCEAN personality profile:
O:75 (adapts strategy, never invents risk rules), C:95 (always follows checklist), 
E:15 (zero FOMO, contrarian), A:10 (cuts losses mercilessly), N:5 (zero emotion).

You are a HOMO ECONOMICUS: maximize expected value, zero cognitive biases, zero irrational exuberance.

IMMUTABLE RULES:
1. CAPITAL PRESERVATION is primary. A 50% loss needs 100% gain to recover.
2. Minimum R:R of 1:2 for standard, 1:3 for aggressive setups.
3. MUST identify specific articulable EDGE. 'I think it will go up' is NOT an edge.
4. REGIME determines method: uptrend→trend-following, range→mean-reversion, downtrend→capital preservation.
5. Max 0.5% risk per trade (1% for highest conviction). Max 5% total exposure.
6. NEVER trade BNB pairs. BNB is reserved for commissions.
7. Pre-trade checklist: ALL 12 items must pass.

PORTFOLIO STRATEGY:
- CORE (70-90%): BTC, ETH, top L1s — conservative, trend-following
- SATELLITE (10-30%): High-risk altcoins, memecoins — momentum/scalp plays
- Satellite % adjusts dynamically based on recent win rate

RESPOND ONLY IN VALID JSON. No markdown, no explanation outside JSON."""

TRADE_DECISION_PROMPT = """
MARKET CONTEXT:
{market_context}

KNOWLEDGE BASE (from RAG):
{rag_context}

SIGNAL FROM TRADINGVIEW:
{signal}

PORTFOLIO STATE:
- Open positions: {open_positions}
- Daily P&L: {daily_pnl}%
- Weekly P&L: {weekly_pnl}%
- Satellite allocation: {satellite_pct}%
- Recent trades (last 5): {recent_trades}

SELF-LEARNING FEEDBACK:
{feedback}

Based on your knowledge base, market context, and self-learning feedback, evaluate this signal.

Respond ONLY in this exact JSON format:
{{
  "action": "BUY" | "SELL" | "NO_TRADE",
  "pair": "BTCUSDT",
  "direction": "LONG" | "SHORT",
  "bucket": "CORE" | "SATELLITE",
  "template": "T1_PULLBACK" | "T2_BREAK_RETEST" | "T3_RANGE_EXTREME" | "T4_LIQ_HUNT" | "T5_MOMENTUM" | "T6_MEME_SCALP",
  "entry_price": 87500,
  "stop_loss": 86100,
  "take_profit_1": 89200,
  "take_profit_2": 91000,
  "position_size_pct": 0.5,
  "confidence": 78,
  "regime_btc": "GREEN" | "YELLOW" | "RED",
  "trend_regime": "STRONG_UP",
  "vol_regime": "NORMAL",
  "confluence_score": 7,
  "edge_description": "Specific articulable edge",
  "reasoning": "Full reasoning chain",
  "checklist": {{
    "regime_identified": true,
    "aligned_higher_tf": true,
    "confluence_gte_5": true,
    "rr_gte_2": true,
    "sl_at_invalidation": true,
    "size_within_limits": true,
    "total_risk_under_5pct": true,
    "no_macro_event_4h": true,
    "mmsi_under_75": true,
    "altcoin_sps_dis_ok": true,
    "daily_dd_ok": true,
    "edge_articulated": true
  }},
  "checklist_pass": true,
  "risks": ["risk1", "risk2"],
  "self_learning_adjustment": "Any parameter adjustments recommended based on recent performance"
}}"""


async def call_gemini(prompt: str, system: str = SYSTEM_PROMPT) -> dict:
    """Call Gemini 2.5 Flash API (free tier)."""
    if not GEMINI_API_KEY:
        log.error("GEMINI_API_KEY not set")
        return {"action": "NO_TRADE", "reasoning": "API key not configured"}

    url = "https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": system + "\n\n---\n\n" + prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.8,
            "maxOutputTokens": 2048
        }
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            return json.loads(text)

        except json.JSONDecodeError as e:
            log.error(f"Gemini JSON parse error: {e}. Raw text: {text[:200]}")
            return {"action": "NO_TRADE", "reasoning": "LLM returned invalid JSON"}

        except httpx.HTTPStatusError as e:
            body = e.response.text
            log.error(f"Gemini HTTP error status={e.response.status_code} body={body}")
            return {"action": "NO_TRADE", "reasoning": f"LLM error: HTTP {e.response.status_code} | {body[:300]}"}

        except Exception as e:
            log.error(f"Gemini error: {e}")
            return {"action": "NO_TRADE", "reasoning": f"LLM error: {str(e)}"}


# ══════════════════════════════════════════════════════════
# RISK MANAGER
# ══════════════════════════════════════════════════════════
def check_kill_switches() -> tuple[bool, str]:
    """Check if any kill switch is active. Returns (is_active, reason)."""
    if daily_pnl <= RISK_PARAMS["daily_drawdown_kill"]:
        return True, f"Daily drawdown {daily_pnl:.2%} exceeds limit {RISK_PARAMS['daily_drawdown_kill']:.2%}"
    if weekly_pnl <= RISK_PARAMS["weekly_drawdown_kill"]:
        return True, f"Weekly drawdown {weekly_pnl:.2%} exceeds limit {RISK_PARAMS['weekly_drawdown_kill']:.2%}"
    return False, ""


def validate_trade(decision: dict) -> tuple[bool, str]:
    """Validate a trade decision against risk rules."""
    pair = decision.get("pair", "").upper()

    # BNB protection
    if any(protected in pair for protected in RISK_PARAMS["protected_assets"]):
        return False, f"BLOCKED: {pair} is a protected asset (BNB reserved for commissions)"

    # Checklist must pass
    if not decision.get("checklist_pass", False):
        return False, "Checklist did not pass"

    # Confidence minimum
    if decision.get("confidence", 0) < RISK_PARAMS["min_confidence"]:
        return False, f"Confidence {decision['confidence']}% below minimum {RISK_PARAMS['min_confidence']}%"

    # Confluence minimum
    if decision.get("confluence_score", 0) < RISK_PARAMS["min_confluence"]:
        return False, f"Confluence {decision['confluence_score']} below minimum {RISK_PARAMS['min_confluence']}"

    # R:R minimum
    entry = decision.get("entry_price", 0)
    sl = decision.get("stop_loss", 0)
    tp1 = decision.get("take_profit_1", 0)
    if entry and sl and tp1:
        risk = abs(entry - sl)
        reward = abs(tp1 - entry)
        if risk > 0:
            rr = reward / risk
            if rr < RISK_PARAMS["min_rr"]:
                return False, f"R:R {rr:.2f} below minimum {RISK_PARAMS['min_rr']}"

    # Total exposure check
    current_exposure = sum(p.get("risk_pct", 0) for p in open_positions)
    new_risk = decision.get("position_size_pct", 0) / 100
    if current_exposure + new_risk > RISK_PARAMS["max_total_exposure"]:
        return False, f"Total exposure {(current_exposure + new_risk):.2%} would exceed {RISK_PARAMS['max_total_exposure']:.2%}"

    # Satellite allocation check
    if decision.get("bucket") == "SATELLITE":
        sat_exposure = sum(p.get("risk_pct", 0) for p in open_positions if p.get("bucket") == "SATELLITE")
        if (sat_exposure + new_risk) * 100 > satellite_pct:
            return False, f"Satellite exposure would exceed current allocation of {satellite_pct}%"

    # Kill switches
    killed, reason = check_kill_switches()
    if killed:
        return False, f"KILL SWITCH: {reason}"

    return True, "All checks passed"


def compute_self_learning_feedback() -> str:
    """Analyze recent trades and generate feedback for the agent."""
    if len(trade_log) < 3:
        return "Insufficient data for self-learning (need 3+ trades)."

    recent = trade_log[-10:]
    wins = sum(1 for t in recent if t.get("resultado") == "WIN")
    losses = sum(1 for t in recent if t.get("resultado") == "LOSS")
    total = wins + losses
    win_rate = wins / total if total > 0 else 0

    sl_too_short = sum(1 for t in recent if t.get("sl_too_short"))
    tp_too_high = sum(1 for t in recent if t.get("tp_too_high"))

    feedback_parts = [f"Last {len(recent)} trades: {wins}W/{losses}L, Win Rate: {win_rate:.0%}"]

    if sl_too_short >= 3:
        feedback_parts.append(f"WARNING: {sl_too_short} trades had SL too short. Consider ATR multiplier 2.5 instead of {RISK_PARAMS['atr_multiplier']}")
    if tp_too_high >= 3:
        feedback_parts.append(f"WARNING: {tp_too_high} trades had unreachable TP. Consider reducing TP to 1.5R")

    # Satellite performance
    sat_trades = [t for t in recent if t.get("bucket") == "SATELLITE"]
    if sat_trades:
        sat_wins = sum(1 for t in sat_trades if t.get("resultado") == "WIN")
        sat_wr = sat_wins / len(sat_trades) if sat_trades else 0
        feedback_parts.append(f"Satellite performance: {sat_wr:.0%} win rate ({len(sat_trades)} trades)")
        if sat_wr < 0.4:
            feedback_parts.append("RECOMMENDATION: Reduce satellite allocation to minimum (10%)")
        elif sat_wr > 0.55:
            feedback_parts.append("RECOMMENDATION: Satellite performing well, maintain or increase to 25%")

    # Shorts analysis
    shorts = [t for t in recent if t.get("direction") == "SHORT"]
    if len(shorts) >= 3:
        short_losses = sum(1 for t in shorts if t.get("resultado") == "LOSS")
        if short_losses / len(shorts) > 0.6:
            feedback_parts.append("WARNING: Shorts losing >60%. Consider pausing shorts for 48h or verifying regime is truly bearish.")

    return "\n".join(feedback_parts)


# ══════════════════════════════════════════════════════════
# GOOGLE SHEETS BRIDGE
# ══════════════════════════════════════════════════════════
async def log_to_sheet(action: str, data: dict) -> dict:
    """Send data to Google Sheet via Apps Script."""
    if not SHEETS_WEBAPP_URL:
        log.warning("SHEETS_WEBAPP_URL not configured")
        return {"ok": False, "error": "Sheets not configured"}
    
    payload = {"action": action, **data}
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(SHEETS_WEBAPP_URL, json=payload, follow_redirects=True)
            result = r.json()
            log.info(f"Sheet {action}: {result.get('ok', False)}")
            return result
        except Exception as e:
            log.error(f"Sheet error: {e}")
            return {"ok": False, "error": str(e)}


async def get_sheet_feedback() -> str:
    """Get self-learning feedback from Google Sheet."""
    if not SHEETS_WEBAPP_URL:
        return compute_self_learning_feedback()  # Fallback to in-memory
    
    try:
        result = await log_to_sheet("get_feedback", {})
        if result.get("ok"):
            return result.get("feedback", "No feedback available")
    except:
        pass
    return compute_self_learning_feedback()


# ══════════════════════════════════════════════════════════
# API ENDPOINTS
# ══════════════════════════════════════════════════════════
@app.get("/")
async def root():
    return {
        "status": "CryptoAgent v1.0 running",
        "paper_trading": PAPER_TRADING,
        "rag_loaded": rag.loaded,
        "total_trades": len(trade_log),
        "open_positions": len(open_positions),
        "satellite_pct": satellite_pct,
        "kill_switch_active": check_kill_switches()[0]
    }


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/webhook")
async def webhook(request: Request):
    """Main webhook endpoint. Receives TradingView alerts."""
    global trade_counter, daily_pnl, satellite_pct

    # Validate secret
    body = await request.json()
    if body.get("secret") != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")

    signal = body
    pair = signal.get("pair", "UNKNOWN").upper()
    log.info(f"Signal received: {pair} | {signal.get('signal_type', 'N/A')}")

    # BNB protection — immediate reject
    if any(p in pair for p in RISK_PARAMS["protected_assets"]):
        return {"action": "BLOCKED", "reason": f"{pair} is protected (BNB for commissions)"}

    # Kill switch check
    killed, kill_reason = check_kill_switches()
    if killed:
        return {"action": "BLOCKED", "reason": kill_reason}

    # Get market context
    market_ctx = await get_market_context()

    # Build RAG query from signal
    rag_query = f"{signal.get('signal_type', '')} {pair} {signal.get('regime', '')} {signal.get('template', '')} risk management position sizing"
    rag_context = rag.build_context(rag_query, k=5, max_words=1500)

    # Self-learning feedback
    feedback = compute_self_learning_feedback()

    # Recent trades summary
    recent_summary = []
    for t in trade_log[-5:]:
        recent_summary.append(f"{t.get('pair')}:{t.get('resultado','?')}:{t.get('pnl_R','?')}")

    # Build Gemini prompt
    prompt = TRADE_DECISION_PROMPT.format(
        market_context=json.dumps(market_ctx, indent=2),
        rag_context=rag_context,
        signal=json.dumps(signal, indent=2),
        open_positions=json.dumps([{"pair": p["pair"], "direction": p["direction"]} for p in open_positions]),
        daily_pnl=f"{daily_pnl:.2%}",
        weekly_pnl=f"{weekly_pnl:.2%}",
        satellite_pct=satellite_pct,
        recent_trades=", ".join(recent_summary) or "No trades yet",
        feedback=feedback
    )

    # Call Gemini
    decision = await call_gemini(prompt)

    # Validate trade
    is_valid, validation_msg = validate_trade(decision)

    trade_counter += 1
    trade_id = f"T-{trade_counter:04d}"

    # Log the trade
    trade_record = {
        "trade_id": trade_id,
        "timestamp": datetime.utcnow().isoformat(),
        "pair": decision.get("pair", pair),
        "direction": decision.get("direction", ""),
        "bucket": decision.get("bucket", ""),
        "template": decision.get("template", ""),
        "regime_btc": decision.get("regime_btc", ""),
        "trend_regime": decision.get("trend_regime", ""),
        "vol_regime": decision.get("vol_regime", ""),
        "fear_greed": market_ctx.get("fear_greed", ""),
        "funding_rate": market_ctx.get("btc_funding", ""),
        "confluence_score": decision.get("confluence_score", 0),
        "confidence": decision.get("confidence", 0),
        "entry_price": decision.get("entry_price", 0),
        "stop_loss": decision.get("stop_loss", 0),
        "take_profit_1": decision.get("take_profit_1", 0),
        "take_profit_2": decision.get("take_profit_2", 0),
        "position_size_pct": decision.get("position_size_pct", 0),
        "edge": decision.get("edge_description", ""),
        "ejecutado": is_valid,
        "motivo_no_ejecutar": "" if is_valid else validation_msg,
        "reasoning": decision.get("reasoning", ""),
        "action": decision.get("action", "NO_TRADE"),
    }
    trade_log.append(trade_record)

    # Log to Google Sheet
    await log_to_sheet("log_trade", trade_record)

    if is_valid and decision.get("action") != "NO_TRADE":
        # Add to open positions (paper mode)
        if PAPER_TRADING:
            open_positions.append({
                "trade_id": trade_id,
                "pair": decision.get("pair"),
                "direction": decision.get("direction"),
                "bucket": decision.get("bucket"),
                "entry": decision.get("entry_price"),
                "sl": decision.get("stop_loss"),
                "tp1": decision.get("take_profit_1"),
                "risk_pct": decision.get("position_size_pct", 0) / 100,
                "opened_at": datetime.utcnow().isoformat()
            })
    return {
        "trade_id": trade_id,
        "action": decision.get("action", "NO_TRADE") if is_valid else "REJECTED",
        "executed": is_valid and decision.get("action") != "NO_TRADE",
        "paper_mode": PAPER_TRADING,
        "decision": decision,
        "validation": validation_msg,
        "market_context": market_ctx
    }


@app.get("/trades")
async def get_trades():
    """Get all trade history."""
    return {"total": len(trade_log), "trades": trade_log[-50:]}


@app.get("/positions")
async def get_positions():
    """Get open positions."""
    return {"count": len(open_positions), "positions": open_positions}


@app.get("/status")
async def get_status():
    """Get full agent status."""
    killed, kill_reason = check_kill_switches()
    return {
        "paper_trading": PAPER_TRADING,
        "rag_loaded": rag.loaded,
        "rag_chunks": len(rag.metadata) if rag.loaded else 0,
        "personality": PERSONALITY,
        "risk_params": RISK_PARAMS,
        "satellite_pct": satellite_pct,
        "total_trades": len(trade_log),
        "open_positions": len(open_positions),
        "daily_pnl": daily_pnl,
        "weekly_pnl": weekly_pnl,
        "kill_switch_active": killed,
        "kill_switch_reason": kill_reason,
        "feedback": compute_self_learning_feedback()
    }


@app.post("/close-trade")
async def close_trade(request: Request):
    """Manually close a trade (or webhook from TradingView on SL/TP hit)."""
    global daily_pnl, weekly_pnl
    body = await request.json()
    trade_id = body.get("trade_id")
    close_price = body.get("close_price", 0)
    motivo = body.get("motivo", "manual")

    # Find position
    pos = None
    for p in open_positions:
        if p["trade_id"] == trade_id:
            pos = p
            break

    if not pos:
        return {"error": f"Position {trade_id} not found"}

    # Calculate P&L
    entry = pos["entry"]
    direction = pos["direction"]
    if direction == "LONG":
        pnl_pct = (close_price - entry) / entry
    else:
        pnl_pct = (entry - close_price) / entry

    risk = abs(entry - pos["sl"]) / entry
    pnl_r = pnl_pct / risk if risk > 0 else 0
    resultado = "WIN" if pnl_pct > 0 else "LOSS" if pnl_pct < 0 else "BREAKEVEN"

    # Update running P&L
    daily_pnl += pnl_pct * pos["risk_pct"]
    weekly_pnl += pnl_pct * pos["risk_pct"]

    # Remove from open
    open_positions.remove(pos)

    # Update trade log
    for t in trade_log:
        if t["trade_id"] == trade_id:
            t["resultado"] = resultado
            t["pnl_R"] = f"{pnl_r:+.2f}R"
            t["precio_cierre"] = close_price
            t["motivo_cierre"] = motivo
            # Self-diagnosis
            t["sl_too_short"] = (resultado == "LOSS" and motivo == "SL_hit" and
                                 ((direction == "LONG" and close_price < entry and close_price * 1.02 > pos["tp1"]) or
                                  (direction == "SHORT" and close_price > entry)))
            break

    # Log close to Google Sheet
    await log_to_sheet("close_trade", {
        "trade_id": trade_id,
        "close_price": close_price,
        "resultado": resultado,
        "pnl_usdt": round(pnl_pct * pos["risk_pct"] * 10000, 2),  # Approximate
        "pnl_R": f"{pnl_r:+.2f}R",
        "duration_hours": "",
        "motivo_cierre": motivo,
        "sl_too_short": "SÍ" if (resultado == "LOSS" and motivo == "SL_hit") else "NO",
        "tp_too_high": "NO",
        "regime_changed": "NO",
        "strategy_correct": "SÍ" if resultado == "WIN" else "",
        "post_trade_notes": f"P&L: {pnl_r:+.2f}R | Daily: {daily_pnl:.2%} | Weekly: {weekly_pnl:.2%}"
    })

    return {"trade_id": trade_id, "resultado": resultado, "pnl_r": pnl_r}


# ── Keep-alive endpoint (prevents Railway cold starts) ──
@app.get("/ping")
async def ping():
    return {"pong": True, "time": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
