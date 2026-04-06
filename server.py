"""
CryptoAgent v2.0 — Clean Webhook Server
Resolves: Gemini JSON, no Telegram, market fallbacks, idempotency, release_id
TradingView → Render webhook → RAG + Gemini → Google Sheets
"""
import os, json, logging, pickle, hashlib
import numpy as np
from datetime import datetime
from sklearn.metrics.pairwise import cosine_similarity
from fastapi import FastAPI, Request, HTTPException
import httpx

RELEASE_ID = "v2.2-20260405"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
SHEETS_WEBAPP_URL = os.environ.get("SHEETS_WEBAPP_URL", "")
PAPER_TRADING = os.environ.get("PAPER_TRADING", "true").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("CryptoAgent")
app = FastAPI(title="CryptoAgent", version=RELEASE_ID)

trade_log = []
open_positions = []
daily_pnl = 0.0
weekly_pnl = 0.0
satellite_pct = 20.0
trade_counter = 0
seen_signals = set()

PERSONALITY = {"O": 75, "C": 95, "E": 15, "A": 10, "N": 5}

RISK_PARAMS = {
    "max_risk_per_trade": 0.005,
    "max_total_exposure": 0.05,
    "daily_drawdown_kill": -0.03,
    "weekly_drawdown_kill": -0.05,
    "min_confluence": 5,
    "min_confidence": 65,
    "min_rr": 2.0,
    "atr_multiplier": 2.0,
    "satellite_min": 10,
    "satellite_max": 30,
    "protected_assets": ["BNB", "BNBUSDT", "BNBBUSD"],
}

# ═══════════════════════════════════════════════════════════
# RAG
# ═══════════════════════════════════════════════════════════
class RAGSearch:
    def __init__(self):
        self.loaded = False
        self.chunk_count = 0
        try:
            with open("rag/tfidf_vectorizer.pkl", "rb") as f:
                self.vectorizer = pickle.load(f)
            with open("rag/tfidf_matrix.pkl", "rb") as f:
                self.tfidf_matrix = pickle.load(f)
            with open("rag/chunks_metadata.json", "r") as f:
                self.metadata = json.load(f)
            if not hasattr(self.vectorizer, 'idf_'):
                raise ValueError("Vectorizer not fitted")
            self.chunk_count = len(self.metadata)
            self.loaded = True
            log.info(f"RAG loaded: {self.chunk_count} chunks, vocab={len(self.vectorizer.vocabulary_)}")
        except Exception as e:
            log.error(f"RAG load failed: {e}")

    def search(self, query, k=5):
        if not self.loaded:
            return []
        q_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self.tfidf_matrix).flatten()
        top_idx = scores.argsort()[-k:][::-1]
        return [
            {"score": float(scores[i]), "doc": self.metadata[i]["doc_source"],
             "section": self.metadata[i]["section"], "text": self.metadata[i]["text"][:1500]}
            for i in top_idx if scores[i] >= 0.03
        ]

    def build_context(self, query, k=5, max_words=1500):
        results = self.search(query, k)
        parts, total = [], 0
        for r in results:
            w = len(r["text"].split())
            if total + w > max_words:
                break
            parts.append(f'[{r["doc"]} | {r["section"]}]\n{r["text"]}')
            total += w
        return "\n\n---\n\n".join(parts)

rag = RAGSearch()

# ═══════════════════════════════════════════════════════════
# MARKET CONTEXT
# ═══════════════════════════════════════════════════════════
async def get_market_context():
    ctx = {"fear_greed": 50, "fear_greed_label": "Neutral",
           "btc_price": 0, "btc_24h_change": 0, "eth_price": 0, "sol_price": 0, "btc_funding": 0}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            d = r.json()
            ctx["fear_greed"] = int(d["data"][0]["value"])
            ctx["fear_greed_label"] = d["data"][0]["value_classification"]
        except Exception as e:
            log.warning(f"Fear&Greed failed: {e}")

        # Prices: CoinPaprika first (free, no key, no geo block), then Binance, then CoinGecko
        paprika_ids = {"btc_price": "btc-bitcoin", "eth_price": "eth-ethereum", "sol_price": "sol-solana"}
        for key, coin_id in paprika_ids.items():
            try:
                r = await client.get(f"https://api.coinpaprika.com/v1/tickers/{coin_id}")
                if r.status_code == 200:
                    d = r.json()
                    ctx[key] = float(d.get("quotes", {}).get("USD", {}).get("price", 0))
                    if key == "btc_price":
                        ctx["btc_24h_change"] = float(d.get("quotes", {}).get("USD", {}).get("percent_change_24h", 0))
                else:
                    raise Exception(f"CoinPaprika {r.status_code}")
            except Exception as e:
                log.warning(f"CoinPaprika {key} failed ({e}), trying Binance")
                try:
                    symbol = {"btc_price": "BTCUSDT", "eth_price": "ETHUSDT", "sol_price": "SOLUSDT"}[key]
                    r = await client.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
                    if r.status_code == 200:
                        ctx[key] = float(r.json().get("price", 0))
                except:
                    log.warning(f"All price sources failed for {key}")
    return ctx

