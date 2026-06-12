"""
Phase 4 — the immutable hard limits as enforced inside server.py: DEFENSIVE blocks new trades,
max 1 position per pair, consecutive-loss kill switch, and that regime.HARD_LIMITS stays in sync
with server's RISK_FLOORS / RISK_PARAMS so the two never silently diverge.
"""
import pytest
import regime
import server


def _full_bias():
    return {k: {"pass": True, "reason": ""} for k in server.BIAS_KEYS}


def make_decision(**ov):
    d = {"action": "BUY", "pair": "BTCUSDT", "direction": "LONG", "bucket": "CORE",
         "entry_price": 100.0, "stop_loss": 98.0, "take_profit_1": 105.0, "confidence": 80,
         "confluence_score": 7, "checklist_pass": True, "rr_pesimista": 2.5,
         "bear_case": "trend exhaustion", "bias_check": _full_bias()}
    d.update(ov)
    return d


@pytest.fixture(autouse=True)
def clean_state():
    server.open_positions = []
    server.daily_pnl = 0.0
    server.weekly_pnl = 0.0
    server.consecutive_losses = 0
    yield
    server.open_positions = []
    server.consecutive_losses = 0


def test_defensive_params_block_any_buy():
    eff = regime.resolve_params("DEFENSIVE", server.RISK_PARAMS, server.RISK_FLOORS)
    ok, msg = server.validate_trade(make_decision(), params=eff)
    assert not ok and "DEFENSIVE" in msg


def test_conservative_confluence_8_rejects_confluence_7():
    eff = regime.resolve_params("CONSERVATIVE", server.RISK_PARAMS, server.RISK_FLOORS)
    ok, msg = server.validate_trade(make_decision(confluence_score=7), params=eff)
    assert not ok and "Confluence" in msg


def test_aggressive_allows_confluence_5():
    eff = regime.resolve_params("AGGRESSIVE", server.RISK_PARAMS, server.RISK_FLOORS)
    ok, msg = server.validate_trade(make_decision(confluence_score=5, confidence=70), params=eff)
    assert ok, msg


def test_max_one_position_per_pair():
    server.open_positions = [{"pair": "BTCUSDT", "qty": 0.01, "entry": 100, "sl": 98,
                              "equity_at_open": 10000}]
    ok, msg = server.validate_trade(make_decision())
    assert not ok and "max" in msg.lower()


def test_consecutive_losses_trip_kill_switch():
    server.consecutive_losses = regime.HARD_LIMITS["max_consecutive_losses"]
    killed, reason = server.check_kill_switches()
    assert killed and "consecutive losses" in reason


def test_four_losses_do_not_trip():
    server.consecutive_losses = 4
    killed, _ = server.check_kill_switches()
    assert not killed


# ── single-source-of-truth checks: regime ↔ server must agree ────────────────
def test_hard_limits_match_server_params():
    assert regime.HARD_LIMITS["max_total_exposure"] == server.RISK_PARAMS["max_total_exposure"]
    assert regime.HARD_LIMITS["daily_drawdown_kill"] == server.RISK_PARAMS["daily_drawdown_kill"]
    assert regime.HARD_LIMITS["weekly_drawdown_kill"] == server.RISK_PARAMS["weekly_drawdown_kill"]
    assert regime.HARD_LIMITS["max_risk_per_trade_ceiling"] == server.RISK_FLOORS["max_risk_per_trade_max"]
    assert list(regime.HARD_LIMITS["protected_assets"]) == server.RISK_PARAMS["protected_assets"]
