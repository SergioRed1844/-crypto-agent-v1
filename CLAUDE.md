# CLAUDE.md — CryptoAgent v4.2 (rama `v4.2-contexto`)

AI-assisted crypto trading system. Currently **paper trading only** (`TRADING_MODE=paper`).

## Architecture
1. **TradingView** (Pine `pine/CryptoAgent_v2_sensor.pine`, 4H bar close) → `POST /webhook` (secret + TradingView IPs).
2. **`app/server.py`** (FastAPI) stores the signal in a durable queue; a single **leader** (Postgres advisory lock) consumes it.
3. **`app/graph.py`** (LangGraph): `gather` → code analysts in parallel **technical · regime · derivatives · context** →
   `rules_gate` (any veto → NO_TRADE without LLM) → LLM **sentiment ∥ methodology** → `aggregate` → **bull ∥ bear** →
   **judge** → deterministic **risk_gate** → `execute` (paper sim or Binance spot + OCO) → `journal`.
4. **Context model (`app/context/`, v4.2):** 3-year event calendar + history since 2009 + event study weights +
   on-chain whale watch + market moderators → `context_signal.json` (RISK_ON/NEUTRAL/CAUTION/BLACKOUT/RISK_OFF).
   Built by GitHub Actions on this branch (`context-watch` hourly, `context-refresh` days 1 & 15, `context-backtest`
   monthly); the server reads it via `CONTEXT_REMOTE_BASE` (`app/context/live.py`). Docs: `docs/MODELO_CONTEXTO.md`.
5. **`app/risk.py`** enforces hard limits + v4.2 checks: net target ≥ `MIN_NET_GAIN_PCT` (1.5%), net R:R ≥ `MIN_NET_RR`
   (1.8), losing streak < 5, context veto, size × context `size_mult`.
6. **`app/store.py`** SQLite/Postgres: decisions, positions (write-ahead), kv. Google Sheets mirror via
   `sheets/google_apps_script.js` (context tabs: Calendario, Eventos, Pesos, Alertas, Contexto).

## Run & test locally
```bash
./run_tests.sh                                   # smoke, recovery, stress, execution, onchain, context (offline, mock)
python -m app.context.pipeline calendar          # rebuild calendar.json + CALENDARIO.md from sources
python -m app.context.pipeline signal            # recompute context_signal.json with what is on disk
DATA_MODE=mock LLM_PROVIDER=mock uvicorn app.server:app --port 8000
```
Network-dependent jobs (news, on-chain, event study, backtests) run in GitHub Actions; this workspace usually cannot
reach exchanges.

## Skills (`.claude/skills/`) and when to use them
- **context-event-calendar** — events, calendar sources, proposals, biweekly refresh.
- **context-impact-model** — variables, event study, weights, signal state machine, integration with the committee.
- **onchain-whale-watch** — Satoshi-era / dormant-whale detection and the exit response.
- **graham-trading-philosophy** — any decision logic or prompt. **risk-regime-engine** — limits and posture.
- **market-data-pipeline** — data sources (v1 catalog; v4.2 sources are in `data/context/sources/apis.json`).
- **deploy-render-runbook** — deploying (v4.2 blueprint: `render.yaml`, `branch: v4.2-contexto`, autoDeploy off).

## Radar EB — agente 2 (integrado en esta rama, solo alertas)
Vigía horario de cripto + EUA + BMV que **no opera**: setups de compra del corpus de microcomportamientos
(pánico sin daño, capitulación, choque político, miedo de hogares, choque del peso, atención+momentum, retroceso en
tendencia) → modelo de **Bayes empírico** (`radar/`) → regla `relativo` (ventaja creíble sobre comprar un día
cualquiera) → ficha por issue de GitHub (correo), Gmail y/o WhatsApp (CallMeBot) y resumen diario 8:00 CDMX.
Lee el `context_signal.json` de esta misma rama (CAUTION sube la exigencia; solo resta). Estado en `data/radar/`.
Workflows: `radar-scan` (cada hora, cron en main + heartbeat), `radar-backtest` (al cambiar `radar/**` y mensual).
Método: `docs/RADAR_EB.md`; validación: `data/radar/BACKTEST.md`; skill: `radar-eb-model`.
Pruebas: `python -m tests.test_radar`. El Radar nunca toca `app/` (salvo leer `app/context/classifier` para Gemini)
ni llaves de exchange; sus vetos solo restan. Secrets opcionales: `RADAR_SMTP_USER`/`RADAR_SMTP_PASS`/`RADAR_EMAIL_TO`,
`CALLMEBOT_PHONE`/`CALLMEBOT_APIKEY`, `FINNHUB_API_KEY` (calendario de resultados); `GEMINI_API_KEY` ya existe.

## Non-negotiable safety rules
- **`PAPER_TRADING=true` always** during all development (in v4.x: `TRADING_MODE=paper`). Flipping to live is a manual
  human decision made only after the paper gate (≥30 trades, ≥2 weeks, win rate >50%, avg R:R ≥2.0, drawdown <10%).
  Claude must never flip it.
- **Never request, print, or commit API keys or secrets.** Env vars live in Render / GitHub Actions secrets only.
  `.gitignore` must cover `.env`. Logs must never include URLs that carry keys (FRED, CryptoPanic).
- **Never run destructive git** (force push, branch deletion) without explicit confirmation.
- **BNB and BNB* pairs stay blocked** in code (`protected_assets`).
- **Hard limits are immutable**: daily −3% / weekly −5% kill switches, ≤5% total exposure, ≤0.5% risk per trade ceiling,
  max 5 consecutive losses, 1 position per pair.
- **The context model may only REDUCE risk** (veto, smaller size, more confluence, exit to USDT). It never opens trades,
  never relaxes a limit, and unverified events stay `proposed` (no blackout).
- **Never invent dates or data.** Every curated event has a source; estimates are labelled.
- **If a test fails, fix it before advancing a phase.** No "we'll look at it later."
- Commits to branches that Render deploys must carry **`[skip render]`** unless a deploy is intended.
