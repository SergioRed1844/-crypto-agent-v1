"""Configuración del Radar EB (agente 2: solo alertas, NUNCA opera).

Todo lo que es juicio (umbrales, costos, metas) vive aquí y se puede sobrescribir por variable de entorno.
Los costos son ESTIMACIONES (comisión + deslizamiento, ida y vuelta) y así se etiquetan en las fichas.
"""
import os

# ── Universo ────────────────────────────────────────────────────────────────────────────────────────────
# BNB y BNB* quedan fuera por la misma regla dura del bot de trading (protected_assets).
CRYPTO = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "LTC", "TRX", "BCH"]
US = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "SMH", "GLD",
      "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM", "WMT"]
BMV = ["NAFTRACISHRS.MX", "WALMEX.MX", "GFNORTEO.MX", "AMXB.MX", "FEMSAUBD.MX", "GMEXICOB.MX", "CEMEXCPO.MX",
       "BIMBOA.MX", "GAPB.MX", "ASURB.MX", "OMAB.MX", "KOFUBL.MX", "AC.MX", "ORBIA.MX", "PINFRA.MX",
       "ALSEA.MX", "LIVEPOLC-1.MX", "BBAJIOO.MX", "GRUMAB.MX", "KIMBERA.MX"]
PROTECTED = ("BNB",)

BENCH = {"crypto": "BTC", "us": "SPY", "bmv": "^MXX"}     # el "mercado" de cada clase
AUX = ["^MXX", "^VIX", "MXN=X"]                           # series de contexto (no son candidatos)
# índices/ETFs amplios: umbrales de caída más chicos que para una acción suelta
BROAD = {"SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "SMH", "GLD",
         "NAFTRACISHRS.MX", "^MXX"}


def asset_class(sym: str) -> str:
    if sym in CRYPTO or sym == "BTC":
        return "crypto"
    if sym.endswith(".MX") or sym == "^MXX":
        return "bmv"
    return "us"


def universe() -> list[str]:
    syms = CRYPTO + US + BMV
    return [s for s in syms if not s.upper().startswith(PROTECTED)]


# ── Costos de ida y vuelta (estimación) ─────────────────────────────────────────────────────────────────
COST_RT = {"crypto": 0.003, "us": 0.002, "bmv": 0.006}   # BMV: comisión de casa de bolsa + IVA + spread

# ── Horizontes y metas ──────────────────────────────────────────────────────────────────────────────────
HORIZONS = (7, 30, 90)                                  # días naturales
TARGET = {7: 0.015, 30: 0.03, 90: 0.05}                 # éxito = ganancia NETA ≥ meta al cierre del horizonte
MAE_LIMIT = {"crypto": -0.15, "us": -0.10, "bmv": -0.10}  # "riesgo de caída": peor punto durante la tenencia
ENTRY_LAGS = (1, 2, 3, 5, 8)                            # día de entrada después del disparador (1 = siguiente)
SPLIT_DATE = os.getenv("RADAR_SPLIT_DATE", "2022-01-01")  # entrenamiento < fecha ≤ prueba fuera de muestra


def bars_for(h_days: int, cls: str) -> int:
    """Días naturales → barras. Cripto opera 7 días; bolsa ~5 de cada 7."""
    return h_days if cls == "crypto" else max(1, round(h_days * 5 / 7))


# ── Umbral de alerta ("Selectivo") ──────────────────────────────────────────────────────────────────────
def _f(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


ALERT = {
    "p_min": _f("RADAR_P_MIN", 0.65),          # probabilidad encogida de ganar ≥ meta neta
    "q10_min": _f("RADAR_Q10_MIN", 0.55),      # cota baja (percentil 10 de la posterior)
    "lift_min": _f("RADAR_LIFT_MIN", 0.05),    # mejor que comprar un día cualquiera de ese activo
    "ret_min": _f("RADAR_RET_MIN", 0.03),      # rendimiento neto esperado encogido
    "neff_min": int(_f("RADAR_NEFF_MIN", 8)),  # episodios independientes mínimos del setup en la clase
    "max_week": int(_f("RADAR_MAX_WEEK", 3)),  # tope de alertas sueltas por semana (rodante 7 días)
    "caution_extra": _f("RADAR_CAUTION_EXTRA", 0.05),  # contexto v4.2 en CAUTION → +5 pp de exigencia
    "cooldown_days": int(_f("RADAR_ALERT_COOLDOWN", 7)),  # misma (activo, setup) no se repite antes
}

STALE_DAYS = {"crypto": 3, "us": 5, "bmv": 5}           # último dato más viejo → sin alerta

# ── Fuentes externas (sin llaves) ───────────────────────────────────────────────────────────────────────
REPO = os.getenv("GITHUB_REPOSITORY", "SergioRed1844/-crypto-agent-v1")
CONTEXT_BRANCH = os.getenv("RADAR_CONTEXT_BRANCH", "v4.2-contexto")
CONTEXT_RAW = os.getenv("RADAR_CONTEXT_RAW",
                        f"https://raw.githubusercontent.com/{REPO}/{CONTEXT_BRANCH}/data/context/context_signal.json")
CACHE_DIR = os.getenv("RADAR_CACHE", ".cache/radar")
OUT_DIR = os.getenv("RADAR_OUT", "data/radar")
TZ_LOCAL = os.getenv("RADAR_TZ", "America/Mexico_City")
DIGEST_HOUR_LOCAL = int(_f("RADAR_DIGEST_HOUR", 8))     # resumen diario "sigo vivo" a esta hora local

# Wikipedia (atención y miedo de hogares; proxy de Google Trends/FEARS, ver C08-012 y C12-008)
WIKI_ATTENTION = {"BTC": ("en", "Bitcoin"), "ETH": ("en", "Ethereum"), "SOL": ("en", "Solana_(blockchain_platform)"),
                  "XRP": ("en", "Ripple_Labs"), "DOGE": ("en", "Dogecoin"), "_CRYPTO": ("en", "Cryptocurrency")}
FEARS_TERMS = {
    "en": ["Recession", "Stock_market_crash", "Inflation", "Unemployment", "Bankruptcy", "Financial_crisis"],
    "es": ["Recesión", "Crisis_económica", "Inflación", "Devaluación", "Desempleo"],
}
