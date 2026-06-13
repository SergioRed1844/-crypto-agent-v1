// ═══════════════════════════════════════════════════════════
// CryptoAgent v1.0 — Google Apps Script
// Recibe datos del servidor y los escribe en Google Sheet
// 
// INSTRUCCIONES DE INSTALACIÓN:
// 1. Abre tu Google Sheet del feedback loop
// 2. Menú: Extensiones → Apps Script
// 3. Borra el código que haya y pega TODO este código
// 4. Click "Guardar" (ícono de disquete)
// 5. Click "Implementar" → "Nueva implementación"
// 6. Tipo: "Aplicación web"
// 7. Ejecutar como: "Yo" (tu cuenta)
// 8. Acceso: "Cualquier persona"
// 9. Click "Implementar"
// 10. Copia la URL que te da — esa va como variable en Render
// ═══════════════════════════════════════════════════════════

// Nombre de la hoja principal (debe coincidir con tu Sheet)
const SHEET_NAME = "Trade Log";
const DASHBOARD_SHEET = "Dashboard Métricas";
const PARAMS_SHEET = "Parámetros Dinámicos";

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const action = data.action || "log_trade";
    
    let result;
    switch(action) {
      case "log_trade":
        result = logTrade(data);
        break;
      case "close_trade":
        result = closeTrade(data);
        break;
      case "update_param":
        result = updateParam(data);
        break;
      case "get_feedback":
        result = getFeedback(data);
        break;
      case "get_recent_trades":
        result = getRecentTrades(data);
        break;
      default:
        result = { ok: false, error: "Unknown action: " + action };
    }
    
    return ContentService
      .createTextOutput(JSON.stringify(result))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch(err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  // Para test: abre la URL en el navegador
  const action = e.parameter.action || "status";
  
  if (action === "status") {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = ss.getSheetByName(SHEET_NAME);
    const lastRow = sheet.getLastRow();
    return ContentService
      .createTextOutput(JSON.stringify({
        ok: true,
        status: "CryptoAgent Google Sheet Bridge active",
        total_rows: lastRow - 2, // minus header and description rows
        sheet_name: SHEET_NAME
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
  
  if (action === "get_feedback") {
    const result = getFeedback({});
    return ContentService
      .createTextOutput(JSON.stringify(result))
      .setMimeType(ContentService.MimeType.JSON);
  }
  
  return ContentService
    .createTextOutput(JSON.stringify({ ok: true, msg: "Use POST to send data" }))
    .setMimeType(ContentService.MimeType.JSON);
}


// ═══════════════════════════════════════════════════════════
// LOG A NEW TRADE (signal received, executed or rejected)
// ═══════════════════════════════════════════════════════════
function logTrade(data) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME);
  
  if (!sheet) return { ok: false, error: "Sheet '" + SHEET_NAME + "' not found" };
  
  const lastRow = sheet.getLastRow();
  const newRow = lastRow + 1;
  
  // Compute rolling metrics from existing data
  const rollingStats = computeRollingStats(sheet, lastRow);
  
  // Map data to the 39 columns (A to AM)
  const row = [
    data.trade_id || "",                          // A: trade_id
    data.timestamp || new Date().toISOString(),    // B: timestamp
    data.pair || "",                               // C: par
    data.direction || "",                          // D: dirección
    data.bucket || "",                             // E: bucket
    data.template || "",                           // F: template_usado
    data.regime_btc || "",                         // G: régimen_BTC
    data.trend_regime || "",                       // H: trend_regime
    data.vol_regime || "",                         // I: vol_regime
    data.fear_greed || "",                         // J: fear_greed
    data.funding_rate || "",                       // K: funding_rate
    data.confluence_score || "",                   // L: confluence_score
    data.confidence || "",                         // M: confidence_%
    data.entry_price || "",                        // N: entry_price
    data.stop_loss || "",                          // O: stop_loss
    data.take_profit_1 || "",                      // P: take_profit_1
    data.take_profit_2 || "",                      // Q: take_profit_2
    data.position_size_pct || "",                  // R: position_size_%
    data.risk_R || "1R",                           // S: riesgo_R
    data.edge_description || "",                   // T: edge_description
    data.ejecutado ? "SÍ" : "NO",                 // U: ejecutado
    data.motivo_no_ejecutar || "",                 // V: motivo_no_ejecutar
    "",                                            // W: precio_cierre (filled on close)
    "",                                            // X: resultado (filled on close)
    "",                                            // Y: pnl_usdt (filled on close)
    "",                                            // Z: pnl_R (filled on close)
    "",                                            // AA: duración_horas (filled on close)
    "",                                            // AB: motivo_cierre (filled on close)
    "",                                            // AC: SL_demasiado_corto (filled on close)
    "",                                            // AD: TP_demasiado_alto (filled on close)
    "",                                            // AE: régimen_cambió (filled on close)
    "",                                            // AF: estrategia_correcta (filled on close)
    data.reasoning || "",                          // AG: notas_post_trade
    rollingStats.win_rate_10,                      // AH: win_rate_10
    rollingStats.avg_rr_10,                        // AI: avg_RR_10
    rollingStats.satellite_pct,                    // AJ: satellite_%
    rollingStats.drawdown_daily,                   // AK: drawdown_diario_%
    rollingStats.drawdown_weekly,                  // AL: drawdown_semanal_%
    "",                                            // AM: ajuste_recomendado
    // ── GRAHAM v6 audit trail (Phase 2/4): logged on every decision incl NO_TRADE ──
    data.posture_used || "",                       // AN: postura_usada
    data.rr_pesimista || "",                       // AO: RR_pesimista
    data.bear_case || "",                          // AP: tesis_en_contra (pre-mortem)
    data.bias_check || ""                          // AQ: bias_check (JSON 6 chequeos)
  ];
  
  sheet.getRange(newRow, 1, 1, row.length).setValues([row]);
  
  // Color code the row
  if (data.ejecutado) {
    // Will be colored on close (WIN=green, LOSS=red)
  } else {
    sheet.getRange(newRow, 1, 1, row.length).setBackground("#F2F2F2"); // Gray for skipped
  }
  
  return { 
    ok: true, 
    trade_id: data.trade_id, 
    row: newRow,
    rolling_stats: rollingStats
  };
}


// ═══════════════════════════════════════════════════════════
// CLOSE A TRADE (update the row with results)
// ═══════════════════════════════════════════════════════════
function closeTrade(data) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME);
  
  if (!sheet) return { ok: false, error: "Sheet not found" };
  
  const tradeId = data.trade_id;
  if (!tradeId) return { ok: false, error: "trade_id required" };
  
  // Find the row with this trade_id
  const lastRow = sheet.getLastRow();
  const tradeIds = sheet.getRange("A3:A" + lastRow).getValues();
  let targetRow = -1;
  
  for (let i = 0; i < tradeIds.length; i++) {
    if (tradeIds[i][0] === tradeId) {
      targetRow = i + 3; // +3 because data starts at row 3
      break;
    }
  }
  
  if (targetRow === -1) return { ok: false, error: "Trade " + tradeId + " not found" };
  
  // Update close columns (W to AF)
  sheet.getRange(targetRow, 23).setValue(data.close_price || "");      // W: precio_cierre
  sheet.getRange(targetRow, 24).setValue(data.resultado || "");         // X: resultado
  sheet.getRange(targetRow, 25).setValue(data.pnl_usdt || "");         // Y: pnl_usdt
  sheet.getRange(targetRow, 26).setValue(data.pnl_R || "");            // Z: pnl_R
  sheet.getRange(targetRow, 27).setValue(data.duration_hours || "");    // AA: duración_horas
  sheet.getRange(targetRow, 28).setValue(data.motivo_cierre || "");     // AB: motivo_cierre
  sheet.getRange(targetRow, 29).setValue(data.sl_too_short || "");      // AC: SL_demasiado_corto
  sheet.getRange(targetRow, 30).setValue(data.tp_too_high || "");       // AD: TP_demasiado_alto
  sheet.getRange(targetRow, 31).setValue(data.regime_changed || "");    // AE: régimen_cambió
  sheet.getRange(targetRow, 32).setValue(data.strategy_correct || "");  // AF: estrategia_correcta
  sheet.getRange(targetRow, 33).setValue(data.post_trade_notes || "");  // AG: notas_post_trade
  
  // Update rolling stats
  const rollingStats = computeRollingStats(sheet, lastRow);
  sheet.getRange(targetRow, 34).setValue(rollingStats.win_rate_10);
  sheet.getRange(targetRow, 35).setValue(rollingStats.avg_rr_10);
  sheet.getRange(targetRow, 36).setValue(rollingStats.satellite_pct);
  sheet.getRange(targetRow, 37).setValue(rollingStats.drawdown_daily);
  sheet.getRange(targetRow, 38).setValue(rollingStats.drawdown_weekly);
  
  // Generate adjustment recommendation
  const adjustment = generateAdjustment(rollingStats, data);
  sheet.getRange(targetRow, 39).setValue(adjustment);
  
  // Color code row based on result
  const bgColor = data.resultado === "WIN" ? "#E2EFDA" : 
                   data.resultado === "LOSS" ? "#FCE4D6" : "#FFF2CC";
  sheet.getRange(targetRow, 1, 1, 39).setBackground(bgColor);
  
  return { 
    ok: true, 
    trade_id: tradeId, 
    row: targetRow, 
    resultado: data.resultado,
    rolling_stats: rollingStats,
    adjustment: adjustment
  };
}


