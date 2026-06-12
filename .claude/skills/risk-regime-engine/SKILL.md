---
name: risk-regime-engine
description: Specification of CryptoAgent's dynamic posture selector (aggressive ↔ defensive) — the regime table, per-posture parameters, and the IMMUTABLE hard limits no posture may ever relax (kill switches, max consecutive losses, total exposure, BNB lock, one position per pair). Load when editing posture/regime logic, RISK_PARAMS, RISK_FLOORS, validate_trade, or the learning loop.
---

# Risk & regime engine — dynamic posture within immutable limits

The agent recomputes its **posture** on every signal from the `market_context` (see
[[market-data-pipeline]]). Posture only moves parameters **inside** the hard limits — never outside.
Posture and its rationale are logged on every decision (Sheets), feeding the learning loop.

## Regime → posture table

| Regime | Conditions (ALL) | Posture | Risk/trade | Min confluence | Min R:R |
|---|---|---|---|---|---|
| **HEALTHY TREND** | strong trend + normal volatility + F&G 25–60 + neutral funding | **AGGRESSIVE** | 0.75% | 5 | 2.0 |
| **NEUTRAL** | mixed conditions | **STANDARD** | 0.5% | 6 | 2.0 |
| **EUPHORIA** | F&G > 75 OR extreme funding OR price >X% in 24h | **CONSERVATIVE** | 0.25% | 8 | 3.0 |
| **PANIC / CHAOS** | EXTREME volatility OR very bearish news OR sources disagree | **DEFENSIVE** | 0% new trades; manage open only | — | — |

## Immutable hard limits — NO posture may relax these

Implemented as constants (frozen `RISK_FLOORS` + dedicated guards in `validate_trade` /
`check_kill_switches`). The posture may make the agent *pickier* or *less* risky, never the reverse.

- **Daily kill switch −3%**, **weekly kill switch −5%** (`daily_drawdown_kill`, `weekly_drawdown_kill`).
- **Max 5 consecutive losses** → stand down.
- **Total capital-at-risk ≤ 5%** across all open positions (`max_total_exposure`).
- **Risk per trade ≤ 0.5% absolute ceiling** — note the AGGRESSIVE 0.75% row above is a *target*
  that is still clamped by `RISK_FLOORS["max_risk_per_trade_max"]`; the floor wins. Never above 0.5%.
- **BNB and BNB* pairs are permanently blocked** (`protected_assets`).
- **Max 1 position per pair.**
- **Every position has a valid stop** (stop ≠ entry; sized by `sl_atr_mult × ATR`).

> Conflict rule: when a posture target and a hard limit disagree, **the hard limit always wins.**
> The aggressive risk target must be read as "up to, but never exceeding, the 0.5% ceiling."

## Relationship to the learning loop

`adapt_parameters()` already tunes *selectivity* (`min_confidence`, `min_confluence`, `min_rr`,
`sl_atr_mult`) within `RISK_FLOORS` based on rolling results. The posture selector is a *second*,
faster layer reacting to the live regime. Both must respect the same floors; neither can touch the
kill switches, exposure cap, BNB lock, or the absolute risk-per-trade ceiling.
