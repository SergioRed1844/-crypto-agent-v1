"""
backtest.py — Faithful historical test of the CryptoAgent strategy (DEV/ANALYSIS tool).

Replicates the CryptoAgent_v1.pine signal logic (EMAs, RSI, MACD, Bollinger, ATR,
StochRSI, candlestick patterns, Fibonacci, the 6 templates and the confluence score)
in Python, then simulates LONG entries (the spot bot is long-only) with the SAME
SL/TP management the live monitor uses (exit at TP1 or stop).

HONEST SCOPE:
- Measures the win rate of the Pine SIGNALS + mechanical SL/TP on real history.
- Does NOT include the Gemini or Mr. Market filters — those only REJECT trades, so the
  live bot trades a subset of these; treat this as a baseline, not a guarantee.
- Includes round-trip fees; excludes slippage. Past performance != future results.

Requires pandas (dev-only; not a runtime dependency). Run:
    .venv/bin/python backtest.py
"""
import sys
import time
import httpx
import numpy as np
import pandas as pd

# ── strategy params (mirror the Pine inputs) ──
EMA_FAST, EMA_MID, EMA_SLOW = 21, 50, 200
ATR_LEN, ATR_MULT, MIN_RR = 14, 2.0, 2.0
MIN_VOLUME = 1.2
MIN_CONFLUENCE = 5
INTERVAL = "4h"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
HISTORY_BARS = 3000          # ~500 days on 4h
MAX_HOLD = 30                # bars before a time-stop exit
FEE_RATE = 0.001             # Binance spot taker, per side


