---
name: deploy-render-runbook
description: Runbook for deploying CryptoAgent to Render (paper trading) — render.yaml blueprint, the real environment variables the code reads, how to validate /health, /status and /pipeline, how to read Render logs, and troubleshooting of known errors (RAG not loaded, webhook 401, cold start, missing persistent disk). Load when deploying, editing render.yaml, or diagnosing a deploy.
---

# Deploy / Render runbook

Pipeline: **TradingView → Render (FastAPI) → RAG + market_context + Gemini → paper/Binance → Google Sheets.**
Stack: Python 3.10, FastAPI + uvicorn, SQLite (`store.py`) on a persistent disk.

## Environment variables (what the code ACTUALLY reads — source of truth is `server.py`)

| Variable | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | **Yes** | aistudio.google.com. Model: `gemini-2.5-flash`. |
| `WEBHOOK_SECRET` | **Yes** | shared secret for TradingView; webhook returns 401 without a match. |
| `SHEETS_WEBAPP_URL` | **Yes** | URL of the deployed Google Apps Script Web App (journal + feedback). |
| `PAPER_TRADING` | **Yes = `true`** | non-negotiable at launch; flipping to `false` is a manual human decision post-gate. |
| `DATA_DIR` | recommended | where `store.py` writes `cryptoagent_state.db`; must point at the mounted disk (`/data`). |
| `PAPER_EQUITY` | No | simulated equity for sizing/PnL. Default **10000**. (NOT `PAPER_BALANCE`.) |
| `MONITOR_INTERVAL_SEC` | No | position-monitor loop interval. Default 60. |
| `MRMARKET_ENABLED` / `MRMARKET_BLOCK_EUPHORIA` | No | Mr. Market behavioral guard. Default true/true. |
| `CRYPTOPANIC_API_KEY` | No | news sentiment; degrades gracefully if absent. |
| `BINANCE_API_KEY` / `BINANCE_SECRET` | No | **LIVE only** — leave unset for paper. |

Secrets are set in the Render dashboard (`sync: false` in `render.yaml`), never committed.

## render.yaml blueprint

`render.yaml` defines a `web` service with a **1 GB persistent disk mounted at `/data`** and
`DATA_DIR=/data` so the SQLite state survives redeploys (this is what makes persistence real —
[[risk-regime-engine]] state, trades and positions all live there). Build:
`pip install -r requirements.txt`; start: `uvicorn server:app --host 0.0.0.0 --port $PORT`;
health check: `/health`. Keep `branch: main` and `PAPER_TRADING="true"`.

> The disk and `DATA_DIR` only auto-apply when you create the service **from the Blueprint**. If
> the service was wired up manually, add the Disk + `DATA_DIR` from the dashboard by hand.

## Validation after deploy

1. `GET /health` → `{"status":"ok"}`.
2. `GET /status` → check `paper_trading:true`, `rag.loaded:true`, kill switch inactive.
3. `GET /pipeline` → `overall: "READY"` (self-check: RAG, env vars, Gemini, data sources, store writable).
4. End-to-end: POST a synthetic signal with the valid secret to `/webhook` → JSON decision,
   row appears in Sheets, and any paper position survives a redeploy (persistence proof).

## Troubleshooting (known errors)

- **`RAG load failed` / `rag_loaded:false`** → the `rag/*.pkl` + `chunks_metadata.json` artifacts
  weren't deployed, or scikit-learn version drift unfitted the vectorizer. Confirm files are
  committed and `scikit-learn==1.4.0` matches the pickle.
- **Webhook 401** → `secret` in the TradingView alert body ≠ `WEBHOOK_SECRET`. Expected when wrong;
  a *correct* secret must return a decision JSON.
- **Cold start** (free/idle plan) → first request after idle is slow; health check + a keep-warm
  ping mitigate. Not an error.
- **State lost on redeploy** → disk not mounted or `DATA_DIR` not pointing at it. Verify
  `/data` disk exists and `DATA_DIR=/data`.
- **Binance region block** → public endpoints 451; the price/funding fallback chain handles it.
  Does not affect paper trading sizing (uses `PAPER_EQUITY`).
