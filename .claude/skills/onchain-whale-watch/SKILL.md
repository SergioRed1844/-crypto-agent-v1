---
name: onchain-whale-watch
description: CryptoAgent v4.2's on-chain alert rule — detecting when Satoshi-era (Patoshi, P2PK 2009–2010) or long-dormant whale bitcoins are SPENT, severity thresholds, the risk-off/exit response, Esplora (mempool.space/blockstream) usage limits, and false positives. Load when editing app/context/onchain.py, alert thresholds, the watch workflow, or when an on-chain alert fires.
---

# On-chain whale watch

## Facts (data/context/sources/onchain_facts.json, researched 2026-10-11)
- Satoshi/Patoshi: ~1.1M BTC (Lerner; Arkham ≈1.096M) in ~22,000 coinbase outputs of 50 BTC, blocks 1–~54,316,
  locked as **P2PK** (no address reuse). It is NOT "~25 wallets". ~99.9% never moved.
- The genesis address receives dust every day (80k+ deposits) and has never spent: **receiving ≠ moving**.
  Only inputs (spends) count.
- Precedents: 2020-05-20 (50 BTC from Feb 2009, brief dip), 2025-07-04 (~80,000 BTC from 2011 sold via Galaxy),
  2026-09-05 (600 BTC from 2010), Mt. Gox trustee still ~34–35k BTC with an Oct-31-2026 deadline.

## Detection (`python -m app.context.onchain`, hourly in GitHub Actions + optional every 5 min in the server)
Parse each new raw block. SATOSHI_ERA (critica): a non-coinbase input that spends a P2PK output (scriptSig =
one DER-signature push, no pubkey, no witness) whose source block ≤ 60,000. EARLY_MINER (alta): same with source
≤ 210,000 and ≥ 50 BTC. DORMANT_WHALE: txs ≥ 100 BTC; inputs ≥ 5 BTC are dated via /tx/:prev/status →
alta if ≥ 500 BTC aged ≥10y or ≥ 5,000 BTC aged ≥5y; media if ≥ 1,000 BTC aged ≥5y. Thresholds live in
`onchain.DEFAULTS`; they are heuristics (Glassnode bands 5y/7y/10y), not a published standard — calibrate.

## Response (engine + server)
critica → RISK_OFF + exit_all: the leader sells all bot positions to USDT once per alert id and sets the kill
switch (human reviews, then POST /resume). alta → RISK_OFF 48 h (no new buys, positions keep their OCO).
media → CAUTION 24 h (half size, +2 confluence). The watch workflow opens a GitHub issue (email) on alta/critica.

## API etiquette (mempool.space, fallback blockstream.info)
Limits are unpublished; 429 then bans. Keep ≤ ~1 req/s (client sleeps 0.25 s + backoff), budget 500 calls/run,
cache confirmed data, fall back to blockstream on 429/5xx. Never poll all 22k Patoshi outputs; scanning blocks is
cheaper and catches every spend.

## Known limits
No reorg handling (a replaced block at the same height is not rescanned); entity-labelled exchange inflows
(Arkham/CryptoQuant) are not available for free; a stuck block (persistent 404) holds `last_height` — check logs.
