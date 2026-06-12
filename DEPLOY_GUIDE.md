# CryptoAgent — Guía de Deploy (Render · Paper Trading)

Pipeline: **TradingView → Render (FastAPI) → RAG + market_context + Gemini → paper/Binance → Google Sheets.**
Esta guía refleja el código real (`server.py`, `store.py`, `valuation.py`, `render.yaml`). **No usa Telegram.**
El logging y el feedback de aprendizaje van por **Google Sheets** (`SHEETS_WEBAPP_URL`).

> 🔒 Empezamos y nos mantenemos en `PAPER_TRADING=true`. Pasar a `false` es una decisión
> **manual y humana**, sólo tras superar el gate de paper trading (final de esta guía).

---

## Paso 0 — Requisitos

- Repo en GitHub (este). Nota: el nombre empieza con guion (`-crypto-agent-v1`), lo que rompe
  algunos comandos de terminal. Recomendado renombrarlo (Settings → General → Repository name)
  y luego actualizar el remote local: `git remote set-url origin <nueva-url>`.
- Cuenta en **Render** (render.com) y en **Google** (para el Apps Script).
- `GEMINI_API_KEY` desde aistudio.google.com.

---

## Paso 1 — Desplegar el Google Apps Script (journal + feedback)

El agente registra cada decisión y lee feedback de aprendizaje desde una hoja de Google,
a través de un **Apps Script desplegado como Web App**. El script usa
`SpreadsheetApp.getActiveSpreadsheet()`, así que **DEBE crearse vinculado a una hoja**
(Extensiones → Apps Script), NO como proyecto suelto en script.google.com. Pasos exactos:

1. Crea una hoja nueva en **https://sheets.new** y nómbrala (p. ej. `CryptoAgent Journal`).
2. En esa hoja: **Extensiones → Apps Script** (crea un proyecto ligado a la hoja).
3. Borra el código por defecto y **pega todo** `google_apps_script.js` de este repo. Guarda (Ctrl/Cmd+S).
4. **Implementar → Nueva implementación** → ⚙ → **Aplicación web**; *Ejecutar como* = **Yo**;
   *Quién tiene acceso* = **Cualquier usuario**. **Implementar** → **Autorizar acceso**.
5. Copia la **URL de la app web** (termina en `/exec`). Esa es tu `SHEETS_WEBAPP_URL`.

---

## Paso 2 — Crear el servicio en Render (Blueprint)

El repo incluye `render.yaml` (infra como código): servicio web Python + **disco persistente de 1 GB
montado en `/data`** con `DATA_DIR=/data`, imprescindible para que el estado/aprendizaje (SQLite)
sobreviva a los redeploys.

1. Render → **New → Blueprint** → conecta este repo. Render lee `render.yaml`.
2. Build: `pip install -r requirements.txt` · Start: `uvicorn server:app --host 0.0.0.0 --port $PORT`
   · Health check: `/health` (ya definidos en el blueprint).
3. En **Environment**, rellena los secretos (`sync: false`, no se versionan): ver tabla abajo.
4. Deploy. (Si el servicio ya existía creado a mano, añade el **Disk** en `/data` y la variable
   `DATA_DIR=/data` desde el dashboard — el blueprint no reconfigura servicios manuales.)

### Variables de entorno (lo que el código realmente lee)

| Variable | Obligatoria | Valor / Notas |
|---|---|---|
| `GEMINI_API_KEY` | **Sí** | aistudio.google.com. Modelo `gemini-2.5-flash`. Sin ella → siempre `NO_TRADE`. |
| `WEBHOOK_SECRET` | **Sí** | Frase secreta para TradingView. Secret incorrecto → 401. |
| `SHEETS_WEBAPP_URL` | **Sí** | URL `/exec` del Apps Script del Paso 1. |
| `PAPER_TRADING` | **Sí = `true`** | Innegociable al inicio. |
| `DATA_DIR` | Recomendada | `/data` (donde `store.py` escribe `cryptoagent_state.db`). |
| `PAPER_EQUITY` | No | Capital simulado para sizing/PnL. Default **10000**. |
| `MONITOR_INTERVAL_SEC` | No | Intervalo del monitor de posiciones. Default 60. |
| `MRMARKET_ENABLED` / `MRMARKET_BLOCK_EUPHORIA` | No | Guardia conductual "Mr. Market" (Graham). Default true/true. |
| `CRYPTOPANIC_API_KEY` | No | Sentimiento de noticias; degrada con elegancia si falta. |
| `BINANCE_API_KEY` / `BINANCE_SECRET` | No | **SOLO live.** Dejar vacías en paper. |

---

## Paso 3 — Verificar el deploy

Con la URL pública de Render (`https://crypto-agent-XXXX.onrender.com`):

- `GET /health` → `{"status":"ok"}`
- `GET /status` → `paper_trading:true`, `rag.loaded:true`, kill switch inactivo
- `GET /pipeline` → `overall: "READY"` (auto-chequeo: RAG, variables, Gemini, fuentes de datos, store)

---

## Paso 4 — Test end-to-end (webhook público)

```bash
curl -X POST https://TU-URL/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"TU_WEBHOOK_SECRET","pair":"BTCUSDT","signal_type":"T1_PULLBACK",
       "confluence_score":7,"regime":"GREEN","trend":"STRONG_UP","volatility":"NORMAL",
       "price":65000,"rsi":45,"atr":800}'
```

Debes recibir JSON con `trade_id`, `action` (BUY/NO_TRADE/REJECTED), `executed`, `decision`.
Verifica además: (a) aparece una fila en la Google Sheet; (b) un trade paper aparece en
`GET /status` y **sobrevive a un redeploy** (persistencia en el disco `/data`).

---

## Paso 5 — Alertas en TradingView

1. Pine Editor → pega `CryptoAgent_v1.pine` → **Add to chart**.
2. Inputs: **Webhook URL** = `https://TU-URL/webhook`; **Webhook Secret** = el mismo `WEBHOOK_SECRET`.
3. Crea **3 alertas** (Webhook URL = `https://TU-URL/webhook`, Open-ended): la señal principal,
   "EXTREME VOL" y "Regime Change", según el Pine Script.
4. Pares 4H sugeridos: **BTCUSDT, ETHUSDT, SOLUSDT**. NO usar BNBUSDT (bloqueado por el agente).

---

## Paso 6 — Gate de Paper Trading (antes de discutir live)

Mantén `PAPER_TRADING=true` y observa **mínimo 30 trades y 2 semanas**. Sólo se puede *discutir*
pasar a `false` si: **win rate > 50%**, **R:R promedio ≥ 2.0**, **drawdown < 10%**. El cambio es
manual y humano; Claude nunca lo hace.

---

## Troubleshooting

| Problema | Solución |
|---|---|
| Render no despliega | `requirements.txt` en la raíz; revisa logs de build en el dashboard. |
| `rag_loaded:false` | La carpeta `rag/` (3 archivos) debe estar en el repo; `scikit-learn==1.4.0`. |
| Webhook 401 | El `secret` del body ≠ `WEBHOOK_SECRET`. |
| Estado se pierde en redeploy | Falta el disco `/data` o `DATA_DIR` no apunta a él. |
| Cold start lento (plan idle) | Ping periódico a `/ping`. No es un error. |
| Binance bloqueado por región (451) | La cadena de fallback de precios lo maneja; no afecta el sizing paper. |
