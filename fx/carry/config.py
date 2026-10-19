"""Universo y reglas de la Estrategia B, tal como quedaron pre-registradas el 19-oct-2026."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ccy:
    code: str
    sym: str            # Dukascopy
    oanda: str
    inv: bool           # True si el par es USDXXX (subir el par = bajar la moneda)
    point: float
    rng: tuple[float, float]
    cost_bp: float      # sobreprecio OANDA estimado por lado, en puntos base del nocional
    em: bool
    bis: str
    oecd: str


UNIVERSE: tuple[Ccy, ...] = (
    Ccy("EUR", "EURUSD", "EUR_USD", False, 1e-5, (0.8, 1.8), 0.5, False, "XM", "EZ"),
    Ccy("JPY", "USDJPY", "USD_JPY", True, 1e-3, (60, 220), 0.5, False, "JP", "JP"),
    Ccy("GBP", "GBPUSD", "GBP_USD", False, 1e-5, (0.95, 2.3), 0.5, False, "GB", "GB"),
    Ccy("CHF", "USDCHF", "USD_CHF", True, 1e-5, (0.55, 1.4), 0.5, False, "CH", "CH"),
    Ccy("AUD", "AUDUSD", "AUD_USD", False, 1e-5, (0.5, 1.15), 0.8, False, "AU", "AU"),
    Ccy("NZD", "NZDUSD", "NZD_USD", False, 1e-5, (0.45, 1.0), 0.8, False, "NZ", "NZ"),
    Ccy("CAD", "USDCAD", "USD_CAD", True, 1e-5, (0.9, 1.6), 0.8, False, "CA", "CA"),
    Ccy("NOK", "USDNOK", "USD_NOK", True, 1e-5, (5.0, 13.5), 2.0, False, "NO", "NO"),
    Ccy("SEK", "USDSEK", "USD_SEK", True, 1e-5, (5.5, 13.5), 2.0, False, "SE", "SE"),
    Ccy("MXN", "USDMXN", "USD_MXN", True, 1e-5, (9.0, 32.0), 3.0, True, "MX", "MX"),
    Ccy("ZAR", "USDZAR", "USD_ZAR", True, 1e-5, (8.0, 25.0), 3.0, True, "ZA", "ZA"),
    Ccy("PLN", "USDPLN", "USD_PLN", True, 1e-5, (2.8, 5.5), 3.0, True, "PL", "PL"),
    Ccy("HUF", "USDHUF", "USD_HUF", True, 1e-3, (180.0, 480.0), 3.0, True, "HU", "HU"),
)
BY_CODE = {c.code: c for c in UNIVERSE}
START_YEAR = 2015
EVAL_START = "2016-01-01"

# Señales
MOM_XS = (252, 21)            # MOM2-12: de t−252 a t−21 días hábiles
MOM_TS = (63, 126, 252)
EWMA_LAMBDA = 0.97
VIX_P = (0.80, 0.95)          # carry × 0.5 / × 0
CARRY_CRASH_SIGMA = 2.0

# Tamaño y límites
SIGMA_TARGET = 0.04
MAX_GROSS = 5.0
MAX_PER_CCY = 1.0
MAX_NET_USD = 3.0
BAND_REL, BAND_ABS, MIN_POS = 0.20, 0.10, 0.02
EM_FRIDAY_CUT = 0.25
WEEKLY_CAP, DAILY_CAP = 0.015, 0.01
DD_YELLOW, DD_RED = 0.04, 0.08

# Calendario (hora de Nueva York)
REBAL_DOW, REBAL_HOUR = 0, 10        # lunes 10:00 NY (open de la vela de las 10)
SIGNAL_HOUR = 9                      # datos hasta la vela que cierra a las 10:00 NY
FRIDAY_CUT_HOUR = 15
DAILY_CLOSE_HOUR = 17

# Costos
FIN_MARKUP = 0.010                   # recargo anual estimado de OANDA sobre el nocional [verificar]
COST_STRESS = 2.0
