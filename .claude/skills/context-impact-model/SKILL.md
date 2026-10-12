---
name: context-impact-model
description: The CryptoAgent v4.2 context model's math and contract — variable taxonomy (dependent, independent qualitative/quantitative, moderators, mediators, controls, constants), the event study since 2010, Bayesian shrinkage of weights, the context signal state machine (RISK_ON/NEUTRAL/CAUTION/BLACKOUT/RISK_OFF) and how it plugs into the trading committee and risk gate. Load when editing app/context/engine.py, event_study.py, variables.py, priors.json, the context agent, or when judging whether context "adds value".
---

# Context impact model

Purpose: make the trading model understand WHY the market may move, without letting narrative override
evidence. The context layer can VETO, SHRINK size, or DEMAND more technical confluence. It never opens a trade
by itself (Graham golden rule: doubt → no trade).

## Variables (single source: `app/context/variables.py`, rendered into docs/MODELO_CONTEXTO.md)
- **Dependent (Y):** BTC abnormal return z at 1/3/7/30 days after the event (`ar_z_h`), its magnitude
  (`abs_ar_z_h`), 7d/30d vol ratio, altcoin response, and finally `trade_R` of the trading model.
- **Independent (X):** qualitative discrete attributes (category, subcategory, country, crypto_stance, scheduled,
  surprise, status, prior_tier, onchain_type), counts (news volume 24h, CryptoPanic important votes, same-category
  events in 30d), continuous (GDP share, ex-ante prediction-market probability, surprise z vs consensus,
  rate change bps, BTC-years moved, news tone, F&G, funding, OI change, DXY/VIX/Nasdaq/10Y changes,
  stablecoin supply change, ETF flows).
- **Moderators (Z):** BTC regime (GREEN/YELLOW/RED), vol regime, F&G zone, leverage zone, halving phase,
  BTC–Nasdaq correlation, weekend liquidity. **Mediator (M):** same-day reaction of Nasdaq/dollar.
- **Controls/constants (C):** 90-day drift/vol (removed to get ABNORMAL returns), day of week, random-day
  baseline, universe, fees/slippage, immutable hard limits, event windows.

## Event study (`python -m app.context.event_study --fetch`, GitHub Actions monthly)
z_h = (ln(close[d+h−1]/close[d−1]) − h·μ90) / (σ90·√h). Per category: mean |z3| vs 4,000 random days
(permutation p), signed effect with the stance sign and hit rate (binomial p). Weights are **excess over a random
day**, shrunk to the prior: `w = (n·empirical + k·prior)/(n + k)`, k = 8 (`priors.json`). Evidence labels:
fuerte (n≥10, p<0.05), moderada, débil, sin datos. Regime moderator multipliers shrink with k = 15.

## Signal (`engine.compute`, contract in its docstring; file `context_signal.json`)
magnitude_e = ½·w_abs[cat] + ½·tier_prior; event_risk = 1 − Π(1 − min(1,mag)·P(status)·proximity);
bias = tanh(Σ stance·direction·e^(−age/decay)·confidence·moderator / 1.5) + market steps (VIX≥30, DXY+2%,
Nasdaq −8%, stablecoins ±2%). States: on-chain critical/high or bias ≤ −0.5 → RISK_OFF (veto; critical also
exit_all); confirmed exact/day event of magnitude ≥ 0.4 inside its window → BLACKOUT (veto); bias ≤ −0.2,
event_risk ≥ 0.5, medium alert or stale inputs (>36 h) → CAUTION (size ×0.5, +2 confluence);
bias ≥ 0.2 and event_risk < 0.3 → RISK_ON (votes LONG); else NEUTRAL (size 1 − ½·event_risk, ≥0.5).

## Integration (trading graph)
`agents.context` runs in parallel with technical/regime/derivatives (code, no LLM) and reads `app/context/live.py`
(remote files from the v4.2-contexto branch via CONTEXT_REMOTE_BASE, cached 10 min; blackout/alerts evaluated
with the CURRENT time). Any veto → no LLM calls, NO_TRADE. `aggregate` requires confluence 5 + extra_confluence.
`risk.evaluate` multiplies risk by size_mult and adds checks: ganancia_neta_minima (net target ≥ 1.5%),
rr_neto_minimo (net R:R ≥ 1.8), racha_perdidas (< 5 in a row), contexto_sin_veto. The leader loop flattens to
USDT once per critical alert and sets the kill switch (manual /resume).

## Rules when changing this model
1. No look-ahead: backtests use priors (not full-sample weights) and only events dated before the signal day.
2. Hindsight bias: "it was obvious" (e.g., 2024 US election) is not a signal; use the ex-ante probability and
   model the SURPRISE = outcome − prior probability.
3. A layer stays only if `tools/backtest_variants.py` shows better OUT-of-sample expectancy with ≥30 trades and a
   higher IC95 lower bound. Report negative results; never tune thresholds on the out-of-sample window.
4. Never relax hard limits (see risk-regime-engine). PAPER only.
