// Tablero en GitHub: genera forward/results/README.md + curva.svg + equity.csv a partir de los resultados.
// Solo LEE resultados: no toca reglas, motor ni prerregistro. Lo llama run_forward.js al final de cada corrida;
// también se puede correr suelto: node forward/report.js
const fs = require("fs"), path = require("path");
const DIR = __dirname, RES = path.join(DIR, "results"), EQ = 1000, H = 36e5, DAY = 864e5, MTY = -6 * H;
const NAMES = { swing: "Swing", intradia: "Intradía", scalp: "Scalp" };
const TFS = { swing: "1D / 4H / 1H", intradia: "4H / 1H / 15m", scalp: "1H / 15m / 5m" };
const COLORS = { swing: "#2563eb", intradia: "#ea580c", scalp: "#7c3aed" };
const CUT_NAMES = { corte_1: "Corte 1", corte_2: "Corte 2", corte_final: "Corte final" };
const WHY = { SL: "stop", SL_GAP: "stop (hueco)", TP: "objetivo" };
const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const p2 = n => String(n).padStart(2, "0");
const mty = (ms, withDay = true) => { const d = new Date(ms + MTY);
  return `${withDay ? `${DIAS[d.getUTCDay()]} ${d.getUTCDate()} ${MESES[d.getUTCMonth()]} ` : ""}${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`; };
const usd = pct => (pct || 0) / 100 * EQ;
const sgn = (v, d = 2) => { const r = +(+v).toFixed(d); return (r > 0 ? "+" : r < 0 ? "−" : "") + Math.abs(r).toFixed(d); };
const pctf = v => (v == null ? "—" : `${Math.round(v * 100)}%`);
const px = v => (v == null ? "—" : Math.abs(v) >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 2 }) : String(v));
const coin = s => s.replace("USDT", "");
const read = f => JSON.parse(fs.readFileSync(f, "utf8"));
const totals = s => { const p = s.portfolio, c = usd(p.ret_pct), f = usd(p.open_pct);
  return { c, f, t: c + f, n: p.trades || 0, open: p.open || 0, wr: p.win_rate }; };
const isNum = v => /^[*+\-−]*[\d—]/.test(String(v));  // columnas numéricas a la derecha, texto a la izquierda
const table = (head, rows) => [`| ${head.join(" | ")} |`,
  `|${head.map((h, i) => (i && rows.length && rows.every(r => isNum(r[i])) ? " ---: " : " --- ")).join("|")}|`,
  ...rows.map(r => `| ${r.join(" | ")} |`)].join("\n");

function nice(x) { const p = 10 ** Math.floor(Math.log10(x)), f = x / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; }

