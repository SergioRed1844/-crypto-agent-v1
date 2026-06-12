"""
Phase 3 — market_context pure aggregation: cross-validation, composite score, F&G trend,
news sentiment, and the SOLO-OBSERVATION degradation rule. No network (we feed `assemble`
synthetic source dicts), so these are deterministic.
"""
import market_context as mc


def _all_sources():
    """A healthy full read of all six sources."""
    return {
        "coingecko": {"BTCUSDT": {"price": 65000, "change_24h": 1.2},
                      "ETHUSDT": {"price": 3500, "change_24h": 0.8},
                      "SOLUSDT": {"price": 150, "change_24h": 2.0}},
        "coinpaprika": {"BTCUSDT": {"price": 65100, "change_24h": 1.1},
                        "ETHUSDT": {"price": 3505, "change_24h": 0.7},
                        "SOLUSDT": {"price": 150.2, "change_24h": 1.9}},
        "binance": None,
        "fear_greed": {"value": 45, "label": "Fear", "series": [45, 44, 46, 43, 42, 40, 38, 39, 41, 50]},
        "cryptopanic": [{"votes": {"positive": 8, "negative": 2}}, {"votes": {"bullish": 3, "bearish": 1}}],
        "funding": 0.0001,
        "open_interest": 1.2e9,
        "global": {"btc_dominance": 52.3, "total_mcap_usd": 2.4e12},
    }


# ── cross-validation ─────────────────────────────────────────────────────────
def test_prices_agree_reliable():
    out = mc.cross_validate_prices({"BTCUSDT": {"coingecko": 65000, "coinpaprika": 65100, "binance": None}})
    assert out["BTCUSDT"]["reliable"] is True
    assert 64900 < out["BTCUSDT"]["consensus"] < 65200


def test_prices_disagree_unreliable():
    # 65000 vs 67000 ≈ 3% > 1% limit
    out = mc.cross_validate_prices({"BTCUSDT": {"coingecko": 65000, "coinpaprika": 67000, "binance": None}})
    assert out["BTCUSDT"]["reliable"] is False
    assert out["BTCUSDT"]["disagreement_pct"] > 1.0


def test_single_source_usable_but_flagged():
    out = mc.cross_validate_prices({"BTCUSDT": {"coingecko": 65000, "coinpaprika": None, "binance": None}})
    assert out["BTCUSDT"]["consensus"] == 65000
    assert out["BTCUSDT"]["reliable"] is True  # usable, just not cross-validated


# ── composite score ──────────────────────────────────────────────────────────
def test_composite_in_range_and_signed():
    # extreme greed + hot funding + bullish news + big pump → strongly positive
    hot = mc.composite_score(fear_greed=90, funding=0.001, news_score=0.9, btc_24h_change=15)
    assert 0 < hot <= 100
    # extreme fear + negative funding + bearish news + dump → strongly negative
    cold = mc.composite_score(fear_greed=10, funding=-0.001, news_score=-0.9, btc_24h_change=-15)
    assert -100 <= cold < 0
    # neutral
    assert abs(mc.composite_score(50, 0.0, 0.0, 0.0)) < 1


def test_composite_handles_missing_components():
    # only F&G available → still bounded, driven by it
    s = mc.composite_score(fear_greed=80, funding=None, news_score=None, btc_24h_change=None)
    assert 0 < s <= 100


# ── F&G trend & news ─────────────────────────────────────────────────────────
def test_fear_greed_trend():
    assert mc.fear_greed_trend([60, 58, 57, 55, 54, 40, 39, 38, 37, 36]) == "RISING"
    assert mc.fear_greed_trend([30, 32, 33, 35, 36, 55, 56, 57, 58, 59]) == "FALLING"
    assert mc.fear_greed_trend([50, 50, 49, 51, 50, 50, 49, 51, 50, 50]) == "FLAT"


def test_news_sentiment():
    score, n = mc.news_sentiment([{"votes": {"positive": 9, "negative": 1}}])
    assert score == 0.8 and n == 1
    assert mc.news_sentiment(None) == (None, 0)


# ── assemble + SOLO-OBSERVATION ──────────────────────────────────────────────
def test_assemble_healthy_not_solo():
    ctx = mc.assemble(_all_sources(), pair="BTCUSDT")
    assert ctx["solo_observation"] is False
    assert ctx["btc_price"] > 0
    assert ctx["price_reliable"]["BTCUSDT"] is True
    assert -100 <= ctx["composite_score"] <= 100
    assert ctx["fear_greed_trend"] in ("RISING", "FALLING", "FLAT", "UNKNOWN")
    assert all(ctx["sources_ok"].values())


def test_two_critical_sources_down_triggers_solo():
    s = _all_sources()
    s["coingecko"] = None      # critical 1
    s["fear_greed"] = None     # critical 2
    ctx = mc.assemble(s, pair="BTCUSDT")
    assert ctx["solo_observation"] is True
    assert "coingecko" in ctx["critical_down"] and "fear_greed" in ctx["critical_down"]


def test_one_critical_source_down_not_solo():
    s = _all_sources()
    s["coinpaprika"] = None    # only one critical down → still operate (degraded)
    ctx = mc.assemble(s, pair="BTCUSDT")
    assert ctx["solo_observation"] is False


def test_price_disagreement_flags_pair_unreliable():
    s = _all_sources()
    s["coinpaprika"]["BTCUSDT"]["price"] = 70000  # ~7.5% off CoinGecko's 65000
    ctx = mc.assemble(s, pair="BTCUSDT")
    assert ctx["price_reliable"]["BTCUSDT"] is False
    assert ctx["solo_observation"] is False  # disagreement is a per-pair flag, not a critical outage
