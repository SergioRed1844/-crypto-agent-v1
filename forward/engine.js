// CryptoAgent v4.1 — motor de reglas en JavaScript (port 1:1 de app/indicators.py, agents.technical/regime,
// agents._default_levels y backtest.signals/portfolio). Verificado contra Python con forward/parity_test.js.
// Velas: arrays [ts_ms, open, high, low, close, volume]. Sin LLM ni noticias.
(function (root) {
  const TF = { "5m": 3e5, "15m": 9e5, "1h": 36e5, "4h": 144e5, "1d": 864e5 };
  const P = { risk_per_trade: 0.005, max_open_positions: 2, max_correlated_risk: 0.015, max_position_notional: 0.25,
              min_confluence: 5, min_rr: 2.0, fee: 0.001, slip: 0.0005, warmup: 210 };

  function ema(x, n) { const a = 2 / (n + 1), y = new Array(x.length); y[0] = x[0];
    for (let i = 1; i < x.length; i++) y[i] = a * x[i] + (1 - a) * y[i - 1]; return y; }
  function wilder(x, n) { // ewm(alpha=1/n, adjust=False) que arranca en el primer valor no-NaN
    const a = 1 / n, y = new Array(x.length).fill(NaN); let s = NaN;
    for (let i = 0; i < x.length; i++) { if (Number.isNaN(x[i])) { y[i] = s; continue; }
      s = Number.isNaN(s) ? x[i] : a * x[i] + (1 - a) * s; y[i] = s; } return y; }
  function rsiLast(c, n = 14) {
    const up = [NaN], dn = [NaN];
    for (let i = 1; i < c.length; i++) { const d = c[i] - c[i - 1]; up.push(Math.max(d, 0)); dn.push(Math.max(-d, 0)); }
    const u = wilder(up, n), d = wilder(dn, n), i = c.length - 1;
    if (!(d[i] > 0) || Number.isNaN(u[i])) return 50;
    return 100 - 100 / (1 + u[i] / d[i]);
  }
  function atrLast(b, n = 14) {
    const tr = b.map((r, i) => i === 0 ? r[2] - r[3] :
      Math.max(r[2] - r[3], Math.abs(r[2] - b[i - 1][4]), Math.abs(r[3] - b[i - 1][4])));
    const w = wilder(tr, n); return w[w.length - 1];
  }
  function trendRegime(b) {
    const c = b.map(r => r[4]), e21 = ema(c, 21), e50 = ema(c, 50), e200 = ema(c, 200), L = c.length - 1;
    const p = c[L], a = e21[L], m = e50[L], g = e200[L];
    const rising = e21[L] > e21[L - 4] && e50[L] > e50[L - 4];
    const falling = e21[L] < e21[L - 4] && e50[L] < e50[L - 4];
    if (p > a && a > m && m > g && rising) return "STRONG_UP";
    if (p < a && a < m && m < g && falling) return "STRONG_DOWN";
    if (p > g) return "WEAK_UP";
    if (p < g) return "WEAK_DOWN";
    return "RANGE";
  }
  function volRegime(daily) {
    const c = daily.map(r => r[4]), r = [];
    for (let i = 1; i < c.length; i++) r.push(Math.log(c[i]) - Math.log(c[i - 1]));
    const t = r.slice(-30), mu = t.reduce((s, v) => s + v, 0) / t.length;
    const sd = Math.sqrt(t.reduce((s, v) => s + (v - mu) ** 2, 0) / (t.length - 1));
    const v = sd * Math.sqrt(365) * 100;
    return [v < 40 ? "LOW" : v < 70 ? "NORMAL" : v < 100 ? "HIGH" : "EXTREME", v];
  }
  function snapshot(b) {
    const c = b.map(r => r[4]), L = c.length - 1, last20 = b.slice(-20), prev20 = b.slice(-21, -1);
    const vm = last20.reduce((s, r) => s + r[5], 0) / last20.length;
    return { close: c[L], ema21: ema(c, 21)[L], ema50: ema(c, 50)[L], ema200: ema(c, 200)[L], rsi: rsiLast(c),
             atr: atrLast(b), vol_ratio: b[L][5] / Math.max(vm, 1e-9),
             swing_low_20: Math.min(...last20.map(r => r[3])), prior_high_20: Math.max(...prev20.map(r => r[2])) };
  }
  // última vela CERRADA a la hora t (open + tf <= t): búsqueda binaria
  function cutIdx(b, tf, t) { let lo = 0, hi = b.length - 1, k = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (b[mid][0] + TF[tf] <= t) { k = mid; lo = mid + 1; } else hi = mid - 1; }
    return k; }
  function tail(b, tf, t, n = 300) { const k = cutIdx(b, tf, t); return k < 0 ? [] : b.slice(Math.max(0, k - n + 1), k + 1); }

  function marketAt(d, scale, t, pair) {
    const htf = tail(d[scale.htf], scale.htf, t), st = tail(d[scale.setup], scale.setup, t),
          tg = tail(d[scale.trigger], scale.trigger, t), daily = tail(d["1d"], "1d", t), btc = tail(d.btc1d, "1d", t);
    if (htf.length < P.warmup || st.length < 60 || tg.length < 60 || daily.length < 31 || btc.length < 200) return null;
    const bt = trendRegime(btc), [vr, va] = volRegime(daily);
    return { pair, price: st[st.length - 1][4], tf: { "1d": snapshot(htf), "4h": snapshot(st), "1h": snapshot(tg) },
             trend_regime_1d: trendRegime(htf), vol_regime: vr, vol_annualized_pct: va, btc_trend_1d: bt,
             btc_regime: { STRONG_UP: "GREEN", WEAK_UP: "GREEN", RANGE: "YELLOW", WEAK_DOWN: "YELLOW", STRONG_DOWN: "RED" }[bt] };
  }
  function technical(m) {
    const h4 = m.tf["4h"], h1 = m.tf["1h"]; let cs = 0;
    const htfOk = m.trend_regime_1d === "STRONG_UP" || m.trend_regime_1d === "WEAK_UP";
    if (htfOk) cs += 2;
    if (Math.abs(h4.close - h4.ema21) <= h4.atr) cs += 2;
    if (h4.close > h4.ema50 && h4.ema50 > h4.ema200) cs += 1;
    if (h4.vol_ratio > 1.5 && h4.close >= h4.prior_high_20 * 0.995) cs += 2;
    if (h1.rsi >= 40 && h1.rsi <= 65 && h1.close > h1.ema21) cs += 2;
    if (h4.rsi > 75) cs -= 2;
    cs = Math.max(0, Math.min(10, cs));
    return { long: htfOk && cs >= P.min_confluence, cs };
  }
  function regime(m) {
    const veto = (m.btc_regime === "RED" && !m.pair.startsWith("BTC")) || m.vol_regime === "EXTREME";
    return { long: m.btc_regime === "GREEN" && !veto, veto };
  }
  function defaultLevels(m) {
    const h4 = m.tf["4h"], price = m.price, atr = h4.atr;
    let sl = h4.swing_low_20 - 0.25 * atr;
    if (!(0.5 * atr <= price - sl && price - sl <= 3 * atr)) sl = price - 2 * atr;
    const tp = price + 2.5 * (price - sl);
    return [Math.round(sl * 1e8) / 1e8, Math.round(tp * 1e8) / 1e8];
  }
  // señales: decisión al cierre de cada vela de setup; la entrada es al open de la siguiente
  function signals(d, scale, pair, fromClose, toClose) {
    const st = d[scale.setup], out = new Map(), tf = TF[scale.setup];
    for (let i = 0; i < st.length - 1; i++) {
      const tc = st[i][0] + tf;
      if (tc < fromClose || tc > toClose) continue;
      const m = marketAt(d, scale, tc, pair); if (!m) continue;
      const t = technical(m), g = regime(m);
      if (t.long && g.long && !g.veto) { const [sl, tp] = defaultLevels(m);
        out.set(st[i + 1][0], { ref: m.price, sl_ref: sl, tp_ref: tp, cs: t.cs, decided: tc }); }
    }
    return out;
  }
  const sizeMult = cs => cs >= 8 ? 1.0 : cs >= 6 ? 0.75 : 0.5;
  // portafolio con los límites de producción; endTs: velas con open >= endTs no cuentan (corte)
  function portfolio(series, sigs, scale, endTs, opts = {}) {
    const fee = P.fee, slip = P.slip, maxOpen = opts.maxOpen ?? P.max_open_positions;
    const idx = {}, times = new Set();
    for (const [pair, b] of Object.entries(series)) { idx[pair] = new Map(b.map((r, i) => [r[0], r]));
      b.forEach(r => { if (r[0] < endTs) times.add(r[0]); }); }
    const T = [...times].sort((a, b) => a - b), pos = {}, trades = [];
    for (const t of T) {
      for (const pair of Object.keys(series)) {
        const sg = sigs[pair].get(t), bar = idx[pair].get(t);
        if (!sg || pos[pair] || Object.keys(pos).length >= maxOpen || !bar) continue;
        const entry = bar[1] * (1 + slip), sl = entry - (sg.ref - sg.sl_ref), tp = entry + (sg.tp_ref - sg.ref);
        if (entry <= sl || (tp - entry) / (entry - sl) < P.min_rr) continue;
        const unit = (entry - sl) + (entry + sl) * fee;
        const rf = Math.min(sizeMult(sg.cs) * P.risk_per_trade, P.max_position_notional * unit / entry);
        if (Object.values(pos).reduce((s, p) => s + p.rf, 0) + rf > P.max_correlated_risk + 1e-12) continue;
        pos[pair] = { t, entry, sl, tp, cs: sg.cs, rf, unit };
      }
      for (const pair of Object.keys(pos)) {
        const bar = idx[pair].get(t); if (!bar) continue;
        const p = pos[pair], [, o, hi, lo] = bar; let px = null, why = null;
        if (p.t !== t && o <= p.sl) { px = o * (1 - slip); why = "SL_GAP"; }
        else if (lo <= p.sl) { px = p.sl * (1 - slip); why = "SL"; }
        else if (hi >= p.tp) { px = p.tp; why = "TP"; }
        if (px !== null) { const r = ((px - p.entry) - (p.entry + px) * fee) / p.unit;
          trades.push({ pair, entry_time: p.t, exit_time: t, entry: p.entry, exit: px, reason: why, R: r, cs: p.cs,
                        rf: p.rf, pct: r * p.rf * 100 }); delete pos[pair]; }
      }
    }
    // abiertas al corte: valor a mercado con el último cierre antes del corte
    const open = Object.entries(pos).map(([pair, p]) => { const b = series[pair].filter(r => r[0] < endTs);
      const last = b[b.length - 1][4]; const r = ((last - p.entry) - (p.entry + last) * fee) / p.unit;
      return { pair, entry_time: p.t, entry: p.entry, mark: last, sl: p.sl, tp: p.tp, R: r, cs: p.cs, rf: p.rf, pct: r * p.rf * 100 }; });
    return { trades, open };
  }
  root.CAEngine = { TF, P, ema, rsiLast, atrLast, trendRegime, volRegime, snapshot, marketAt, technical, regime,
                    defaultLevels, signals, portfolio, cutIdx };
  if (typeof module !== "undefined") module.exports = root.CAEngine;
})(typeof window !== "undefined" ? window : globalThis);
