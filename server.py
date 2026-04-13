"""
CryptoAgent v5.0 — Production Server
TradingView → Render → RAG + Gemini + News + Range Detection → Binance → Google Sheets

v5.0 Changes:
  - FIX: Binance 451 — paper mode uses virtual balance, no Binance calls
  - FIX: All Binance calls wrapped with region-aware error handling
  - NEW: CryptoPanic news sentiment integration
  - NEW: Range/channel detection for sideways market trading
  - NEW: Compound reinvestment — profits auto-reinvest, never withdraw
  - NEW: Multi-asset diversification scoring
  - NEW: Configurable paper_balance via env var
  - NEW: News sentiment score feeds into Gemini decision
  - NEW: /pipeline endpoint shows full trading pipeline status
  - NEW: Price data from CoinGecko as additional fallback (no Binance API needed)
"""
import os, json, logging, pickle, hashlib, hmac, re, time, asyncio, math
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
RELEASE_ID = "v5.2-20260412"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
SHEETS_WEBAPP_URL = os.environ.get("SHEETS_WEBAPP_URL", "")
PAPER_TRADING = os.environ.get("PAPER_TRADING", "true").lower() == "true"
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET = os.environ.get("BINANCE_SECRET", "")
CRYPTOPANIC_API_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "")
PAPER_BALANCE = float(os.environ.get("PAPER_BALANCE", "400"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("CryptoAgent")

app = FastAPI(title="CryptoAgent", version=RELEASE_ID)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════
# BINANCE — only init if NOT paper trading
# ═══════════════════════════════════════════════════════════
exchange = None
binance_available = False
try:
    import ccxt
    if BINANCE_API_KEY and BINANCE_SECRET and not PAPER_TRADING:
        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        try:
            exchange.load_markets()
            binance_available = True
            log.info(f"Binance live — {len(exchange.markets)} markets")
        except Exception as e:
            log.warning(f"Binance init error (region block?): {e}")
            exchange = None
    elif PAPER_TRADING:
        log.info(f"Paper trading mode — virtual balance: ${PAPER_BALANCE}")
    else:
        log.info("Binance keys not set")
except ImportError:
    log.warning("ccxt not installed")

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
paper_balance_usdt = PAPER_BALANCE  # Track virtual balance in paper mode
paper_coins = {}  # Track virtual coin holdings

class TTLCache:
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
        for k in [k for k, t in self.cache.items() if now - t > self.ttl]:
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
    "compound_reinvest": True,  # Always reinvest profits
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
# MARKET CONTEXT — No Binance API needed for prices
# ═══════════════════════════════════════════════════════════
SUPPORTED_PAIRS = {
    "BTCUSDT": {"paprika": "btc-bitcoin", "gecko": "bitcoin", "key": "btc_price", "ccxt": "BTC/USDT"},
    "ETHUSDT": {"paprika": "eth-ethereum", "gecko": "ethereum", "key": "eth_price", "ccxt": "ETH/USDT"},
    "SOLUSDT": {"paprika": "sol-solana", "gecko": "solana", "key": "sol_price", "ccxt": "SOL/USDT"},
}

async def get_market_context():
    ctx = {
        "fear_greed": 50, "fear_greed_label": "Neutral",
        "btc_price": 0, "btc_24h_change": 0, "eth_price": 0, "sol_price": 0,
        "btc_funding": 0, "timestamp": datetime.now(timezone.utc).isoformat(),
        "news_sentiment": "neutral", "news_score": 0, "news_headlines": [],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        # Fear & Greed
        try:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            d = r.json()
            ctx["fear_greed"] = int(d["data"][0]["value"])
            ctx["fear_greed_label"] = d["data"][0]["value_classification"]
        except Exception as e:
            log.warning(f"Fear&Greed failed: {e}")

        # Prices: CoinPaprika → CoinGecko fallback (NO Binance API needed)
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
                # CoinGecko fallback (free, no key needed, no region blocks)
                try:
                    r = await client.get(
                        f"https://api.coingecko.com/api/v3/simple/price?ids={info['gecko']}&vs_currencies=usd&include_24hr_change=true"
                    )
                    if r.status_code == 200:
                        d = r.json().get(info['gecko'], {})
                        ctx[key] = float(d.get("usd", 0))
                        if key == "btc_price":
                            ctx["btc_24h_change"] = float(d.get("usd_24h_change", 0))
                except Exception:
                    log.warning(f"All price sources failed for {key}")

        # CryptoPanic News Sentiment
        news = await get_crypto_news(client)
        if news:
            ctx["news_sentiment"] = news["sentiment"]
            ctx["news_score"] = news["score"]
            ctx["news_headlines"] = news["headlines"][:5]

    return ctx


async def get_crypto_news(client: httpx.AsyncClient) -> dict:
    """Fetch news from CryptoPanic and compute sentiment score."""
    if not CRYPTOPANIC_API_KEY:
        return None
    try:
        r = await client.get(
            f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_API_KEY}"
            f"&currencies=BTC,ETH,SOL&filter=important&public=true"
        )
        if r.status_code != 200:
            log.warning(f"CryptoPanic HTTP {r.status_code}")
            return None
        data = r.json()
        results = data.get("results", [])
        if not results:
            return {"sentiment": "neutral", "score": 0, "headlines": []}

        # Compute sentiment from votes
        bullish = 0
        bearish = 0
        headlines = []
        for post in results[:20]:
            votes = post.get("votes", {})
            bullish += int(votes.get("positive", 0))
            bearish += int(votes.get("negative", 0))
            title = post.get("title", "")
            if title:
                headlines.append(title)

        total_votes = bullish + bearish
        if total_votes > 0:
            score = ((bullish - bearish) / total_votes) * 100  # -100 to +100
        else:
            score = 0

        if score > 30:
            sentiment = "strongly_bullish"
        elif score > 10:
            sentiment = "bullish"
        elif score < -30:
            sentiment = "strongly_bearish"
        elif score < -10:
            sentiment = "bearish"
        else:
            sentiment = "neutral"

        return {"sentiment": sentiment, "score": round(score, 1), "headlines": headlines}
    except Exception as e:
        log.warning(f"CryptoPanic error: {e}")
        return None


def get_current_price(pair: str, market_ctx: dict) -> float:
    info = SUPPORTED_PAIRS.get(pair.upper())
    return float(market_ctx.get(info["key"], 0)) if info else 0.0


async def get_balance() -> dict:
    """Get balance with mark-to-market valuation."""
    global paper_balance_usdt
    if PAPER_TRADING:
        coin_holdings = dict(paper_coins)
        # Mark-to-market: estimate coin values using last known prices
        mtm_value = 0.0
        price_map = {"BTC": 0, "ETH": 0, "SOL": 0}
        # Try to get prices from open positions or use a quick fetch
        for pos in open_positions:
            bc = pos.base_coin
            if bc in price_map and pos.entry > 0:
                price_map[bc] = pos.highest_price  # Use latest tracked price
        for coin, amount in coin_holdings.items():
            if amount > 0 and coin in price_map and price_map[coin] > 0:
                mtm_value += amount * price_map[coin]
        total_equity = paper_balance_usdt + mtm_value
        return {
            "usdt_free": round(paper_balance_usdt, 2),
            "usdt_total": round(total_equity, 2),
            "coins": coin_holdings,
            "mtm_value": round(mtm_value, 2),
            "equity": round(total_equity, 2),
            "mode": "paper",
        }

    if not exchange:
        return {"usdt_free": 0, "usdt_total": 0, "coins": {}, "mode": "no_exchange"}

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
            "coins": coins,
            "mode": "live",
        }
    except Exception as e:
        log.error(f"Balance error: {e}")
        return {"usdt_free": 0, "usdt_total": 0, "coins": {}, "error": str(e), "mode": "error"}


# ═══════════════════════════════════════════════════════════
# RANGE/CHANNEL DETECTION
# ═══════════════════════════════════════════════════════════
class RangeDetector:
    """Detect when price is in a sideways channel for mean-reversion trading."""
    def __init__(self):
        self.price_history = {}  # pair -> list of prices

    def add_price(self, pair: str, price: float):
        if pair not in self.price_history:
            self.price_history[pair] = []
        self.price_history[pair].append({"price": price, "ts": time.time()})
        # Keep last 200 data points
        self.price_history[pair] = self.price_history[pair][-200:]

    def detect_range(self, pair: str, lookback: int = 50) -> dict:
        """Detect if price is ranging and identify channel bounds."""
        history = self.price_history.get(pair, [])
        if len(history) < lookback:
            return {"is_ranging": False, "reason": "insufficient_data", "data_points": len(history)}

        prices = [h["price"] for h in history[-lookback:]]
        high = max(prices)
        low = min(prices)
        current = prices[-1]
        channel_width_pct = ((high - low) / low) * 100

        # Range criteria: channel < 15% width, price touched both bounds
        near_high_count = sum(1 for p in prices if p > high * 0.97)
        near_low_count = sum(1 for p in prices if p < low * 1.03)
        is_ranging = (channel_width_pct < 15 and near_high_count >= 3 and near_low_count >= 3)

        # Position within range (0 = bottom, 100 = top)
        range_position = ((current - low) / (high - low) * 100) if high != low else 50

        # Determine signal
        signal = "none"
        if is_ranging:
            if range_position < 20:
                signal = "BUY_RANGE_BOTTOM"
            elif range_position > 80:
                signal = "SELL_RANGE_TOP"

        return {
            "is_ranging": is_ranging,
            "channel_high": round(high, 2),
            "channel_low": round(low, 2),
            "channel_width_pct": round(channel_width_pct, 2),
            "range_position": round(range_position, 1),
            "signal": signal,
            "near_high_touches": near_high_count,
            "near_low_touches": near_low_count,
            "data_points": len(prices),
        }

range_detector = RangeDetector()

# ═══════════════════════════════════════════════════════════
# POSITION MODEL (inspired by banbot Order/ExitTrigger)
# ═══════════════════════════════════════════════════════════
class Position:
    """Formal position with lifecycle, exit plan, and per-trade tracking."""
    def __init__(self, trade_id, pair, direction, entry, sl, tp1, tp2,
                 qty, cost_usdt, position_size_pct, bucket, template, opened_at, order_id):
        self.trade_id = trade_id
        self.pair = pair
        self.base_coin = pair.upper().replace("USDT", "").replace("BUSD", "")
        self.direction = direction  # LONG only for spot
        self.bucket = bucket
        self.template = template
        self.entry = float(entry)
        self.qty = float(qty)           # Exact coins bought
        self.cost_usdt = float(cost_usdt)  # Exact USDT spent
        self.position_size_pct = float(position_size_pct)
        # Exit plan
        self.sl = float(sl)
        self.tp1 = float(tp1)
        self.tp2 = float(tp2)
        self.trailing_active = False
        self.trailing_sl = 0.0
        self.tp1_hit = False
        self.qty_remaining = float(qty)  # Decreases on partial TP
        # Metadata
        self.opened_at = opened_at
        self.order_id = order_id
        self.status = "OPEN"  # OPEN, PARTIALLY_CLOSED, CLOSED
        self.highest_price = float(entry)
        self.lowest_price = float(entry)

    def update_price(self, price: float):
        """Track price extremes for trailing stop and SL/TP analysis."""
        self.highest_price = max(self.highest_price, price)
        self.lowest_price = min(self.lowest_price, price)
        # Trailing stop: after TP1 hit, trail at entry (breakeven) or higher
        if self.trailing_active and self.direction == "LONG":
            # Trail at max(entry, highest - (entry - original_sl))
            original_risk = abs(self.entry - self.sl) if self.sl > 0 else self.entry * 0.02
            self.trailing_sl = max(self.entry, self.highest_price - original_risk)

    def check_exit(self, price: float) -> str:
        """Check if price triggers any exit condition. Returns reason or empty string."""
        if self.status == "CLOSED":
            return ""
        self.update_price(price)
        if self.direction == "LONG":
            # Stop loss
            if self.sl > 0 and price <= self.sl:
                return "stop_loss_hit"
            # Trailing stop (after TP1)
            if self.trailing_active and self.trailing_sl > 0 and price <= self.trailing_sl:
                return "trailing_stop_hit"
            # Take profit 2
            if self.tp2 > 0 and price >= self.tp2:
                return "take_profit_2_hit"
            # Take profit 1 (partial)
            if not self.tp1_hit and self.tp1 > 0 and price >= self.tp1:
                return "take_profit_1_hit"
        # Time stop: position open > 24h with < 0.5% favorable move (aligned with prompt)
        try:
            opened = datetime.fromisoformat(self.opened_at.replace('Z', '+00:00'))
            hours_open = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
            if hours_open > 24:
                pnl_pct = (price - self.entry) / self.entry if self.direction == "LONG" else (self.entry - price) / self.entry
                if pnl_pct < 0.005:
                    return "time_stop_24h"
        except Exception:
            pass
        return ""

    def to_dict(self):
        return {
            "trade_id": self.trade_id, "pair": self.pair, "base_coin": self.base_coin,
            "direction": self.direction, "bucket": self.bucket, "entry": self.entry,
            "sl": self.sl, "tp1": self.tp1, "tp2": self.tp2,
            "qty": self.qty, "qty_remaining": self.qty_remaining,
            "cost_usdt": round(self.cost_usdt, 2),
            "trailing_active": self.trailing_active, "trailing_sl": round(self.trailing_sl, 2),
            "tp1_hit": self.tp1_hit, "status": self.status,
            "highest_price": round(self.highest_price, 2),
            "opened_at": self.opened_at, "order_id": self.order_id,
            "position_size_pct": self.position_size_pct,
            "risk_pct": self.position_size_pct / 100,
        }


def compute_position_qty(equity: float, entry: float, sl: float, max_risk_pct: float) -> float:
    """Proper risk-based position sizing (banbot pattern).
    risk_amount = equity * max_risk_pct
    qty = risk_amount / abs(entry - sl)
    """
    if entry <= 0 or sl <= 0 or abs(entry - sl) < 0.0001:
        # Fallback: simple % of equity
        return equity * max_risk_pct / entry if entry > 0 else 0
    risk_amount = equity * max_risk_pct
    distance = abs(entry - sl)
    qty = risk_amount / distance
    return qty


async def check_positions_for_exits(current_prices: dict) -> list:
    """Position monitor (polymarket-bot pattern): scan all open positions for exit triggers."""
    exits = []
    for pos in list(open_positions):
        price = current_prices.get(pos.pair.upper(), 0)
        if price <= 0:
            continue
        reason = pos.check_exit(price)
        if reason:
            exits.append({"trade_id": pos.trade_id, "pair": pos.pair, "reason": reason, "price": price})
    return exits

# ═══════════════════════════════════════════════════════════
# GEMINI LLM
# ═══════════════════════════════════════════════════════════
SYSTEM_PROMPT_TEMPLATE = """You are an institutional-grade crypto trading agent.
Personality: O:75 C:95 E:15 A:10 N:5 (Homo Economicus, zero biases).

CRITICAL: Respond ONLY in English. All JSON keys/values in English.
Values: action: "BUY"/"SELL"/"NO_TRADE", direction: "LONG"/"SHORT", bucket: "CORE"/"SATELLITE", regime_btc: "GREEN"/"YELLOW"/"RED", confidence: 0-100.

IMMUTABLE RULES:
1. CAPITAL PRESERVATION is primary.
2. Min R:R 1:2 standard, 1:3 aggressive.
3. MUST identify specific EDGE.
4. REGIME determines method: uptrend=trend-following, RANGE=mean-reversion, downtrend=preservation.
5. Max 0.5% risk/trade, max 5% total exposure.
6. NEVER trade BNB.
7. Pre-trade checklist: ALL 12 items pass.
8. Stale entry (>0.5% drift) = NO_TRADE.
9. 5+ consecutive losses = bias NO_TRADE.

FEAR & GREED INDEX DECISION MATRIX (apply BEFORE final confidence):
- FNG 0-10 (Extreme Fear): Strong BUY bias. Historically best entries. Add +15 confidence to BUY signals.
- FNG 11-25 (Fear): Moderate BUY bias. Add +10 confidence to BUY signals.
- FNG 26-45 (Low Neutral): Slight BUY bias. Add +5 confidence to BUY signals.
- FNG 46-55 (Neutral): No adjustment. Trade purely on technicals.
- FNG 56-75 (Greed): Caution. Subtract -5 confidence from BUY signals. Tighten SL.
- FNG 76-90 (High Greed): High caution. Subtract -10 from BUY. Consider SELL signals more favorably.
- FNG 91-100 (Extreme Greed): Defensive mode. Subtract -20 from BUY. Strong SELL bias. Reduce position sizes by 50%.
IMPORTANT: FNG adjusts confidence but NEVER overrides technical invalidity. A bad setup at FNG=5 is still NO_TRADE.

NEWS SENTIMENT SCORING (apply AFTER FNG adjustment):
- strongly_bullish (score > +30): If signal is BUY/LONG, add +10 confidence. If SELL/SHORT, subtract -15 (conflict).
- bullish (score +10 to +30): If BUY, add +5. If SELL, subtract -10.
- neutral (score -10 to +10): No adjustment. Trade on technicals only.
- bearish (score -10 to -30): If SELL/SHORT, add +5. If BUY/LONG, subtract -10.
- strongly_bearish (score < -30): If SELL/SHORT, add +10. If BUY/LONG, subtract -15 (conflict).
IMPORTANT: News-technical CONFLICT (news bearish + signal bullish or vice versa) is a WARNING. If final confidence drops below 50 after adjustments, force NO_TRADE.

RANGE TRADING STRATEGY (when range_detected = true):
- When range_position < 20%: BUY at channel bottom, SL 1% below channel_low, TP at channel_high.
- When range_position > 80%: SELL at channel top, SL 1% above channel_high, TP at channel_low.
- Channel width must be > 3% for profitability after fees.
- Use tighter position sizes (0.3%) for range plays.
- If channel breaks (price outside 105% of bounds), EXIT immediately via close-trade.

STOP LOSS AND TAKE PROFIT STRATEGY:
- SL: Always ATR * 2.0 minimum. Never tighter than 0.5% from entry.
- TP1: R:R of 2.0 minimum (take 50% of position).
- TP2: R:R of 3.0 (let remaining 50% ride with trailing stop).
- Trailing stop: After TP1 hit, move SL to breakeven (entry price).
- Time stop: If position hasn't moved 0.5% in 24h in the expected direction, consider closing.

COMPOUND REINVESTMENT:
- All profits stay and are reinvested automatically.
- Position sizes are % of TOTAL current balance (grows with wins).
- As balance grows, absolute position sizes grow proportionally.

DIVERSIFICATION:
- Never >40% of capital in one asset.
- Spread across BTC, ETH, SOL when possible.

AVAILABLE BALANCE: {available_balance}

Respond with ONLY valid JSON."""

TRADE_PROMPT = """MARKET CONTEXT:
{market_context}

FEAR & GREED INDEX: {fng_value} ({fng_label})
Apply the FNG Decision Matrix from your rules to adjust confidence.

NEWS SENTIMENT: {news_context}
Apply News Sentiment Scoring rules. Flag any news-technical conflicts.

RANGE DETECTION:
{range_context}

KNOWLEDGE BASE:
{rag_context}

SIGNAL: {signal}

CURRENT MARKET PRICE: {current_price}

PORTFOLIO: positions={positions}, daily_pnl={daily_pnl}, weekly_pnl={weekly_pnl}, satellite={satellite_pct}%, consecutive_losses={consecutive_losses}, available_usdt={available_usdt}

ASSET DIVERSIFICATION: {diversification}

SELF-LEARNING FEEDBACK:
{feedback}

DECISION PROCESS (follow in order):
1. Evaluate technical signal quality (confluence, template, regime).
2. Apply Fear & Greed adjustment to confidence.
3. Apply News Sentiment adjustment to confidence.
4. Check for news-technical conflict. If conflict AND confidence < 50 after adjustments, force NO_TRADE.
5. If range_detected=true, apply Range Trading Strategy for SL/TP.
6. Set position_size_pct based on current total balance (compound reinvestment).
7. Verify all 12 checklist items pass.

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
    for nf in ["entry_price", "stop_loss", "take_profit_1", "take_profit_2",
               "position_size_pct", "confidence", "confluence_score"]:
        val = result.get(nf, 0)
        if isinstance(val, str):
            val = val.replace("%", "").replace(",", "").strip()
        try:
            result[nf] = float(val)
        except (ValueError, TypeError):
            result[nf] = 0.0
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
                    await asyncio.sleep(min(30, 5 * (attempt + 1)))
                    continue
                if r.status_code != 200:
                    log.error(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
                    if attempt < retries:
                        await asyncio.sleep(3)
                        continue
                    return {"action": "NO_TRADE", "reasoning": f"Gemini HTTP {r.status_code}"}
                data = r.json()
                raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return normalize_gemini(json.loads(raw))
        except json.JSONDecodeError:
            log.error(f"Gemini bad JSON: {raw[:200]}")
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
    return {"action": "NO_TRADE", "reasoning": "Gemini failed"}

# ═══════════════════════════════════════════════════════════
# BINANCE EXECUTION (with paper mode tracking)
# ═══════════════════════════════════════════════════════════
def format_ccxt_pair(pair: str) -> str:
    pair = pair.upper().strip()
    if '/' in pair:
        return pair
    for quote in ['USDT', 'BUSD', 'USDC']:
        if pair.endswith(quote):
            return f"{pair[:-len(quote)]}/{quote}"
    return pair

def execute_trade(pair: str, action: str, position_size_pct: float, current_price: float,
                  entry_price: float = 0, stop_loss: float = 0) -> tuple:
    """Execute trade with proper risk-based sizing.
    Returns (success, order_id_or_error, qty_filled, cost_usdt)."""
    global paper_balance_usdt, paper_coins

    entry = entry_price if entry_price > 0 else current_price
    equity = paper_balance_usdt if PAPER_TRADING else 0

    # Compute qty using risk-based sizing if SL is available
    if stop_loss > 0 and entry > 0 and abs(entry - stop_loss) > 0.0001:
        qty = compute_position_qty(equity if PAPER_TRADING else current_price * 100,
                                   entry, stop_loss, RISK_PARAMS["max_risk_per_trade"])
        invest = qty * entry
    else:
        # Fallback: use position_size_pct of cash
        invest = equity * (position_size_pct / 100) if PAPER_TRADING else 0
        qty = invest / current_price if current_price > 0 else 0

    if PAPER_TRADING:
        if action == 'BUY':
            # Cap at available cash
            invest = min(invest, paper_balance_usdt * 0.95)  # Keep 5% buffer
            if invest < RISK_PARAMS["min_order_usdt"]:
                return False, f"Paper order {invest:.2f} < min {RISK_PARAMS['min_order_usdt']}", 0, 0
            base = pair.replace("USDT", "").replace("BUSD", "")
            amount = invest / current_price
            paper_balance_usdt -= invest
            paper_coins[base] = paper_coins.get(base, 0) + amount
            log.info(f"PAPER BUY: {pair} ${invest:.2f} = {amount:.8f} {base} (risk-sized). Bal: ${paper_balance_usdt:.2f}")
            order_id = f"PAPER-{datetime.now(timezone.utc).strftime('%H%M%S%f')[:10]}"
            return True, order_id, amount, invest

        elif action == 'SELL':
            base = pair.replace("USDT", "").replace("BUSD", "")
            if base == 'BNB':
                return False, "BNB protected", 0, 0
            held = paper_coins.get(base, 0)
            if held <= 0:
                return False, f"No {base} to sell", 0, 0
            sell_amount = min(held, qty) if qty > 0 else held
            proceeds = sell_amount * current_price
            if proceeds < RISK_PARAMS["min_order_usdt"]:
                sell_amount = held
                proceeds = sell_amount * current_price
            paper_coins[base] = held - sell_amount
            if paper_coins.get(base, 0) < 0.0000001:
                paper_coins.pop(base, None)
            paper_balance_usdt += proceeds
            log.info(f"PAPER SELL: {pair} {sell_amount:.8f} = ${proceeds:.2f}. Bal: ${paper_balance_usdt:.2f}")
            order_id = f"PAPER-{datetime.now(timezone.utc).strftime('%H%M%S%f')[:10]}"
            return True, order_id, sell_amount, proceeds

        return False, f"Unknown action: {action}", 0, 0

    # Live trading
    if not exchange:
        return False, "Binance not available", 0, 0
    try:
        if not exchange.markets:
            exchange.load_markets()
        ccxt_pair = format_ccxt_pair(pair)
        balance = exchange.fetch_balance()

        if action == 'BUY':
            usdt_free = float(balance.get('USDT', {}).get('free', 0))
            live_invest = min(invest, usdt_free * 0.95) if invest > 0 else usdt_free * (position_size_pct / 100)
            if live_invest < RISK_PARAMS["min_order_usdt"]:
                return False, f"Order {live_invest:.2f} < min. Free: {usdt_free:.2f}", 0, 0
            if current_price <= 0:
                return False, "Price is 0", 0, 0
            amount = live_invest / current_price
            if ccxt_pair in exchange.markets:
                amount = float(exchange.amount_to_precision(ccxt_pair, amount))
            order = exchange.create_order(symbol=ccxt_pair, type='market', side='buy', amount=amount)
            log.info(f"LIVE BUY: {ccxt_pair} amt={amount} cost={live_invest:.2f} id={order['id']}")
            return True, str(order['id']), amount, live_invest

        elif action == 'SELL':
            base_coin = ccxt_pair.split('/')[0]
            if base_coin == 'BNB':
                return False, "BNB protected", 0, 0
            coin_free = float(balance.get(base_coin, {}).get('free', 0))
            if coin_free <= 0:
                return False, f"No {base_coin}", 0, 0
            sell_amount = min(coin_free, qty) if qty > 0 else coin_free
            if ccxt_pair in exchange.markets:
                sell_amount = float(exchange.amount_to_precision(ccxt_pair, sell_amount))
            if sell_amount * current_price < RISK_PARAMS["min_order_usdt"]:
                sell_amount = coin_free
                if ccxt_pair in exchange.markets:
                    sell_amount = float(exchange.amount_to_precision(ccxt_pair, sell_amount))
            order = exchange.create_order(symbol=ccxt_pair, type='market', side='sell', amount=sell_amount)
            proceeds = sell_amount * current_price
            log.info(f"LIVE SELL: {ccxt_pair} amt={sell_amount} id={order['id']}")
            return True, str(order['id']), sell_amount, proceeds

        return False, f"Unknown: {action}", 0, 0
    except Exception as e:
        log.error(f"Binance error: {e}")
        return False, str(e), 0, 0

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
        return True, f"Circuit breaker: {consecutive_losses} losses"
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
    sig_price = float(signal.get("price", 0) or 0)
    threshold = (atr / sig_price) if (atr > 0 and sig_price > 0) else RISK_PARAMS["max_entry_drift_pct"]
    threshold = max(0.003, min(0.02, threshold))
    if drift > threshold:
        return True, f"Stale: {current:.2f} drifted {drift:.2%} from {entry:.2f}"
    return False, ""

def get_diversification() -> str:
    """Calculate current asset diversification for prompt."""
    if not open_positions:
        return "No open positions. Free to diversify across BTC, ETH, SOL."
    by_pair = {}
    for p in open_positions:
        pair = p.pair
        by_pair[pair] = by_pair.get(pair, 0) + 1
    parts = [f"{pair}: {count} position(s)" for pair, count in by_pair.items()]
    return "Current: " + ", ".join(parts)

def validate_trade(d: dict, signal: dict = None, market_ctx: dict = None):
    pair = d.get("pair", "").upper()
    action = str(d.get("action", "NO_TRADE")).upper()
    direction = str(d.get("direction", "")).upper()

    if any(p in pair for p in RISK_PARAMS["protected_assets"]):
        return False, f"BLOCKED: {pair} (BNB)"
    if action == "NO_TRADE":
        return False, d.get("reasoning", "NO_TRADE")

    # SPOT-ONLY: reject SHORT signals (banbot recommendation)
    if action == "SELL" and direction == "SHORT" and not any(
        p.pair.upper() == pair and p.direction == "LONG" for p in open_positions
    ):
        return False, "SHORT rejected: spot-only mode, no LONG position to close"

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
        return False, f"Confluence < {RISK_PARAMS['min_confluence']}"

    entry = float(d.get("entry_price", 0) or 0)
    sl = float(d.get("stop_loss", 0) or 0)
    tp1 = float(d.get("take_profit_1", 0) or 0)
    if entry and sl and abs(entry - sl) < 0.0001:
        return False, "SL = entry"
    if entry and sl and tp1:
        risk = abs(entry - sl)
        if risk > 0 and abs(tp1 - entry) / risk < RISK_PARAMS["min_rr"]:
            return False, f"R:R < {RISK_PARAMS['min_rr']}"

    # Real risk validation: risk_amount = position_value * (distance_to_sl / entry)
    if entry > 0 and sl > 0:
        risk_per_unit = abs(entry - sl) / entry
        pos_size_pct = d.get("position_size_pct", 0) / 100
        actual_risk = pos_size_pct * risk_per_unit
        if actual_risk > RISK_PARAMS["max_risk_per_trade"] * 2:
            return False, f"Real risk {actual_risk:.3%} > 2x max_risk_per_trade"

    # Exposure check
    cur_exp = sum(p.position_size_pct / 100 for p in open_positions)
    new_risk = d.get("position_size_pct", 0) / 100
    if cur_exp + new_risk > RISK_PARAMS["max_total_exposure"]:
        return False, f"Exposure {cur_exp + new_risk:.2%} > max"

    # Diversification: max 40% in one asset
    pair_exp = sum(p.position_size_pct / 100 for p in open_positions if p.pair.upper() == pair)
    if pair_exp + new_risk > 0.40:
        return False, f"{pair} would be {(pair_exp + new_risk):.0%} of portfolio (max 40%)"

    # Max positions per pair
    pair_pos = sum(1 for p in open_positions if p.pair.upper() == pair)
    if pair_pos >= RISK_PARAMS["max_positions_per_pair"]:
        return False, f"Max positions for {pair}"

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
            log.warning(f"Sheet feedback: {e}")
    if len(trade_log) < 3:
        return "Insufficient data"
    recent = ([t for t in trade_log[-20:] if t.get("pair", "").upper() == pair.upper()][-10:]
              if pair else trade_log[-10:])
    if not recent:
        return f"No trades for {pair}" if pair else "No trades"
    wins = sum(1 for t in recent if t.get("resultado") == "WIN")
    losses = sum(1 for t in recent if t.get("resultado") == "LOSS")
    total = wins + losses
    if total > 0:
        return f"{pair or 'ALL'} last {len(recent)}: {wins}W/{losses}L WR:{wins/total:.0%}"
    return "No closed trades"

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
                return r.json()
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
        "kill_switch": killed, "binance_connected": binance_available,
        "news_enabled": bool(CRYPTOPANIC_API_KEY),
    }

@app.get("/health")
async def health():
    return {"status": "ok", "release": RELEASE_ID}

@app.get("/ping")
async def ping():
    return {"pong": True, "release": RELEASE_ID}

@app.get("/balance")
async def balance_endpoint():
    return await get_balance()

@app.get("/status")
async def get_status():
    killed, reason = check_kill_switches()
    bal = await get_balance()
    return {
        "release": RELEASE_ID, "paper_trading": PAPER_TRADING,
        "rag": {"loaded": rag.loaded, "chunks": rag.chunk_count},
        "state": {"trades": len(trade_log), "open": len(open_positions),
                  "daily_pnl": daily_pnl, "weekly_pnl": weekly_pnl,
                  "consecutive_losses": consecutive_losses},
        "kill_switch": {"active": killed, "reason": reason},
        "balance": bal,
        "news_enabled": bool(CRYPTOPANIC_API_KEY),
        "feedback": await get_feedback()
    }

@app.get("/pipeline")
async def pipeline_status():
    """Full trading pipeline health check."""
    p = {}
    p["1_tradingview"] = {"status": "Configure alerts in TradingView pointing to /webhook"}
    p["2_webhook"] = {"status": "READY", "secret_set": bool(WEBHOOK_SECRET)}
    p["3_rag"] = {"status": "OK" if rag.loaded else "MISSING", "chunks": rag.chunk_count}
    p["4_market_data"] = {}
    try:
        ctx = await get_market_context()
        p["4_market_data"] = {"btc": ctx["btc_price"], "fng": ctx["fear_greed"], "news": ctx["news_sentiment"], "ok": ctx["btc_price"] > 0}
    except Exception as e:
        p["4_market_data"] = {"ok": False, "error": str(e)}
    p["5_gemini"] = {"key_set": bool(GEMINI_API_KEY)}
    p["6_validation"] = {"risk_params": RISK_PARAMS}
    p["7_execution"] = {"mode": "PAPER" if PAPER_TRADING else "LIVE", "binance_ok": binance_available or PAPER_TRADING}
    bal = await get_balance()
    p["7_execution"]["balance"] = bal
    p["8_sheets"] = {"url_set": bool(SHEETS_WEBAPP_URL)}
    if SHEETS_WEBAPP_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(SHEETS_WEBAPP_URL + "?action=status", follow_redirects=True)
                p["8_sheets"]["ok"] = r.status_code == 200
        except Exception:
            p["8_sheets"]["ok"] = False
    p["9_feedback_loop"] = {"status": "Sheets → feedback → Gemini prompt → refined decisions"}
    p["10_compound"] = {"enabled": True, "current_balance": bal.get("usdt_free", 0), "initial": PAPER_BALANCE}
    all_ok = all([rag.loaded, bool(GEMINI_API_KEY), bool(WEBHOOK_SECRET), bool(SHEETS_WEBAPP_URL), (binance_available or PAPER_TRADING)])
    p["overall"] = "READY" if all_ok else "ISSUES_FOUND"
    return p

@app.post("/webhook")
async def webhook(request: Request):
    global trade_counter, consecutive_losses
    body = await request.json()

    if not hmac.compare_digest(str(body.get("secret", "")), WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid secret")

    pair = body.get("pair", "UNKNOWN").upper()
    signal_type = body.get("signal_type", "N/A")
    log.info(f"Signal: {pair} | {signal_type}")

    if signal_type == "KILL_SWITCH":
        return {"action": "KILL_SWITCH", "reason": body.get("reason")}
    if signal_type == "REGIME_CHANGE":
        return {"action": "INFO", "regime_change": body.get("new_regime")}

    sig_hash = hashlib.md5(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    if sig_hash in seen_signals:
        return {"action": "DUPLICATE"}
    seen_signals.add(sig_hash)

    if any(p in pair for p in RISK_PARAMS["protected_assets"]):
        return {"action": "BLOCKED", "reason": "BNB protected"}

    killed, kill_reason = check_kill_switches()
    if killed:
        return {"action": "BLOCKED", "reason": kill_reason}

    # Gather all context
    market_ctx = await get_market_context()
    current_price = get_current_price(pair, market_ctx)

    # Track price for range detection
    range_detector.add_price(pair, current_price)
    range_data = range_detector.detect_range(pair)

    bal = await get_balance()
    rag_context = rag.build_context(
        f"{signal_type} {pair} {body.get('regime','')} {body.get('template','')} risk management range",
        k=5, max_words=1500
    )
    feedback = await get_feedback(pair=pair)
    diversification = get_diversification()

    # Build prompts
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(available_balance=json.dumps(bal))
    news_ctx = f"Sentiment: {market_ctx.get('news_sentiment', 'neutral')}, Score: {market_ctx.get('news_score', 0)}/100"
    if market_ctx.get("news_headlines"):
        news_ctx += "\nTop headlines: " + " | ".join(market_ctx["news_headlines"][:3])

    prompt = TRADE_PROMPT.format(
        market_context=json.dumps({k: v for k, v in market_ctx.items() if k != "news_headlines"}),
        fng_value=market_ctx.get("fear_greed", 50),
        fng_label=market_ctx.get("fear_greed_label", "Neutral"),
        news_context=news_ctx,
        range_context=json.dumps(range_data),
        rag_context=rag_context or "No RAG context",
        signal=json.dumps(body),
        current_price=f"{current_price:.2f}",
        positions=len(open_positions),
        daily_pnl=f"{daily_pnl:.2%}",
        weekly_pnl=f"{weekly_pnl:.2%}",
        satellite_pct=satellite_pct,
        consecutive_losses=consecutive_losses,
        available_usdt=f"{bal.get('usdt_free', 0):.2f}",
        diversification=diversification,
        feedback=feedback
    )

    decision = await call_gemini(prompt, system_prompt)
    is_valid, validation_msg = validate_trade(decision, signal=body, market_ctx=market_ctx)

    trade_counter += 1
    trade_id = f"T-{trade_counter:04d}"

    binance_order_id = "N/A"
    qty_filled = 0.0
    cost_usdt = 0.0
    if is_valid and decision.get("action") in ("BUY", "SELL"):
        success, exec_msg, qty_filled, cost_usdt = execute_trade(
            pair=decision.get("pair", pair),
            action=decision.get("action"),
            position_size_pct=decision.get("position_size_pct", 0),
            current_price=current_price,
            entry_price=decision.get("entry_price", 0),
            stop_loss=decision.get("stop_loss", 0),
        )
        if not success:
            is_valid = False
            validation_msg = f"Execution: {exec_msg}"
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
        "news_sentiment": market_ctx.get("news_sentiment", ""),
        "news_score": market_ctx.get("news_score", 0),
        "range_detected": range_data.get("is_ranging", False),
        "range_position": range_data.get("range_position", 0),
    }
    trade_log.append(record)
    await log_to_sheet("log_trade", record)

    if is_valid and decision.get("action") != "NO_TRADE":
        pos_pair = decision.get("pair", pair)
        pos_size_pct = decision.get("position_size_pct", 0)

        pos_obj = Position(
            trade_id=trade_id, pair=pos_pair,
            direction=decision.get("direction", "LONG"),
            entry=decision.get("entry_price", current_price),
            sl=decision.get("stop_loss", 0),
            tp1=decision.get("take_profit_1", 0),
            tp2=decision.get("take_profit_2", 0),
            qty=qty_filled,            # Exact fill from execute_trade
            cost_usdt=cost_usdt,       # Exact cost from execute_trade
            position_size_pct=pos_size_pct,
            bucket=decision.get("bucket", "CORE"),
            template=decision.get("template", ""),
            opened_at=datetime.now(timezone.utc).isoformat(),
            order_id=binance_order_id,
        )
        open_positions.append(pos_obj)

    return {
        "trade_id": trade_id,
        "action": decision.get("action", "NO_TRADE") if is_valid else "REJECTED",
        "executed": is_valid and decision.get("action") != "NO_TRADE",
        "paper_mode": PAPER_TRADING,
        "binance_order_id": binance_order_id,
        "decision": decision, "validation": validation_msg,
        "balance": bal, "range": range_data,
    }

@app.get("/trades")
async def get_trades():
    return {"total": len(trade_log), "trades": trade_log[-50:]}

@app.get("/positions")
async def get_positions():
    return {"count": len(open_positions), "positions": [p.to_dict() for p in open_positions]}

@app.get("/range/{pair}")
async def get_range(pair: str):
    """Get range detection data for a pair."""
    return range_detector.detect_range(pair.upper())

@app.get("/check-positions")
async def check_positions_endpoint():
    """Position monitor: scan all positions, auto-execute exits on SL/TP/trailing/time triggers."""
    market_ctx = await get_market_context()
    current_prices = {
        "BTCUSDT": market_ctx.get("btc_price", 0),
        "ETHUSDT": market_ctx.get("eth_price", 0),
        "SOLUSDT": market_ctx.get("sol_price", 0),
    }
    for pos in list(open_positions):
        price = current_prices.get(pos.pair.upper(), 0)
        if price > 0:
            pos.update_price(price)

    exits = await check_positions_for_exits(current_prices)
    executed = []
    for ex in exits:
        result = await _execute_close(ex["trade_id"], ex["price"], ex["reason"])
        executed.append(result)

    return {
        "checked": len(open_positions) + len(executed),
        "exits_executed": executed,
        "positions_remaining": [p.to_dict() for p in open_positions],
    }


async def _execute_close(tid: str, cp: float, motivo: str, body_extra: dict = None) -> dict:
    """Shared close logic for /close-trade and /check-positions auto-closer."""
    global daily_pnl, weekly_pnl, consecutive_losses, paper_balance_usdt, paper_coins

    pos = next((p for p in open_positions if p.trade_id == tid), None)
    if not pos:
        return {"trade_id": tid, "error": "not found"}

    entry = pos.entry
    sl = pos.sl
    tp1 = pos.tp1
    tp2 = pos.tp2
    pair = pos.pair.upper()
    base_coin = pos.base_coin
    direction = pos.direction

    if entry <= 0:
        return {"trade_id": tid, "error": "invalid entry"}

    # Auto-detect reason
    if motivo == "auto":
        detected = pos.check_exit(cp)
        if detected:
            motivo = detected

    # PnL
    pnl_pct = (cp - entry) / entry if direction == "LONG" else (entry - cp) / entry
    risk = abs(entry - sl) / entry if sl > 0 else 0
    pnl_r = pnl_pct / risk if risk > 0 else 0
    resultado = "WIN" if pnl_pct > 0 else "LOSS" if pnl_pct < 0 else "BREAKEVEN"

    # SL/TP quality analysis for self-learning
    sl_too_short = "NO"
    tp_too_high = "NO"
    if resultado == "LOSS" and sl > 0 and direction == "LONG":
        if abs(entry - sl) / entry < 0.005:
            sl_too_short = "YES"
    if resultado == "LOSS" and tp1 > 0 and direction == "LONG":
        if pos.highest_price > entry and pos.highest_price < tp1:
            tp_too_high = "YES"

    # Determine sell qty — TP1 partial vs full
    is_partial = False
    sell_qty = pos.qty_remaining

    if motivo == "take_profit_1_hit" and not pos.tp1_hit and pos.qty_remaining > 0:
        sell_qty = pos.qty_remaining * 0.5
        is_partial = True
        pos.tp1_hit = True
        pos.trailing_active = True
        pos.qty_remaining -= sell_qty
        pos.trailing_sl = pos.entry  # Breakeven
        pos.status = "PARTIALLY_CLOSED"
        log.info(f"TP1 PARTIAL {tid}: sold 50% ({sell_qty:.8f}), trailing ON, SL→{pos.entry:.2f}")
    else:
        sell_qty = pos.qty_remaining
        pos.qty_remaining = 0
        pos.status = "CLOSED"

    # Execute liquidation
    pnl_usdt = 0.0
    if PAPER_TRADING:
        if direction == "LONG" and sell_qty > 0:
            proceeds = sell_qty * cp
            pnl_usdt = proceeds - (sell_qty * entry)
            held = paper_coins.get(base_coin, 0)
            paper_coins[base_coin] = max(0, held - sell_qty)
            if paper_coins.get(base_coin, 0) < 0.0000001:
                paper_coins.pop(base_coin, None)
            paper_balance_usdt += proceeds
            log.info(f"PAPER CLOSE {'PARTIAL' if is_partial else 'FULL'} {tid}: "
                     f"{sell_qty:.8f} {base_coin} @ {cp:.2f} = ${proceeds:.2f} (P&L: ${pnl_usdt:+.2f})")
        elif direction == "SHORT":
            pv = pos.cost_usdt * (sell_qty / pos.qty if pos.qty > 0 else 1)
            pnl_usdt = pv * pnl_pct
            paper_balance_usdt += pnl_usdt
    else:
        if exchange and direction == "LONG" and sell_qty > 0:
            try:
                ccxt_pair = format_ccxt_pair(pair)
                sq = float(exchange.amount_to_precision(ccxt_pair, sell_qty)) if ccxt_pair in getattr(exchange, 'markets', {}) else sell_qty
                order = exchange.create_order(symbol=ccxt_pair, type='market', side='sell', amount=sq)
                pnl_usdt = sq * (cp - entry)
                log.info(f"LIVE CLOSE {tid}: {sq} {base_coin}, order={order['id']}")
            except Exception as e:
                log.error(f"LIVE CLOSE {tid}: {e}")

    # Update tracking
    wpnl = (pnl_pct * 0.5 if is_partial else pnl_pct) * (pos.position_size_pct / 100)
    daily_pnl += wpnl
    weekly_pnl += wpnl

    if resultado == "LOSS":
        consecutive_losses += 1
    elif resultado == "WIN":
        consecutive_losses = 0

    if not is_partial:
        if pos in open_positions:
            open_positions.remove(pos)

    for t in trade_log:
        if t["trade_id"] == tid:
            t.update({"resultado": resultado, "pnl_R": f"{pnl_r:+.2f}R",
                       "precio_cierre": cp, "motivo_cierre": motivo, "pnl_usdt": round(pnl_usdt, 2)})

    duration_hours = ""
    try:
        opened = datetime.fromisoformat(pos.opened_at.replace('Z', '+00:00'))
        duration_hours = f"{(datetime.now(timezone.utc) - opened).total_seconds() / 3600:.1f}"
    except Exception:
        pass

    await log_to_sheet("close_trade", {
        "trade_id": tid, "close_price": cp, "resultado": resultado,
        "pnl_R": f"{pnl_r:+.2f}R", "motivo_cierre": motivo, "pnl_usdt": round(pnl_usdt, 2),
        "duration_hours": duration_hours, "sl_too_short": sl_too_short, "tp_too_high": tp_too_high,
        "post_trade_notes": f"Daily:{daily_pnl:.2%} Weekly:{weekly_pnl:.2%} Losses:{consecutive_losses}"
    })

    log.info(f"CLOSE {tid}: {resultado} {motivo} pnl_r={pnl_r:+.2f}R ${pnl_usdt:+.2f} partial={is_partial}")
    return {
        "trade_id": tid, "resultado": resultado, "motivo": motivo,
        "pnl_r": round(pnl_r, 2), "pnl_pct": round(pnl_pct * 100, 2),
        "pnl_usdt": round(pnl_usdt, 2), "partial": is_partial,
        "sl_too_short": sl_too_short, "tp_too_high": tp_too_high,
    }


@app.post("/close-trade")
async def close_trade(request: Request):
    body = await request.json()
    tid = body.get("trade_id")
    cp = float(body.get("close_price", 0))
    motivo = body.get("motivo", "manual")
    result = await _execute_close(tid, cp, motivo, body)
    bal = await get_balance()
    result["balance"] = bal
    return result

@app.get("/self-test")
async def self_test():
    results = {}
    results["rag"] = {"loaded": rag.loaded, "chunks": rag.chunk_count}
    results["gemini"] = {"key_set": bool(GEMINI_API_KEY)}
    results["execution"] = {"mode": "PAPER" if PAPER_TRADING else "LIVE", "ready": binance_available or PAPER_TRADING}
    results["sheets"] = {"url_set": bool(SHEETS_WEBAPP_URL)}
    results["news"] = {"cryptopanic_key_set": bool(CRYPTOPANIC_API_KEY)}
    try:
        ctx = await get_market_context()
        results["market"] = {"btc": ctx["btc_price"], "fng": ctx["fear_greed"], "news": ctx["news_sentiment"], "ok": ctx["btc_price"] > 0}
    except Exception as e:
        results["market"] = {"ok": False, "error": str(e)}
    bal = await get_balance()
    results["balance"] = bal
    results["config"] = {"paper": PAPER_TRADING, "release": RELEASE_ID, "secret_set": bool(WEBHOOK_SECRET)}
    results["overall"] = "READY" if all([
        rag.loaded, bool(GEMINI_API_KEY), bool(WEBHOOK_SECRET), bool(SHEETS_WEBAPP_URL),
        (binance_available or PAPER_TRADING), results.get("market", {}).get("ok", False)
    ]) else "ISSUES"
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
