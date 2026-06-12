"""
CryptoAgent v3.0 — Production Server
Merges v2.5.2 (stable) + Binance execution via ccxt
TradingView → Render → RAG + Gemini → Binance (when PAPER_TRADING=false) → Google Sheets
"""
import os, json, logging, pickle, hashlib, re, asyncio
import numpy as np
from datetime import datetime, timezone
from sklearn.metrics.pairwise import cosine_similarity
from fastapi import FastAPI, Request, HTTPException
import httpx
import store
import valuation
import market_context

RELEASE_ID = "v3.1-20260608"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
SHEETS_WEBAPP_URL = os.environ.get("SHEETS_WEBAPP_URL", "")
PAPER_TRADING = os.environ.get("PAPER_TRADING", "true").lower() == "true"
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET = os.environ.get("BINANCE_SECRET", "")
# Simulated account equity used for paper-trading position sizing and PnL.
PAPER_EQUITY = float(os.environ.get("PAPER_EQUITY", "10000"))
# How often (seconds) the background monitor checks open positions for SL/TP hits.
MONITOR_INTERVAL = int(os.environ.get("MONITOR_INTERVAL_SEC", "60"))
# "Mr. Market" behavioral valuation (Graham). Enabled by default.
MRMARKET_ENABLED = os.environ.get("MRMARKET_ENABLED", "true").lower() == "true"
# Hard-refuse new LONG entries when the crowd is in extreme euphoria (over-estimation).
# Set false if your strategy is pure momentum/trend-following and you want it as bias only.
MRMARKET_BLOCK_EUPHORIA = os.environ.get("MRMARKET_BLOCK_EUPHORIA", "true").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("CryptoAgent")
app = FastAPI(title="CryptoAgent", version=RELEASE_ID)

# Binance exchange (only initialized if keys are present)
exchange = None
try:
    import ccxt
    if BINANCE_API_KEY and BINANCE_SECRET:
        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY, 'secret': BINANCE_SECRET,
            'enableRateLimit': True, 'options': {'defaultType': 'spot'}
        })
        log.info("Binance exchange initialized (spot)")
    else:
        log.info("Binance keys not set — paper trading only")
except ImportError:
    log.warning("ccxt not installed — paper trading only")

# ── Durable state: load from SQLite on startup (survives Railway restarts) ──
store.init()
trade_log = store.all_trades()
open_positions = store.all_positions()
trade_counter = int(store.get_kv("trade_counter", 0))
satellite_pct = float(store.get_kv("satellite_pct", 20.0))
daily_pnl = float(store.get_kv("daily_pnl", 0.0))
weekly_pnl = float(store.get_kv("weekly_pnl", 0.0))


def _utc_day():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_week():
    iso = datetime.now(timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def refresh_pnl_window():
    """Reset daily/weekly PnL counters when the UTC day/week rolls over."""
    global daily_pnl, weekly_pnl
    if store.get_kv("pnl_day") != _utc_day():
        daily_pnl = 0.0
        store.set_kv("daily_pnl", 0.0)
        store.set_kv("pnl_day", _utc_day())
    if store.get_kv("pnl_week") != _utc_week():
        weekly_pnl = 0.0
        store.set_kv("weekly_pnl", 0.0)
        store.set_kv("pnl_week", _utc_week())


def add_pnl(delta_pct: float):
    """Apply a realized PnL fraction (of equity) to the rolling counters."""
    global daily_pnl, weekly_pnl
    refresh_pnl_window()
    daily_pnl += delta_pct
    weekly_pnl += delta_pct
    store.set_kv("daily_pnl", daily_pnl)
    store.set_kv("weekly_pnl", weekly_pnl)


refresh_pnl_window()
log.info(f"State loaded: trades={len(trade_log)} open_positions={len(open_positions)} "
         f"trade_counter={trade_counter} daily_pnl={daily_pnl:.4f} weekly_pnl={weekly_pnl:.4f}")

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
    # Multiplier the agent is told to use when sizing its stop (widens after stops-too-tight).
    "sl_atr_mult": 2.0,
}

# Hard limits the self-learning loop may NEVER cross. Capital-preservation is not negotiable:
# the bot may adapt how PICKY it is, never how much it risks or whether it has a stop.
RISK_FLOORS = {
    "max_risk_per_trade_max": 0.005,   # learning can never raise risk-per-trade above 0.5%
    "min_confidence_floor": 50,        # never accept setups below 50% confidence
    "min_confidence_ceil": 90,
    "min_confluence_floor": 3,
    "min_confluence_ceil": 9,
    "min_rr_floor": 1.5,               # never take a target worse than 1.5R
    "min_rr_ceil": 3.0,
    "sl_atr_mult_floor": 1.5,
    "sl_atr_mult_ceil": 3.5,
}

# Keys that the learning loop is allowed to tune. Everything else (drawdown kills,
# max_risk_per_trade, protected_assets...) is frozen.
_ADAPTABLE_KEYS = ["min_confidence", "min_confluence", "min_rr", "sl_atr_mult"]


def _apply_param_overrides():
    """Reload learned parameter overrides from the store on startup so learning persists."""
    overrides = store.get_kv("risk_overrides", {}) or {}
    for k, v in overrides.items():
        if k in _ADAPTABLE_KEYS:
            RISK_PARAMS[k] = v
    # max_risk_per_trade can only ever have been lowered; clamp defensively.
    RISK_PARAMS["max_risk_per_trade"] = min(RISK_PARAMS["max_risk_per_trade"],
                                            RISK_FLOORS["max_risk_per_trade_max"])
    if overrides:
        log.info(f"Loaded learned overrides: {overrides}")


_apply_param_overrides()


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


def closed_trades(n=20, pair=None):
    """Most recent closed trades (with a result), optionally filtered by pair."""
    rows = [t for t in trade_log if t.get("resultado") in ("WIN", "LOSS", "BREAKEVEN")]
    if pair:
        rows = [t for t in rows if str(t.get("pair", "")).upper() == pair.upper()]
    return rows[-n:]


def _rate(rows, key, val="SÍ"):
    rows = [r for r in rows if r.get(key) not in (None, "")]
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get(key) == val) / len(rows)


