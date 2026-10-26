// ═══════════════════════════════════════════════════════════
// Rebotes — alerta de lunes y miércoles → tu Google Sheet (Apps Script)
// Recibe lo que manda .github/workflows/rebotes-alerta.yml (rebotes/alerta.py) y escribe 3 pestañas:
//   Señales   (agrega filas en cada corrida, con la columna "corrida")
//   Bitácora  (se reemplaza completa: todas las señales y su resultado en papel)
//   Resumen   (se reemplaza: números de la última corrida)
// Son señales del estudio, no recomendación de compra. Solo papel.
//
// INSTALACIÓN (una vez, unos 5 minutos):
//  1. Abre tu hoja → menú Extensiones → Apps Script.
//  2. Borra lo que haya en Código.gs, pega TODO este archivo y guarda (ícono de disquete).
//  3. (Recomendado) Configuración del proyecto (engrane) → Propiedades del script → Agregar propiedad:
//     nombre REB_TOKEN, valor = una frase larga que inventes. Pon la MISMA frase en GitHub →
//     Settings → Secrets and variables → Actions → New repository secret → REB_SHEET_TOKEN.
//     Sin REB_TOKEN cualquiera con la URL podría escribir en estas tres pestañas.
//  4. Implementar → Nueva implementación → tipo "Aplicación web" → Ejecutar como: "Yo" →
//     Quién tiene acceso: "Cualquier persona" → Implementar → autoriza con tu cuenta.
//  5. Copia la URL de la aplicación web (termina en /exec) y guárdala en GitHub como secreto REB_SHEET_URL.
//  6. Prueba: GitHub → Actions → rebotes-alerta → Run workflow. Deben aparecer las pestañas.
// Si cambias este código, vuelve a Implementar → Administrar implementaciones → editar → Versión nueva
// (la URL se mantiene).
// ═══════════════════════════════════════════════════════════

const REB_TABS = ["Señales", "Bitácora", "Resumen"];

function doPost(e) {
  let result;
  try {
    const data = JSON.parse(e.postData.contents);
    result = rebotesWrite(data);
  } catch (err) {
    result = { ok: false, error: String(err) };
  }
  return ContentService.createTextOutput(JSON.stringify(result)).setMimeType(ContentService.MimeType.JSON);
}

function rebotesWrite(data) {
  const expected = PropertiesService.getScriptProperties().getProperty("REB_TOKEN");
  if (expected && data.token !== expected) return { ok: false, error: "token inválido" };
  const tabs = data.tabs || {};
  // Un texto que empieza con = + - @ se volvería fórmula: se escapa con '.
  const safe = function (v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string" && /^[=+\-@]/.test(v)) return "'" + v;
    return v;
  };
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  const written = {};
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    Object.keys(tabs).forEach(function (name) {
      if (REB_TABS.indexOf(name) < 0) return;                  // solo estas pestañas
      const t = tabs[name];
      const header = t.header || [];
      if (!header.length) return;
      const rows = (t.rows || []).map(function (r) {
        return header.map(function (_, i) { return safe(r[i]); });
      });
      const sh = ss.getSheetByName(name) || ss.insertSheet(name);
      if (t.mode === "replace" || sh.getLastRow() === 0) {
        if (t.mode === "replace") sh.clearContents();
        sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight("bold");
        sh.setFrozenRows(1);
      }
      if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, header.length).setValues(rows);
      written[name] = rows.length;
    });
  } finally {
    lock.releaseLock();
  }
  return { ok: true, written: written, corrida: data.corrida || "", token: expected ? "verificado" : "sin REB_TOKEN" };
}
