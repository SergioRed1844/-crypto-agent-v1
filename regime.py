"""
regime.py — dynamic posture engine (Phase 4). See the risk-regime-engine skill.

On every signal the agent picks a POSTURE from the live market_context and (optionally) the
incoming signal, then resolves the per-signal risk thresholds. The posture may only move
parameters INSIDE the immutable hard limits — never outside.

  Regime         Posture        risk/trade   min confluence   min R:R
  HEALTHY TREND  AGGRESSIVE      0.75%*       5                2.0
  NEUTRAL        STANDARD        0.5%         (learned)        (learned, >=2.0)
  EUPHORIA       CONSERVATIVE    0.25%        8                3.0
  PANIC/CHAOS    DEFENSIVE       0% new trades (manage open only)

  * AGGRESSIVE's 0.75% is a TARGET; the immutable 0.5% ceiling always wins (see HARD_LIMITS).

This module is pure (no I/O, no server import) so it is fully unit-testable.
"""
from types import MappingProxyType

# ── IMMUTABLE HARD LIMITS — no posture, and no learning, may ever relax these ──
# Exposed as a read-only mapping so an accidental write raises instead of silently passing.
HARD_LIMITS = MappingProxyType({
    "daily_drawdown_kill": -0.03,        # −3% day → kill switch
    "weekly_drawdown_kill": -0.05,       # −5% week → kill switch
    "max_total_exposure": 0.05,          # ≤5% total capital-at-risk
    "max_risk_per_trade_ceiling": 0.005,  # ≤0.5% per trade, absolute ceiling
    "max_consecutive_losses": 5,         # 5 losses in a row → stand down
    "max_positions_per_pair": 1,         # one position per pair
    "protected_assets": ("BNB", "BNBUSDT", "BNBBUSD"),  # permanently blocked
})

# Posture targets. STANDARD intentionally defers selectivity to the LEARNED params (the
# self-learning loop tunes the neutral baseline); the other postures use fixed table values.
POSTURES = {
    "AGGRESSIVE":   {"risk_per_trade": 0.0075, "min_confluence": 5, "min_rr": 2.0,
                     "min_confidence": 60, "no_new_trades": False},
    "STANDARD":     {"risk_per_trade": 0.005,  "min_confluence": None, "min_rr": None,
                     "min_confidence": None, "no_new_trades": False},
    "CONSERVATIVE": {"risk_per_trade": 0.0025, "min_confluence": 8, "min_rr": 3.0,
                     "min_confidence": 75, "no_new_trades": False},
    "DEFENSIVE":    {"risk_per_trade": 0.0,    "min_confluence": 9, "min_rr": 3.0,
                     "min_confidence": 90, "no_new_trades": True},
}

# Thresholds for regime detection (documented so they can be tuned in one place).
EUPHORIA_FG = 75
EUPHORIA_FUNDING = 0.0005      # |funding| at/above this = extreme leverage
EUPHORIA_24H = 8.0            # % move in 24h that signals a chase
PANIC_24H = 12.0             # % move in 24h that signals chaos/extreme vol
PANIC_NEWS = -0.5            # news sentiment at/below this = very bearish
HEALTHY_FG_LO, HEALTHY_FG_HI = 25, 60
HEALTHY_FUNDING = 0.0002     # |funding| at/below this = neutral


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def select_posture(market_ctx: dict, signal: dict = None) -> tuple:
    """Return (posture_name, reason). Most-defensive regimes are tested first."""
    mc = market_ctx or {}
    sig = signal or {}
    fg = mc.get("fear_greed", 50)
    funding = mc.get("btc_funding", 0) or 0
    chg = abs(mc.get("btc_24h_change", 0) or 0)
    news = mc.get("news_score", None)
    vol = str(sig.get("volatility") or sig.get("vol_regime") or "").upper()
    trend = str(sig.get("trend") or sig.get("trend_regime") or sig.get("regime") or "").upper()

    # 1) PANIC / CHAOS → DEFENSIVE
    if mc.get("solo_observation") or vol == "EXTREME" or (news is not None and news <= PANIC_NEWS) or chg >= PANIC_24H:
        return "DEFENSIVE", (f"panic/chaos (solo_obs={bool(mc.get('solo_observation'))}, "
                             f"vol={vol or 'n/a'}, news={news}, 24h={chg:.1f}%)")
    # 2) EUPHORIA → CONSERVATIVE
    if fg > EUPHORIA_FG or abs(funding) >= EUPHORIA_FUNDING or chg >= EUPHORIA_24H:
        return "CONSERVATIVE", (f"euphoria (F&G={fg}, funding={funding:.5f}, 24h={chg:.1f}%)")
    # 3) HEALTHY TREND → AGGRESSIVE (requires evidence of a strong uptrend)
    strong_up = trend in ("STRONG_UP", "GREEN", "WEAK_UP") or trend.startswith("UP")
    if (HEALTHY_FG_LO <= fg <= HEALTHY_FG_HI and abs(funding) <= HEALTHY_FUNDING
            and chg <= 6.0 and strong_up):
        return "AGGRESSIVE", (f"healthy trend (F&G={fg}, funding={funding:.5f}, trend={trend})")
    # 4) NEUTRAL → STANDARD
    return "STANDARD", (f"neutral/mixed (F&G={fg}, funding={funding:.5f}, trend={trend or 'n/a'})")


def resolve_params(posture: str, base: dict, floors: dict) -> dict:
    """
    Produce the effective per-signal risk params for `posture`, starting from the LEARNED base
    params and clamping every value to the immutable floors/ceiling. Drop-in compatible with the
    keys validate_trade reads from RISK_PARAMS, plus `posture` and `no_new_trades`.
    """
    p = POSTURES[posture]
    # STANDARD uses the learned baseline; other postures use their fixed table values.
    confl = base["min_confluence"] if p["min_confluence"] is None else p["min_confluence"]
    conf = base["min_confidence"] if p["min_confidence"] is None else p["min_confidence"]
    rr = base["min_rr"] if p["min_rr"] is None else p["min_rr"]

    # Risk per trade: target, but never above the learned risk nor the absolute 0.5% ceiling.
    risk = min(p["risk_per_trade"], base["max_risk_per_trade"], HARD_LIMITS["max_risk_per_trade_ceiling"])

    eff = dict(base)  # carry over immutable + non-posture params unchanged
    eff.update({
        "posture": posture,
        "no_new_trades": p["no_new_trades"],
        "max_risk_per_trade": 0.0 if p["no_new_trades"] else risk,
        "min_confluence": _clamp(confl, floors["min_confluence_floor"], floors["min_confluence_ceil"]),
        "min_confidence": _clamp(conf, floors["min_confidence_floor"], floors["min_confidence_ceil"]),
        "min_rr": _clamp(rr, floors["min_rr_floor"], floors["min_rr_ceil"]),
        # Immutable safety values are forced to the hard limits regardless of `base`.
        "max_total_exposure": HARD_LIMITS["max_total_exposure"],
        "daily_drawdown_kill": HARD_LIMITS["daily_drawdown_kill"],
        "weekly_drawdown_kill": HARD_LIMITS["weekly_drawdown_kill"],
    })
    return eff