def adapt_parameters():
    """
    AGGRESSIVE self-tuning of SELECTIVITY only, bounded by RISK_FLOORS.
    Called after each close. Adjusts how picky the agent is and how it shapes stops/targets,
    based on rolling outcomes. Never touches risk-per-trade or the kill switches.
    """
    rows = closed_trades(n=20)
    n = len(rows)
    if n < 8:   # aggressive: act early, but not from pure noise
        return
    wins = sum(1 for r in rows if r.get("resultado") == "WIN")
    losses = sum(1 for r in rows if r.get("resultado") == "LOSS")
    decided = wins + losses
    if decided == 0:
        return
    wr = wins / decided
    sl_short_rate = _rate(rows, "sl_too_short")
    tp_high_rate = _rate(rows, "tp_too_high")

    before = {k: RISK_PARAMS[k] for k in _ADAPTABLE_KEYS}

    # 1) Selectivity follows win rate (aggressive steps).
    if wr < 0.45:
        RISK_PARAMS["min_confidence"] = _clamp(RISK_PARAMS["min_confidence"] + 5,
                                               RISK_FLOORS["min_confidence_floor"], RISK_FLOORS["min_confidence_ceil"])
        RISK_PARAMS["min_confluence"] = _clamp(RISK_PARAMS["min_confluence"] + 1,
                                               RISK_FLOORS["min_confluence_floor"], RISK_FLOORS["min_confluence_ceil"])
    elif wr > 0.60:
        RISK_PARAMS["min_confidence"] = _clamp(RISK_PARAMS["min_confidence"] - 3,
                                               RISK_FLOORS["min_confidence_floor"], RISK_FLOORS["min_confidence_ceil"])
        RISK_PARAMS["min_confluence"] = _clamp(RISK_PARAMS["min_confluence"] - 1,
                                               RISK_FLOORS["min_confluence_floor"], RISK_FLOORS["min_confluence_ceil"])

    # 2) Stops too tight → tell the agent to widen its stop (more ATR).
    if sl_short_rate > 0.30:
        RISK_PARAMS["sl_atr_mult"] = _clamp(round(RISK_PARAMS["sl_atr_mult"] + 0.25, 2),
                                            RISK_FLOORS["sl_atr_mult_floor"], RISK_FLOORS["sl_atr_mult_ceil"])

    # 3) Targets too ambitious → take profit sooner (lower required R:R).
    if tp_high_rate > 0.30:
        RISK_PARAMS["min_rr"] = _clamp(round(RISK_PARAMS["min_rr"] - 0.25, 2),
                                       RISK_FLOORS["min_rr_floor"], RISK_FLOORS["min_rr_ceil"])
    elif wr > 0.60 and tp_high_rate < 0.10:
        RISK_PARAMS["min_rr"] = _clamp(round(RISK_PARAMS["min_rr"] + 0.25, 2),
                                       RISK_FLOORS["min_rr_floor"], RISK_FLOORS["min_rr_ceil"])

    # 4) Satellite allocation from satellite-bucket performance.
    sat_rows = [r for r in rows if r.get("bucket") == "SATELLITE"]
    sat_dec = [r for r in sat_rows if r.get("resultado") in ("WIN", "LOSS")]
    global satellite_pct
    if len(sat_dec) >= 4:
        sat_wr = sum(1 for r in sat_dec if r.get("resultado") == "WIN") / len(sat_dec)
        if sat_wr > 0.55:
            satellite_pct = _clamp(satellite_pct + 5, RISK_PARAMS["satellite_min"], RISK_PARAMS["satellite_max"])
        elif sat_wr < 0.40:
            satellite_pct = _clamp(satellite_pct - 5, RISK_PARAMS["satellite_min"], RISK_PARAMS["satellite_max"])
        store.set_kv("satellite_pct", satellite_pct)

    after = {k: RISK_PARAMS[k] for k in _ADAPTABLE_KEYS}
    changed = {k: (before[k], after[k]) for k in _ADAPTABLE_KEYS if before[k] != after[k]}
    if changed:
        store.set_kv("risk_overrides", {k: RISK_PARAMS[k] for k in _ADAPTABLE_KEYS})
        reason = (f"n={n} WR={wr:.0%} sl_short={sl_short_rate:.0%} tp_high={tp_high_rate:.0%} → "
                  + ", ".join(f"{k}:{v[0]}→{v[1]}" for k, v in changed.items()))
        log.info(f"LEARN adapt: {reason}")
        store.set_kv("last_adaptation", {"at": datetime.utcnow().isoformat(), "reason": reason})


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
PRICE_KEYS = {"BTCUSDT": "btc_price", "ETHUSDT": "eth_price", "SOLUSDT": "sol_price"}

async def get_market_context(pair: str = "BTCUSDT"):
    """Delegate to the Phase-3 multi-source aggregator (6 APIs, cross-validation, TTL cache,
    SOLO-OBSERVATION). Falls back to a minimal degraded object if the module itself errors."""
    funding_pair = pair.upper() if pair.upper() in market_context.ASSETS else "BTCUSDT"
    try:
        return await market_context.build_context(pair=pair.upper(), funding_pair=funding_pair)
    except Exception as e:
        log.error(f"market_context failed, minimal fallback: {e}")
        return {"fear_greed": 50, "fear_greed_label": "Neutral", "btc_price": 0, "btc_24h_change": 0,
                "eth_price": 0, "sol_price": 0, "btc_funding": 0, "composite_score": 0,
                "sources_ok": {}, "price_reliable": {}, "critical_down": ["module_error"],
                "solo_observation": True, "degradation": ["market_context exception"]}

def get_current_price(pair: str, market_ctx: dict) -> float:
    key = PRICE_KEYS.get(pair.upper(), "btc_price")
    return float(market_ctx.get(key, 0))

# ═══════════════════════════════════════════════════════════
# GEMINI LLM + NORMALIZER
# ═══════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are a disciplined operator trained in the school of Benjamin Graham,
adapted to a speculative asset. You are NOT a signal bot — you are an intelligent investor.
Personality: O:75 C:95 E:15 A:10 N:5 (deliberate, skeptical, zero ego).

MENTAL FRAME (Graham, adapted to crypto):
- MARGIN OF SAFETY (redefined): crypto has no cash flows / intrinsic value, so your margin of
  safety is CONFLUENCE + SURVIVABILITY. Only enter when price, technical structure, regime,
  sentiment and news ALL point the same direction AND the reward:risk survives a PESSIMISTIC
  scenario (assume your ATR-based stop is hit immediately): rr_pesimista >= 2.0.
- MR. MARKET: the market is a manic-depressive partner; its prices are offers you may ignore,
  not truths. Extreme FEAR + intact structure = potential opportunity. Extreme EUPHORIA =
  maximum skepticism, NEVER a reason to chase. Never chase momentum out of FOMO.
- INVESTMENT vs SPECULATION: only act when there is an articulable EDGE and a valid stop.
- PROCESS OVER OUTCOME: a confluence-9 setup that fails ONE hard rule is rejected without exception.

GOLDEN RULE: when in doubt, or when data sources contradict each other -> NO_TRADE.
Not trading IS a position.

CRITICAL: respond ONLY in English. All JSON keys and values in English. Use EXACTLY:
- action: "BUY", "SELL", or "NO_TRADE"   (SELL/SHORT not executable on spot, long-only)
- direction: "LONG" or "SHORT"
- bucket: "CORE" or "SATELLITE"
- regime_btc: "GREEN", "YELLOW", or "RED"
- confidence: integer 0-100 (real conviction, never 0 for BUY/SELL)

IMMUTABLE RULES:
1. CAPITAL PRESERVATION is primary. A 50% loss needs 100% gain to recover.
2. Minimum R:R 2.0 (standard), 3.0 (euphoria/conservative posture) — measured pessimistically.
3. MUST identify a specific articulable EDGE.
4. REGIME determines method: uptrend=trend-following, range=mean-reversion, downtrend=preserve.
5. Max 0.5% risk per trade, max 5% total exposure.
6. NEVER trade BNB pairs.
7. If entry price is stale (market moved past your ATR/0.5% threshold), action = NO_TRADE.

ANTI-BIAS CHECKLIST (mandatory): you MUST output a `bias_check` object with these 6 fields, each
{"pass": true|false, "reason": "<one line>"}. If ANY is false, action MUST be NO_TRADE:
- recency: am I extrapolating the last few candles instead of the full regime?
- confirmation: state the strongest thesis AGAINST the trade (pre-mortem). Put it in `bear_case`.
- anchoring: does the call depend on an arbitrary reference price (ATH, round number)?
- sunk_cost: are recent losses pushing me to "win it back"? (check the feedback history)
- fomo_herd: is news/sentiment euphoric AND price already moved a lot in 24h?
- overconfidence: do the data sources disagree (price discrepancy / contradictory signals)?

