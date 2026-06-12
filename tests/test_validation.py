"""
Phase 2 — the Graham decision gate (validate_trade + the 6-point anti-bias checklist).
Synthetic decisions that MUST approve or MUST reject. validate_trade is called with
signal=market_ctx=None to isolate the core gates from network-dependent stale/Mr.Market checks.
"""
import pytest
import server


def _full_bias(all_pass=True):
    return {k: {"pass": all_pass, "reason": "" if all_pass else "biased"}
            for k in server.BIAS_KEYS}


def make_decision(**overrides):
    """A baseline decision that should PASS every hard rule; override to break one."""
    d = {
        "action": "BUY", "pair": "BTCUSDT", "direction": "LONG", "bucket": "CORE",
        "template": "T1_PULLBACK", "entry_price": 100.0, "stop_loss": 98.0,
        "take_profit_1": 105.0, "take_profit_2": 110.0, "position_size_pct": 0.5,
        "confidence": 80, "confluence_score": 7, "regime_btc": "GREEN",
        "checklist_pass": True, "edge_description": "pullback to value in uptrend",
        "reasoning": "confluence + intact structure", "risks": [],
        "posture_used": "STANDARD", "rr_pesimista": 2.5,
        "bear_case": "trend could be exhausted; loss of 20-week MA invalidates",
        "bias_check": _full_bias(True),
    }
    d.update(overrides)
    return d


@pytest.fixture(autouse=True)
def clean_state():
    """Isolate the module globals validate_trade reads."""
    server.open_positions = []
    server.daily_pnl = 0.0
    server.weekly_pnl = 0.0
    yield


# ── decisions that MUST be approved ──────────────────────────────────────────
def test_clean_setup_approved():
    ok, msg = server.validate_trade(make_decision())
    assert ok, msg


def test_rr_pesimista_zero_is_skipped_not_fatal():
    # If the model omits rr_pesimista (0), we fall back to the entry/sl/tp R:R check only.
    ok, msg = server.validate_trade(make_decision(rr_pesimista=0))
    assert ok, msg


# ── decisions that MUST be rejected ──────────────────────────────────────────
def test_bnb_blocked():
    ok, msg = server.validate_trade(make_decision(pair="BNBUSDT"))
    assert not ok and "protected" in msg


def test_no_trade_rejected():
    ok, _ = server.validate_trade(make_decision(action="NO_TRADE"))
    assert not ok


def test_short_sell_rejected_on_spot():
    assert not server.validate_trade(make_decision(action="SELL"))[0]
    assert not server.validate_trade(make_decision(direction="SHORT"))[0]


def test_checklist_must_pass():
    ok, msg = server.validate_trade(make_decision(checklist_pass=False))
    assert not ok and "Checklist" in msg


def test_bias_check_missing_forces_no_trade():
    ok, msg = server.validate_trade(make_decision(bias_check={}))
    assert not ok and "bias_check missing" in msg


def test_single_failing_bias_check_rejects():
    bc = _full_bias(True)
    bc["fomo_herd"] = {"pass": False, "reason": "euphoric news + +12% in 24h"}
    ok, msg = server.validate_trade(make_decision(bias_check=bc))
    assert not ok and "fomo_herd" in msg


def test_absent_single_bias_key_rejects():
    bc = _full_bias(True)
    del bc["anchoring"]
    ok, msg = server.validate_trade(make_decision(bias_check=bc))
    assert not ok and "anchoring:absent" in msg


def test_missing_bear_case_rejects():
    ok, msg = server.validate_trade(make_decision(bear_case=""))
    assert not ok and "bear_case" in msg


def test_low_confidence_rejected():
    ok, msg = server.validate_trade(make_decision(confidence=40))
    assert not ok and "Confidence" in msg


def test_low_confluence_rejected():
    ok, msg = server.validate_trade(make_decision(confluence_score=2))
    assert not ok and "Confluence" in msg


def test_zero_risk_stop_rejected():
    ok, msg = server.validate_trade(make_decision(stop_loss=100.0))
    assert not ok and "zero risk" in msg


def test_bad_rr_rejected():
    # tp1 too close: reward 1 vs risk 2 → R:R 0.5
    ok, msg = server.validate_trade(make_decision(take_profit_1=101.0))
    assert not ok and "R:R" in msg


def test_pessimistic_rr_below_min_rejected():
    ok, msg = server.validate_trade(make_decision(rr_pesimista=1.2))
    assert not ok and "Pessimistic R:R" in msg


# ── bias-check helpers ───────────────────────────────────────────────────────
def test_evaluate_bias_check_all_pass():
    ok, _ = server.evaluate_bias_check(make_decision())
    assert ok


def test_bias_item_pass_accepts_variants():
    assert server._bias_item_pass({"pass": True})[0] is True
    assert server._bias_item_pass({"aprobado": "sí"})[0] is True
    assert server._bias_item_pass(True)[0] is True
    assert server._bias_item_pass("pass")[0] is True
    assert server._bias_item_pass({"pass": False})[0] is False
    assert server._bias_item_pass("nope")[0] is False


def test_normalize_maps_spanish_bias_keys():
    raw = {"action": "COMPRAR",
           "bias_check": {"recencia": {"pass": True}, "anclaje": {"pass": True},
                          "manada": {"pass": True}}}
    norm = server.normalize_gemini(raw)
    assert norm["action"] == "BUY"
    assert "recency" in norm["bias_check"]
    assert "anchoring" in norm["bias_check"]
    assert "fomo_herd" in norm["bias_check"]
