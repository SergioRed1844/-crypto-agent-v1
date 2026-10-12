# CryptoAgent v4.2 — modelo de contexto

**Rama `v4.2-contexto`.** Sobre la base v4.1 (comité LangGraph, ejecución segura) se agrega un **modelo de contexto**
que le dice al comité cuándo NO comprar, cuándo comprar más chico y cuándo salir a USDT:

- **Calendario a 3 años** con fuente: Fed/BCE/BoJ/BoE/Banxico, CPI/NFP/PCE/PIB, plazos fiscales y arancelarios,
  elecciones de los países con ≥1% del PIB mundial, regulación cripto e IA, Mt. Gox, halving, vencimientos.
  Vista: [`data/context/CALENDARIO.md`](data/context/CALENDARIO.md).
- **Historia desde 2009** (≈260 eventos) y **estudio de eventos** con BTC desde 2010 → pesos por categoría con
  encogimiento bayesiano ([`EVENTOS.md`](data/context/EVENTOS.md)).
- **Vigía on-chain**: si se gastan monedas de la era Satoshi (P2PK 2009–2010) o de ballenas dormidas → RISK_OFF;
  si es era Satoshi, venta a USDT y kill switch.
- **Noticias** (CryptoPanic + GDELT global) clasificadas cada hora y cada 15 días; auditoría de huecos con
  Gemini + Google Search.
- **Señal de contexto** cada hora: [`data/context/CONTEXTO.md`](data/context/CONTEXTO.md).
- **Reglas nuevas** del risk gate: ganancia neta ≥ 1.5% y R:R neto ≥ 1.8; 5 pérdidas seguidas → pausa.
- Comparación de variantes con datos reales: [`BACKTEST_V42.md`](data/context/BACKTEST_V42.md).

Diseño completo (jerarquía de agentes, variables dependientes/independientes/moderadoras/constantes, ponderación,
APIs): [`docs/MODELO_CONTEXTO.md`](docs/MODELO_CONTEXTO.md). Solo papel.

## Secretos (GitHub → Settings → Secrets and variables → Actions). Todos opcionales; sin ellos el sistema degrada.
| Secreto | Para qué | Sin él |
|---|---|---|
| `GEMINI_API_KEY` | clasificar noticias en JSON y auditar huecos del calendario con Google Search | reglas de palabras clave, sin auditoría |
| `CRYPTOPANIC_API_KEY` (+ variable `CRYPTOPANIC_PLAN`) | noticias cripto con votos | solo GDELT |
| `FRED_API_KEY` (gratis en fred.stlouisfed.org) | dólar, VIX, 10 años, Nasdaq | sin esas variables |
| `SHEETS_WEBAPP_URL`, `SHEETS_TOKEN` | espejo en tu Google Sheet | solo GitHub |

---

# CryptoAgent v4.1 — comité multiagente (LangGraph) · TradingView → Binance Spot

TradingView es el **sensor**: avisa en cada cierre de vela 4H. El **servidor** decide con reglas en código
(las mismas que valida `backtest.py`) y solo si pasan consulta a los agentes LLM. Un **risk gate en código**
tiene la última palabra. Cada compra sale con **OCO en Binance** (take-profit LIMIT_MAKER + stop a mercado).

```
TradingView ─webhook─▶ /webhook (valida, guarda en cola, responde en ms)
                              │
                      worker LÍDER (1 sola instancia opera; advisory lock de Postgres)
                              │
gather ─┬ technical  ┐
        ├ regime     ├─▶ rules_gate ─(no)────────────────────────────▶ aggregate ─▶ journal
        └ derivatives┘       │ sí
                  sentiment ∥ methodology (LLM) ─▶ aggregate ─(PASS)─▶ bull ∥ bear ─▶ judge
                                                         ─▶ risk_gate ─(aprobado)─▶ execute (compra + OCO) ─▶ journal
reconcile cada 5 min: recupera compras en duda, cierra SL/TP, re-protege parciales, reintenta lo desprotegido
```

## Garantías probadas (`./run_tests.sh`, sin red ni dinero)
| Riesgo | Cómo se cubre |
|---|---|
| Servidor se cae entre compra y OCO | Posición PENDING escrita antes de comprar; `recover_pending` la protege con la cantidad real |
| Timeout en compra/OCO/venta | Se consulta Binance por `clientOrderId` antes de reintentar; nunca se duplica |
| Stop que no llena en una caída | Pata baja `STOP_LOSS` (a mercado) + venta de respaldo si el precio perfora el stop |
| Venderte tus propias monedas | Tope = lo que tenía el usuario justo antes de la compra (línea base). **Usa una subcuenta** de todos modos |
| Parciales y patas canceladas | Re-consulta tras cancelar; vende solo el resto del bot; polvo se cierra en BD |
| Dos instancias en un deploy | Solo el líder procesa; cola con `FOR UPDATE SKIP LOCKED`; índice único (modo, par) |
| Mezclar paper/testnet/live | Todas las consultas filtran por modo; no arranca si hay posiciones vivas de otro modo |
| Webhooks falsos o viejos | IPs de TradingView (entrada derecha de X-Forwarded-For), secret, timeframe 240, ≤30 min desde el cierre |
| BTC/ETH/SOL correlacionados | Máx. 2 posiciones y 1.5% de riesgo abierto total |
| LLM caído o manipulado | Titulares tratados como datos; niveles de stop/TP siempre deterministas; `RULES_ONLY_FALLBACK` |

