"""CryptoAgent v4 — configuración central. Todo por variables de entorno."""
import os

def _b(name, default="false"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")

RELEASE_ID = "v4.2-contexto"

# Modos
TRADING_MODE = os.environ.get("TRADING_MODE", "paper").lower()   # paper | testnet | live
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()  # gemini | mock
DATA_MODE = os.environ.get("DATA_MODE", "live").lower()          # live | mock (tests offline)

# Secretos
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
# Distinto al del webhook: ese viaja en cada alerta de TradingView y queda en su bitácora
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
# Solo acepta webhooks desde las 4 IPs publicadas por TradingView
TV_IP_ALLOWLIST = _b("TV_IP_ALLOWLIST", "true")
TV_IPS = {"52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7"}
# Minutos máximos entre el cierre de la vela 4H y la llegada del webhook (rechaza replays)
SIGNAL_MAX_AGE_MIN = int(os.environ.get("SIGNAL_MAX_AGE_MIN", "30"))
# Qué entrada de X-Forwarded-For es la IP real (-1 = la que agrega el proxy de Render al final)
TV_XFF_INDEX = int(os.environ.get("TV_XFF_INDEX", "-1"))
RULES_ONLY_FALLBACK = _b("RULES_ONLY_FALLBACK", "true")
# Techo de capital que el bot puede usar aunque la cuenta tenga más USDT (0 = sin techo)
MAX_BOT_CAPITAL = float(os.environ.get("MAX_BOT_CAPITAL", "0"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")  # cámbialo sin tocar código
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET = os.environ.get("BINANCE_SECRET", "")
CRYPTOPANIC_API_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///cryptoagent.db")  # Postgres en prod
SHEETS_WEBAPP_URL = os.environ.get("SHEETS_WEBAPP_URL", "")  # opcional, solo espejo

FEE_RATE = float(os.environ.get("FEE_RATE", "0.001"))  # 0.1% por lado (Binance spot sin descuento BNB)
SLIPPAGE = float(os.environ.get("SLIPPAGE", "0.0005"))  # 0.05% estimado en la compra a mercado y en el stop

# Modelo de contexto (v4.2): calendario, eventos, on-chain. Ver docs/MODELO_CONTEXTO.md
CONTEXT_ENABLED = _b("CONTEXT_ENABLED", "true")
CONTEXT_ONCHAIN_LIVE = _b("CONTEXT_ONCHAIN_LIVE", "false")  # vigía on-chain también dentro del servidor (cada 5 min)
# Una alerta CRÍTICA (se gastan monedas de la era Satoshi) vende todo a USDT y activa el kill switch (reanudar a mano)
CONTEXT_EXIT_ON_CRITICAL = _b("CONTEXT_EXIT_ON_CRITICAL", "true")

# Universo
ALLOWED_PAIRS = [p.strip().upper() for p in os.environ.get("ALLOWED_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")]
PROTECTED_ASSETS = {"BNB"}  # nunca se compra ni se vende

# Riesgo (de Crypto_Trading_Master_Methodology_v1)
RISK = {
    "risk_per_trade": min(0.005, float(os.environ.get("RISK_PER_TRADE", "0.005"))),  # 0.5% del equity: TECHO inmutable
    "max_open_risk": 0.05,           # checklist #7
    "max_position_notional": 0.25,   # ningún trade > 25% del equity en nocional
    # BTC/ETH/SOL se mueven juntos (correlación alta): 3 posiciones = casi la misma apuesta x3
    "max_open_positions": int(os.environ.get("MAX_OPEN_POSITIONS", "2")),
    "max_correlated_risk": 0.015,    # riesgo abierto total en majors
    "stop_gap_market_exit": True,    # si el precio perfora el límite del stop sin llenarse → venta a mercado
    "daily_dd_kill": -0.03,
    "weekly_dd_kill": -0.05,
    "min_confluence": 5,             # checklist #3
    "min_rr": 2.0,                   # checklist #4 (bruto)
    # v4.2 — "solo entrar si hay X% de ganancia": el objetivo YA restando comisiones y slippage de ida y vuelta
    "min_net_gain_pct": float(os.environ.get("MIN_NET_GAIN_PCT", "0.015")),   # objetivo neto >= 1.5%
    "min_net_rr": float(os.environ.get("MIN_NET_RR", "1.8")),                 # ganancia neta / pérdida neta
    "max_consecutive_losses": 5,     # inmutable (CLAUDE.md): 5 pérdidas seguidas → no más compras hasta reset manual
    "min_judge_confidence": 65,
    "min_votes_long": 3,             # de 5 analistas
    "max_entry_drift_atr": 0.5,      # señal vieja si el precio se movió > 0.5 ATR
    "macro_blackout_hours": 4,       # checklist #8
    "min_notional_usdt": 10.0,
}