PORTFOLIO: CORE 70-90% (BTC/ETH/L1s) + SATELLITE 10-30% (high-risk altcoins/memes).
Respond with ONLY valid JSON in English."""

TRADE_PROMPT = """MARKET CONTEXT:
{market_context}

KNOWLEDGE BASE:
{rag_context}

SIGNAL: {signal}

CURRENT MARKET PRICE: {current_price}

PORTFOLIO: positions={positions}, daily_pnl={daily_pnl}, weekly_pnl={weekly_pnl}, satellite={satellite_pct}%

MR. MARKET BEHAVIORAL READ (Graham — is the crowd under/over-estimating this price?):
{valuation}
Use it as a contrarian bias: prefer buying when UNDERVALUED/DEEPLY_UNDERVALUED (crowd fearful),
demand a much stronger edge or stand aside when OVERVALUED, and NEVER buy into EUPHORIC blow-offs.
This is a bias on top of the technical signal — it does not override regime or risk rules, and a
cheap market can get cheaper, so still require your edge and a valid stop.

CURRENT ADAPTIVE POLICY (learned from your own past results — respect it):
{policy}

SELF-LEARNING FEEDBACK FROM PREVIOUS TRADES:
{feedback}

Apply the lessons above: only take this trade if it clears the current policy thresholds; size your
stop using sl_atr_mult × ATR; do not set a target beyond what the learned R:R supports. If recent
results for this pair/regime/template are poor, demand a stronger edge or return NO_TRADE.

CURRENT POSTURE (regime-based; respect its risk/confluence/R:R thresholds):
{posture}