def fetch_history(symbol, interval=INTERVAL, total=HISTORY_BARS):
    """Page backwards through Binance public klines to gather `total` bars."""
    out = []
    end = None
    with httpx.Client(timeout=20) as c:
        while len(out) < total:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000"
            if end:
                url += f"&endTime={end}"
            r = c.get(url)
            if r.status_code != 200:
                break
            batch = r.json()
            if not batch:
                break
            out = batch + out
            end = batch[0][0] - 1
            if len(batch) < 1000:
                break
            time.sleep(0.25)
    df = pd.DataFrame(out, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tb", "tq", "ig"])
    for col in ["o", "h", "l", "c", "v"]:
        df[col] = df[col].astype(float)
    return df.drop_duplicates("t").reset_index(drop=True)


def wilder_rma(series, n):
    return series.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = wilder_rma(gain, n) / wilder_rma(loss, n).replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df, n=14):
    h, l, c = df["h"], df["l"], df["c"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return wilder_rma(tr, n)


def compute_indicators(df):
    c, h, l, o, v = df["c"], df["h"], df["l"], df["o"], df["v"]
    df["ema21"] = c.ewm(span=EMA_FAST, adjust=False).mean()
    df["ema50"] = c.ewm(span=EMA_MID, adjust=False).mean()
    df["ema200"] = c.ewm(span=EMA_SLOW, adjust=False).mean()
    df["rsi"] = rsi(c)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    df["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    df["bb_up"], df["bb_low"], df["bb_mid"] = mid + 2 * sd, mid - 2 * sd, mid
    bbw = (df["bb_up"] - df["bb_low"]) / df["bb_mid"] * 100
    df["bb_squeeze"] = bbw < bbw.rolling(120).mean() * 0.75
    df["atr"] = atr(df)
    df["atr_pct"] = df["atr"] / c * 100
    df["vol_ratio"] = v / v.rolling(20).mean()
    # StochRSI
    rmin = df["rsi"].rolling(14).min()
    rmax = df["rsi"].rolling(14).max()
    stoch = ((df["rsi"] - rmin) / (rmax - rmin).replace(0, np.nan) * 100).fillna(50)
    df["stoch_k"] = stoch.rolling(3).mean()
    # regimes
    df["strong_up"] = (df.ema21 > df.ema50) & (df.ema50 > df.ema200) & (df.ema21 > df.ema21.shift(5)) & (df.ema50 > df.ema50.shift(5))
    df["weak_up"] = (c > df.ema200) & ~df["strong_up"]
    df["strong_down"] = (df.ema21 < df.ema50) & (df.ema50 < df.ema200) & (df.ema21 < df.ema21.shift(5)) & (df.ema50 < df.ema50.shift(5))
    df["weak_down"] = (c < df.ema200) & ~df["strong_down"]
    df["is_range"] = ~df["strong_up"] & ~df["weak_up"] & ~df["strong_down"] & ~df["weak_down"]
    df["trend_aligned"] = (df["strong_up"] | df["weak_up"]) & (c > df.ema200)
    # candles
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper = h - c.combine(o, max)
    lower = c.combine(o, min) - l
    df["green"] = c > o
    df["red"] = c < o
    df["hammer"] = (lower > body * 2) & (upper < body * 0.5) & df["red"]
    df["bull_engulf"] = df["green"] & df["red"].shift(1) & (o <= c.shift(1)) & (c >= o.shift(1)) & (body > body.shift(1))
    df["marubozu"] = (body / rng) > 0.95
    morning = df["red"].shift(2) & (body.shift(2) > body.shift(1) * 2) & ((body.shift(1) / rng.shift(1)) < 0.3) & df["green"] & (c > (o.shift(2) + c.shift(2)) / 2)
    df["morning_star"] = morning.fillna(False)
    df["bull_candle"] = df["hammer"] | df["bull_engulf"] | df["morning_star"]
    # fib & structure
    sh = h.rolling(50).max()
    sl = l.rolling(50).min()
    rng_fib = (sh - sl)
    df["near_618"] = ((c - (sh - rng_fib * 0.618)).abs() / c) < 0.01
    df["near_786"] = ((c - (sh - rng_fib * 0.786)).abs() / c) < 0.01
    df["near_ema21"] = ((c - df.ema21).abs() / c) < 0.005
    df["swing_low"] = sl
    hh20 = h.rolling(20).max()
    df["breakout"] = (c > hh20.shift(1)) & (c.shift(1) <= hh20.shift(2))
    df["retest"] = (c.shift(1) > hh20.shift(2)) & (c <= hh20.shift(2) * 1.005)
    df["at_bb_low"] = (c <= df.bb_low * 1.005) & df["is_range"]
    # simplified bullish divergence: price 20-bar low but RSI above its 20-bar low
    df["bull_div"] = (l <= l.rolling(20).min()) & (df["rsi"] > df["rsi"].rolling(20).min() * 1.05)
    return df


def confluence_long(r):
    score = 0
    if r["trend_aligned"]:
        score += 2
    if r["near_618"] or r["near_786"]:
        score += 2
    if r["near_ema21"]:
        score += 1
    if r["bull_div"] and r["trend_aligned"]:
        score += 2
    if r["bull_candle"] and r["trend_aligned"]:
        score += 1
    if r["vol_ratio"] > MIN_VOLUME:
        score += 1
    if r["bb_squeeze"]:
        score += 1
    if r["stoch_k"] < 20 and r["trend_aligned"]:
        score += 1
    if r["macd_hist"] > 0 and r["trend_aligned"]:
        score += 1
    return score


def template_long(r):
    if r["trend_aligned"] and r["near_ema21"] and (r["near_618"] or r["near_786"]) and (r["bull_candle"] or r["stoch_k"] < 20):
        return "T1_PULLBACK"
    if r["trend_aligned"] and (r["breakout"] or r["retest"]) and r["vol_ratio"] > 1.5:
        return "T2_BREAK_RETEST"
    if r["at_bb_low"] and r["is_range"]:
        return "T3_RANGE_EXTREME"
    if (r["l"] < r["swing_low"] * 1.001) and (r["c"] > r["swing_low"]) and r["vol_ratio"] > 2.0 and (r["hammer"] or r["bull_engulf"]):
        return "T4_LIQ_HUNT"
    if r["strong_up"] and r["marubozu"] and r["green"] and r["vol_ratio"] > 1.5:
        return "T5_MOMENTUM"
    if r["atr_pct"] > 4.0 and r["vol_ratio"] > 3.0 and (r["bull_engulf"] or r["hammer"]):
        return "T6_MEME_SCALP"
    return "NONE"


def simulate(df, symbol):
    trades = []
    i = EMA_SLOW + 50           # warm-up
    n = len(df)
    while i < n - 1:
        r = df.iloc[i]
        if pd.isna(r["atr"]) or r["atr"] <= 0:
            i += 1
            continue
        tmpl = template_long(r)
        score = confluence_long(r)
        is_long = score >= MIN_CONFLUENCE and r["trend_aligned"] and tmpl != "NONE"
        is_range_long = score >= MIN_CONFLUENCE and tmpl == "T3_RANGE_EXTREME" and r["at_bb_low"]
        if not (is_long or is_range_long):
            i += 1
            continue
        entry = r["c"]
        risk = r["atr"] * ATR_MULT
        sl = entry - risk
        tp1 = entry + risk * MIN_RR
        # walk forward
        outcome, bars = None, 0
        for j in range(i + 1, min(i + 1 + MAX_HOLD, n)):
            bars = j - i
            lo, hi = df.iloc[j]["l"], df.iloc[j]["h"]
            if lo <= sl:                      # conservative: stop before target if both in-bar
                outcome = -1.0
                break
            if hi >= tp1:
                outcome = MIN_RR
                break
        if outcome is None:                   # time-stop at last bar's close
            outcome = (df.iloc[min(i + MAX_HOLD, n - 1)]["c"] - entry) / risk
        fee_r = (FEE_RATE * 2 * entry) / risk  # round-trip fees in R units
        net = outcome - fee_r
        trades.append({"symbol": symbol, "template": tmpl, "bars": bars,
                       "gross_R": round(outcome, 3), "net_R": round(net, 3),
                       "result": "WIN" if net > 0 else "LOSS"})
        i = i + max(bars, 1)                   # one position at a time
    return trades


def report(trades):
    if not trades:
        print("No trades generated.")
        return
    df = pd.DataFrame(trades)
    wins = df[df.net_R > 0]
    losses = df[df.net_R <= 0]
    n = len(df)
    wr = len(wins) / n * 100
    avg_r = df.net_R.mean()
    pf = wins.net_R.sum() / abs(losses.net_R.sum()) if len(losses) and losses.net_R.sum() != 0 else float("inf")
    # equity curve & max drawdown (in R)
    eq = df.net_R.cumsum()
    dd = (eq - eq.cummax()).min()
    # max consecutive losses
    mcl = cur = 0
    for res in df.result:
        cur = cur + 1 if res == "LOSS" else 0
        mcl = max(mcl, cur)

    print("\n" + "=" * 60)
    print(f"  BACKTEST — {INTERVAL} — {', '.join(SYMBOLS)}")
    print("=" * 60)
    print(f"  Trades cerrados:        {n}")
    print(f"  Win rate:               {wr:.1f}%   ({len(wins)}W / {len(losses)}L)")
    print(f"  Expectancy (R/trade):   {avg_r:+.3f}R   <- el número que importa")
    print(f"  Profit factor:          {pf:.2f}")
    print(f"  Total acumulado:        {eq.iloc[-1]:+.1f}R")
    print(f"  Max drawdown:           {dd:.1f}R")
    print(f"  Max pérdidas seguidas:  {mcl}")
    print(f"  Duración media:         {df.bars.mean():.1f} velas ({df.bars.mean()*4:.0f}h)")
    print("\n  Por template:")
    for t, g in df.groupby("template"):
        gw = (g.net_R > 0).sum()
        print(f"    {t:18s} n={len(g):3d}  WR={gw/len(g)*100:4.0f}%  exp={g.net_R.mean():+.2f}R")
    print("\n  Por símbolo:")
    for s, g in df.groupby("symbol"):
        gw = (g.net_R > 0).sum()
        print(f"    {s:10s} n={len(g):3d}  WR={gw/len(g)*100:4.0f}%  exp={g.net_R.mean():+.2f}R")
    print("=" * 60)
    # honest verdict
    print("\n  VEREDICTO (criterios del checklist):")
    print(f"    Win rate >= 50%:      {'✅' if wr >= 50 else '❌'} ({wr:.0f}%)")
    print(f"    Expectancy > 0:       {'✅' if avg_r > 0 else '❌'} ({avg_r:+.2f}R)")
    print(f"    Profit factor > 1.3:  {'✅' if pf > 1.3 else '❌'} ({pf:.2f})")
    print("  Nota: sin filtro Gemini/Mr.Market (que solo mejora la selección). Comisiones incluidas, slippage no.")


if __name__ == "__main__":
    all_trades = []
    for sym in SYMBOLS:
        print(f"Descargando {sym} ({HISTORY_BARS} velas {INTERVAL})...", flush=True)
        df = fetch_history(sym)
        print(f"  {len(df)} velas desde {pd.to_datetime(df.t.iloc[0], unit='ms').date()} "
              f"hasta {pd.to_datetime(df.t.iloc[-1], unit='ms').date()}", flush=True)
        df = compute_indicators(df)
        t = simulate(df, sym)
        print(f"  {len(t)} trades LONG generados", flush=True)
        all_trades += t
    report(all_trades)
