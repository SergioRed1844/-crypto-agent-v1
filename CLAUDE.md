# CLAUDE.md — CryptoAgent

AI-assisted crypto trading system. Currently **paper trading only**.

## Architecture (10 lines)

1. **TradingView** fires alerts (Pine: `CryptoAgent_v1.pine`) → HTTP POST to `/webhook` with a shared `secret`.
2. **`server.py`** (FastAPI) is the brain: dedups the signal, checks kill switches, gathers context.
3. **Market context**: `get_market_context()` today (→ `market_context.py` after Phase 3) pulls price/F&G/funding from multiple APIs (see [market-data-pipeline]).
4. **Mr. Market valuation** (`valuation.py`): Graham behavioral read — is the crowd under/over-estimating? Output is a *bias*, not an override.
5. **RAG** (`rag/`, TF-IDF over ~76 chunks): retrieves strategy/risk knowledge for the prompt.
6. **Gemini** (`gemini-2.5-flash`) returns a strict-JSON decision (action, confidence, bias_check, bear_case, posture_used, entry/stop/tp, rr_pesimista).
7. **`validate_trade()`** enforces the hard rules (BNB lock, R:R, exposure, confidence/confluence, bias_check, kill switches, stale-price).
8. **Execution**: paper sim or Binance spot via `ccxt` (`open_long`, OCO). Long-only on spot.
9. **`store.py`** (SQLite at `$DATA_DIR`) persists trades/positions/kv across redeploys; a background monitor closes positions on SL/TP and runs `adapt_parameters()` (self-learning).
10. **Google Sheets** (`google_apps_script.js` Web App) is the journal + feedback source for the learning loop.

## Run & test locally

```bash
.venv/bin/python -c "import fastapi, httpx, sklearn, numpy, ccxt"   # deps smoke test
DATA_DIR=./_localdata PAPER_TRADING=true .venv/bin/uvicorn server:app --port 8000
curl localhost:8000/health
curl localhost:8000/status
# webhook (replace SECRET): expect 401 on wrong secret, decision JSON on correct
curl -s localhost:8000/webhook -H 'content-type: application/json' \
  -d '{"secret":"SECRET","pair":"BTCUSDT","signal_type":"T1_PULLBACK","price":65000,"atr":800}'
.venv/bin/python -m pytest -q          # unit tests (validation, market_context, persistence)
```

## Skills (in `.claude/skills/`) and when to use them

- **graham-trading-philosophy** — editing the Gemini prompt, `validate_trade`, `valuation.py`, or any decision logic. The constitution + the 6-point `bias_check`.
- **market-data-pipeline** — editing `market_context.py` / data fetchers / adding a source.
- **risk-regime-engine** — editing posture/regime logic, `RISK_PARAMS`, `RISK_FLOORS`, exposure/kill-switch rules.
- **deploy-render-runbook** — deploying to Render, editing `render.yaml`, diagnosing a deploy.

## Non-negotiable safety rules

- **`PAPER_TRADING=true` always** during all development. Flipping to `false` is a manual human
  decision made only after the paper gate (≥30 trades, ≥2 weeks, win rate >50%, avg R:R ≥2.0,
  drawdown <10%). Claude must never flip it.
- **Never request, print, or commit API keys or secrets.** Env vars live in Render/the environment
  only. `.gitignore` must cover `.env`.
- **Never run destructive git** (force push, branch deletion) without explicit confirmation.
- **BNB and BNB* pairs stay blocked** in code (`protected_assets`).
- **Hard limits are immutable** (see risk-regime-engine): daily −3% / weekly −5% kill switches,
  ≤5% total exposure, ≤0.5% risk per trade ceiling, max 5 consecutive losses, 1 position per pair.
- **If a test fails, fix it before advancing a phase.** No "we'll look at it later."