// ═══════════════════════════════════════════════════════════
// COMPUTE ROLLING STATISTICS
// ═══════════════════════════════════════════════════════════
function computeRollingStats(sheet, lastRow) {
  if (lastRow < 3) return { win_rate_10: "", avg_rr_10: "", satellite_pct: "20%", drawdown_daily: "", drawdown_weekly: "" };
  
  // Get last 10 closed trades
  const startRow = Math.max(3, lastRow - 9);
  const range = sheet.getRange(startRow, 1, lastRow - startRow + 1, 39);
  const data = range.getValues();
  
  let wins = 0, losses = 0, totalRR = 0, rrCount = 0;
  let dailyPnl = 0, weeklyPnl = 0;
  const today = new Date();
  const weekAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
  const dayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  
  let satWins = 0, satTotal = 0;
  
  for (let i = 0; i < data.length; i++) {
    const resultado = data[i][23]; // Column X (0-indexed = 23)
    const pnlR = data[i][25];     // Column Z
    const bucket = data[i][4];     // Column E
    const pnlUsdt = data[i][24];   // Column Y
    const timestamp = data[i][1];  // Column B
    
    if (resultado === "WIN") wins++;
    if (resultado === "LOSS") losses++;
    
    if (pnlR && pnlR !== "") {
      const rVal = parseFloat(String(pnlR).replace("R", "").replace("+", ""));
      if (!isNaN(rVal)) {
        totalRR += rVal;
        rrCount++;
      }
    }
    
    if (bucket === "SATELLITE" && (resultado === "WIN" || resultado === "LOSS")) {
      satTotal++;
      if (resultado === "WIN") satWins++;
    }
    
    // Daily/weekly PnL
    if (pnlUsdt && pnlUsdt !== "") {
      const pnl = parseFloat(pnlUsdt);
      if (!isNaN(pnl)) {
        weeklyPnl += pnl;
        if (timestamp && new Date(timestamp) >= dayStart) {
          dailyPnl += pnl;
        }
      }
    }
  }
  
  const total = wins + losses;
  const winRate = total > 0 ? (wins / total * 100).toFixed(0) + "%" : "";
  const avgRR = rrCount > 0 ? (totalRR / rrCount).toFixed(2) + ":1" : "";
  
  // Dynamic satellite adjustment
  let satellitePct = 20; // default
  if (satTotal >= 5) {
    const satWR = satWins / satTotal;
    if (satWR > 0.55) satellitePct = Math.min(30, satellitePct + 5);
    if (satWR < 0.40) satellitePct = Math.max(10, satellitePct - 5);
  }
  
  return {
    win_rate_10: winRate,
    avg_rr_10: avgRR,
    satellite_pct: satellitePct + "%",
    drawdown_daily: dailyPnl !== 0 ? dailyPnl.toFixed(2) : "",
    drawdown_weekly: weeklyPnl !== 0 ? weeklyPnl.toFixed(2) : ""
  };
}