function chart(hist, START, FINAL, cuts, scales) {
  const W = 760, HT = 330, m = { l: 52, r: 112, t: 58, b: 34 }, iw = W - m.l - m.r, ih = HT - m.t - m.b;
  const pts = [{ t: START, ...Object.fromEntries(scales.map(k => [k, 0])) }, ...hist.filter(h => h.t > START && h.t <= FINAL)];
  const vals = pts.flatMap(p => scales.map(k => p[k]));
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (hi - lo < 20) { const mid = (hi + lo) / 2; lo = Math.min(lo, mid - 10); hi = Math.max(hi, mid + 10); }
  const step = nice((hi - lo) / 5); lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
  const x = t => m.l + (t - START) / (FINAL - START) * iw, y = v => m.t + (hi - v) / (hi - lo) * ih;
  const o = [`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${HT}" viewBox="0 0 ${W} ${HT}" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">`,
    `<rect x="0.5" y="0.5" width="${W - 1}" height="${HT - 1}" rx="10" fill="#ffffff" stroke="#e5e7eb"/>`,
    `<text x="${m.l}" y="22" font-size="14" font-weight="600" fill="#111827">P&amp;L por escala: cerrado + flotante (USDT sobre 1,000 hipotéticos)</text>`];
  for (let v = lo; v <= hi + step / 2; v += step) {
    const yy = y(v).toFixed(1), zero = Math.abs(v) < step / 1e6;
    o.push(`<line x1="${m.l}" x2="${m.l + iw}" y1="${yy}" y2="${yy}" stroke="${zero ? "#6b7280" : "#eef0f3"}" stroke-width="${zero ? 1.2 : 1}"/>`,
      `<text x="${m.l - 8}" y="${(+yy + 4).toFixed(1)}" font-size="11" fill="#6b7280" text-anchor="end">${zero ? "0" : sgn(v, step < 1 ? 1 : 0)}</text>`);
  }
  for (let t = Math.ceil((START + MTY) / DAY) * DAY - MTY; t < FINAL; t += DAY) {
    const d = new Date(t + MTY);
    o.push(`<line x1="${x(t).toFixed(1)}" x2="${x(t).toFixed(1)}" y1="${m.t + ih}" y2="${m.t + ih + 5}" stroke="#9ca3af"/>`,
      `<text x="${x(t).toFixed(1)}" y="${m.t + ih + 18}" font-size="11" fill="#6b7280" text-anchor="middle">${DIAS[d.getUTCDay()]} ${d.getUTCDate()}</text>`);
  }
  o.push(`<text x="${m.l}" y="${m.t + ih + 18}" font-size="11" fill="#6b7280" text-anchor="start">inicio</text>`,
    `<text x="${m.l + iw}" y="${m.t + ih + 18}" font-size="11" fill="#9ca3af" text-anchor="end">hora de Monterrey</text>`);
  for (const c of cuts) {
    const xx = x(c.ts).toFixed(1);
    o.push(`<line x1="${xx}" x2="${xx}" y1="${m.t - 4}" y2="${m.t + ih}" stroke="#9ca3af" stroke-dasharray="4 4"/>`,
      `<text x="${xx}" y="${m.t - 10}" font-size="11" fill="#374151" text-anchor="${c.k === "corte_final" ? "end" : "middle"}">${CUT_NAMES[c.k]} · ${mty(c.ts, false)}</text>`);
  }
  const labels = [];
  for (const k of scales) {
    const line = pts.map(p => `${x(p.t).toFixed(1)},${y(p[k]).toFixed(1)}`).join(" "), last = pts.at(-1);
    o.push(`<polyline points="${line}" fill="none" stroke="${COLORS[k]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`,
      `<circle cx="${x(last.t).toFixed(1)}" cy="${y(last[k]).toFixed(1)}" r="3.5" fill="${COLORS[k]}" stroke="#ffffff" stroke-width="1.5"/>`);
    labels.push({ k, x: x(last.t) + 8, y: y(last[k]) + 4, v: last[k] });
  }
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 14) labels[i].y = labels[i - 1].y + 14;
  for (const l of labels) o.push(`<text x="${l.x.toFixed(1)}" y="${l.y.toFixed(1)}" font-size="11.5" font-weight="600" fill="${COLORS[l.k]}">${NAMES[l.k]} ${sgn(l.v)}</text>`);
  o.push("</svg>");
  return o.join("\n");
}

