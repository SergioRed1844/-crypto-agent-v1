---
name: market-data-pipeline
description: Catalog of the market-data sources CryptoAgent reads (CoinGecko, CoinPaprika, alternative.me Fear&Greed, CryptoPanic, Binance public futures/spot, CoinGecko global), their endpoints, rate limits, which field each contributes, how they cross-validate, and the graceful-degradation rules. Load when editing market_context.py, get_market_context, valuation.py fetchers, or adding/repairing a data source.
---

# Market data pipeline — sources, cross-validation, degradation

**Principle: APIs only, never HTML scraping** (fragile + bannable). Aggregate everything into a
single timestamped object in `market_context.py` with a composite score, data-quality flags, and
a 5-minute TTL cache. **Never invent data.** If a source fails, degrade; if ≥2 critical sources
fail, enter SOLO-OBSERVATION mode (log, do not trade).

## Sources

| # | Source | Endpoint | Free-tier limit | Contributes |
|---|---|---|---|---|
| 1 | **CoinGecko** | `/simple/price`, `/coins/{id}/market_chart`, `/global` | ~10–30 req/min (no key) | price, 24h/7d change, volume; `/global` → BTC dominance + total market cap |
| 2 | **CoinPaprika** | `/v1/tickers/{coin_id}` | ~20k/mo, no key | **second price source for cross-validation** (anti-bias #6) |
| 3 | **alternative.me F&G** | `/fng/?limit=30` | generous, no key | Fear & Greed **30-day series** (detect sentiment turns), not just today's value |
| 4 | **CryptoPanic** | `/v1/posts/?auth_token=…&currencies=BTC` | requires `CRYPTOPANIC_API_KEY` (optional) | headlines + bullish/bearish votes → news sentiment score |
| 5 | **Binance public** | `api.binance.com /api/v3/ticker/price`, `/klines`; `fapi.binance.com /fapi/v1/premiumIndex`, `/openInterest` | weight-based, no key | spot price fallback, OHLCV (valuation.py), **funding rate + open interest** (leverage/squeeze risk) |
| 6 | **CoinGecko global** | `/global` (same as #1) | shared with #1 | dominance & total cap → rotation context |

`coin_id` maps: CoinGecko `bitcoin/ethereum/solana`; CoinPaprika `btc-bitcoin/eth-ethereum/sol-solana`.

## Cross-validation (feeds anti-bias check #6)

- Compare CoinGecko vs CoinPaprika spot price per asset. **Disagreement >1% → flag the asset's
  price as unreliable.** If a *critical* asset (the signal's pair) is unreliable → NO_TRADE.
- Funding **very positive** = crowd over-leveraged long → squeeze risk → caution flag.
- F&G series: a sharp turn (e.g. extreme-fear → rising) is more informative than a single value.

## Composite score & quality flags

- Composite sentiment/positioning score in **[-100, +100]** (negative = crowd over-pessimistic/
  buy-bias zone per Graham; positive = over-optimistic/avoid). Built from F&G, funding, news score,
  price stretch. Keep weights interpretable and documented in code.
- `data_quality`: which sources responded, per-asset price agreement, staleness of cache entry.

## Graceful degradation

- Each fetch is independently `try/except`; one failure must not abort the others.
- Cache (TTL 5 min) prevents hammering rate limits and provides a last-good fallback.
- Binance may be region-blocked: keep the existing fallback chain (CoinPaprika ↔ Binance ↔ CoinGecko).
- **≥2 critical sources down → SOLO-OBSERVATION**: build the object with quality flags, log the
  degradation, and the agent returns `NO_TRADE` for new entries (open positions still managed by
  the monitor).

## Current state (pre-Phase-3)

`get_market_context()` in `server.py` only fetches F&G `limit=1`, CoinPaprika prices, and a Binance
price fallback. `valuation.py` separately fetches klines + funding. Phase 3 consolidates all 6
sources, cross-validation, composite score, TTL cache and degradation into `market_context.py`.
