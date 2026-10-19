"""Parámetros del agente FX. Los marcados [PROPUESTA — calibrar] vienen del corpus FX (F14-016, F15-017) y se
validan en el backtest; los límites duros (HARD) no se relajan en código ni por el supervisor LLM."""
from __future__ import annotations

import os
from dataclasses import dataclass

# ── Universo ────────────────────────────────────────────────────────────────────────────────────────────────────
# usd_sign: +1 si comprar el par = comprar USD (USD base), −1 si comprar el par = vender USD.
# point: escala de precio de Dukascopy (entero × point = precio). pip: pip convencional (OANDA pipLocation).
# rng: rango plausible de precio para validar la escala al descargar.


@dataclass(frozen=True)
class Pair:
    sym: str          # Dukascopy
    oanda: str        # OANDA v20
    pip: float
    point: float
    usd_sign: int
    rng: tuple[float, float]
    em: bool = False
    # Costo extra estimado de OANDA sobre el spread de Dukascopy, por operación redonda, en pips [estimado —
    # se recalibra con los fills de práctica (F15-017 B)]. Más deslizamiento por lado.
    oanda_markup_pips: float = 0.9
    slip_pips: float = 0.2


PAIRS: dict[str, Pair] = {
    "EURUSD": Pair("EURUSD", "EUR_USD", 1e-4, 1e-5, -1, (0.80, 1.80)),
    "GBPUSD": Pair("GBPUSD", "GBP_USD", 1e-4, 1e-5, -1, (0.95, 2.30), oanda_markup_pips=1.2),
    "USDJPY": Pair("USDJPY", "USD_JPY", 1e-2, 1e-3, +1, (60.0, 220.0)),
    "USDCHF": Pair("USDCHF", "USD_CHF", 1e-4, 1e-5, +1, (0.55, 1.40), oanda_markup_pips=1.2),
    "USDMXN": Pair("USDMXN", "USD_MXN", 1e-4, 1e-5, +1, (9.0, 32.0), em=True, oanda_markup_pips=40.0,
                   slip_pips=5.0),
}
DATA_START_YEAR = 2015

# ── Slots de anuncios (hora local de quien publica; el horario de verano lo resuelve zoneinfo) ─────────────────────
# El agente NO necesita conocer el consenso: detecta la sorpresa por la reacción del precio (z de los primeros
# 15 min frente a la escala típica de ese minuto) y apuesta al drift posterior (Almeida et al. 1998; F14-016).
# pairs=None → todos. Cada slot se valida fuera de muestra; los que no muestren ventaja quedan inactivos.


@dataclass(frozen=True)
class Slot:
    name: str
    tz: str
    hhmm: str
    pairs: tuple[str, ...] | None = None
    note: str = ""


SLOTS: tuple[Slot, ...] = (
    Slot("US_0830", "America/New_York", "08:30", note="NFP, IPC, ventas minoristas, PIB, solicitudes de desempleo"),
    Slot("US_1000", "America/New_York", "10:00", note="ISM, JOLTS, confianza del consumidor"),
    Slot("US_1400", "America/New_York", "14:00", note="FOMC (decisión y minutas)"),
    Slot("UK_1200", "Europe/London", "12:00", ("GBPUSD", "EURUSD"), note="Banco de Inglaterra"),
    Slot("MX_1300", "America/Mexico_City", "13:00", ("USDMXN",), note="Banxico"),
)

# Nadie cruza otro slot mayor con la posición abierta (regla conocida de antemano, F14-016 "Exclusiones"): la
# posición sale 5 min antes del T0 de los slots listados (calculado ese día, con el horario de verano real), y si eso
# deja menos de MIN_HOLD_MIN no se entra. Además no se entra a ±5 min del T0 de otro slot del mismo par.
# El BCE (14:15 CET) quedó fuera ANTES de ver datos: su T+15 cae justo en las 8:30 NY de los datos de EE. UU.
SLOT_EXIT_BEFORE = {"UK_1200": ("US_0830",), "US_0830": ("US_1400",), "US_1000": ("US_1400",)}
MIN_HOLD_MIN = 10

# ── Estrategia A (F14-016) — rejilla pequeña y declarada para DSR/PBO ─────────────────────────────────────────────
ENTRY_LAG_MIN = 15                 # señal = signo de la reacción T0→T+15; entrada en T+15 (ventana T+5..T+20)
Z_GRID = (2.0, 3.0)                # |z| mínimo
HOLD_GRID = (60, 120, 360)         # minutos (T+6 h del corpus, recortado por blackouts)
SCALE_WINDOW_DAYS = 250            # escala robusta del slot: últimos ~250 días hábiles, solo pasado
MIN_SCALE_OBS = 120
STOP_SIGMA = 1.5                   # stop = 1.5 × vol esperada del horizonte (F14-016)
SPREAD_MAX_X = 1.5                 # no entrar si spread > 1.5 × típico de ese minuto (F14-016, F15-017 C)
EB_P_MIN = 0.80                    # P(ventaja neta > 0) a posteriori para activar un (par, slot)
EB_MIN_N = 12                      # eventos mínimos por (par, slot) en entrenamiento
WF_FIRST_TEST_YEAR = 2018          # walk-forward anual expansivo: entrena ≤ Y−1, opera Y
COST_STRESS = 2.0                  # prueba de estrés: costos × 2 (F14-016)