function build() {
  const pre = read(path.join(DIR, "prerregistro.json")), base = read(path.join(DIR, "baseline_historica.json"));
  const L = read(path.join(RES, "latest.json")), scales = Object.keys(L.scales);
  const START = Date.parse(pre.inicio_ventana_utc);
  const cuts = Object.entries(pre.cortes_utc).map(([k, v]) => ({ k, ts: Date.parse(v) }));
  const FINAL = Date.parse(pre.cortes_utc.corte_final), upTo = L.to;

  // historial hora por hora (para la curva): una fila por corrida, sin duplicados
  const eqFile = path.join(RES, "equity.csv");
  const hdr = "hasta_utc,generado_utc," + scales.flatMap(k => [`${k}_cerrado_usdt`, `${k}_flotante_usdt`]).join(",");
  let rows = fs.existsSync(eqFile) ? fs.readFileSync(eqFile, "utf8").trim().split("\n").slice(1).filter(Boolean) : [];
  const key = new Date(upTo).toISOString();
  if (!rows.some(r => r.startsWith(key + ","))) {
    rows.push([key, L.generated_utc, ...scales.flatMap(k => { const t = totals(L.scales[k]); return [t.c.toFixed(2), t.f.toFixed(2)]; })].join(","));
    rows.sort();
  }
  fs.writeFileSync(eqFile, hdr + "\n" + rows.join("\n") + "\n");
  const hist = rows.map(r => { const v = r.split(","), o = { t: Date.parse(v[0]) };
    scales.forEach((k, i) => { o[k] = +v[2 + 2 * i] + +v[3 + 2 * i]; }); return o; });
  fs.writeFileSync(path.join(RES, "curva.svg"), chart(hist, START, FINAL, cuts, scales));

  const T = Object.fromEntries(scales.map(k => [k, totals(L.scales[k])]));
  const sum = f => scales.reduce((s, k) => s + T[k][f], 0);
  const next = cuts.find(c => upTo < c.ts);
  const md = [];
  md.push("# CryptoAgent v4.1 — prueba en papel", "",
    "> **Simulación con dinero hipotético.** No hay keys ni órdenes reales: el bot solo lee velas públicas de Binance y calcula qué habría hecho con las reglas congeladas.", "",
    `**Actualizado:** ${mty(Date.parse(L.generated_utc))} (Monterrey) · velas hasta ${mty(upTo)} · fuente ${L.source.replace(/^Binance \(https:\/\/(.*)\)$/, "Binance ($1)")}  `,
    `**Estado:** ${next ? `en curso — próximo corte: **${CUT_NAMES[next.k]}, ${mty(next.ts)}** (Monterrey)` : "**terminada** — corte final guardado"}  `,
    `**Ventana:** ${mty(START)} → ${mty(FINAL)} (Monterrey) · 8 monedas × 3 escalas · cuenta de 1,000 USDT por escala · 0.5% de riesgo por trade (1R ≈ 5 USDT) · comisión y slippage incluidos`, "",
    `**Las 3 escalas juntas (3,000 hipotéticos): ${sgn(sum("t"))} USDT** — cerrado ${sgn(sum("c"))}, flotante ${sgn(sum("f"))}, ${sum("n")} trades cerrados, ${sum("open")} posiciones abiertas.`, "",
    "![P&L por escala](curva.svg)", "",
    "## Resumen por escala", "",
    table(["Escala", "Trades cerrados", "Ganadas", "Cerrado USDT", "Flotante USDT", "**Total USDT**", "Abiertas", "Señales de compra"],
      scales.map(k => [`${NAMES[k]} (${TFS[k]})`, T[k].n, T[k].n ? pctf(T[k].wr) : "—", sgn(T[k].c), sgn(T[k].f), `**${sgn(T[k].t)}**`, T[k].open,
        Object.values(L.scales[k].signals).reduce((s, v) => s + v.length, 0)])), "");

  md.push("## Cortes", "", "Cada corte se congela una sola vez al pasar su hora (no se reescribe).", "",
    table(["Corte", "Hora (Monterrey)", "Estado", ...scales.map(k => `${NAMES[k]} USDT`), "Trades cerrados"],
      cuts.map(c => { const f = path.join(RES, `${c.k}.json`);
        if (!fs.existsSync(f)) return [CUT_NAMES[c.k], mty(c.ts), "pendiente", ...scales.map(() => "—"), "—"];
        const cj = read(f);
        return [CUT_NAMES[c.k], mty(c.ts), "guardado", ...scales.map(k => sgn(totals(cj.scales[k]).t)),
          scales.reduce((s, k) => s + (cj.scales[k].portfolio.trades || 0), 0)]; })), "");

  const open = scales.flatMap(k => L.scales[k].open_positions.map(p => ({ k, ...p })));
  md.push("## Posiciones abiertas", "", "Lo flotante ya descuenta la comisión de entrada y de salida: una posición apenas arriba de su precio de entrada todavía sale negativa.", "");
  md.push(open.length ? table(["Escala", "Moneda", "Entrada (Monterrey)", "Precio entrada", "Precio actual", "Stop", "Objetivo", "R flotante", "USDT flotante"],
    open.map(p => [NAMES[p.k], coin(p.pair), mty(p.in), px(p.entry), px(p.mark), px(p.sl), px(p.tp), sgn(p.R), sgn(usd(p.pct))])) : "Ninguna.", "");

  const closed = scales.flatMap(k => L.scales[k].trades.map(t => ({ k, ...t }))).sort((a, b) => b.out - a.out);
  md.push("## Operaciones cerradas", "");
  md.push(closed.length ? table(["Escala", "Moneda", "Entrada", "Salida", "Precio entrada → salida", "Motivo", "R", "USDT"],
    closed.slice(0, 60).map(t => [NAMES[t.k], coin(t.pair), mty(t.in), mty(t.out), `${px(t.entry)} → ${px(t.exit)}`, WHY[t.why] || t.why, sgn(t.R), sgn(usd(t.pct))]))
    : "Todavía ninguna.", closed.length > 60 ? `\n(${closed.length - 60} más en latest.json)` : "", "");

  const coins = pre.monedas;
  const cell = (k, c) => { const m = L.scales[k].per_coin[c] || {}, n = m.trades || 0, r = (m.total_R || 0) + (m.open_R || 0);
    return n || m.open ? `${n} tr · ${sgn(r)}R${m.open ? " (abierta)" : ""}` : `— (${m.signals || 0} señ.)`; };
  md.push("## Por moneda", "", "Cada moneda corrida sola con su propia cuenta (por eso no suma igual que el portafolio). R incluye lo flotante.", "",
    table(["Moneda", ...scales.map(k => NAMES[k]), "Buy & hold desde el inicio"],
      coins.map(c => [coin(c), ...scales.map(k => cell(k, c)), (v => (v == null ? "—" : `${sgn(v)}%`))(L.scales.scalp ? L.scales.scalp.per_coin[c].buy_hold_pct : null)])), "");

  const K = base.keys, days = { swing: 365, intradia: 90, scalp: 30 };
  md.push("## Línea base histórica (mismas reglas, antes de la ventana)", "",
    table(["Escala", "Ventana", "Trades", "Ganadas", "Expectativa", "Profit factor", "Retorno", "IC95 expectativa"],
      Object.entries(base.h).map(([k, h]) => { const p = Object.fromEntries(K.map((n, i) => [n, h.port[i]])), ic = h.port[K.length];
        return [NAMES[k], `${days[k]} días`, p.trades, pctf(p.win_rate), `${sgn(p.expectancy_R, 3)}R`, p.profit_factor ?? "—", `${sgn(p.ret_pct)}%`,
          `[${sgn(ic[0], 2)}, ${sgn(ic[1], 2)}]R`]; })), "",
    "Ninguna escala mostró ventaja en el histórico: el intervalo de confianza de la expectativa incluye 0 en las tres. Con pocos trades, lo de esta ventana es sobre todo ruido; el corte final se lee contra esta tabla.", "",
    `Reglas congeladas: \`forward/prerregistro.json\` (hash del código ${pre.hash_codigo}). Motor: \`forward/engine.js\`. Datos crudos: \`latest.json\`, \`corte_*.json\`, \`equity.csv\`.`, "");
  const text = md.join("\n");
  fs.writeFileSync(path.join(RES, "README.md"), text);
  if (process.env.GITHUB_STEP_SUMMARY) {
    const repo = process.env.GITHUB_REPOSITORY || "SergioRed1844/-crypto-agent-v1";
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, text.replace("![P&L por escala](curva.svg)",
      `[Ver tablero con gráfica](https://github.com/${repo}/blob/forward-test/forward/results/README.md)`));
  }
  return { rows: rows.length, total: +sum("t").toFixed(2) };
}

module.exports = { build };
if (require.main === module) console.log("tablero:", JSON.stringify(build()));
