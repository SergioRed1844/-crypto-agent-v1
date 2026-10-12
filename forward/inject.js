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
// Corre en una pestaña de api.binance.com (mismo origen: sin CORS). Requiere engine.js cargado antes.
// Uso: window.__CA_RUN({cutTs}) → guarda el resultado en window.__CA_RESULT
(function () {
  const E = window.CAEngine, TF = E.TF;
  const COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"];
  const SCALES = {
    swing: { htf: "1d", setup: "4h", trigger: "1h", histDays: 365 },
    intradia: { htf: "4h", setup: "1h", trigger: "15m", histDays: 90 },
    scalp: { htf: "1h", setup: "15m", trigger: "5m", histDays: 30 } };
  const START = Date.parse("2026-10-12T00:00:00Z");  // inicio de la ventana hacia adelante (prerregistro)
  const DAY = 864e5;
  const NEED_DAYS = { "1d": 720, "4h": 420, "1h": 380, "15m": 95, "5m": 33 };
  const prog = window.__CA_PROGRESS = { fetched: 0, total: COINS.length * 5, stage: "descargando" };

  async function klines(sym, tf, since) {
    const out = []; let cur = since;
    for (;;) {
      const r = await fetch(`/api/v3/klines?symbol=${sym}&interval=${tf}&startTime=${cur}&limit=1000`);
      if (!r.ok) throw new Error(`${sym} ${tf} HTTP ${r.status}`);
      const rows = await r.json(); if (!rows.length) break;
      for (const x of rows) out.push([x[0], +x[1], +x[2], +x[3], +x[4], +x[5]]);
      cur = rows[rows.length - 1][0] + TF[tf]; if (rows.length < 1000) break;
    }
    const now = Date.now(); return out.filter(r => r[0] + TF[tf] <= now);  // solo velas cerradas
  }
  function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function metrics(tr) {
    if (!tr.length) return { trades: 0 };
    const R = tr.map(t => t.R), w = R.filter(r => r > 0), l = R.filter(r => r <= 0), n = R.length;
    let eq = 0, pk = 0, dd = 0; for (const r of R) { eq += r; pk = Math.max(pk, eq); dd = Math.min(dd, eq - pk); }
    const mean = R.reduce((s, v) => s + v, 0) / n, g = rng(1), bs = [];
    for (let k = 0; k < 2000; k++) { let s = 0; for (let i = 0; i < n; i++) s += R[Math.floor(g() * n)]; bs.push(s / n); }
    bs.sort((a, b) => a - b);
    const sl = l.reduce((s, v) => s + v, 0);
    return { trades: n, win_rate: +(w.length / n).toFixed(3), expectancy_R: +mean.toFixed(3),
             profit_factor: sl < 0 ? +(w.reduce((s, v) => s + v, 0) / -sl).toFixed(2) : null,
             total_R: +R.reduce((s, v) => s + v, 0).toFixed(2), max_dd_R: +dd.toFixed(2),
             ret_pct: +tr.reduce((s, t) => s + t.pct, 0).toFixed(2),
             ic95_R: [+bs[49].toFixed(3), +bs[1949].toFixed(3)] };
  }
  function bh(b, from, to) { const s = b.filter(r => r[0] >= from && r[0] < to); if (s.length < 1) return null;
    return +((s[s.length - 1][4] / s[0][1] - 1) * 100).toFixed(2); }

  function runWindow(D, sc, from, to, detail) {
    const sigs = {}, series = {}, perCoin = {};
    for (const c of COINS) { sigs[c] = E.signals(D[c], sc, c, from, to - TF[sc.setup]); series[c] = D[c][sc.setup]; }
    const port = E.portfolio(series, sigs, sc, to);
    for (const c of COINS) {
      const one = E.portfolio({ [c]: series[c] }, { [c]: sigs[c] }, sc, to);
      perCoin[c] = { ...metrics(one.trades), signals: sigs[c].size, open: one.open.length,
                     open_R: +one.open.reduce((s, p) => s + p.R, 0).toFixed(2), buy_hold_pct: bh(series[c], from, to) };
    }
    const curve = []; let cum = 0;
    for (const t of [...port.trades].sort((a, b) => a.exit_time - b.exit_time)) { cum += t.pct; curve.push([t.exit_time, +cum.toFixed(3)]); }
    const res = { from, to, portfolio: { ...metrics(port.trades), open: port.open.length,
                  open_pct: +port.open.reduce((s, p) => s + p.pct, 0).toFixed(3) }, per_coin: perCoin, curve };
    if (detail) { const f = x => +(+x).toPrecision(6);
      res.trades = port.trades.map(t => ({ pair: t.pair, in: t.entry_time, out: t.exit_time, entry: f(t.entry), exit: f(t.exit),
                                         why: t.reason, R: +t.R.toFixed(3), cs: t.cs, pct: +t.pct.toFixed(3) }));
      res.open_positions = port.open.map(p => ({ pair: p.pair, in: p.entry_time, entry: f(p.entry), mark: f(p.mark), sl: f(p.sl),
                                               tp: f(p.tp), R: +p.R.toFixed(3), cs: p.cs, pct: +p.pct.toFixed(3) }));
      res.signals = Object.fromEntries(COINS.map(c => [c, [...sigs[c].values()].map(s => s.decided)])); }
    return res;
  }

  window.__CA_RUN = async function ({ cutTs, withHistory = true }) {
    const now = Date.now(), D = {}, jobs = [];
    for (const c of COINS) { D[c] = {};
      for (const tf of Object.keys(NEED_DAYS)) jobs.push([c, tf]); }
    const pool = async () => { while (jobs.length) { const [c, tf] = jobs.shift();
      D[c][tf] = await klines(c, tf, now - NEED_DAYS[tf] * DAY); prog.fetched++; } };
    await Promise.all([pool(), pool(), pool(), pool()]);
    for (const c of COINS) D[c].btc1d = D.BTCUSDT["1d"];
    prog.stage = "calculando";
    const out = { generated_utc: new Date(now).toISOString(), window_start: START, cut: cutTs,
                  data_until: Math.max(...COINS.map(c => D[c]["5m"].at(-1)[0] + TF["5m"])), coins: COINS, scales: {} };
    for (const [name, sc] of Object.entries(SCALES)) {
      out.scales[name] = { def: sc, forward: runWindow(D, sc, START, Math.min(cutTs, now), true) };
      if (withHistory) out.scales[name].history = runWindow(D, sc, START - sc.histDays * DAY, START, false);
      prog.stage = `listo ${name}`;
    }
    out.last_price = Object.fromEntries(COINS.map(c => [c, D[c]["5m"].at(-1)[4]]));
    prog.stage = "terminado"; window.__CA_RESULT = out; return "ok";
  };
})();
window.__CA_ERR=null; window.__CA_RESULT=null; window.__CA_RUN({cutTs: Date.parse('2026-10-14T20:00:00Z')}).catch(e=>window.__CA_ERR=String(e.stack||e)); 'iniciado'