// ═══════════════════════════════════════════════════════════
// GENERATE ADJUSTMENT RECOMMENDATION
// ═══════════════════════════════════════════════════════════
function generateAdjustment(stats, tradeData) {
  const parts = [];
  
  // Parse win rate
  const wr = parseFloat(stats.win_rate_10);
  if (!isNaN(wr)) {
    if (wr < 40) parts.push("Win rate bajo (" + wr + "%). Reducir size 50%.");
    if (wr > 60) parts.push("Win rate saludable (" + wr + "%). Mantener estrategia.");
  }
  
  // SL analysis
  if (tradeData.sl_too_short === "SÍ") {
    parts.push("SL muy corto. Considerar ATR*2.5.");
  }
  if (tradeData.tp_too_high === "SÍ") {
    parts.push("TP inalcanzable. Reducir a 1.5R.");
  }
  if (tradeData.regime_changed === "SÍ") {
    parts.push("Régimen cambió mid-trade. Agregar time stop más agresivo.");
  }
  
  return parts.join(" | ") || "Sin ajustes necesarios.";
}


// ═══════════════════════════════════════════════════════════
// GET FEEDBACK FOR AGENT (called before each trade decision)
// ═══════════════════════════════════════════════════════════
function getFeedback(data) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME);
  const lastRow = sheet.getLastRow();
  
  if (lastRow < 3) return { ok: true, feedback: "No trades yet. No feedback available.", trades: 0 };
  
  // I-01/I-02: Filter by pair if provided
  const filterPair = (data.pair || "").toUpperCase();
  
  // Get all trade data
  const allData = sheet.getRange(3, 1, lastRow - 2, 39).getValues();
  
  // Filter by pair if specified
  const filtered = filterPair 
    ? allData.filter(r => String(r[2]).toUpperCase() === filterPair) 
    : allData;
  
  // Take last 10 of filtered set
  const recent = filtered.slice(-10);
  
  if (recent.length === 0) {
    return { ok: true, feedback: filterPair ? "No trades for " + filterPair : "No trades yet", trades: 0 };
  }
  
  // Compute stats from filtered data
  let wins = 0, losses = 0, totalRR = 0, rrCount = 0;
  let slTooShort = 0, tpTooHigh = 0, staleCount = 0;
  
  for (let i = 0; i < recent.length; i++) {
    const resultado = recent[i][23]; // Column X
    const pnlR = recent[i][25];     // Column Z
    const motivo = String(recent[i][21] || ""); // Column V: motivo_no_ejecutar
    
    if (resultado === "WIN") wins++;
    if (resultado === "LOSS") losses++;
    if (recent[i][28] === "SÍ") slTooShort++;
    if (recent[i][29] === "SÍ") tpTooHigh++;
    if (motivo.toLowerCase().indexOf("stale") >= 0) staleCount++;
    
    if (pnlR && pnlR !== "") {
      const rVal = parseFloat(String(pnlR).replace("R", "").replace("+", ""));
      if (!isNaN(rVal)) { totalRR += rVal; rrCount++; }
    }
  }
  
  const total = wins + losses;
  const feedbackParts = [];
  const prefix = filterPair || "ALL";

  if (total > 0) {
    const avgR = rrCount > 0 ? (totalRR/rrCount).toFixed(2) : "0.00";
    feedbackParts.push(prefix + " last " + recent.length + ": " + wins + "W/" + losses + "L WR:" + Math.round(wins/total*100) + "% avgR:" + avgR);
  }
  // Per-context breakdowns: win rate by regime (col G=6) and by template (col F=5).
  feedbackParts.push.apply(feedbackParts, wrBreakdown_(recent, 6, "regime"));
  feedbackParts.push.apply(feedbackParts, wrBreakdown_(recent, 5, "tmpl"));

  if (slTooShort >= 2) feedbackParts.push("⚠ " + slTooShort + " stops too tight → widen stops");
  if (tpTooHigh >= 2) feedbackParts.push("⚠ " + tpTooHigh + " targets too far → take profit sooner");
  if (staleCount >= 2) feedbackParts.push(staleCount + " stale signal rejections.");

  return {
    ok: true,
    trades: recent.length,
    pair_filter: filterPair || "ALL",
    feedback: feedbackParts.join(" | ") || "No closed trades for " + prefix
  };
}

