"""
CryptoAgent v4.0 — Production Server (Optimized)
TradingView → Render → RAG + Gemini → Binance (when PAPER_TRADING=false) → Google Sheets

Changes from v3:
  - Removed all Telegram references
  - Fixed SELL logic: sells proportional amount, not entire balance
  - Fixed ccxt pair formatting (handles edge cases like SOLUSDT)
  - Added daily/weekly PnL reset scheduler
  - Added retry logic for Gemini API calls
  - Added proper error handling for Binance minimum order sizes
  - Fixed stale signal detection with bounded threshold
  - Added max position per pair protection
  - Added circuit breaker for repeated losses
  - Fixed memory leak in seen_signals (now uses TTL)
  - Added startup self-test for all dependencies
  - Added Binance balance check before trade decisions
  - Fixed close_trade PnL calculation for portfolio tracking
  - Hardened webhook secret comparison (timing-safe)
  - Added /balance and /self-test endpoints
  - SYSTEM_PROMPT now includes available balance for LLM sizing
"""
import os, json, logging, pickle, hashlib, hmac, re, time, asyncio
import numpy as np
from datetime import datetime, timezone
from collections import OrderedDict
from sklearn.metrics.pairwise import cosine_similarity
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
RELEASE_ID = "v4.0-20260410"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
SHEETS_WEBAPP_URL = os.environ.get("SHEETS_WEBAPP_URL", "")
PAPER_TRADING = os.environ.get("PAPER_TRADING", "true").lower() == "true"
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET = os.environ.get("BINANCE_SECRET", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("CryptoAgent")

app = FastAPI(title="CryptoAgent", version=RELEASE_ID)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════
# BINANCE EXCHANGE INIT
# ═══════════════════════════════════════════════════════════
exchange = None
try:
    import ccxt
    if BINANCE_API_KEY and BINANCE_SECRET:
        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        try:
            exchange.load_markets()
            log.info(f"Binance initialized — {len(exchange.markets)} markets loaded")
        except Exception as e:
            log.warning(f"Binance markets load deferred: {e}")
    else:
        log.info("Binance keys not set — paper trading only")
except ImportError:
    log.warning("ccxt not installed — paper trading only")

# ═══════════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════════
trade_log = []
open_positions = []
daily_pnl = 0.0
weekly_pnl = 0.0
satellite_pct = 20.0
trade_counter = 0
last_daily_reset = datetime.now(timezone.utc).date()
last_weekly_reset = datetime.now(timezone.utc).isocalendar()[1]
consecutive_losses = 0

class TTLCache:
    """Signal dedup cache with TTL to prevent memory leaks."""
    def __init__(self, ttl_seconds=3600, max_size=200):
        self.cache = OrderedDict()
        self.ttl = ttl_seconds
        self.max_size = max_size

    def add(self, key):
        now = time.time()
        self._evict(now)
        self.cache[key] = now
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def __contains__(self, key):
        self._evict(time.time())
        return key in self.cache

    def _evict(self, now):
        expired = [k for k, t in self.cache.items() if now - t > self.ttl]
        for k in expired:
            del self.cache[k]

seen_signals = TTLCache(ttl_seconds=3600)

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
    "max_entry_drift_pct": 0.005,
    "max_consecutive_losses": 5,
    "max_positions_per_pair": 1,
    "min_order_usdt": 6.0,
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
            log.info(f"RAG loaded: {self.chunk_count} chunks")
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
SUPPORTED_PAIRS = {
    "BTCUSDT": {"paprika": "btc-bitcoin", "key": "btc_price", "ccxt": "BTC/USDT"},
    "ETHUSDT": {"paprika": "eth-ethereum", "key": "eth_price", "ccxt": "ETH/USDT"},
    "SOLUSDT": {"paprika": "sol-solana", "key": "sol_price", "ccxt": "SOL/USDT"},
}

async def get_market_context():
    ctx = {
        "fear_greed": 50, "fear_greed_label": "Neutral",
        "btc_price": 0, "btc_24h_change": 0, "eth_price": 0, "sol_price": 0,
        "btc_funding": 0, "timestamp": datetime.now(timezone.utc).isoformat()
    }
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            d = r.json()
            ctx["fear_greed"] = int(d["data"][0]["value"])
            ctx["fear_greed_label"] = d["data"][0]["value_classification"]
        except Exception as e:
            log.warning(f"Fear&Greed failed: {e}")

        for pair, info in SUPPORTED_PAIRS.items():
            key = info["key"]
            try:
                r = await client.get(f"https://api.coinpaprika.com/v1/tickers/{info['paprika']}")
                if r.status_code == 200:
                    d = r.json()
                    ctx[key] = float(d.get("quotes", {}).get("USD", {}).get("price", 0))
                    if key == "btc_price":
                        ctx["btc_24h_change"] = float(d.get("quotes", {}).get("USD", {}).get("percent_change_24h", 0))
                else:
                    raise Exception(f"HTTP {r.status_code}")
            except Exception:
                try:
                    r = await client.get(f"https://api.binance.com/api/v3/ticker/price?symbol={pair}")
                    if r.status_code == 200:
                        ctx[key] = float(r.json().get("price", 0))
                except Exception:
                    log.warning(f"All price sources failed for {key}")
    return ctx

def get_current_price(pair: str, market_ctx: dict) -> float:
    info = SUPPORTED_PAIRS.get(pair.upper())
    return float(market_ctx.get(info["key"], 0)) if info else 0.0

async def get_binance_balance() -> dict:
    if not exchange:
        return {"usdt_free": 0, "usdt_total": 0, "coins": {}}
    try:
        balance = exchange.fetch_balance()
        usdt = balance.get('USDT', {})
        coins = {}
        for sym in ['BTC', 'ETH', 'SOL']:
            free = float(balance.get(sym, {}).get('free', 0))
            if free > 0:
                coins[sym] = free
        return {
            "usdt_free": float(usdt.get('free', 0)),
            "usdt_total": float(usdt.get('total', 0)),
            "coins": coins
        }
    except Exception as e:
        log.error(f"Balance fetch error: {e}")
        return {"usdt_free": 0, "usdt_total": 0, "coins": {}, "error": str(e)}

# ═══════════════════════════════════════════════════════════
# GEMINI LLM
# ═══════════════════════════════════════════════════════════
SYSTEM_PROMPT_TEMPLATE = """You are an institutional-grade crypto trading agent.
Personality: O:75 C:95 E:15 A:10 N:5 (Homo Economicus, zero biases).

CRITICAL: You MUST respond ONLY in English. All JSON keys and values MUST be in English.
Use EXACTLY these values:
- action: "BUY", "SELL", or "NO_TRADE"
- direction: "LONG" or "SHORT"
- bucket: "CORE" or "SATELLITE"
- regime_btc: "GREEN", "YELLOW", or "RED"
- confidence: integer 0-100

IMMUTABLE RULES:
1. CAPITAL PRESERVATION is primary. A 50% loss needs 100% gain to recover.
2. Minimum R:R of 1:2 for standard, 1:3 for aggressive.
3. MUST identify specific articulable EDGE.
4. REGIME determines method: uptrend=trend-following, range=mean-reversion, downtrend=capital preservation.
5. Max 0.5% risk per trade, max 5% total exposure.
6. NEVER trade BNB pairs.
7. Pre-trade checklist: ALL 12 items must pass.
8. If entry price is stale (>0.5% drift), NO_TRADE.
9. Fear & Greed: extreme fear=opportunity, extreme greed=caution.
10. If consecutive losses >= 5, bias heavily toward NO_TRADE.

PORTFOLIO: CORE 70-90% (BTC/ETH) + SATELLITE 10-30% (altcoins).
Total capital is small (~$400 USD). Minimum Binance order ~$6 USDT.

AVAILABLE BALANCE: {available_balance}

Respond with ONLY valid JSON in English."""

TRADE_PROMPT = """MARKET CONTEXT:
{market_context}

KNOWLEDGE BASE:
{rag_context}

SIGNAL: {signal}

CURRENT MARKET PRICE: {current_price}

PORTFOLIO: positions={positions}, daily_pnl={daily_pnl}, weekly_pnl={weekly_pnl}, satellite={satellite_pct}%, consecutive_losses={consecutive_losses}, available_usdt={available_usdt}

SELF-LEARNING FEEDBACK:
{feedback}

Evaluate this signal. If entry differs >0.5% from current price, reject as stale.
Ensure position_size_pct produces at least $6 USDT order.
Respond with ONLY this JSON:
{{"action":"BUY","pair":"BTCUSDT","direction":"LONG","bucket":"CORE","template":"T1_PULLBACK","entry_price":0,"stop_loss":0,"take_profit_1":0,"take_profit_2":0,"position_size_pct":0.5,"confidence":75,"regime_btc":"GREEN","trend_regime":"STRONG_UP","vol_regime":"NORMAL","confluence_score":7,"edge_description":"","reasoning":"","checklist_pass":true,"risks":[],"self_learning_adjustment":"none"}}"""

_KEY_MAP = {
    "acción": "action", "accion": "action", "par": "pair",
    "dirección": "direction", "direccion": "direction",
    "cubo": "bucket", "plantilla": "template",
    "precio_entrada": "entry_price", "precio_de_entrada": "entry_price",
    "parada_de_pérdida": "stop_loss", "toma_de_ganancias_1": "take_profit_1",
    "toma_de_ganancias_2": "take_profit_2", "objetivo_1": "take_profit_1",
    "objetivo_2": "take_profit_2", "tamaño_posición_pct": "position_size_pct",
    "tamaño_de_posición_pct": "position_size_pct", "confianza": "confidence",
    "régimen_btc": "regime_btc", "regimen_btc": "regime_btc",
    "régimen_de_tendencia": "trend_regime", "regimen_de_tendencia": "trend_regime",
    "régimen_vol": "vol_regime", "regimen_vol": "vol_regime",
    "puntuación_confluencia": "confluence_score", "puntuacion_confluencia": "confluence_score",
    "descripción_del_edge": "edge_description", "descripcion_del_edge": "edge_description",
    "razonamiento": "reasoning", "checklist_aprobado": "checklist_pass",
    "riesgos": "risks", "ajuste_auto_aprendizaje": "self_learning_adjustment",
}
_VAL_MAP = {
    "COMPRAR": "BUY", "VENDER": "SELL", "SIN_OPERACIÓN": "NO_TRADE",
    "NO_OPERAR": "NO_TRADE", "LARGO": "LONG", "CORTO": "SHORT",
    "NÚCLEO": "CORE", "NUCLEO": "CORE", "SATÉLITE": "SATELLITE", "SATELITE": "SATELLITE",
    "VERDE": "GREEN", "AMARILLO": "YELLOW", "ROJO": "RED",
    "ALZA_FUERTE": "STRONG_UP", "ALZA_DÉBIL": "WEAK_UP", "RANGO": "RANGE",
    "BAJA_FUERTE": "STRONG_DOWN", "BAJA_DÉBIL": "WEAK_DOWN",
    "BAJO": "LOW", "NORMAL": "NORMAL", "ALTO": "HIGH", "EXTREMO": "EXTREME",
}
_DEFAULTS = {
    "action": "NO_TRADE", "pair": "", "direction": "", "bucket": "CORE",
    "template": "", "entry_price": 0, "stop_loss": 0, "take_profit_1": 0,
    "take_profit_2": 0, "position_size_pct": 0, "confidence": 0,
    "regime_btc": "YELLOW", "trend_regime": "RANGE", "vol_regime": "NORMAL",
    "confluence_score": 0, "edge_description": "", "reasoning": "",
    "checklist_pass": False, "risks": [], "self_learning_adjustment": "",
}

def normalize_gemini(d: dict) -> dict:
    result = {}
    for k, v in d.items():
        new_key = _KEY_MAP.get(k.lower().strip(), k)
        if isinstance(v, str):
            new_val = _VAL_MAP.get(v.upper().strip(), v)
        elif isinstance(v, dict):
            new_val = {_KEY_MAP.get(sk.lower().strip(), sk): sv for sk, sv in v.items()}
        else:
            new_val = v
        result[new_key] = new_val

    for field, default in _DEFAULTS.items():
        if field not in result:
            result[field] = default

    action = str(result.get("action", "")).upper()
    conf = 0
    try:
        conf = float(result.get("confidence", 0))
    except (ValueError, TypeError):
        conf = 0
    conf = max(0, min(100, conf))
    if action in ("BUY", "SELL") and conf == 0:
        confl = float(result.get("confluence_score", 0) or 0)
        conf = min(95, max(55, confl * 10))
    result["confidence"] = round(conf, 1)

    for num_field in ["entry_price", "stop_loss", "take_profit_1", "take_profit_2",
                      "position_size_pct", "confidence", "confluence_score"]:
        val = result.get(num_field, 0)
        if isinstance(val, str):
            val = val.replace("%", "").replace(",", "").strip()
        try:
            result[num_field] = float(val)
        except (ValueError, TypeError):
            result[num_field] = 0.0
    return result


async def call_gemini(prompt: str, system_prompt: str, retries: int = 2) -> dict:
    if not GEMINI_API_KEY:
        return {"action": "NO_TRADE", "reasoning": "GEMINI_API_KEY not set"}

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": system_prompt + "\n\n" + prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096, "responseMimeType": "application/json"}
    }

    for attempt in range(retries + 1):
        raw = ""
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 429:
                    wait = min(30, 5 * (attempt + 1))
                    log.warning(f"Gemini rate limited, waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                if r.status_code != 200:
                    log.error(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
                    if attempt < retries:
                        await asyncio.sleep(3)
                        continue
                    return {"action": "NO_TRADE", "reasoning": f"Gemini HTTP {r.status_code}"}
                data = r.json()
                raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                parsed = json.loads(raw)
                return normalize_gemini(parsed)
        except json.JSONDecodeError:
            log.error(f"Gemini bad JSON (attempt {attempt+1}): {raw[:200]}")
            try:
                cleaned = re.sub(r'^```json\s*', '', raw)
                cleaned = re.sub(r'\s*```$', '', cleaned)
                if cleaned.count('{') > cleaned.count('}'):
                    cleaned += '}' * (cleaned.count('{') - cleaned.count('}'))
                return normalize_gemini(json.loads(cleaned))
            except Exception:
                if attempt < retries:
                    await asyncio.sleep(2)
                    continue
                return {"action": "NO_TRADE", "reasoning": "Gemini invalid JSON"}
        except Exception as e:
            log.error(f"Gemini error: {e}")
            if attempt < retries:
                await asyncio.sleep(3)
                continue
            return {"action": "NO_TRADE", "reasoning": str(e)}
    return {"action": "NO_TRADE", "reasoning": "Gemini failed after retries"}

# ═══════════════════════════════════════════════════════════
# BINANCE EXECUTION
# ═══════════════════════════════════════════════════════════
def format_ccxt_pair(pair: str) -> str:
    pair = pair.upper().strip()
    if '/' in pair:
        return pair
    for quote in ['USDT', 'BUSD', 'USDC']:
        if pair.endswith(quote):
            return f"{pair[:-len(quote)]}/{quote}"
    return pair

def execute_binance_trade(pair: str, action: str, position_size_pct: float, current_price: float) -> tuple:
    if PAPER_TRADING:
        log.info(f"PAPER: {action} {pair} size={position_size_pct}% price={current_price:.2f}")
        return True, f"PAPER-{datetime.now(timezone.utc).strftime('%H%M%S%f')[:10]}"

    if not exchange:
        return False, "Binance not configured"

    try:
        if not exchange.markets:
            exchange.load_markets()

        ccxt_pair = format_ccxt_pair(pair)
        balance = exchange.fetch_balance()

        if action == 'BUY':
            usdt_free = float(balance.get('USDT', {}).get('free', 0))
            invest_amount = usdt_free * (position_size_pct / 100)

            if invest_amount < RISK_PARAMS["min_order_usdt"]:
                return False, f"Order {invest_amount:.2f} USDT < min {RISK_PARAMS['min_order_usdt']}. Free: {usdt_free:.2f}"

            if current_price <= 0:
                return False, "Price is 0"

            amount = invest_amount / current_price
            if ccxt_pair in exchange.markets:
                amount = float(exchange.amount_to_precision(ccxt_pair, amount))

            order = exchange.create_order(symbol=ccxt_pair, type='market', side='buy', amount=amount)
            log.info(f"BINANCE BUY: {ccxt_pair} amt={amount} cost={invest_amount:.2f} id={order['id']}")
            return True, str(order['id'])

        elif action == 'SELL':
            base_coin = ccxt_pair.split('/')[0]
            if base_coin.upper() == 'BNB':
                return False, "BLOCKED: BNB is protected"

            coin_free = float(balance.get(base_coin, {}).get('free', 0))
            if coin_free <= 0:
                return False, f"No {base_coin} balance"

            sell_ratio = min(1.0, position_size_pct / 100 * 20)
            sell_amount = coin_free * sell_ratio

            if ccxt_pair in exchange.markets:
                sell_amount = float(exchange.amount_to_precision(ccxt_pair, sell_amount))

            if sell_amount * current_price < RISK_PARAMS["min_order_usdt"]:
                sell_amount = coin_free
                if ccxt_pair in exchange.markets:
                    sell_amount = float(exchange.amount_to_precision(ccxt_pair, sell_amount))

            order = exchange.create_order(symbol=ccxt_pair, type='market', side='sell', amount=sell_amount)
            log.info(f"BINANCE SELL: {ccxt_pair} amt={sell_amount} id={order['id']}")
            return True, str(order['id'])

        return False, f"Unknown action: {action}"
    except Exception as e:
        log.error(f"Binance error: {e}")
        return False, str(e)

# ═══════════════════════════════════════════════════════════
# RISK MANAGEMENT
# ═══════════════════════════════════════════════════════════
def reset_pnl_if_needed():
    global daily_pnl, weekly_pnl, last_daily_reset, last_weekly_reset
    now = datetime.now(timezone.utc)
    if now.date() != last_daily_reset:
        log.info(f"Daily PnL reset: {daily_pnl:.4f} → 0")
        daily_pnl = 0.0
        last_daily_reset = now.date()
    if now.isocalendar()[1] != last_weekly_reset:
        log.info(f"Weekly PnL reset: {weekly_pnl:.4f} → 0")
        weekly_pnl = 0.0
        last_weekly_reset = now.isocalendar()[1]

def check_kill_switches():
    reset_pnl_if_needed()
    if daily_pnl <= RISK_PARAMS["daily_drawdown_kill"]:
        return True, f"Daily DD {daily_pnl:.2%}"
    if weekly_pnl <= RISK_PARAMS["weekly_drawdown_kill"]:
        return True, f"Weekly DD {weekly_pnl:.2%}"
    if consecutive_losses >= RISK_PARAMS["max_consecutive_losses"]:
        return True, f"Circuit breaker: {consecutive_losses} consecutive losses"
    return False, ""

def stale_signal_check(signal: dict, decision: dict, market_ctx: dict) -> tuple:
    action = str(decision.get("action", "")).upper()
    if action not in ("BUY", "SELL"):
        return False, ""
    pair = str(decision.get("pair") or signal.get("pair") or "").upper()
    entry = float(decision.get("entry_price") or signal.get("price") or 0)
    current = get_current_price(pair, market_ctx)
    if current <= 0:
        return True, f"Price unavailable for {pair}"
    if entry <= 0:
        return True, "entry_price is 0"
    drift = abs(current - entry) / entry
    atr = float(signal.get("atr", 0) or 0)
    signal_price = float(signal.get("price", 0) or 0)
    threshold = (atr / signal_price) if (atr > 0 and signal_price > 0) else RISK_PARAMS["max_entry_drift_pct"]
    threshold = max(0.003, min(0.02, threshold))
    if drift > threshold:
        return True, f"Stale: {current:.2f} drifted {drift:.2%} from {entry:.2f} (max {threshold:.2%})"
    return False, ""

def validate_trade(d: dict, signal: dict = None, market_ctx: dict = None):
    pair = d.get("pair", "").upper()
    action = str(d.get("action", "NO_TRADE")).upper()

    if any(p in pair for p in RISK_PARAMS["protected_assets"]):
        return False, f"BLOCKED: {pair} (BNB)"
    if action == "NO_TRADE":
        return False, d.get("reasoning", "Model decided NO_TRADE")
    if not d.get("checklist_pass", False):
        return False, "Checklist failed"
    if signal and market_ctx:
        is_stale, msg = stale_signal_check(signal, d, market_ctx)
        if is_stale:
            return False, msg

    conf = float(d.get("confidence", 0) or 0)
    if conf < RISK_PARAMS["min_confidence"]:
        return False, f"Confidence {conf:.0f}% < {RISK_PARAMS['min_confidence']}%"
    if d.get("confluence_score", 0) < RISK_PARAMS["min_confluence"]:
        return False, f"Confluence {d.get('confluence_score')} < {RISK_PARAMS['min_confluence']}"

    entry = float(d.get("entry_price", 0) or 0)
    sl = float(d.get("stop_loss", 0) or 0)
    tp1 = float(d.get("take_profit_1", 0) or 0)
    if entry and sl and abs(entry - sl) < 0.0001:
        return False, "SL = entry (zero risk)"
    if entry and sl and tp1:
        risk = abs(entry - sl)
        if risk > 0 and abs(tp1 - entry) / risk < RISK_PARAMS["min_rr"]:
            return False, f"R:R < {RISK_PARAMS['min_rr']}"

    cur_exp = sum(p.get("risk_pct", 0) for p in open_positions)
    new_risk = d.get("position_size_pct", 0) / 100
    if cur_exp + new_risk > RISK_PARAMS["max_total_exposure"]:
        return False, f"Exposure {cur_exp + new_risk:.2%} > {RISK_PARAMS['max_total_exposure']:.2%}"

    pair_positions = sum(1 for p in open_positions if p.get("pair", "").upper() == pair)
    if pair_positions >= RISK_PARAMS["max_positions_per_pair"]:
        return False, f"Max positions for {pair} reached"

    killed, reason = check_kill_switches()
    if killed:
        return False, f"KILL: {reason}"
    return True, "All checks passed"

# ═══════════════════════════════════════════════════════════
# FEEDBACK & SHEETS
# ═══════════════════════════════════════════════════════════
async def get_feedback(pair: str = "") -> str:
    if SHEETS_WEBAPP_URL:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                payload = {"action": "get_feedback"}
                if pair:
                    payload["pair"] = pair
                r = await client.post(SHEETS_WEBAPP_URL, json=payload, follow_redirects=True)
                data = r.json()
                if data.get("ok") and data.get("feedback"):
                    return data["feedback"]
        except Exception as e:
            log.warning(f"Sheet feedback error: {e}")

    if len(trade_log) < 3:
        return "Insufficient data"
    recent = ([t for t in trade_log[-20:] if t.get("pair", "").upper() == pair.upper()][-10:]
              if pair else trade_log[-10:])
    if not recent:
        return f"No trades for {pair}" if pair else "No trades"
    wins = sum(1 for t in recent if t.get("resultado") == "WIN")
    losses = sum(1 for t in recent if t.get("resultado") == "LOSS")
    total = wins + losses
    parts = []
    if total > 0:
        parts.append(f"{pair or 'ALL'} last {len(recent)}: {wins}W/{losses}L WR:{wins/total:.0%}")
    return " | ".join(parts) if parts else "No closed trades"

async def log_to_sheet(sheet_action: str, data: dict):
    if not SHEETS_WEBAPP_URL:
        return {"ok": False, "error": "Sheets not configured"}
    try:
        payload = dict(data)
        if "action" in payload:
            payload["decision_action"] = payload.pop("action")
        payload["action"] = sheet_action
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(SHEETS_WEBAPP_URL, json=payload, follow_redirects=True)
            try:
                result = r.json()
                log.info(f"Sheet {sheet_action}: ok={result.get('ok')}")
                return result
            except Exception:
                return {"ok": False}
    except Exception as e:
        log.warning(f"Sheet error: {e}")
        return {"ok": False, "error": str(e)}

# ═══════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════
@app.get("/")
async def root():
    killed, reason = check_kill_switches()
    return {
        "status": "CryptoAgent running", "release": RELEASE_ID,
        "paper_trading": PAPER_TRADING, "rag_loaded": rag.loaded,
        "total_trades": len(trade_log), "open_positions": len(open_positions),
        "kill_switch": killed, "binance_connected": exchange is not None,
    }

@app.get("/health")
async def health():
    return {"status": "ok", "release": RELEASE_ID}

@app.get("/ping")
async def ping():
    return {"pong": True, "release": RELEASE_ID}

@app.get("/status")
async def get_status():
    killed, reason = check_kill_switches()
    bal = await get_binance_balance() if exchange else {}
    return {
        "release": RELEASE_ID, "paper_trading": PAPER_TRADING,
        "rag": {"loaded": rag.loaded, "chunks": rag.chunk_count},
        "risk_params": RISK_PARAMS,
        "state": {"trades": len(trade_log), "open": len(open_positions),
                  "daily_pnl": daily_pnl, "weekly_pnl": weekly_pnl,
                  "consecutive_losses": consecutive_losses},
        "kill_switch": {"active": killed, "reason": reason},
        "binance": {"connected": exchange is not None, "paper": PAPER_TRADING, "balance": bal},
        "feedback": await get_feedback()
    }

@app.get("/balance")
async def balance_endpoint():
    if not exchange:
        return {"error": "Binance not configured", "paper": PAPER_TRADING}
    return await get_binance_balance()

@app.post("/webhook")
async def webhook(request: Request):
    global trade_counter, consecutive_losses
    body = await request.json()

    if not hmac.compare_digest(str(body.get("secret", "")), WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid secret")

    pair = body.get("pair", "UNKNOWN").upper()
    signal_type = body.get("signal_type", "N/A")
    log.info(f"Signal: {pair} | {signal_type}")

    # Special signals
    if signal_type == "KILL_SWITCH":
        log.warning(f"Kill switch: {body.get('reason')}")
        return {"action": "KILL_SWITCH", "reason": body.get("reason")}
    if signal_type == "REGIME_CHANGE":
        log.info(f"Regime: {body.get('old_regime')} → {body.get('new_regime')}")
        return {"action": "INFO", "regime_change": body.get("new_regime")}

    # Dedup
    sig_hash = hashlib.md5(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    if sig_hash in seen_signals:
        return {"action": "DUPLICATE"}
    seen_signals.add(sig_hash)

    if any(p in pair for p in RISK_PARAMS["protected_assets"]):
        return {"action": "BLOCKED", "reason": "BNB protected"}

    killed, kill_reason = check_kill_switches()
    if killed:
        return {"action": "BLOCKED", "reason": kill_reason}

    # Context
    market_ctx = await get_market_context()
    current_price = get_current_price(pair, market_ctx)
    bal = await get_binance_balance() if exchange else {"usdt_free": 0}
    rag_context = rag.build_context(
        f"{signal_type} {pair} {body.get('regime','')} {body.get('template','')} risk management",
        k=5, max_words=1500
    )
    feedback = await get_feedback(pair=pair)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(available_balance=json.dumps(bal))
    prompt = TRADE_PROMPT.format(
        market_context=json.dumps(market_ctx),
        rag_context=rag_context or "No RAG context",
        signal=json.dumps(body),
        current_price=f"{current_price:.2f}",
        positions=len(open_positions),
        daily_pnl=f"{daily_pnl:.2%}",
        weekly_pnl=f"{weekly_pnl:.2%}",
        satellite_pct=satellite_pct,
        consecutive_losses=consecutive_losses,
        available_usdt=f"{bal.get('usdt_free', 0):.2f}",
        feedback=feedback
    )

    decision = await call_gemini(prompt, system_prompt)
    is_valid, validation_msg = validate_trade(decision, signal=body, market_ctx=market_ctx)

    trade_counter += 1
    trade_id = f"T-{trade_counter:04d}"

    binance_order_id = "N/A"
    if is_valid and decision.get("action") in ("BUY", "SELL"):
        success, exec_msg = execute_binance_trade(
            pair=decision.get("pair", pair),
            action=decision.get("action"),
            position_size_pct=decision.get("position_size_pct", 0),
            current_price=current_price
        )
        if not success:
            is_valid = False
            validation_msg = f"Binance: {exec_msg}"
        else:
            binance_order_id = exec_msg

    record = {
        "trade_id": trade_id, "timestamp": datetime.now(timezone.utc).isoformat(),
        "pair": decision.get("pair", pair), "direction": decision.get("direction", ""),
        "bucket": decision.get("bucket", ""), "template": decision.get("template", ""),
        "regime_btc": decision.get("regime_btc", ""), "trend_regime": decision.get("trend_regime", ""),
        "vol_regime": decision.get("vol_regime", ""), "fear_greed": market_ctx.get("fear_greed", ""),
        "funding_rate": market_ctx.get("btc_funding", ""),
        "confluence_score": decision.get("confluence_score", 0),
        "confidence": decision.get("confidence", 0),
        "entry_price": decision.get("entry_price", 0), "stop_loss": decision.get("stop_loss", 0),
        "take_profit_1": decision.get("take_profit_1", 0), "take_profit_2": decision.get("take_profit_2", 0),
        "position_size_pct": decision.get("position_size_pct", 0),
        "edge_description": decision.get("edge_description", ""),
        "ejecutado": is_valid and decision.get("action") != "NO_TRADE",
        "motivo_no_ejecutar": "" if is_valid else validation_msg,
        "reasoning": decision.get("reasoning", ""),
        "decision_action": decision.get("action", "NO_TRADE"),
        "signal_price": body.get("price", 0), "current_market_price": current_price,
        "signal_hash": sig_hash, "release": RELEASE_ID,
        "feedback_used": feedback, "binance_order_id": binance_order_id,
        "execution_mode": "PAPER" if PAPER_TRADING else "LIVE",
    }
    trade_log.append(record)
    await log_to_sheet("log_trade", record)

    if is_valid and decision.get("action") != "NO_TRADE":
        open_positions.append({
            "trade_id": trade_id, "pair": decision.get("pair", pair),
            "direction": decision.get("direction"), "bucket": decision.get("bucket"),
            "entry": decision.get("entry_price"), "sl": decision.get("stop_loss"),
            "tp1": decision.get("take_profit_1"),
            "risk_pct": decision.get("position_size_pct", 0) / 100,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "binance_order_id": binance_order_id,
        })

    return {
        "trade_id": trade_id,
        "action": decision.get("action", "NO_TRADE") if is_valid else "REJECTED",
        "executed": is_valid and decision.get("action") != "NO_TRADE",
        "paper_mode": PAPER_TRADING,
        "binance_order_id": binance_order_id,
        "decision": decision, "validation": validation_msg,
    }

@app.get("/trades")
async def get_trades():
    return {"total": len(trade_log), "trades": trade_log[-50:]}

@app.get("/positions")
async def get_positions():
    return {"count": len(open_positions), "positions": open_positions}

@app.post("/close-trade")
async def close_trade(request: Request):
    global daily_pnl, weekly_pnl, consecutive_losses
    body = await request.json()
    tid = body.get("trade_id")
    cp = float(body.get("close_price", 0))
    motivo = body.get("motivo", "manual")

    pos = next((p for p in open_positions if p["trade_id"] == tid), None)
    if not pos:
        return {"error": f"Position {tid} not found"}

    entry = float(pos.get("entry", 0))
    sl = float(pos.get("sl", 0))
    if entry <= 0:
        return {"error": "Invalid entry price"}

    pnl_pct = ((cp - entry) / entry) if pos["direction"] == "LONG" else ((entry - cp) / entry)
    risk = abs(entry - sl) / entry if sl > 0 else 0
    pnl_r = pnl_pct / risk if risk > 0 else 0
    resultado = "WIN" if pnl_pct > 0 else "LOSS" if pnl_pct < 0 else "BREAKEVEN"

    weighted_pnl = pnl_pct * pos.get("risk_pct", 0)
    daily_pnl += weighted_pnl
    weekly_pnl += weighted_pnl

    if resultado == "LOSS":
        consecutive_losses += 1
    elif resultado == "WIN":
        consecutive_losses = 0

    open_positions.remove(pos)
    for t in trade_log:
        if t["trade_id"] == tid:
            t.update({"resultado": resultado, "pnl_R": f"{pnl_r:+.2f}R", "precio_cierre": cp, "motivo_cierre": motivo})

    duration_hours = ""
    try:
        opened = datetime.fromisoformat(pos["opened_at"].replace('Z', '+00:00'))
        duration_hours = f"{(datetime.now(timezone.utc) - opened).total_seconds() / 3600:.1f}"
    except Exception:
        pass

    await log_to_sheet("close_trade", {
        "trade_id": tid, "close_price": cp, "resultado": resultado,
        "pnl_R": f"{pnl_r:+.2f}R", "motivo_cierre": motivo,
        "pnl_usdt": round(pnl_pct * cp * pos.get("risk_pct", 0) * 100, 2),
        "duration_hours": duration_hours,
        "sl_too_short": "NO", "tp_too_high": "NO",
        "regime_changed": "NO", "strategy_correct": "",
        "post_trade_notes": f"Daily:{daily_pnl:.2%} Weekly:{weekly_pnl:.2%} Losses:{consecutive_losses}"
    })
    return {"trade_id": tid, "resultado": resultado, "pnl_r": round(pnl_r, 2)}

@app.get("/self-test")
async def self_test():
    results = {}
    results["rag"] = {"loaded": rag.loaded, "chunks": rag.chunk_count}
    if rag.loaded:
        results["rag"]["search_works"] = len(rag.search("pre-trade checklist", k=1)) > 0
    results["gemini"] = {"key_set": bool(GEMINI_API_KEY)}
    results["binance"] = {"key_set": bool(BINANCE_API_KEY), "connected": exchange is not None}
    if exchange:
        try:
            bal = exchange.fetch_balance()
            results["binance"]["usdt_free"] = float(bal.get('USDT', {}).get('free', 0))
            results["binance"]["ok"] = True
        except Exception as e:
            results["binance"]["ok"] = False
            results["binance"]["error"] = str(e)
    results["sheets"] = {"url_set": bool(SHEETS_WEBAPP_URL)}
    try:
        ctx = await get_market_context()
        results["market"] = {"btc": ctx.get("btc_price", 0), "fng": ctx.get("fear_greed", 0), "ok": ctx.get("btc_price", 0) > 0}
    except Exception as e:
        results["market"] = {"ok": False, "error": str(e)}

    results["config"] = {"paper": PAPER_TRADING, "release": RELEASE_ID, "secret_set": bool(WEBHOOK_SECRET)}
    results["overall"] = "READY" if all([
        results["rag"]["loaded"], results["gemini"]["key_set"],
        results.get("binance", {}).get("ok", True) or PAPER_TRADING,
        results["sheets"]["url_set"],
    ]) else "ISSUES"
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