# ═══════════════════════════════════════════════════════════
# GEMINI LLM
# ═══════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are an institutional-grade crypto trading agent.
Personality: O:75 C:95 E:15 A:10 N:5 (Homo Economicus, zero biases).

CRITICAL: You MUST respond ONLY in English. All JSON keys and values must be in English.
Never translate keys or enum values. Use exactly these values:
- action: "BUY", "SELL", or "NO_TRADE" (never "COMPRAR", "VENDER")
- direction: "LONG" or "SHORT" (never "LARGO", "CORTO")
- bucket: "CORE" or "SATELLITE" (never "NUCLEO", "SATELITE")

IMMUTABLE RULES:
1. CAPITAL PRESERVATION is primary. A 50% loss needs 100% gain to recover.
2. Minimum R:R of 1:2 for standard, 1:3 for aggressive setups.
3. MUST identify specific articulable EDGE. 'I think it will go up' is NOT an edge.
4. REGIME determines method: uptrend=trend-following, range=mean-reversion, downtrend=capital preservation.
5. Max 0.5% risk per trade, max 5% total exposure.
6. NEVER trade BNB pairs.
7. Pre-trade checklist: ALL 12 items must pass.

PORTFOLIO: CORE 70-90% (BTC/ETH/L1s) + SATELLITE 10-30% (high-risk altcoins/memes).

You MUST respond with ONLY valid JSON in English. No markdown fences, no explanation outside JSON."""

TRADE_PROMPT = """MARKET CONTEXT:
{market_context}

KNOWLEDGE BASE:
{rag_context}

SIGNAL: {signal}

PORTFOLIO: positions={positions}, daily_pnl={daily_pnl}, weekly_pnl={weekly_pnl}, satellite={satellite_pct}%

FEEDBACK: {feedback}

