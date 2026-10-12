// Corre el motor JS sobre los mismos CSV que backtest.py y emite señales + trades para comparar con Python.
const fs = require("fs"), E = require("./engine.js");
const dir = process.argv[2], pairs = process.argv[3].split(","), start = Date.parse(process.argv[4]);
const load = (p, tf) => fs.readFileSync(`${dir}/${p}_${tf}.csv`, "utf8").trim().split("\n").slice(1)
  .map(l => l.split(",").map(Number));
const scale = { htf: "1d", setup: "4h", trigger: "1h" };
const data = {}, sigs = {}, series = {};
for (const p of pairs) data[p] = { "1d": load(p, "1d"), "4h": load(p, "4h"), "1h": load(p, "1h") };
for (const p of pairs) { data[p].btc1d = data["BTCUSDT"]["1d"];
  sigs[p] = E.signals(data[p], scale, p, start + E.TF["4h"], Infinity); series[p] = data[p]["4h"]; }
const res = E.portfolio(series, sigs, scale, Infinity);
console.log(JSON.stringify({ signals: Object.fromEntries(pairs.map(p => [p, [...sigs[p].entries()].map(([t, s]) => [t, s.cs, +s.sl_ref.toFixed(4)])])),
  trades: res.trades.map(t => [t.pair, t.entry_time, t.exit_time, t.reason, +t.R.toFixed(6)]) }));