# ── Blackouts (F15-017 C) — hora de Nueva York salvo que se diga ──────────────────────────────────────────────────
LONDON_FIX = ("Europe/London", "16:00", 2.5)    # ±2.5 min
ROLLOVER_NY = ("16:55", "17:10")
FORCE_EXIT_NY = "16:50"            # nadie cruza el rollover (spread y financiamiento)
FRIDAY_CUTOFF_NY = "15:55"         # viernes: todo plano antes de 16:00 NY y sin entradas después
WEEK_OPEN_NY = ("Sun", "17:00")
YEAR_END_BLACKOUT = ((12, 24), (1, 2))
EVENT_GUARD_MIN = 5                # T−5/T+5 de eventos mayores conocidos (calendario en vivo)


# ── Riesgo ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Risk:
    risk_per_event: float = 0.0035      # 0.35% del capital si salta el stop, repartido entre pares del mismo evento
    weekly_loss_cap: float = 0.015      # gobernador semanal: −1.5% → todo plano hasta el domingo 17:00 NY
    daily_loss_cap: float = 0.010       # −1% en el día → pausa hasta el día siguiente
    loss_streak_pause: int = 3          # 3 pérdidas seguidas → pausa 24 h (R1–R8)
    dd_yellow: float = 0.05             # 1×σ* (σ* 5% anual): tamaño a la mitad
    dd_red: float = 0.10                # 2×σ*: apagado total hasta revisión humana
    max_leverage: float = 5.0           # apalancamiento bruto ≤ 5× (F14-017, R1)
    max_positions: int = 4
    one_per_pair: bool = True
    max_net_usd_x: float = 3.0          # |USD neto| ≤ 3× capital
    budget_safety: float = 0.9          # cada operación arriesga ≤ 90% de lo que queda del tope semanal/diario


# Techos inmutables: si alguien sube un parámetro por encima de esto, el arranque falla.
HARD = {"risk_per_event": 0.005, "weekly_loss_cap": 0.015, "daily_loss_cap": 0.02, "dd_red": 0.10,
        "max_leverage": 5.0, "loss_streak_pause": 3}


def check_risk(r: Risk) -> Risk:
    if r.risk_per_event > HARD["risk_per_event"]:
        raise ValueError("risk_per_event por encima del techo inmutable")
    if r.weekly_loss_cap > HARD["weekly_loss_cap"] or r.daily_loss_cap > HARD["daily_loss_cap"]:
        raise ValueError("tope de pérdida por encima del techo inmutable")
    if r.dd_red > HARD["dd_red"] or r.max_leverage > HARD["max_leverage"]:
        raise ValueError("drawdown o apalancamiento por encima del techo inmutable")
    if r.loss_streak_pause > HARD["loss_streak_pause"]:
        raise ValueError("racha de pérdidas por encima del techo inmutable")
    return r


RISK = check_risk(Risk())

# ── Modo y endpoints ───────────────────────────────────────────────────────────────────────────────────────────────
OANDA_HOSTS = {
    "practice": ("https://api-fxpractice.oanda.com", "https://stream-fxpractice.oanda.com"),
    "live": ("https://api-fxtrade.oanda.com", "https://stream-fxtrade.oanda.com"),
}
LIVE_CONFIRM = "SI-ENTIENDO-EL-RIESGO"
# IPs de origen de las alertas de TradingView (soporte de TradingView; verificar si cambian).
TRADINGVIEW_IPS = ("52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7")


def mode() -> str:
    """paper (defecto) | practice | live. live exige doble confirmación humana en el entorno."""
    m = os.environ.get("FX_MODE", "paper").strip().lower()
    if m not in ("paper", "practice", "live", "backtest"):
        raise ValueError(f"FX_MODE inválido: {m}")
    if m == "live" and os.environ.get("FX_LIVE_CONFIRM") != LIVE_CONFIRM:
        raise RuntimeError("FX_MODE=live sin FX_LIVE_CONFIRM: se niega a operar dinero real")
    return m


DATA_DIR = os.environ.get("FX_DATA_DIR", "data/fx")
CACHE_DIR = os.environ.get("FX_CACHE_DIR", ".cache/fx")