Evaluate this signal. Respond with ONLY this JSON (fill in real values):
{{"action":"BUY","pair":"BTCUSDT","direction":"LONG","bucket":"CORE","template":"T1_PULLBACK","entry_price":66800,"stop_loss":65400,"take_profit_1":69600,"take_profit_2":71000,"position_size_pct":0.5,"confidence":75,"regime_btc":"GREEN","trend_regime":"STRONG_UP","vol_regime":"NORMAL","confluence_score":7,"edge_description":"describe the edge","reasoning":"full reasoning","checklist_pass":true,"risks":["risk1"],"self_learning_adjustment":"none"}}"""


async def call_gemini(prompt: str) -> dict:
    if not GEMINI_API_KEY:
        return {"action": "NO_TRADE", "reasoning": "GEMINI_API_KEY not set"}

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": SYSTEM_PROMPT + "\n\n" + prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json"
        }
    }

    raw = ""
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code != 200:
                body = r.text[:500]
                log.error(f"Gemini HTTP {r.status_code}: {body}")
                return {"action": "NO_TRADE", "reasoning": f"Gemini HTTP {r.status_code}: {body}"}
            data = r.json()
            raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return json.loads(raw)
        except json.JSONDecodeError:
            log.error(f"Gemini invalid JSON: {raw[:300]}")
            return {"action": "NO_TRADE", "reasoning": "Gemini returned invalid JSON"}
        except Exception as e:
            log.error(f"Gemini error: {e}")
            return {"action": "NO_TRADE", "reasoning": str(e)}

# ═══════════════════════════════════════════════════════════
# RISK MANAGER
# ═══════════════════════════════════════════════════════════
def check_kill_switches():
    if daily_pnl <= RISK_PARAMS["daily_drawdown_kill"]:
        return True, f"Daily DD {daily_pnl:.2%} > {RISK_PARAMS['daily_drawdown_kill']:.2%}"
    if weekly_pnl <= RISK_PARAMS["weekly_drawdown_kill"]:
        return True, f"Weekly DD {weekly_pnl:.2%} > {RISK_PARAMS['weekly_drawdown_kill']:.2%}"
    return False, ""

def validate_trade(d: dict):
    pair = d.get("pair", "").upper()
    if any(p in pair for p in RISK_PARAMS["protected_assets"]):
        return False, f"BLOCKED: {pair} is protected (BNB)"
    if not d.get("checklist_pass", False):
        return False, "Checklist did not pass"
    if d.get("confidence", 0) < RISK_PARAMS["min_confidence"]:
        return False, f"Confidence {d.get('confidence')}% < {RISK_PARAMS['min_confidence']}%"
    if d.get("confluence_score", 0) < RISK_PARAMS["min_confluence"]:
        return False, f"Confluence {d.get('confluence_score')} < {RISK_PARAMS['min_confluence']}"
    entry = d.get("entry_price", 0)
    sl = d.get("stop_loss", 0)
    tp1 = d.get("take_profit_1", 0)
    if entry and sl and tp1:
        risk = abs(entry - sl)
        if risk > 0 and abs(tp1 - entry) / risk < RISK_PARAMS["min_rr"]:
            return False, f"R:R below {RISK_PARAMS['min_rr']}"
    cur_exp = sum(p.get("risk_pct", 0) for p in open_positions)
    new_risk = d.get("position_size_pct", 0) / 100
    if cur_exp + new_risk > RISK_PARAMS["max_total_exposure"]:
        return False, f"Total exposure {cur_exp + new_risk:.2%} > {RISK_PARAMS['max_total_exposure']:.2%}"
    killed, reason = check_kill_switches()
    if killed:
        return False, f"KILL SWITCH: {reason}"
    return True, "All checks passed"

def compute_feedback():
    if len(trade_log) < 3:
        return "Insufficient data (need 3+ trades)"
    recent = trade_log[-10:]
    wins = sum(1 for t in recent if t.get("resultado") == "WIN")
    losses = sum(1 for t in recent if t.get("resultado") == "LOSS")
    total = wins + losses
    return f"Last {len(recent)}: {wins}W/{losses}L WR:{wins/total:.0%}" if total > 0 else "No closed trades"

# ═══════════════════════════════════════════════════════════
# SHEETS BRIDGE
# ═══════════════════════════════════════════════════════════
async def log_to_sheet(action: str, data: dict):
    if not SHEETS_WEBAPP_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(SHEETS_WEBAPP_URL, json={"action": action, **data}, follow_redirects=True)
    except Exception as e:
        log.warning(f"Sheet error: {e}")

# ═══════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════
@app.get("/")
async def root():
    return {"status": "CryptoAgent running", "release": RELEASE_ID,
            "paper_trading": PAPER_TRADING, "rag_loaded": rag.loaded,
            "rag_chunks": rag.chunk_count, "total_trades": len(trade_log),
            "open_positions": len(open_positions), "satellite_pct": satellite_pct,
            "kill_switch_active": check_kill_switches()[0]}

@app.get("/health")
async def health():
    return {"status": "ok", "release": RELEASE_ID}

@app.get("/status")
async def get_status():
    killed, reason = check_kill_switches()
    return {"release": RELEASE_ID, "paper_trading": PAPER_TRADING,
            "rag": {"loaded": rag.loaded, "chunks": rag.chunk_count},
            "personality": PERSONALITY, "risk_params": RISK_PARAMS,
            "state": {"satellite_pct": satellite_pct, "trades": len(trade_log),
                      "open_positions": len(open_positions),
                      "daily_pnl": daily_pnl, "weekly_pnl": weekly_pnl},
            "kill_switch": {"active": killed, "reason": reason},
            "feedback": compute_feedback()}

@app.post("/webhook")
async def webhook(request: Request):
    global trade_counter
    body = await request.json()
    if body.get("secret") != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")

    pair = body.get("pair", "UNKNOWN").upper()
    log.info(f"Signal: {pair} | {body.get('signal_type', 'N/A')}")

    sig_hash = hashlib.md5(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    if sig_hash in seen_signals:
        return {"action": "DUPLICATE", "reason": "Signal already processed"}
    seen_signals.add(sig_hash)
    if len(seen_signals) > 100:
        seen_signals.clear()

    if any(p in pair for p in RISK_PARAMS["protected_assets"]):
        return {"action": "BLOCKED", "reason": f"{pair} is protected (BNB)"}

    killed, kill_reason = check_kill_switches()
    if killed:
        return {"action": "BLOCKED", "reason": kill_reason}

    market_ctx = await get_market_context()
    rag_query = f"{body.get('signal_type','')} {pair} {body.get('regime','')} {body.get('template','')} risk management"
    rag_context = rag.build_context(rag_query, k=5, max_words=1500)

    prompt = TRADE_PROMPT.format(
        market_context=json.dumps(market_ctx),
        rag_context=rag_context or "No RAG context",
        signal=json.dumps(body),
        positions=len(open_positions),
        daily_pnl=f"{daily_pnl:.2%}",
        weekly_pnl=f"{weekly_pnl:.2%}",
        satellite_pct=satellite_pct,
        feedback=compute_feedback()
    )

    decision = await call_gemini(prompt)
    is_valid, validation_msg = validate_trade(decision)

    trade_counter += 1
    trade_id = f"T-{trade_counter:04d}"

    record = {
        "trade_id": trade_id, "timestamp": datetime.utcnow().isoformat(),
        "pair": decision.get("pair", pair), "direction": decision.get("direction", ""),
        "bucket": decision.get("bucket", ""), "template": decision.get("template", ""),
        "regime_btc": decision.get("regime_btc", ""), "trend_regime": decision.get("trend_regime", ""),
        "vol_regime": decision.get("vol_regime", ""), "fear_greed": market_ctx.get("fear_greed", ""),
        "funding_rate": market_ctx.get("btc_funding", ""),
        "confluence_score": decision.get("confluence_score", 0),
        "confidence": decision.get("confidence", 0),
        "entry_price": decision.get("entry_price", 0),
        "stop_loss": decision.get("stop_loss", 0),
        "take_profit_1": decision.get("take_profit_1", 0),
        "take_profit_2": decision.get("take_profit_2", 0),
        "position_size_pct": decision.get("position_size_pct", 0),
        "edge_description": decision.get("edge_description", ""),
        "ejecutado": is_valid and decision.get("action") != "NO_TRADE",
        "motivo_no_ejecutar": "" if is_valid else validation_msg,
        "reasoning": decision.get("reasoning", ""),
        "action": decision.get("action", "NO_TRADE"),
    }
    trade_log.append(record)
    await log_to_sheet("log_trade", record)

    if is_valid and decision.get("action") != "NO_TRADE" and PAPER_TRADING:
        open_positions.append({
            "trade_id": trade_id, "pair": decision.get("pair"),
            "direction": decision.get("direction"), "bucket": decision.get("bucket"),
            "entry": decision.get("entry_price"), "sl": decision.get("stop_loss"),
            "tp1": decision.get("take_profit_1"),
            "risk_pct": decision.get("position_size_pct", 0) / 100,
            "opened_at": datetime.utcnow().isoformat()
        })

    return {"trade_id": trade_id,
            "action": decision.get("action", "NO_TRADE") if is_valid else "REJECTED",
            "executed": is_valid and decision.get("action") != "NO_TRADE",
            "paper_mode": PAPER_TRADING, "decision": decision,
            "validation": validation_msg, "market_context": market_ctx}

@app.get("/trades")
async def get_trades():
    return {"total": len(trade_log), "trades": trade_log[-50:]}

@app.get("/positions")
async def get_positions():
    return {"count": len(open_positions), "positions": open_positions}

@app.post("/close-trade")
async def close_trade(request: Request):
    global daily_pnl, weekly_pnl
    body = await request.json()
    tid = body.get("trade_id")
    cp = body.get("close_price", 0)
    motivo = body.get("motivo", "manual")
    pos = next((p for p in open_positions if p["trade_id"] == tid), None)
    if not pos:
        return {"error": f"Position {tid} not found"}
    pnl_pct = (cp - pos["entry"]) / pos["entry"] if pos["direction"] == "LONG" else (pos["entry"] - cp) / pos["entry"]
    risk = abs(pos["entry"] - pos["sl"]) / pos["entry"]
    pnl_r = pnl_pct / risk if risk > 0 else 0
    resultado = "WIN" if pnl_pct > 0 else "LOSS" if pnl_pct < 0 else "BREAKEVEN"
    daily_pnl += pnl_pct * pos["risk_pct"]
    weekly_pnl += pnl_pct * pos["risk_pct"]
    open_positions.remove(pos)
    for t in trade_log:
        if t["trade_id"] == tid:
            t.update({"resultado": resultado, "pnl_R": f"{pnl_r:+.2f}R", "precio_cierre": cp, "motivo_cierre": motivo})
    await log_to_sheet("close_trade", {
        "trade_id": tid, "close_price": cp, "resultado": resultado,
        "pnl_R": f"{pnl_r:+.2f}R", "motivo_cierre": motivo,
        "pnl_usdt": round(pnl_pct * 10000, 2),
        "sl_too_short": "NO", "tp_too_high": "NO",
        "regime_changed": "NO", "strategy_correct": "",
        "post_trade_notes": f"Daily:{daily_pnl:.2%} Weekly:{weekly_pnl:.2%}"
    })
    return {"trade_id": tid, "resultado": resultado, "pnl_r": pnl_r}

@app.get("/ping")
async def ping():
    return {"pong": True, "release": RELEASE_ID}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
