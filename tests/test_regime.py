"""
Phase 4 — posture selection + the immutable hard limits. regime.py is pure, so these are
deterministic. Floors mirror server.RISK_FLOORS (kept in sync by test_hard_limits).
"""
import regime

FLOORS = {
    "max_risk_per_trade_max": 0.005, "min_confidence_floor": 50, "min_confidence_ceil": 90,
    "min_confluence_floor": 3, "min_confluence_ceil": 9, "min_rr_floor": 1.5, "min_rr_ceil": 3.0,
    "sl_atr_mult_floor": 1.5, "sl_atr_mult_ceil": 3.5,
}
BASE = {
    "max_risk_per_trade": 0.005, "max_total_exposure": 0.05, "daily_drawdown_kill": -0.03,
    "weekly_drawdown_kill": -0.05, "min_confluence": 6, "min_confidence": 65, "min_rr": 2.0,
    "sl_atr_mult": 2.0, "atr_multiplier": 2.0, "satellite_min": 10, "satellite_max": 30,
    "protected_assets": ["BNB"], "max_entry_drift_pct": 0.005,
}


# ── select_posture ───────────────────────────────────────────────────────────
def test_healthy_trend_is_aggressive():
    mc = {"fear_greed": 45, "btc_funding": 0.0001, "btc_24h_change": 2.0, "news_score": 0.1}
    name, _ = regime.select_posture(mc, {"trend": "STRONG_UP"})
    assert name == "AGGRESSIVE"


def test_no_trend_evidence_falls_to_standard():
    # healthy numbers but no strong-up signal → not aggressive
    mc = {"fear_greed": 45, "btc_funding": 0.0001, "btc_24h_change": 2.0}
    name, _ = regime.select_posture(mc, {})
    assert name == "STANDARD"


def test_euphoria_is_conservative():
    assert regime.select_posture({"fear_greed": 82}, {"trend": "STRONG_UP"})[0] == "CONSERVATIVE"
    assert regime.select_posture({"fear_greed": 50, "btc_funding": 0.0009}, {})[0] == "CONSERVATIVE"
    assert regime.select_posture({"fear_greed": 50, "btc_24h_change": 9.0}, {})[0] == "CONSERVATIVE"


def test_panic_is_defensive():
    assert regime.select_posture({"solo_observation": True}, {})[0] == "DEFENSIVE"
    assert regime.select_posture({"fear_greed": 30, "news_score": -0.7}, {})[0] == "DEFENSIVE"
    assert regime.select_posture({"btc_24h_change": -15}, {})[0] == "DEFENSIVE"
    assert regime.select_posture({"fear_greed": 40}, {"volatility": "EXTREME"})[0] == "DEFENSIVE"


def test_defensive_precedence_over_euphoria():
    # extreme move down is panic even if funding looks hot
    mc = {"fear_greed": 80, "btc_24h_change": 20, "btc_funding": 0.001}
    assert regime.select_posture(mc, {})[0] == "DEFENSIVE"


# ── resolve_params: posture inside immutable limits ──────────────────────────
def test_aggressive_risk_capped_at_ceiling():
    eff = regime.resolve_params("AGGRESSIVE", BASE, FLOORS)
    # AGGRESSIVE *targets* 0.75% but the 0.5% ceiling wins
    assert eff["max_risk_per_trade"] == 0.005
    assert eff["min_confluence"] == 5 and eff["min_rr"] == 2.0


def test_conservative_tightens_and_lowers_risk():
    eff = regime.resolve_params("CONSERVATIVE", BASE, FLOORS)
    assert eff["max_risk_per_trade"] == 0.0025
    assert eff["min_confluence"] == 8 and eff["min_rr"] == 3.0 and eff["min_confidence"] == 75


def test_standard_uses_learned_base():
    base = dict(BASE, min_confluence=7, min_rr=2.5, min_confidence=70)
    eff = regime.resolve_params("STANDARD", base, FLOORS)
    assert eff["min_confluence"] == 7 and eff["min_rr"] == 2.5 and eff["min_confidence"] == 70


def test_defensive_blocks_new_trades():
    eff = regime.resolve_params("DEFENSIVE", BASE, FLOORS)
    assert eff["no_new_trades"] is True
    assert eff["max_risk_per_trade"] == 0.0


def test_every_posture_respects_floors_and_ceiling():
    for name in regime.POSTURES:
        eff = regime.resolve_params(name, BASE, FLOORS)
        assert eff["max_risk_per_trade"] <= regime.HARD_LIMITS["max_risk_per_trade_ceiling"]
        assert FLOORS["min_confluence_floor"] <= eff["min_confluence"] <= FLOORS["min_confluence_ceil"]
        assert FLOORS["min_rr_floor"] <= eff["min_rr"] <= FLOORS["min_rr_ceil"]
        # exposure + kill switches are forced to the immutable hard limits
        assert eff["max_total_exposure"] == regime.HARD_LIMITS["max_total_exposure"]
        assert eff["daily_drawdown_kill"] == regime.HARD_LIMITS["daily_drawdown_kill"]


def test_hard_limits_are_immutable():
    import pytest
    with pytest.raises(TypeError):
        regime.HARD_LIMITS["max_total_exposure"] = 0.99