## Paso 1 — Backtest con datos reales (en tu Mac; desde aquí Binance no es accesible)
```bash
pip install -r requirements.txt
python backtest.py --pairs BTCUSDT,ETHUSDT,SOLUSDT --since 2021-01-01
```
**Gate B (para pasar de testnet a live):** fuera de muestra, 100+ trades, `expectancy_R ≥ 0.3`,
`profit_factor ≥ 1.5` y límite inferior de `expectancy_IC95_R > 0`. Si no se cumple, no hay ventaja: no se despliega con dinero.

## Paso 2 — Deploy (paper)
1. Postgres gratis en Neon o Supabase. Copia la URL **directa** (no la del pooler).
2. Render → New → Blueprint → este repo (usa `render.yaml`: región **Frankfurt**, plan **Starter**, `autoDeploy: false`).
   Binance bloquea IPs de EE.UU. (HTTP 451); el plan free se duerme y TradingView corta a los 3 s.
3. Variables: `DATABASE_URL`, `GEMINI_API_KEY` (y opcional `CRYPTOPANIC_API_KEY`). `WEBHOOK_SECRET` y `ADMIN_SECRET` los genera Render.
4. Monitor de uptime (UptimeRobot / Better Stack) sobre `https://TU-SERVICIO/health` cada 5 min con alerta por correo:
   responde 503 si nadie reconcilia hace 15 min.
5. Llena `macro_calendar.json` con fechas oficiales de CPI, FOMC y NFP del mes (formato en `macro_calendar.example.json`).

## Paso 3 — TradingView
1. Pine Editor → pega `pine/CryptoAgent_v2_sensor.pine` → cambia el secret por tu `WEBHOOK_SECRET` → Guardar → Añadir al gráfico.
2. Gráfico en **4H**. Alerta: Condición *CryptoAgent v2.1 Sensor* → **Any alert() function call** → Webhook `https://TU-SERVICIO/webhook`. Mensaje vacío.
3. Una alerta por par: BINANCE:BTCUSDT, ETHUSDT, SOLUSDT. Borra las alertas del v1.
4. Tras la primera alerta, revisa el log `xff=` en Render: la IP usada debe ser una de TradingView. Si sale otra, pon `TV_XFF_INDEX=-2`.

## Paso 4 — Testnet → Live
| Fase | Cambios | Para avanzar |
|---|---|---|
| Paper | `TRADING_MODE=paper` | 30+ trades; métricas similares al backtest; `shadow_stats` comparadas |
| Testnet | `TRADING_MODE=testnet`, keys de testnet.binance.vision, **base de datos nueva** | 10 OCO correctos, 0 errores en 7 días |
| Live | `TRADING_MODE=live`, `RISK_PER_TRADE=0.0025`, `MAX_BOT_CAPITAL`, **subcuenta** | Gate B cumplido |

Keys de Binance: **solo Spot Trading, sin retiros, con whitelist de IP** (outbound IPs de Render de tu región,
o IP dedicada de Render).

## Operación
```bash
curl -H "x-admin-secret: $ADMIN_SECRET" https://TU-SERVICIO/status       # equity, posiciones, stats y shadow_stats
curl -H "x-admin-secret: $ADMIN_SECRET" https://TU-SERVICIO/decisions    # cada decisión con el voto de cada agente
curl -X POST -H "x-admin-secret: $ADMIN_SECRET" "https://TU-SERVICIO/kill?flatten=true"   # detener y cerrar todo
curl -X POST -H "x-admin-secret: $ADMIN_SECRET" https://TU-SERVICIO/resume
```
`shadow_stats` = trades que las reglas solas habrían tomado y el comité bloqueó. Si rinden más que `stats`,
los agentes LLM están restando valor: pon `LLM_PROVIDER=mock` y opera solo con reglas.

## Límites conocidos
- Si operas a mano la misma moneda mientras el bot tiene posición en ella, la línea base deja de proteger tus monedas.
- El backtest no incluye funding ni noticias (no hay histórico gratis); los LLM se miden en vivo con `shadow_stats`.
- La reconciliación es por sondeo cada 5 min (no User Data Stream). El stop y el TP viven en Binance, así que una caída del servidor no deja la posición sin protección.