Evaluate this signal against current market price. If entry price differs >0.5% from current price, reject as stale.
Before approving, run the anti-bias checklist honestly — if ANY check fails, return NO_TRADE.
Compute rr_pesimista = (take_profit_1 - entry_price) / (entry_price - stop_loss) assuming the stop
is reached first; it MUST be >= the posture's min R:R.
Respond with ONLY this JSON (fill real values, confidence 0-100 must reflect conviction):
{{"action":"BUY","pair":"BTCUSDT","direction":"LONG","bucket":"CORE","template":"T1_PULLBACK","entry_price":0,"stop_loss":0,"take_profit_1":0,"take_profit_2":0,"position_size_pct":0.5,"confidence":75,"regime_btc":"GREEN","trend_regime":"STRONG_UP","vol_regime":"NORMAL","confluence_score":7,"edge_description":"","reasoning":"","checklist_pass":true,"risks":[],"self_learning_adjustment":"none","posture_used":"STANDARD","rr_pesimista":2.0,"bear_case":"strongest reason this trade fails","bias_check":{{"recency":{{"pass":true,"reason":""}},"confirmation":{{"pass":true,"reason":""}},"anchoring":{{"pass":true,"reason":""}},"sunk_cost":{{"pass":true,"reason":""}},"fomo_herd":{{"pass":true,"reason":""}},"overconfidence":{{"pass":true,"reason":""}}}}}}"""

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
    # Graham engine (Phase 2): posture + pessimistic R:R + pre-mortem + anti-bias checklist.
    "posture_used": "", "rr_pesimista": 0, "bear_case": "", "bias_check": {},
}

# The 6 mandatory anti-bias checks (see graham-trading-philosophy skill). Canonical keys plus
# the Spanish/variant spellings Gemini sometimes emits, mapped to canonical.
BIAS_KEYS = ["recency", "confirmation", "anchoring", "sunk_cost", "fomo_herd", "overconfidence"]
_BIAS_ALIASES = {
    "recencia": "recency", "confirmación": "confirmation", "confirmacion": "confirmation",
    "anclaje": "anchoring", "costo_hundido": "sunk_cost", "coste_hundido": "sunk_cost",
    "sunk_cost_revenge": "sunk_cost", "venganza": "sunk_cost", "fomo": "fomo_herd",
    "manada": "fomo_herd", "fomo_manada": "fomo_herd", "fomo_herd_check": "fomo_herd",
    "exceso_de_confianza": "overconfidence", "exceso_confianza": "overconfidence",
    "sobreconfianza": "overconfidence",
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
    except:
        conf = 0
    conf = max(0, min(100, conf))
    if action in ("BUY", "SELL") and conf == 0:
        confl = float(result.get("confluence_score", 0) or 0)
        conf = min(95, max(55, confl * 10))
    result["confidence"] = round(conf, 1)

    for num_field in ["entry_price", "stop_loss", "take_profit_1", "take_profit_2",
                      "position_size_pct", "confidence", "confluence_score", "rr_pesimista"]:
        val = result.get(num_field, 0)
        if isinstance(val, str):
            val = val.replace("%", "").replace(",", "").strip()
        try:
            result[num_field] = float(val)
        except:
            result[num_field] = 0.0

    # Keep bias_check a dict; re-key any Spanish/variant subkeys to canonical names.
    bc = result.get("bias_check")
    if isinstance(bc, dict):
        result["bias_check"] = {_BIAS_ALIASES.get(k.lower().strip(), k): v for k, v in bc.items()}
    else:
        result["bias_check"] = {}

    return result


def _bias_item_pass(v) -> tuple:
    """Interpret one anti-bias entry. Accepts {"pass":bool,"reason":str}, bool, or str.
    Returns (passed: bool, reason: str). Unknown/missing → fail (golden rule: doubt → NO_TRADE)."""
    if isinstance(v, dict):
        reason = str(v.get("reason") or v.get("razon") or v.get("razón") or "")
        for k in ("pass", "passed", "aprobado", "ok", "result"):
            if k in v:
                p = v[k]
                if isinstance(p, str):
                    return p.strip().lower() in ("pass", "true", "yes", "sí", "si", "ok"), reason
                return bool(p), reason
        return False, reason or "no pass flag"
    if isinstance(v, bool):
        return v, ""
    if isinstance(v, str):
        return v.strip().lower() in ("pass", "true", "yes", "sí", "si", "ok"), v
    return False, "unrecognized bias entry"


def evaluate_bias_check(decision: dict) -> tuple:
    """
    Enforce the 6-point anti-bias checklist. Returns (ok: bool, reason: str).
    ALL 6 checks must be present AND pass. Missing checklist or any failing/absent
    check → not ok (the decision must become NO_TRADE). This is the implacable gate.
    """
    bc = decision.get("bias_check") or {}
    if not isinstance(bc, dict) or not bc:
        return False, "bias_check missing (required for any BUY/SELL)"
    failed = []
    for key in BIAS_KEYS:
        if key not in bc:
            failed.append(f"{key}:absent")
            continue
        passed, reason = _bias_item_pass(bc[key])
        if not passed:
            failed.append(f"{key}:{reason or 'fail'}")
    if failed:
        return False, "bias_check failed → NO_TRADE [" + "; ".join(failed) + "]"
    return True, "bias_check clear (6/6)"


async def call_gemini(prompt: str) -> dict:
    if not GEMINI_API_KEY:
        return {"action": "NO_TRADE", "reasoning": "GEMINI_API_KEY not set"}

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": SYSTEM_PROMPT + "\n\n" + prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096,
                             "responseMimeType": "application/json"}
    }

    raw = ""
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code != 200:
                body = r.text[:500]
                log.error(f"Gemini HTTP {r.status_code}: {body}")
                return {"action": "NO_TRADE", "reasoning": f"Gemini HTTP {r.status_code}"}
            data = r.json()
            raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            parsed = json.loads(raw)
            return normalize_gemini(parsed)
        except json.JSONDecodeError:
            log.error(f"Gemini invalid JSON: {raw[:500]}")
            try:
                fixed = raw
                if fixed.count('{') > fixed.count('}'):
                    fixed += '""}' * (fixed.count('{') - fixed.count('}'))
                parsed = json.loads(fixed)
                return normalize_gemini(parsed)
            except:
                return {"action": "NO_TRADE", "reasoning": "Gemini returned invalid JSON"}
        except Exception as e:
            log.error(f"Gemini error: {e}")
            return {"action": "NO_TRADE", "reasoning": str(e)}

# ═══════════════════════════════════════════════════════════
# BINANCE EXECUTION ENGINE
# ═══════════════════════════════════════════════════════════
def to_ccxt_pair(pair: str) -> str:
    """BTCUSDT -> BTC/USDT (handles USDT and BUSD quote assets)."""
    p = pair.upper()
    if p.endswith("USDT"):
        return p[:-4] + "/USDT"
    if p.endswith("BUSD"):
        return p[:-4] + "/BUSD"
    return p


def get_equity_usdt() -> float:
    """Account equity used for risk sizing. Free USDT in live, PAPER_EQUITY in paper."""
    if PAPER_TRADING or not exchange:
        return PAPER_EQUITY
    try:
        bal = exchange.fetch_balance()
        return float(bal.get("USDT", {}).get("free", 0)) or PAPER_EQUITY
    except Exception as e:
        log.warning(f"fetch_balance failed, using PAPER_EQUITY: {e}")
        return PAPER_EQUITY


def compute_position_qty(equity: float, entry: float, stop: float, cash_available: float = None) -> float:
    """
    Risk-based sizing: risk exactly max_risk_per_trade of equity on the stop distance.
        qty = (equity * max_risk_per_trade) / |entry - stop|
    The capital-at-risk (not notional) is what's controlled — max_total_exposure caps the
    SUM of per-trade risk across open positions (enforced in validate_trade), so ~10 trades
    of 0.5% each. Here we only additionally clamp notional to the cash actually available,
    so we never try to spend money we don't have.
    """
    if equity <= 0 or entry <= 0 or stop <= 0:
        return 0.0
    stop_dist = abs(entry - stop)
    if stop_dist < entry * 1e-6:
        return 0.0
    risk_amount = equity * RISK_PARAMS["max_risk_per_trade"]
    qty = risk_amount / stop_dist
    if cash_available is not None and cash_available > 0 and qty * entry > cash_available:
        qty = cash_available / entry
    return qty


def open_long(pair: str, entry: float, stop: float, tp1: float, tp2: float, current_price: float) -> tuple:
    """
    Open a LONG (spot market buy) sized by risk. Returns (success, info_dict | error_str).
    info_dict: {order_id, qty, notional, equity, oco}
    """
    equity = get_equity_usdt()

    if PAPER_TRADING:
        # Cash not really tracked in paper: bound notional by equity minus already-deployed.
        deployed = sum(float(p.get("notional", 0)) for p in open_positions)
        cash_available = max(0.0, equity - deployed)
        qty = compute_position_qty(equity, entry or current_price, stop, cash_available)
        if qty <= 0:
            return False, "Sizing produced zero quantity (no cash budget or bad entry/stop)"
        notional = qty * current_price
        log.info(f"PAPER BUY {pair} qty={qty:.6f} notional={notional:.2f} "
                 f"(risk {RISK_PARAMS['max_risk_per_trade']:.2%} of {equity:.2f})")
        return True, {"order_id": f"PAPER-{datetime.utcnow().strftime('%H%M%S')}",
                      "qty": qty, "notional": notional, "equity": equity, "oco": None}

    if not exchange:
        return False, "Binance exchange not configured"

    try:
        ccxt_pair = to_ccxt_pair(pair)
        usdt_free = float(exchange.fetch_balance().get("USDT", {}).get("free", 0))
        qty = compute_position_qty(equity, entry or current_price, stop, usdt_free)
        if qty <= 0:
            return False, "Sizing produced zero quantity (insufficient cash or bad entry/stop)"
        notional = qty * current_price
        if notional < 5:
            return False, f"Notional {notional:.2f} USDT below Binance minimum (5)"
        qty = float(exchange.amount_to_precision(ccxt_pair, qty))
        if qty <= 0:
            return False, "Quantity rounds to zero at exchange precision"
        order = exchange.create_order(symbol=ccxt_pair, type="market", side="buy", amount=qty)
        filled_qty = float(order.get("filled") or qty)
        log.info(f"BINANCE BUY {ccxt_pair} qty={filled_qty:.6f} order_id={order['id']}")
        oco = place_protective_oco(ccxt_pair, filled_qty, stop, tp1, tp2)
        return True, {"order_id": str(order["id"]), "qty": filled_qty,
                      "notional": filled_qty * current_price, "equity": equity, "oco": oco}
    except Exception as e:
        log.error(f"Binance open_long error: {e}")
        return False, str(e)


def place_protective_oco(ccxt_pair: str, qty: float, stop: float, tp1: float, tp2: float):
    """
    Server-side safety net (LIVE only): an OCO sell that protects the position even if
    this bot process dies. Take-profit = tp1 (closest target), stop = stop_loss.
    Best-effort: failures are logged but do not abort the trade (the monitor still guards it).
    Returns the OCO order-list id or None.
    """
    if PAPER_TRADING or not exchange:
        return None
    try:
        tp_price = float(exchange.price_to_precision(ccxt_pair, tp1))
        stop_price = float(exchange.price_to_precision(ccxt_pair, stop))
        stop_limit = float(exchange.price_to_precision(ccxt_pair, stop * 0.999))
        amount = float(exchange.amount_to_precision(ccxt_pair, qty))
        resp = exchange.private_post_order_oco({
            "symbol": exchange.market(ccxt_pair)["id"],
            "side": "SELL",
            "quantity": amount,
            "price": tp_price,                 # take-profit limit
            "stopPrice": stop_price,           # stop trigger
            "stopLimitPrice": stop_limit,      # stop-limit price
            "stopLimitTimeInForce": "GTC",
        })
        oco_id = resp.get("orderListId")
        log.info(f"OCO placed {ccxt_pair} tp={tp_price} stop={stop_price} listId={oco_id}")
        return oco_id
    except Exception as e:
        log.error(f"OCO placement failed for {ccxt_pair} (monitor will still guard): {e}")
        return None


def cancel_protective_oco(ccxt_pair: str, oco_id):
    """Cancel a resting OCO before the monitor market-closes (LIVE only)."""
    if PAPER_TRADING or not exchange or oco_id is None:
        return
    try:
        exchange.private_delete_orderlist({
            "symbol": exchange.market(ccxt_pair)["id"],
            "orderListId": oco_id,
        })
        log.info(f"Cancelled OCO {oco_id} on {ccxt_pair}")
    except Exception as e:
        log.warning(f"Could not cancel OCO {oco_id} (may already be filled): {e}")


def market_sell(ccxt_pair: str, qty: float) -> tuple:
    """Market-sell an exact quantity to close a position (LIVE only). Returns (ok, info)."""
    if PAPER_TRADING:
        return True, f"PAPER-SELL-{datetime.utcnow().strftime('%H%M%S')}"
    if not exchange:
        return False, "Binance exchange not configured"
    try:
        # Don't oversell: clamp to free balance (handles dust / already-filled OCO).
        base = ccxt_pair.split("/")[0]
        free = float(exchange.fetch_balance().get(base, {}).get("free", 0))
        sell_qty = min(qty, free)
        if sell_qty <= 0:
            return False, f"No {base} balance to sell (position likely already closed)"
        sell_qty = float(exchange.amount_to_precision(ccxt_pair, sell_qty))
        order = exchange.create_order(symbol=ccxt_pair, type="market", side="sell", amount=sell_qty)
        log.info(f"BINANCE SELL {ccxt_pair} qty={sell_qty:.6f} order_id={order['id']}")
        return True, str(order["id"])
    except Exception as e:
        log.error(f"Binance market_sell error: {e}")
        return False, str(e)

# ═══════════════════════════════════════════════════════════
# RISK MANAGER + STALE SIGNAL + VALIDATION
# ═══════════════════════════════════════════════════════════
def check_kill_switches():
    refresh_pnl_window()
    if daily_pnl <= RISK_PARAMS["daily_drawdown_kill"]:
        return True, f"Daily DD {daily_pnl:.2%} > {RISK_PARAMS['daily_drawdown_kill']:.2%}"
    if weekly_pnl <= RISK_PARAMS["weekly_drawdown_kill"]:
        return True, f"Weekly DD {weekly_pnl:.2%} > {RISK_PARAMS['weekly_drawdown_kill']:.2%}"
    return False, ""


def stale_signal_check(signal: dict, decision: dict, market_ctx: dict) -> tuple:
    action = str(decision.get("action", "")).upper()
    if action not in ("BUY", "SELL"):
        return False, ""
    pair = str(decision.get("pair") or signal.get("pair") or "").upper()
    entry = float(decision.get("entry_price") or signal.get("price") or 0)
    current = get_current_price(pair, market_ctx)
    if current <= 0:
        return True, f"Cannot validate: market price unavailable for {pair}"
    if entry <= 0:
        return True, "Cannot validate: entry_price is 0"
    drift = abs(current - entry) / entry
    atr = float(signal.get("atr", 0) or 0)
    signal_price = float(signal.get("price", 0) or 0)
    threshold = (atr / signal_price) if (atr > 0 and signal_price > 0) else RISK_PARAMS["max_entry_drift_pct"]
    if drift > threshold:
        return True, f"Stale: price {current:.2f} drifted {drift:.2%} from entry {entry:.2f} (threshold {threshold:.2%})"
    return False, ""


def validate_trade(d: dict, signal: dict = None, market_ctx: dict = None):
    pair = d.get("pair", "").upper()
    action = str(d.get("action", "NO_TRADE")).upper()

    if any(p in pair for p in RISK_PARAMS["protected_assets"]):
        return False, f"BLOCKED: {pair} is protected (BNB)"
    if action == "NO_TRADE":
        return False, d.get("reasoning", "Model decided NO_TRADE")
    # Spot account: only LONG (BUY) can open a position. SHORT/SELL can't be opened on spot.
    if action == "SELL" or str(d.get("direction", "")).upper() == "SHORT":
        return False, "SHORT/SELL not supported on spot account (long-only)"
    if not d.get("checklist_pass", False):
        return False, "Checklist did not pass"

    # Data-quality gate (Phase 3): if too few reliable sources, or the traded pair's price could
    # not be cross-validated (anti-bias #6: sources disagree), stand aside — never trade blind.
    if market_ctx is not None:
        if market_ctx.get("solo_observation"):
            return False, ("SOLO-OBSERVATION: >=2 critical data sources down "
                           f"({market_ctx.get('critical_down')}) — no new trades")
        price_reliable = market_ctx.get("price_reliable", {})
        if pair in price_reliable and not price_reliable[pair]:
            return False, f"Data unreliable: {pair} price sources disagree >1% — NO_TRADE (anti-bias #6)"

    # GRAHAM ANTI-BIAS GATE (implacable): all 6 checks must pass, and the pre-mortem
    # bear_case must be articulated. A failing/absent check forces NO_TRADE.
    bias_ok, bias_reason = evaluate_bias_check(d)
    if not bias_ok:
        return False, bias_reason
    if not str(d.get("bear_case", "")).strip():
        return False, "No bear_case (pre-mortem) provided — required for any entry"

    if signal and market_ctx:
        is_stale, stale_msg = stale_signal_check(signal, d, market_ctx)
        if is_stale:
            return False, stale_msg

    # Mr. Market contrarian guard: don't buy what the crowd wildly over-estimates.
    if MRMARKET_ENABLED and market_ctx and action == "BUY":
        vstate = market_ctx.get("valuation_state", "DISABLED")
        vscore = market_ctx.get("mispricing_score", 0)
        if MRMARKET_BLOCK_EUPHORIA and vstate == "EUPHORIC":
            return False, f"Mr.Market: market EUPHORIC (mispricing {vscore}) — refuse to buy crowd over-estimation"
        if vstate == "OVERVALUED" and float(d.get("confidence", 0) or 0) < RISK_PARAMS["min_confidence"] + 10:
            return False, f"Mr.Market: OVERVALUED — require +10% confidence to buy (have {d.get('confidence')})"

    conf = float(d.get("confidence", 0) or 0)
    if conf < RISK_PARAMS["min_confidence"]:
        return False, f"Confidence {conf:.0f}% < {RISK_PARAMS['min_confidence']}%"
    if d.get("confluence_score", 0) < RISK_PARAMS["min_confluence"]:
        return False, f"Confluence {d.get('confluence_score')} < {RISK_PARAMS['min_confluence']}"

    entry, sl, tp1 = d.get("entry_price", 0), d.get("stop_loss", 0), d.get("take_profit_1", 0)
    if entry and sl and abs(entry - sl) < 0.0001:
        return False, "Invalid: stop_loss equals entry_price (zero risk)"
    if entry and sl and tp1:
        risk = abs(entry - sl)
        if risk > 0 and abs(tp1 - entry) / risk < RISK_PARAMS["min_rr"]:
            return False, f"R:R below {RISK_PARAMS['min_rr']}"
    # Margin of safety: the reward:risk must survive a pessimistic read. When the model reports
    # rr_pesimista, enforce it against the posture's required R:R (never below min_rr).
    rr_pes = float(d.get("rr_pesimista", 0) or 0)
    if rr_pes and rr_pes < RISK_PARAMS["min_rr"]:
        return False, f"Pessimistic R:R {rr_pes:.2f} < required {RISK_PARAMS['min_rr']}"

    # Total capital-at-risk = sum of (qty * stop_distance / equity) across open positions.
    # By construction each risk-sized trade contributes ~max_risk_per_trade.
    def _risk_frac(p):
        eq = float(p.get("equity_at_open", 0)) or 1
        return float(p.get("qty", 0)) * abs(float(p.get("entry", 0)) - float(p.get("sl", 0))) / eq
    cur_exp = sum(_risk_frac(p) for p in open_positions)
    new_risk = RISK_PARAMS["max_risk_per_trade"]
    if cur_exp + new_risk > RISK_PARAMS["max_total_exposure"]:
        return False, f"Total risk {cur_exp + new_risk:.2%} > max_total_exposure {RISK_PARAMS['max_total_exposure']:.2%}"

    killed, reason = check_kill_switches()
    if killed:
        return False, f"KILL SWITCH: {reason}"

    return True, "All checks passed"

# ═══════════════════════════════════════════════════════════
# FEEDBACK (Sheet first, memory fallback)
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
        except:
            pass

    return build_feedback_memory(pair)


def _wr_breakdown(rows, key, label, min_n=3):
    """Per-bucket win-rate breakdown (e.g. by regime or template). Returns text parts."""
    groups = {}
    for r in rows:
        g = str(r.get(key, "") or "?")
        res = r.get("resultado")
        if res in ("WIN", "LOSS"):
            groups.setdefault(g, [0, 0])
            groups[g][0 if res == "WIN" else 1] += 1
    out = []
    for g, (w, l) in groups.items():
        if w + l >= min_n:
            out.append(f"{label}:{g} {w}W/{l}L({w/(w+l):.0%})")
    return out


def build_feedback_memory(pair: str = "") -> str:
    """
    Rich, actionable feedback from the in-memory trade journal (used when Sheets is absent).
    Surfaces win rate, R:R, per-regime / per-template breakdown, and SL/TP diagnostics so the
    LLM can learn *under which conditions* it wins or loses — not just an aggregate number.
    """
    closed = [t for t in trade_log if t.get("resultado") in ("WIN", "LOSS", "BREAKEVEN")]
    if pair:
        closed = [t for t in closed if str(t.get("pair", "")).upper() == pair.upper()]
    recent = closed[-20:]
    if len(recent) < 3:
        return f"Insufficient closed trades for {pair or 'ALL'} (need 3+)"

    wins = sum(1 for t in recent if t.get("resultado") == "WIN")
    losses = sum(1 for t in recent if t.get("resultado") == "LOSS")
    total = wins + losses or 1
    rr_vals = []
    for t in recent:
        try:
            rr_vals.append(float(str(t.get("pnl_R", "0")).replace("R", "").replace("+", "")))
        except (ValueError, TypeError):
            pass
    avg_rr = sum(rr_vals) / len(rr_vals) if rr_vals else 0

    parts = [f"{pair or 'ALL'} last {len(recent)}: {wins}W/{losses}L WR:{wins/total:.0%} avgR:{avg_rr:+.2f}"]
    # Per-context breakdowns (the "what works / what doesn't" a trader tracks).
    parts += _wr_breakdown(recent, "regime_btc", "regime")
    parts += _wr_breakdown(recent, "template", "tmpl")
    parts += _wr_breakdown(recent, "valuation_state", "val")

    sl_short = sum(1 for t in recent if t.get("sl_too_short") == "SÍ")
    tp_high = sum(1 for t in recent if t.get("tp_too_high") == "SÍ")
    if sl_short >= 2:
        parts.append(f"⚠ {sl_short} stops too tight (price reversed our way after stop) → widen stops")
    if tp_high >= 2:
        parts.append(f"⚠ {tp_high} targets too far (near-misses on TP) → take profit sooner")
    return " | ".join(parts)

# ═══════════════════════════════════════════════════════════
# SHEETS BRIDGE
# ═══════════════════════════════════════════════════════════
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
                log.info(f"Sheet {sheet_action}: ok={result.get('ok')} row={result.get('row','?')}")
                return result
            except:
                log.warning(f"Sheet {sheet_action}: non-JSON response status={r.status_code}")
                return {"ok": False}
    except Exception as e:
        log.warning(f"Sheet error: {e}")
        return {"ok": False, "error": str(e)}

# ═══════════════════════════════════════════════════════════
# POST-TRADE DIAGNOSTICS (the agent's "trade journal" — what to learn)
# ═══════════════════════════════════════════════════════════
def compute_diagnostics(pos: dict, close_price: float, motivo: str) -> dict:
    """
    Turn raw price excursion into the lessons a trader writes in their journal:
      - mfe_R / mae_R: best/worst the trade got, in R multiples
      - sl_too_short: we got stopped out but price had already moved >=1R our way
      - tp_too_high : we exited without hitting TP after getting >=80% of the way there
      - strategy_correct: was the directional thesis right?
    Heuristics (standard, intentionally simple) — they bias the LLM, they don't command it.
    """
    entry = float(pos.get("entry") or 0)
    sl = float(pos.get("sl") or 0)
    tp1 = float(pos.get("tp1") or 0)
    mfe = float(pos.get("mfe") or close_price)
    mae = float(pos.get("mae") or close_price)
    # Make sure the close price itself counts toward the excursion.
    mfe = max(mfe, close_price)
    mae = min(mae, close_price)

    risk_unit = abs(entry - sl)
    if risk_unit <= 0 or entry <= 0:
        return {"mfe_R": 0.0, "mae_R": 0.0, "sl_too_short": "NO",
                "tp_too_high": "NO", "strategy_correct": ""}

    mfe_R = (mfe - entry) / risk_unit       # LONG: favorable = price up
    mae_R = (entry - mae) / risk_unit       # LONG: adverse = price down (positive number)
    tp1_R = (tp1 - entry) / risk_unit if tp1 > 0 else RISK_PARAMS["min_rr"]

    stopped = "SL" in motivo.upper()
    took_profit = "TP" in motivo.upper()

    sl_too_short = "SÍ" if (stopped and mfe_R >= 1.0) else "NO"
    tp_too_high = "SÍ" if (not took_profit and tp1_R > 0 and mfe_R >= 0.8 * tp1_R) else "NO"
    if took_profit:
        strategy_correct = "SÍ"
    elif mfe_R < 0.5:
        strategy_correct = "NO"
    else:
        strategy_correct = "PARCIAL"

    return {"mfe_R": round(mfe_R, 2), "mae_R": round(mae_R, 2),
            "sl_too_short": sl_too_short, "tp_too_high": tp_too_high,
            "strategy_correct": strategy_correct}


# ═══════════════════════════════════════════════════════════
# POSITION CLOSE (shared by manual endpoint and the auto monitor)
# ═══════════════════════════════════════════════════════════
async def close_position(pos: dict, close_price: float, motivo: str = "manual") -> dict:
    """
    Close one open position: execute the exit (live market sell / paper sim),
    realize PnL, persist, and log to the sheet. Returns a result summary.
    """
    tid = pos["trade_id"]
    entry = float(pos.get("entry") or 0)
    sl = float(pos.get("sl") or 0)
    if entry <= 0 or close_price <= 0:
        return {"error": f"Invalid prices for {tid} (entry={entry} close={close_price})"}

    # Spot is long-only here, but keep the direction-aware formula for safety.
    pnl_pct = (close_price - entry) / entry if pos.get("direction") == "LONG" else (entry - close_price) / entry
    risk = abs(entry - sl) / entry if sl > 0 else 0
    pnl_r = pnl_pct / risk if risk > 0 else 0
    resultado = "WIN" if pnl_pct > 0 else "LOSS" if pnl_pct < 0 else "BREAKEVEN"

    # LIVE exit: cancel the protective OCO, then market-sell the exact position qty.
    exit_order_id = "N/A"
    if not PAPER_TRADING and pos.get("qty", 0) > 0:
        cancel_protective_oco(to_ccxt_pair(pos["pair"]), pos.get("oco_id"))
        ok, info = market_sell(to_ccxt_pair(pos["pair"]), float(pos["qty"]))
        exit_order_id = info if ok else f"SELL_FAILED:{info}"
        if not ok:
            log.error(f"Close {tid}: market sell failed: {info}")

    # Realize PnL as a fraction of account equity (notional_pct scales price-% to equity-%).
    notional_pct = float(pos.get("notional_pct", 0))
    equity_delta = pnl_pct * notional_pct
    add_pnl(equity_delta)
    pnl_usdt = round(pnl_pct * float(pos.get("notional", 0)), 2)

    # Remove from open positions (memory + store).
    global open_positions
    open_positions = [p for p in open_positions if p["trade_id"] != tid]
    store.delete_position(tid)

    # Compute the trade journal entry (real diagnostics, no longer hardcoded).
    diag = compute_diagnostics(pos, close_price, motivo)

    # Update the trade record (memory + store).
    for t in trade_log:
        if t["trade_id"] == tid:
            t.update({"resultado": resultado, "pnl_R": f"{pnl_r:+.2f}R",
                      "precio_cierre": close_price, "motivo_cierre": motivo,
                      "pnl_usdt": pnl_usdt, "exit_order_id": exit_order_id,
                      "closed_at": datetime.utcnow().isoformat(),
                      "mfe_R": diag["mfe_R"], "mae_R": diag["mae_R"],
                      "sl_too_short": diag["sl_too_short"], "tp_too_high": diag["tp_too_high"],
                      "strategy_correct": diag["strategy_correct"]})
            store.upsert_trade(t)
            break

    await log_to_sheet("close_trade", {
        "trade_id": tid, "close_price": close_price, "resultado": resultado,
        "pnl_R": f"{pnl_r:+.2f}R", "motivo_cierre": motivo, "pnl_usdt": pnl_usdt,
        "sl_too_short": diag["sl_too_short"], "tp_too_high": diag["tp_too_high"],
        "regime_changed": "NO", "strategy_correct": diag["strategy_correct"],
        "post_trade_notes": f"mfe={diag['mfe_R']}R mae={diag['mae_R']}R | "
                            f"Daily:{daily_pnl:.2%} Weekly:{weekly_pnl:.2%}",
    })
    log.info(f"Closed {tid}: {resultado} {pnl_r:+.2f}R pnl={pnl_usdt} mfe={diag['mfe_R']}R "
             f"mae={diag['mae_R']}R sl_short={diag['sl_too_short']} tp_high={diag['tp_too_high']} ({motivo})")

    # Learn from the result: aggressively adapt selectivity params (with hard risk floors).
    adapt_parameters()

    return {"trade_id": tid, "resultado": resultado, "pnl_r": pnl_r,
            "pnl_usdt": pnl_usdt, "exit_order_id": exit_order_id, "diagnostics": diag}


# ═══════════════════════════════════════════════════════════
# PRICE FEED + BACKGROUND POSITION MONITOR
# ═══════════════════════════════════════════════════════════
async def fetch_price(pair: str) -> float:
    """Current price for any pair via Binance public ticker (no keys needed)."""
    symbol = pair.upper().replace("/", "")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
            if r.status_code == 200:
                return float(r.json().get("price", 0))
    except Exception as e:
        log.warning(f"fetch_price {symbol} failed: {e}")
    return 0.0


async def monitor_positions():
    """
    Background loop: the heart of automatic risk management. Every MONITOR_INTERVAL
    seconds, check each open position's live price and close it when SL or TP is hit.
    Works identically in paper and live. In live it is backed by the OCO on Binance.
    """
    log.info(f"Position monitor started (every {MONITOR_INTERVAL}s)")
    while True:
        try:
            await asyncio.sleep(MONITOR_INTERVAL)
            refresh_pnl_window()
            for pos in list(open_positions):
                price = await fetch_price(pos["pair"])
                if price <= 0:
                    continue
                # Track max favorable / adverse excursion (raw material for SL/TP learning).
                if price > float(pos.get("mfe", 0)):
                    pos["mfe"] = price
                    store.upsert_position(pos)
                if price < float(pos.get("mae", price)):
                    pos["mae"] = price
                    store.upsert_position(pos)
                sl = float(pos.get("sl") or 0)
                tp1 = float(pos.get("tp1") or 0)
                tp2 = float(pos.get("tp2") or 0)
                # LONG-only spot logic
                if sl > 0 and price <= sl:
                    await close_position(pos, price, "SL_HIT")
                elif tp2 > 0 and price >= tp2:
                    await close_position(pos, price, "TP2_HIT")
                elif tp1 > 0 and price >= tp1:
                    await close_position(pos, price, "TP1_HIT")
        except asyncio.CancelledError:
            log.info("Position monitor stopped")
            raise
        except Exception as e:
            log.error(f"Monitor loop error (continuing): {e}")


@app.on_event("startup")
async def _start_monitor():
    asyncio.create_task(monitor_positions())


# ═══════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════
@app.get("/")
async def root():
    return {"status": "CryptoAgent running", "release": RELEASE_ID,
            "paper_trading": PAPER_TRADING, "rag_loaded": rag.loaded,
            "rag_chunks": rag.chunk_count, "total_trades": len(trade_log),
            "open_positions": len(open_positions), "satellite_pct": satellite_pct,
            "kill_switch_active": check_kill_switches()[0],
            "binance_connected": exchange is not None}

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
                      "daily_pnl": daily_pnl, "weekly_pnl": weekly_pnl,
                      "equity": get_equity_usdt()},
            "sizing": {"paper_equity": PAPER_EQUITY,
                       "risk_per_trade": RISK_PARAMS["max_risk_per_trade"],
                       "monitor_interval_sec": MONITOR_INTERVAL},
            "learning": {"adaptive_params": {k: RISK_PARAMS[k] for k in _ADAPTABLE_KEYS},
                         "satellite_pct": satellite_pct,
                         "overrides": store.get_kv("risk_overrides", {}),
                         "last_adaptation": store.get_kv("last_adaptation", None),
                         "closed_trades": len(closed_trades(n=10000))},
            "kill_switch": {"active": killed, "reason": reason},
            "binance": {"connected": exchange is not None, "paper": PAPER_TRADING},
            "feedback": await get_feedback()}

@app.post("/webhook")
async def webhook(request: Request):
    global trade_counter
    body = await request.json()
    if body.get("secret") != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")

    pair = body.get("pair", "UNKNOWN").upper()
    log.info(f"Signal: {pair} | {body.get('signal_type', 'N/A')}")

    sig_hash = hashlib.md5(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    if store.has_seen(sig_hash):
        return {"action": "DUPLICATE", "reason": "Signal already processed"}
    store.add_seen(sig_hash)
    store.prune_seen(keep=500)

    if any(p in pair for p in RISK_PARAMS["protected_assets"]):
        return {"action": "BLOCKED", "reason": f"{pair} is protected (BNB)"}

    killed, kill_reason = check_kill_switches()
    if killed:
        return {"action": "BLOCKED", "reason": kill_reason}

    market_ctx = await get_market_context(pair)
    current_price = get_current_price(pair, market_ctx)

    # Mr. Market behavioral valuation: is the crowd under/over-estimating this price right now?
    mrmarket = {"valuation_state": "DISABLED", "mispricing_score": 0.0, "cluster": "n/a", "rationale": ""}
    if MRMARKET_ENABLED:
        try:
            mrmarket = await valuation.analyze(pair, market_ctx.get("fear_greed", 50))
            market_ctx["valuation_state"] = mrmarket["valuation_state"]
            market_ctx["mispricing_score"] = mrmarket["mispricing_score"]
            market_ctx["behavioral_cluster"] = mrmarket["cluster"]
            # Populate funding (previously always 0) from the per-pair read.
            if mrmarket.get("features", {}).get("funding") is not None:
                market_ctx["btc_funding"] = mrmarket["features"]["funding"]
            log.info(f"Mr.Market {pair}: {mrmarket['valuation_state']} "
                     f"score={mrmarket['mispricing_score']} cluster={mrmarket['cluster']}")
        except Exception as e:
            log.warning(f"Mr.Market analysis failed: {e}")

    rag_query = f"{body.get('signal_type','')} {pair} {body.get('regime','')} {body.get('template','')} risk management"
    rag_context = rag.build_context(rag_query, k=5, max_words=1500)
    feedback = await get_feedback(pair=pair)

    policy = (f"min_confidence={RISK_PARAMS['min_confidence']}%, "
              f"min_confluence={RISK_PARAMS['min_confluence']}, "
              f"min_RR={RISK_PARAMS['min_rr']}, "
              f"stop=sl_atr_mult×ATR (sl_atr_mult={RISK_PARAMS['sl_atr_mult']})")
    valuation_txt = (f"{mrmarket['valuation_state']} (mispricing={mrmarket['mispricing_score']}, "
                     f"cluster={mrmarket['cluster']}) — {mrmarket['rationale']}")
    # Posture string injected into the prompt. Phase 4's regime engine replaces this with a
    # regime-derived posture; for now it reflects the active (learned) RISK_PARAMS thresholds.
    posture_txt = (f"posture=STANDARD risk_per_trade={RISK_PARAMS['max_risk_per_trade']:.2%} "
                   f"min_confluence={RISK_PARAMS['min_confluence']} min_RR={RISK_PARAMS['min_rr']}")
    prompt = TRADE_PROMPT.format(
        market_context=json.dumps(market_ctx),
        rag_context=rag_context or "No RAG context",
        signal=json.dumps(body),
        current_price=f"{current_price:.2f}",
        positions=len(open_positions),
        daily_pnl=f"{daily_pnl:.2%}",
        weekly_pnl=f"{weekly_pnl:.2%}",
        satellite_pct=satellite_pct,
        valuation=valuation_txt,
        policy=policy,
        feedback=feedback,
        posture=posture_txt,
    )

    decision = await call_gemini(prompt)
    is_valid, validation_msg = validate_trade(decision, signal=body, market_ctx=market_ctx)

    trade_counter += 1
    store.set_kv("trade_counter", trade_counter)
    trade_id = f"T-{trade_counter:04d}"

    # Execute on Binance if valid (BUY = open long; SELL/SHORT already rejected in validate_trade)
    binance_order_id = "N/A"
    exec_info = None
    if is_valid and decision.get("action") == "BUY":
        success, exec_result = open_long(
            pair=decision.get("pair", pair),
            entry=float(decision.get("entry_price") or current_price),
            stop=float(decision.get("stop_loss") or 0),
            tp1=float(decision.get("take_profit_1") or 0),
            tp2=float(decision.get("take_profit_2") or 0),
            current_price=current_price,
        )
        if not success:
            is_valid = False
            validation_msg = f"Binance error: {exec_result}"
        else:
            exec_info = exec_result
            binance_order_id = exec_info["order_id"]

    record = {
        "trade_id": trade_id, "timestamp": datetime.utcnow().isoformat(),
        "pair": decision.get("pair", pair), "direction": decision.get("direction", ""),
        "bucket": decision.get("bucket", ""), "template": decision.get("template", ""),
        "regime_btc": decision.get("regime_btc", ""), "trend_regime": decision.get("trend_regime", ""),
        "vol_regime": decision.get("vol_regime", ""), "fear_greed": market_ctx.get("fear_greed", ""),
        "funding_rate": market_ctx.get("btc_funding", ""),
        "composite_score": market_ctx.get("composite_score", ""),
        "news_score": market_ctx.get("news_score", ""),
        "fear_greed_trend": market_ctx.get("fear_greed_trend", ""),
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
        # Graham engine: pre-mortem, posture and the anti-bias audit trail (feeds the learning loop).
        "bear_case": decision.get("bear_case", ""),
        "posture_used": decision.get("posture_used", ""),
        "rr_pesimista": decision.get("rr_pesimista", 0),
        "bias_check": json.dumps(decision.get("bias_check", {}), ensure_ascii=False),
        "decision_action": decision.get("action", "NO_TRADE"),
        "signal_price": body.get("price", 0),
        "current_market_price": current_price,
        "signal_hash": sig_hash,
        "release": RELEASE_ID,
        "feedback_used": feedback,
        "binance_order_id": binance_order_id,
        "execution_mode": "PAPER" if PAPER_TRADING else "LIVE",
        "qty": exec_info["qty"] if exec_info else 0,
        "notional_usdt": round(exec_info["notional"], 2) if exec_info else 0,
        "equity_at_open": round(exec_info["equity"], 2) if exec_info else 0,
        "valuation_state": mrmarket.get("valuation_state", ""),
        "mispricing_score": mrmarket.get("mispricing_score", 0),
        "behavioral_cluster": mrmarket.get("cluster", ""),
    }
    trade_log.append(record)
    store.upsert_trade(record)
    sheet_result = await log_to_sheet("log_trade", record)
    log.info(f"Trade {trade_id}: action={decision.get('action')} valid={is_valid} binance={binance_order_id} sheet={sheet_result.get('ok') if isinstance(sheet_result, dict) else 'N/A'}")

    if is_valid and decision.get("action") == "BUY" and exec_info:
        equity = exec_info["equity"] or PAPER_EQUITY
        position = {
            "trade_id": trade_id, "pair": decision.get("pair", pair),
            "direction": "LONG", "bucket": decision.get("bucket"),
            # entry recorded at the actual fill (current market price), not the stale signal price
            "entry": current_price,
            "sl": float(decision.get("stop_loss") or 0),
            "tp1": float(decision.get("take_profit_1") or 0),
            "tp2": float(decision.get("take_profit_2") or 0),
            "qty": exec_info["qty"],
            "notional": exec_info["notional"],
            # fraction of equity this position represents (used to convert price-% PnL to equity-% PnL)
            "notional_pct": (exec_info["notional"] / equity) if equity > 0 else 0,
            "equity_at_open": equity,
            "opened_at": datetime.utcnow().isoformat(),
            "binance_order_id": binance_order_id,
            "oco_id": exec_info.get("oco"),
            # Excursion tracking (max favorable / adverse price seen) — fuels SL/TP learning.
            "mfe": current_price,
            "mae": current_price,
            # Snapshot of the regime/template the decision was made under, for per-context learning.
            "regime_btc": decision.get("regime_btc", ""),
            "template": decision.get("template", ""),
            "confluence_score": decision.get("confluence_score", 0),
            "valuation_state": mrmarket.get("valuation_state", ""),
        }
        open_positions.append(position)
        store.upsert_position(position)

    return {"trade_id": trade_id,
            "action": decision.get("action", "NO_TRADE") if is_valid else "REJECTED",
            "executed": is_valid and decision.get("action") != "NO_TRADE",
            "paper_mode": PAPER_TRADING,
            "binance_order_id": binance_order_id,
            "decision": decision,
            "validation": validation_msg, "market_context": market_ctx}

@app.get("/trades")
async def get_trades():
    return {"total": len(trade_log), "trades": trade_log[-50:]}

@app.get("/positions")
async def get_positions():
    return {"count": len(open_positions), "positions": open_positions}

@app.post("/close-trade")
async def close_trade(request: Request):
    body = await request.json()
    tid = body.get("trade_id")
    cp = float(body.get("close_price", 0) or 0)
    motivo = body.get("motivo", "manual")
    pos = next((p for p in open_positions if p["trade_id"] == tid), None)
    if not pos:
        return {"error": f"Position {tid} not found"}
    if cp <= 0:
        cp = await fetch_price(pos["pair"])
    return await close_position(pos, cp, motivo)

@app.get("/ping")
async def ping():
    return {"pong": True, "release": RELEASE_ID}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