// Win-rate breakdown by a column (e.g. regime, template). Only groups with >=3 decided trades.
function wrBreakdown_(rows, colIdx, label) {
  const groups = {};
  for (let i = 0; i < rows.length; i++) {
    const res = rows[i][23]; // resultado (col X)
    if (res !== "WIN" && res !== "LOSS") continue;
    const g = String(rows[i][colIdx] || "?");
    if (!groups[g]) groups[g] = [0, 0];
    groups[g][res === "WIN" ? 0 : 1]++;
  }
  const out = [];
  for (const g in groups) {
    const w = groups[g][0], l = groups[g][1];
    if (w + l >= 3) out.push(label + ":" + g + " " + w + "W/" + l + "L(" + Math.round(w/(w+l)*100) + "%)");
  }
  return out;
}


// ═══════════════════════════════════════════════════════════
// GET RECENT TRADES (for agent context)
// ═══════════════════════════════════════════════════════════
function getRecentTrades(data) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME);
  const lastRow = sheet.getLastRow();
  const n = data.n || 10;
  
  if (lastRow < 3) return { ok: true, trades: [] };
  
  const startRow = Math.max(3, lastRow - n + 1);
  const range = sheet.getRange(startRow, 1, lastRow - startRow + 1, 39);
  const values = range.getValues();
  
  const trades = values.map(r => ({
    trade_id: r[0], timestamp: r[1], pair: r[2], direction: r[3],
    bucket: r[4], template: r[5], regime: r[6], confluence: r[11],
    entry: r[13], sl: r[14], tp1: r[15], ejecutado: r[20],
    resultado: r[23], pnl_usdt: r[24], pnl_R: r[25],
    sl_too_short: r[28], tp_too_high: r[29]
  }));
  
  return { ok: true, trades: trades };
}


