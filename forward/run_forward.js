// Prueba hacia adelante en papel — corre cada hora en GitHub Actions (Node 20, sin dependencias).
// Reglas congeladas en forward/prerregistro.json (hash del código v4.1). Motor: forward/engine.js (paridad 100% con backtest.py).
// Escribe forward/results/latest.json y, al pasar cada corte, forward/results/<corte>.json (inmutable).
const fs = require("fs"), path = require("path"), E = require("./engine.js");
const TF = E.TF, DAY = 864e5;
const PRE = JSON.parse(fs.readFileSync(path.join(__dirname, "prerregistro.json"), "utf8"));
const COINS = PRE.monedas, START = Date.parse(PRE.inicio_ventana_utc);
const CUTS = Object.fromEntries(Object.entries(PRE.cortes_utc).map(([k, v]) => [k, Date.parse(v)]));
const FINAL = CUTS.corte_final;
const SCALES = {
  swing: { htf: "1d", setup: "4h", trigger: "1h" },
  intradia: { htf: "4h", setup: "1h", trigger: "15m" },
  scalp: { htf: "1h", setup: "15m", trigger: "5m" } };
const NEED_DAYS = { "1d": 400, "4h": 70, "1h": 20, "15m": 8, "5m": 6 };  // calentamiento (300 velas) + ventana
const OUT = path.join(__dirname, "results");
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── fuentes de datos ──────────────────────────────────────────
const BINANCE_HOSTS = ["https://data-api.binance.vision", "https://api.binance.com", "https://api-gcp.binance.com",
  "https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com", "https://api4.binance.com"];
async function getJSON(url, tries = 3) {
  for (let i = 0; i < tries; i++) {
    try { const r = await fetch(url, { headers: { "User-Agent": "cryptoagent-forward-test" } });
      if (r.ok) return await r.json();
      if (r.status === 451 || r.status === 403) throw Object.assign(new Error(`HTTP ${r.status}`), { fatal: true });
      await sleep(1500 * (i + 1));
    } catch (e) { if (e.fatal || i === tries - 1) throw e; await sleep(1500 * (i + 1)); }
  }
}
async function pickBinance() {
  for (const h of BINANCE_HOSTS) {
    try { const k = await getJSON(`${h}/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=2`, 1); if (Array.isArray(k) && k.length) return h; }
    catch (e) { console.log(`  ${h}: ${e.message}`); }
  }
  return null;
}
async function binanceKlines(host, sym, tf, since) {
  const out = []; let cur = since;
  for (;;) {
    const rows = await getJSON(`${host}/api/v3/klines?symbol=${sym}&interval=${tf}&startTime=${cur}&limit=1000`);
    if (!rows.length) break;
    for (const x of rows) out.push([x[0], +x[1], +x[2], +x[3], +x[4], +x[5]]);
    cur = rows[rows.length - 1][0] + TF[tf]; if (rows.length < 1000) break;
  }
  return out;
}
// Respaldo si Binance bloquea la IP del runner: Coinbase (pares USD; 4h se arma con velas de 1h alineadas a UTC)
const CB_GRAN = { "5m": 300, "15m": 900, "1h": 3600, "1d": 86400 };
async function coinbaseKlines(sym, tf, since) {
  if (tf === "4h") { const h = await coinbaseKlines(sym, "1h", since), m = new Map();
    for (const r of h) { const k = Math.floor(r[0] / TF["4h"]) * TF["4h"], b = m.get(k);
      if (!b) m.set(k, [k, r[1], r[2], r[3], r[4], r[5]]);
      else { b[2] = Math.max(b[2], r[2]); b[3] = Math.min(b[3], r[3]); b[4] = r[4]; b[5] += r[5]; } }
    return [...m.values()].sort((a, b) => a[0] - b[0]).filter(b => h.filter(r => r[0] >= b[0] && r[0] < b[0] + TF["4h"]).length === 4); }
  const prod = sym.replace("USDT", "-USD"), g = CB_GRAN[tf], step = g * 1000 * 300, out = new Map();
  for (let t = since; t < Date.now(); t += step) {
    const s = new Date(t).toISOString(), e = new Date(Math.min(t + step, Date.now())).toISOString();
    const rows = await getJSON(`https://api.exchange.coinbase.com/products/${prod}/candles?granularity=${g}&start=${s}&end=${e}`);
    for (const x of rows) out.set(x[0] * 1000, [x[0] * 1000, x[3], x[2], x[1], x[4], x[5]]);
    await sleep(150);
  }
  return [...out.values()].sort((a, b) => a[0] - b[0]);
}

// ── métricas (mismas que la línea base) ───────────────────────
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
  t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function metrics(tr) {
  if (!tr.length) return { trades: 0 };
  const R = tr.map(t => t.R), w = R.filter(r => r > 0), l = R.filter(r => r <= 0), n = R.length;
  let eq = 0, pk = 0, dd = 0; for (const r of R) { eq += r; pk = Math.max(pk, eq); dd = Math.min(dd, eq - pk); }
  const mean = R.reduce((s, v) => s + v, 0) / n, g = rng(1), bs = [];
  for (let k = 0; k < 2000; k++) { let s = 0; for (let i = 0; i < n; i++) s += R[Math.floor(g() * n)]; bs.push(s / n); }
  bs.sort((a, b) => a - b); const sl = l.reduce((s, v) => s + v, 0);
  return { trades: n, win_rate: +(w.length / n).toFixed(3), expectancy_R: +mean.toFixed(3),
           profit_factor: sl < 0 ? +(w.reduce((s, v) => s + v, 0) / -sl).toFixed(2) : null,
           total_R: +R.reduce((s, v) => s + v, 0).toFixed(2), max_dd_R: +dd.toFixed(2),
           ret_pct: +tr.reduce((s, t) => s + t.pct, 0).toFixed(3), ic95_R: [+bs[49].toFixed(3), +bs[1949].toFixed(3)] };
}
function bh(b, from, to) { const s = b.filter(r => r[0] >= from && r[0] < to); if (!s.length) return null;
  return +((s[s.length - 1][4] / s[0][1] - 1) * 100).toFixed(2); }
