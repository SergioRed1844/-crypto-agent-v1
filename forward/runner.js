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