// ═══════════════════════════════════════════════════════════
// UPDATE DYNAMIC PARAMETER
// ═══════════════════════════════════════════════════════════
function updateParam(data) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(PARAMS_SHEET);
  
  if (!sheet) return { ok: false, error: "Params sheet not found" };
  
  const paramName = data.param_name;
  const newValue = data.new_value;
  const reason = data.reason || "";
  
  // Find the parameter row
  const lastRow = sheet.getLastRow();
  const params = sheet.getRange("A3:A" + lastRow).getValues();
  
  for (let i = 0; i < params.length; i++) {
    if (params[i][0] === paramName) {
      const row = i + 3;
      const oldValue = sheet.getRange(row, 2).getValue();
      sheet.getRange(row, 2).setValue(newValue);
      sheet.getRange(row, 4).setValue(new Date().toISOString());
      sheet.getRange(row, 5).setValue(reason);
      
      // Also log in history section
      const historyStart = 19; // Row 19 is where history starts
      const histLastRow = sheet.getRange("A" + historyStart + ":A100").getValues().filter(r => r[0] !== "").length;
      const histRow = historyStart + histLastRow;
      sheet.getRange(histRow, 1).setValue(new Date().toISOString());
      sheet.getRange(histRow, 2).setValue(paramName);
      sheet.getRange(histRow, 3).setValue(oldValue);
      sheet.getRange(histRow, 4).setValue(newValue);
      sheet.getRange(histRow, 5).setValue(reason);
      
      return { ok: true, param: paramName, old: oldValue, new: newValue };
    }
  }
  
  return { ok: false, error: "Parameter '" + paramName + "' not found" };
}