function runWindow(D, sc, from, to) {
  const sigs = {}, series = {}, perCoin = {}, f = x => +(+x).toPrecision(6);
  for (const c of COINS) { sigs[c] = E.signals(D[c], sc, c, from, to - TF[sc.setup]); series[c] = D[c][sc.setup]; }
  const port = E.portfolio(series, sigs, sc, to);
  for (const c of COINS) { const one = E.portfolio({ [c]: series[c] }, { [c]: sigs[c] }, sc, to);
    perCoin[c] = { ...metrics(one.trades), signals: sigs[c].size, open: one.open.length,
                   open_R: +one.open.reduce((s, p) => s + p.R, 0).toFixed(3), buy_hold_pct: bh(series[c], from, to) }; }
  return { from, to, portfolio: { ...metrics(port.trades), open: port.open.length,
           open_pct: +port.open.reduce((s, p) => s + p.pct, 0).toFixed(3) }, per_coin: perCoin,
    trades: port.trades.map(t => ({ pair: t.pair, in: t.entry_time, out: t.exit_time, entry: f(t.entry), exit: f(t.exit),
                                    why: t.reason, R: +t.R.toFixed(3), cs: t.cs, pct: +t.pct.toFixed(3) })),
    open_positions: port.open.map(p => ({ pair: p.pair, in: p.entry_time, entry: f(p.entry), mark: f(p.mark), sl: f(p.sl),
                                          tp: f(p.tp), R: +p.R.toFixed(3), cs: p.cs, pct: +p.pct.toFixed(3) })),
    signals: Object.fromEntries(COINS.map(c => [c, [...sigs[c].values()].map(s => s.decided)])) };
}

(async () => {
  const now = Date.now();
  fs.mkdirSync(OUT, { recursive: true });
  if (now > FINAL + 2 * 36e5) { console.log("Prueba terminada (corte final pasado): no se descarga nada."); return; }
  if (now < START) { console.log("La ventana aún no empieza."); }
  let host = await pickBinance(), source = host ? `Binance (${host})` : "Coinbase (respaldo: Binance bloqueó la IP del runner)";
  console.log("Fuente:", source);
  const D = {};
  for (const c of COINS) { D[c] = {};
    for (const tf of Object.keys(NEED_DAYS)) {
      const since = now - NEED_DAYS[tf] * DAY;
      D[c][tf] = (host ? await binanceKlines(host, c, tf, since) : await coinbaseKlines(c, tf, since)).filter(r => r[0] + TF[tf] <= now);
    } }
  for (const c of COINS) D[c].btc1d = D.BTCUSDT["1d"];
  const dataUntil = Math.min(...COINS.map(c => D[c]["5m"].at(-1)[0] + TF["5m"]));
  const snap = to => ({ generated_utc: new Date(now).toISOString(), source, code_hash: PRE.hash_codigo, window_start: START, to,
    data_until: dataUntil, last_price: Object.fromEntries(COINS.map(c => [c, D[c]["5m"].at(-1)[4]])),
    scales: Object.fromEntries(Object.entries(SCALES).map(([n, sc]) => [n, runWindow(D, sc, START, to)])) });
  const latest = snap(Math.min(dataUntil, FINAL));
  fs.writeFileSync(path.join(OUT, "latest.json"), JSON.stringify(latest));
  for (const [name, ts] of Object.entries(CUTS)) {
    const file = path.join(OUT, `${name}.json`);
    if (dataUntil >= ts && !fs.existsSync(file)) { fs.writeFileSync(file, JSON.stringify(snap(ts))); console.log("Corte guardado:", name); }
  }
  const log = path.join(OUT, "runs.csv");
  if (!fs.existsSync(log)) fs.writeFileSync(log, "generated_utc,source,data_until,swing_trades,swing_ret_pct,intradia_trades,intradia_ret_pct,scalp_trades,scalp_ret_pct\n");
  const p = n => latest.scales[n].portfolio;
  fs.appendFileSync(log, [latest.generated_utc, JSON.stringify(source), new Date(dataUntil).toISOString(),
    p("swing").trades, p("swing").ret_pct ?? 0, p("intradia").trades, p("intradia").ret_pct ?? 0, p("scalp").trades, p("scalp").ret_pct ?? 0].join(",") + "\n");
  console.log(JSON.stringify(Object.fromEntries(Object.keys(SCALES).map(n => [n, latest.scales[n].portfolio]))));
  // tablero (solo lectura de resultados; si falla no afecta la prueba)
  try { console.log("tablero:", JSON.stringify(require("./report.js").build())); }
  catch (e) { console.error("tablero falló (la prueba sigue):", e.message); }
})().catch(e => { console.error(e); process.exit(1); });
