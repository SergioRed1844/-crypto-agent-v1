# CryptoAgent v1.0 — Guía de Deploy

## Paso 1: Subir código al repo GitHub

```bash
# En tu terminal, clona tu repo
git clone https://github.com/SergioRed1844/-crypto-agent-v1.git
cd -crypto-agent-v1

# Descomprime el tar.gz del servidor en la raíz
# (copia los archivos: server.py, requirements.txt, Procfile, railway.json, .gitignore, carpeta rag/)

# Sube todo
git add .
git commit -m "CryptoAgent v1.0 - servidor + RAG"
git push origin main
```

## Paso 2: Configurar Railway

1. Ve a **railway.app** → tu dashboard
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Selecciona tu repo: `SergioRed1844/-crypto-agent-v1`
4. Railway detectará automáticamente el `Procfile`

### Variables de entorno (CRÍTICO):
Ve a tu servicio → **Variables** → agrega:

| Variable | Valor | Notas |
|----------|-------|-------|
| `GEMINI_API_KEY` | tu-api-key-de-gemini | La que obtuviste de aistudio.google.com |
| `TELEGRAM_TOKEN` | el-token-de-CryptoAgentAlert2 | El nuevo que generaste |
| `TELEGRAM_CHAT_ID` | tu-chat-id | Obtén con: envía /start a tu bot, luego ve a https://api.telegram.org/bot{TOKEN}/getUpdates |
| `WEBHOOK_SECRET` | inventa-una-frase-secreta | Ejemplo: "mi-crypto-agent-2026-seguro" |
| `PAPER_TRADING` | true | SIEMPRE empezar en paper. Cambiar a "false" solo después de 30 trades exitosos |
| `PORT` | 8000 | Puerto del servidor |

## Paso 3: Verificar deploy

Una vez que Railway haga deploy, tendrás una URL como:
`https://crypto-agent-v1-production-xxxx.up.railway.app`

Prueba en tu navegador:
- `https://TU-URL/` → debe mostrar status del agente
- `https://TU-URL/health` → debe decir {"status": "ok"}
- `https://TU-URL/status` → muestra config completa

## Paso 4: Configurar Pine Script en TradingView

1. En TradingView, ve a **Pine Editor** (pestaña inferior)
2. Copia TODO el contenido de `CryptoAgent_v1.pine`
3. Click **"Add to chart"**
4. Configura los inputs:
   - **Webhook URL**: tu URL de Railway + `/webhook`
   - **Webhook Secret**: el mismo que pusiste en Railway
5. Verás el indicador con EMAs, Bollinger Bands, y la tabla de régimen

### Configurar Alertas Webhook:
1. Click derecho en el indicador → **"Add Alert"**
2. Condition: `CryptoAgent v1.0` → `CryptoAgent Signal`
3. En **Notifications** → marca **"Webhook URL"**
4. Pega: `https://TU-URL/webhook`
5. Expiration: **"Open-ended"**
6. Click **Create**
7. Repite para "EXTREME VOL Alert" y "Regime Change"

## Paso 5: Obtener tu Telegram Chat ID

1. Abre Telegram
2. Busca tu bot `@CryptoAgentAlert2` y envía `/start`
3. En tu navegador, ve a:
   `https://api.telegram.org/bot{TU_TOKEN}/getUpdates`
4. Busca `"chat":{"id":XXXXXXX}` — ese número es tu CHAT_ID
5. Agrégalo como variable en Railway

## Paso 6: Test End-to-End

Envía un test manual con curl:
```bash
curl -X POST https://TU-URL/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"tu-webhook-secret","pair":"BTCUSDT","signal_type":"LONG","confluence_score":7,"template":"T1_PULLBACK","regime":"GREEN","trend":"STRONG_UP","volatility":"NORMAL","price":87500,"rsi":45,"atr":1400}'
```

Deberías recibir:
- Respuesta JSON en la terminal
- Mensaje en Telegram de tu bot

## Paso 7: Paper Trading (MÍNIMO 2 semanas)

- El bot está en modo `PAPER_TRADING=true`
- Todas las señales se procesan pero NO ejecutan en Binance
- Revisa los logs diariamente
- Necesitas mínimo 30 trades con:
  - Win rate > 50%
  - Avg R:R > 2.0
  - Max drawdown < 10%
- Solo entonces cambia `PAPER_TRADING=false`

## Pares Recomendados para Empezar

Aplica el indicador en estos charts de TradingView (timeframe 4H):
1. BTCUSDT (obligatorio)
2. ETHUSDT
3. SOLUSDT

NO aplicar en: BNBUSDT (bloqueado por el agente)

## Troubleshooting

| Problema | Solución |
|----------|----------|
| Railway no despliega | Verifica que `requirements.txt` y `Procfile` están en la raíz |
| Webhook no llega | Verifica URL en TradingView termina en `/webhook` |
| Telegram no envía | Verifica TELEGRAM_TOKEN y CHAT_ID en variables de Railway |
| "RAG not loaded" | Verifica que la carpeta `rag/` con los 3 archivos está en el repo |
| Cold start lento | Agrega un cron job que haga ping a `/ping` cada 5 min |
