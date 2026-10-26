"""Parámetros fijados en el pre-registro del 26-oct-2026 (docs/REBOTES.md). No se ajustan con los datos."""
START = "2005-01-01"
TEST_START = "2019-01-01"
EXTRA = ["SPCE", "RKLB", "SPCX", "ZS", "META", "CRWD", "SPY"]

MIN_PRICE = 3.0
MIN_DOLLAR_VOL = 5e6          # mediana 20 días
MIN_BARS = 260

HOLD = 21                     # velas desde la entrada
TP = 0.30
SL = -0.15
COST_SIDE = 0.0039            # 0.29% GBM (0.25% + IVA) + 0.10% deslizamiento

SETUPS = {
    "CAIDA_GIRO": {"dd": -0.50, "breakout": 20, "cooldown": 60},
    "CAPITULACION": {"r10": -0.25, "vol_mult": 3.0, "cooldown": 30},
    "CATALIZADOR": {"r1": 0.15, "vol_mult": 5.0, "dd_prev": -0.40, "cooldown": 30},
}
BASE_EVERY = 10               # placebo: 1 de cada 10 días elegibles

CAPITAL = 50_000.0
MAX_POS = 5
PLACEBO_REPS = 200
