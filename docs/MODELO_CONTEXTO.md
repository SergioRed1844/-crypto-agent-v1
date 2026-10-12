# Modelo de contexto — CryptoAgent v4.2

**Para qué:** que el modelo de trading entienda *por qué* puede moverse el mercado (Fed, elecciones, regulación,
aranceles, guerras, quiebras, ballenas de la era Satoshi) y actúe con reglas claras: **no comprar**, **comprar más
chico**, **exigir un setup técnico más claro** o **salir a USDT**. El contexto nunca abre una compra por sí solo;
la compra la sigue originando la señal técnica de TradingView.

Todo corre en **papel** (`TRADING_MODE=paper`). Nada de esto mueve dinero.

## 1. Jerarquía de agentes

```
                         ┌──────────────── NIVEL 0 · DIRECTOR DE CONTEXTO ────────────────┐
                         │ app/context/pipeline.py  (GitHub Actions: cada hora y cada 15 días) │
                         └───────────────┬────────────────────────────────────────────────┘
        NIVEL 1 · RECOLECTORES (código, sin LLM, reproducibles)
   ┌──────────────┬──────────────┬──────────────────┬───────────────────────┐
   │ Calendario   │ Noticias     │ On-chain         │ Mercado               │
   │ event_       │ news.py      │ onchain.py       │ macro.py              │
   │ calendar.py  │ CryptoPanic  │ mempool.space    │ F&G, stablecoins,     │
   │ recurring.py │ GDELT global │ era Satoshi /    │ FRED (dólar, VIX,     │
   │ (3 años)     │ consenso FF  │ ballenas         │ 10Y, Nasdaq),         │
   │              │              │ dormidas         │ Polymarket            │
   └──────┬───────┴──────┬───────┴────────┬─────────┴──────────┬────────────┘
          │       NIVEL 2 · ANALISTAS      │                    │
          │   ┌────────────────────┐   ┌───┴────────────────┐   │
          │   │ Clasificador       │   │ Estudio de eventos │   │
          │   │ classifier.py      │   │ event_study.py     │   │
          │   │ reglas + Gemini    │   │ BTC desde 2010,    │   │
          │   │ (JSON estricto)    │   │ pesos encogidos    │   │
          │   └─────────┬──────────┘   └─────────┬──────────┘   │
          │   NIVEL 3 · AUDITOR: coverage_audit (Gemini + Google Search) busca eventos que FALTAN
          │             → entran como "propuestos" hasta que una fuente los confirme
          └─────────────┴──────────────┬─────────┴──────────────┘
                         NIVEL 4 · JUEZ DE CONTEXTO (engine.compute, determinista)
                         estado · veto · tamaño · sesgo · riesgo de evento · salida
                                       │  context_signal.json (rama v4.2-contexto)
 ══════════════════════════════════════╪═══════════ MODELO DE TRADING (servidor) ═══════════════
 TradingView (4H) → webhook → gather ─┬─ technical  (Three Screen + confluencia 0–10)
                                      ├─ regime     (BTC diario, volatilidad)        ← capa 0, veta
                                      ├─ derivatives(funding, F&G)
                                      └─ context    (live.py lee la señal; blackout y alertas con la hora actual)
                                      → rules_gate ─(cualquier veto)→ NO_TRADE
                                      → sentiment ∥ methodology (LLM) → aggregate (≥3 votos LONG, confluencia
                                        5 + extra del contexto) → bull ∥ bear → judge → risk_gate → execute (papel)
```

## 2. Cómo se convierte el contexto en señales claras

| Estado | Cuándo | Qué hace el bot |
|---|---|---|
| **RISK_OFF + salida** | Se gastan monedas de la era Satoshi (alerta crítica) | Vende todo lo del bot a USDT una vez, activa el kill switch (reanudas tú con `/resume`) |
| **RISK_OFF** | Ballena dormida grande (alerta alta) o sesgo de eventos ≤ −0.5 | No compra nada nuevo; las posiciones abiertas siguen con su stop/objetivo |
| **BLACKOUT** | Dentro de la ventana de un evento programado *confirmado* de alto impacto (p.ej. FOMC: 6 h antes a 2 h después) | No compra nada nuevo |
| **CAUTION** | Sesgo ≤ −0.2, riesgo de evento ≥ 0.5 en 72 h, alerta media, o datos de contexto con más de 36 h | Tamaño ×0.5 y exige confluencia técnica ≥ 7 (en vez de 5) |
| **NEUTRAL** | Lo demás | Tamaño 1 − ½·riesgo de evento (mínimo 0.5) |
| **RISK_ON** | Sesgo ≥ +0.2 y riesgo de evento < 0.3 | Tamaño completo; el agente de contexto vota LONG |

Además el `risk_gate` ahora exige, siempre:
- **Ganancia neta mínima:** objetivo ≥ **1.5%** ya restando comisión de ida y vuelta y slippage (`MIN_NET_GAIN_PCT`).
- **R:R neto ≥ 1.8** (`MIN_NET_RR`). Ejemplo real: el scalp de BTC con stop de 0.26% era 2.5:1 bruto y **0.88:1 neto** → rechazado.
- **Racha:** 5 pérdidas seguidas → no más compras hasta `POST /admin/reset-streak`.

## 3. Ponderación (qué pesa más)

1. **Prior experto** por evento (`prior_tier` 1–5, de la investigación) y por categoría (`data/context/priors.json`).
2. **Evidencia histórica**: el estudio de eventos mide, para cada categoría, cuánto movió BTC a 1/3/7/30 días
   *más que un día cualquiera* (retorno anormal estandarizado con drift y vol de 90 días) y si el signo pro/anti
   acertó. p-values contra 4,000 días al azar.
3. **Encogimiento bayesiano**: `peso = (n·evidencia + k·prior)/(n + k)` con k = 8. Con 3 eventos manda el prior;
   con 40, la evidencia. Así no sobreajustamos a dos anécdotas.
4. **Moderadoras**: la misma noticia mala pega más con BTC en tendencia RED (×1.3) o con codicia extrema (×1.25);
   se re-estiman cuando hay ≥15 eventos por celda.
5. **Decaimiento**: el efecto de un evento se desvanece con su vida media por categoría (Fed 5 días, regulación 14,
   pandemia 21).
6. **Probabilidad de ocurrir**: confirmado 1.0, estimado 0.8, esperado 0.7, propuesto 0.5, especulativo 0.35.

Fórmulas exactas en `app/context/engine.py`. Resultados por categoría en `data/context/EVENTOS.md`.

## 4. Variables del modelo

| Variable | Rol | Tipo | Qué mide | Fuente | Frecuencia | Dónde se usa |
|---|---|---|---|---|---|---|
| `ar_z_h` (z) | dependiente | continua | Retorno anormal de BTC a h días (1/3/7/30) desde el cierre previo al evento, menos el drift de 90 días, dividido entre la vol de 90 días·√h | Coin Metrics (2010+) / Binance | diaria | event_study |
| `abs_ar_z_h` (z) | dependiente | continua | Magnitud |z|: cuánto mueve, sin importar la dirección (riesgo) | derivada | diaria | event_study → blackout y tamaño |
| `vol_ratio_7d` (x) | dependiente | continua | Vol realizada 7 días después / 30 días antes | derivada | diaria | event_study |
| `alt_ar_z_h` (z) | dependiente | continua | Retorno anormal de ETH y SOL (beta de altcoins al evento) | Binance 1d | diaria | event_study (secundario) |
| `trade_R` (R) | dependiente | continua | Resultado por operación del modelo de trading en múltiplos de riesgo (Y final) | store / backtest | por trade | backtest de variantes |
| `category` | independiente | discreta_atributo | Tipo de evento (18 categorías) | calendario / clasificador | por evento | pesos por categoría |
| `subcategory` | independiente | discreta_atributo | Subtipo (FOMC, CPI, PRESIDENTIAL, SATOSHI_ERA…) | calendario / clasificador | por evento | dedup y reportes |
| `country` | independiente | discreta_atributo | País o bloque (ISO-2, EU, GLOBAL) | calendario | por evento | ponderación por PIB |
| `crypto_stance` | independiente | discreta_atributo | Postura frente a cripto del resultado: pro / anti / neutral (da el SIGNO esperado) | investigación / LLM | por evento | sesgo direccional |
| `scheduled` | independiente | binaria | ¿La fecha se conocía antes? (programado vs sorpresa) | calendario | por evento | blackout solo aplica a programados |
| `surprise` | independiente | ordinal | expected < partial < surprise | investigación / LLM | por evento | event_study |
| `status` | independiente | ordinal | confirmed > scheduled_estimate > expected > speculative → P(ocurra) | calendario | por evento | riesgo de evento a futuro |
| `prior_tier` | independiente | ordinal | Importancia a priori 1–5 (juicio experto) | investigación | por evento | prior del encogimiento bayesiano |
| `onchain_type` | independiente | discreta_atributo | SATOSHI_ERA / EARLY_MINER / DORMANT_WHALE | vigía on-chain | por bloque | alertas |
| `news_count_24h` | independiente | discreta_conteo | Titulares del tema en 24 h (intensidad de atención) | GDELT / CryptoPanic | horaria | clasificador (urgencia) |
| `important_votes` | independiente | discreta_conteo | Votos 'important' en CryptoPanic | CryptoPanic | horaria | clasificador (urgencia) |
| `events_30d_same_cat` | independiente | discreta_conteo | Eventos de la misma categoría en 30 días (acumulación de choques) | historia | diaria | sesgo (decaimiento) |
| `countries_affected` | independiente | discreta_conteo | Países afectados por el evento | LLM | por evento | reporte |
| `gdp_share_pct` (%) | independiente | continua | Peso del país en el PIB mundial nominal | FMI WEO | anual | tier de elecciones/gobiernos |
| `ex_ante_prob` (0–1) | independiente | continua | Probabilidad del resultado ANTES del evento (evita sesgo de retrospectiva: lo 'evidente' ya estaba en el precio) | Polymarket / Kalshi | diaria | sorpresa = resultado − prob |
| `surprise_z` (z) | independiente | continua | (Dato − consenso) / desviación histórica de sorpresas | FairEconomy (consenso) + FRED (dato) | por publicación | signo de MACRO_DATA |
| `rate_change_bps` (pb) | independiente | continua | Cambio de tasa decidido | bancos centrales | por reunión | signo de MONETARY_POLICY |
| `btc_years_moved` (BTC·años) | independiente | continua | BTC movidos × años dormidos | vigía on-chain | por bloque | severidad de alertas |
| `news_tone` | independiente | continua | Tono promedio de la cobertura | GDELT | diaria | clasificador |
| `fear_greed` (0–100) | independiente | continua | Índice de miedo y codicia (también moderadora por zonas) | alternative.me | diaria | agente derivados + moderadora |
| `funding_rate` (%/8h) | independiente | continua | Funding de perpetuos (apalancamiento de la multitud) | Binance futures | 8 h | agente derivados |
| `open_interest_chg` (%) | independiente | continua | Cambio de interés abierto 24 h | Binance futures | horaria | agente derivados |
| `dxy_20d_pct` (%) | independiente | continua | Cambio 20 días del dólar amplio | FRED DTWEXBGS | diaria | sesgo de mercado |
| `vix` (pts) | independiente | continua | Volatilidad implícita del S&P 500 | FRED VIXCLS | diaria | estado CAUTION |
| `nasdaq_20d_pct` (%) | independiente | continua | Cambio 20 días del Nasdaq Composite | FRED NASDAQCOM | diaria | sesgo de mercado |
| `us10y_20d_bps` (pb) | independiente | continua | Cambio 20 días del bono a 10 años | FRED DGS10 | diaria | sesgo de mercado |
| `stablecoin_30d_pct` (%) | independiente | continua | Cambio 30 días de la oferta total de stablecoins (liquidez cripto) | DefiLlama | diaria | sesgo de mercado |
| `etf_flow_5d_usd` (USD) | independiente | continua | Flujo neto 5 días de ETFs spot de BTC | Farside / SoSoValue | diaria | sesgo de mercado |
| `btc_regime` | moderadora | ordinal | Tendencia diaria de BTC: GREEN / YELLOW / RED. En RED las malas noticias pegan más; en GREEN las buenas | Binance 1d | por vela | multiplicador del sesgo |
| `vol_regime` | moderadora | ordinal | Vol 30 d: LOW / NORMAL / HIGH / EXTREME | Binance 1d | diaria | multiplicador del riesgo de evento |
| `fear_greed_zone` | moderadora | ordinal | ≤20 miedo extremo / 20–80 / ≥80 codicia extrema: con codicia extrema una noticia mala pega más | alternative.me | diaria | multiplicador del sesgo |
| `leverage_zone` | moderadora | ordinal | Funding alto = multitud apalancada (cascadas de liquidación) | Binance futures | 8 h | veto del agente derivados |
| `halving_phase` (días) | moderadora | continua | Días desde el último halving (fase del ciclo de 4 años) | calendario | diaria | reporte (pendiente de evidencia) |
| `btc_nasdaq_corr_30d` (ρ) | moderadora | continua | Correlación 30 d BTC–Nasdaq: si es alta, los eventos macro de EE.UU. pesan más | Binance + FRED | diaria | reporte (pendiente de evidencia) |
| `weekend_liquidity` | moderadora | binaria | Fin de semana / feriado de EE.UU.: liquidez delgada | reloj | horaria | reporte |
| `risk_assets_reaction` (%) | mediadora | continua | Reacción del Nasdaq y del dólar el mismo día: canal por el que la Fed o los aranceles llegan a BTC | FRED | diaria | estudio de eventos (diagnóstico) |
| `baseline_drift_vol_90d` | control | continua | Drift y vol de 90 días previos (se restan para obtener el retorno ANORMAL) | derivada | diaria | event_study |
| `day_of_week` | control | discreta_atributo | Día de la semana del evento | reloj | diaria | event_study |
| `random_day_baseline` | control | continua | Distribución de |z| en días al azar: un evento solo 'pesa' si mueve más que un día cualquiera | derivada | por recálculo | p-value por categoría |
| `universe` | constante | discreta_atributo | BTC, ETH, SOL (spot, solo largos) | config | fija | trading |
| `fees_slippage` (%) | constante | continua | Comisión 0.1% por lado + slippage 0.05% | config | fija | filtro de ganancia neta |
| `hard_limits` | constante | discreta_atributo | Kill −3% día / −5% semana, ≤5% exposición, ≤0.5% riesgo, 5 pérdidas seguidas, 1 posición por par, BNB bloqueado | config | inmutable | risk_gate |
| `event_windows` | constante | discreta_atributo | Base = cierre del día previo; h = 1, 3, 7, 30 días; UTC | event_study | fija | event_study |

**Por qué importa la probabilidad ex-ante:** que Trump ganara en 2024 "era evidente" solo en retrospectiva; antes
del 5-nov los mercados de predicción le daban cerca de 60%, y parte del rally ya estaba en el precio. El modelo
mide la **sorpresa** (resultado − probabilidad previa), no la narrativa. (Tampoco fue "la primera vez que subieron
las criptos": 2013, 2017 y 2020-21 fueron ciclos alcistas mayores.)

## 5. Calendario a 3 años y refresco cada 15 días

- `data/context/CALENDARIO.md` (vista) y `calendar.json` (datos), 345 eventos hasta 2029-10-12.
- Curado con fuente: FOMC, BCE, BoJ, BoE, Banxico; CPI, NFP, PCE, PIB de EE.UU.; plazos fiscales y arancelarios;
  elecciones de los 20 países con ≥1% del PIB mundial + cripto-relevantes (con su % de PIB);
  GENIUS, CLARITY, MiCA, AMLR, FCA; Mt. Gox (plazo 31-oct-2026, ~34k BTC); halving 2028; upgrades.
- Por regla: vencimientos de Deribit y CME; estimados de FOMC/CPI/NFP/Jackson Hole donde aún no hay fecha oficial.
- **Cada 15 días (días 1 y 15)**: noticias de 15 días → eventos; Gemini + Google Search audita huecos; se recalculan
  pesos, calendario y señal; espejo en tu Google Sheet.
- **Cada hora**: vigía on-chain + noticias urgentes + señal. Alerta alta/crítica → issue de GitHub (te llega correo).
- **Mensual**: estudio de eventos + backtest de variantes con datos reales (`BACKTEST_V42.md`).

## 6. Dónde se guarda la información

| Qué | Dónde |
|---|---|
| Calendario, historia, pesos, señal, alertas (fuente de verdad, versionada) | Rama `v4.2-contexto`, carpeta `data/context/` |
| Vista legible | `data/context/CONTEXTO.md`, `CALENDARIO.md`, `EVENTOS.md`, `BACKTEST_V42.md` en GitHub |
| Tu Google Sheet (espejo) | Pestañas Calendario, Eventos, Pesos, Alertas, Contexto vía `sheets/google_apps_script.js` |
| Decisiones y posiciones del bot | Postgres/SQLite (`app/store.py`), cada decisión guarda el estado de contexto |

## 7. APIs y MCP

| Fuente | Área | Estado 2026 | Gratis | ¿Estaba en v4.1? | ¿Conectada en v4.2? | Recomendación |
|---|---|---|---|---|---|---|
| Financial Modeling Prep – Economic Calendar | calendar | Activa (stable API) | Basic $0: 250 calls/día y 5 años de hist | no | no | después (pago) |
| Glassnode API | onchain | Activa. API completa solo en Professional. Light API en Advanced. | Sin API free. Advanced da la Light API:  | no | no | después (pago) |
| Tokenomist API v4 (ex-TokenUnlocks) | calendar | Activa. Dominio api.tokenomist.ai (api.unlocks.app en retiro). | Sin free permanente (trial por solicitud | no | no | después (pago) |
| Whale Alert API | onchain | Activa. Alerts API (WebSocket) + Enterprise REST (v2) en leviathan.whale-alert.io. | No (trial de 7 días del Alerts API) | no | no | después (pago) |
| Binance Public Data dumps (data.binance.vision) | derivatives | Activa (bucket S3 público) | Gratis | no | sí | adoptar ya |
| Binance Spot market-data mirror (data-api.binance.vision) | price | Activa | Gratis | sí | sí | adoptar ya |
| Binance USDⓈ-M Funding Rate History | derivatives | Activa | Gratis | sí | sí | adoptar ya |
| Blockstream Esplora (blockstream.info) | onchain | Activa | Gratis | no | sí | adoptar ya |
| Coin Metrics Community API v4 | price | Activa (verificado en vivo: PriceUSD BTC desde 2010-07-18) | Gratis (community) | no | sí | adoptar ya |
| CoinGecko API (Demo) | price | Activa. Demo gratis con key. | Demo: 10k créditos/mes, 100 req/min, 60+ | sí | no | adoptar ya |
| CryptoPanic API (v2) | news | v2 activa. El path legacy /api/v1/posts/ quedó reemplazado por /api/{plan}/v2/posts/ (plan | Ya no existe según SDKs y guías de 2026  | sí | sí | adoptar ya |
| DefiLlama Stablecoins API | onchain | Activa (verificado en vivo) | Gratis (API abierta; la API Pro es de pa | no | sí | adoptar ya |
| FRED API (St. Louis Fed) | macro | Activa. Existe v1 (por serie) y v2 (bulk por release). | Gratis | no | sí | adoptar ya |
| FRED Release Calendar (releases/dates) | calendar | Activa | Gratis | no | sí | adoptar ya |
| Farside Investors – BTC ETF flows | etf | Activa (HTML, sin API) | Gratis (scraping de tabla HTML) | no | no | adoptar ya |
| ForexFactory / FairEconomy weekly calendar JSON | calendar | Activa (feed no oficial; verificado en vivo con 109 eventos de la semana) | Gratis | no | sí | adoptar ya |
| GDELT DOC 2.0 API | news | Activa, sin cambios de versión. | Gratis | sí | sí | adoptar ya |
| Gemini API – Grounding with Google Search (gemini-2.5-flash) | llm | Soportado en gemini-2.5-flash (tool google_search). 2.5 Flash NO está deprecado ni tiene f | Free tier: grounding gratis hasta 500 RP | sí | sí | adoptar ya |
| Google Apps Script Web App (journal en Sheets) | storage | Activo | Gratis (cuenta gmail) | sí | sí | adoptar ya |
| Polymarket CLOB prices-history | prediction | Activa | Gratis | no | no | adoptar ya |
| Polymarket Gamma API | prediction | Activa. Paginación nueva por cursor (/events/keyset, /markets/keyset con after_cursor). | Gratis | no | sí | adoptar ya |
| SoSoValue OpenAPI v1 (ETF) | etf | Activa, v1 (spec del 2026-09-11) | Key por registro. Las docs no publican p | no | no | adoptar ya |
| alternative.me Fear & Greed | sentiment | Activa. limit=0 devuelve todo el histórico. | Gratis | sí | sí | adoptar ya |
| mempool.space REST API | onchain | Activa | Gratis con rate limits (cifras no public | no | sí | adoptar ya |
| Arkham Intelligence API | onchain | Acceso por solicitud o institucional (instituciones en Arkham Exchange califican) | No público | no | no | evitar |
| Finnhub Economic Calendar | calendar | Endpoint /api/v1/calendar/economic. Docs JS no legibles hoy. Históricamente es endpoint pr | Free general 60 req/min, pero el calenda | no | no | evitar |
| Messari API | news | Docs marcadas 'Legacy' y API en modo mantenimiento (sin nuevos endpoints). Las integracion | No verificado | no | no | evitar |
| Trading Economics Calendar API | calendar | Activa, de pago | No (requiere suscripción; el acceso gues | no | no | evitar |
| Alpha Vantage | macro | Activa. Tiene MCP oficial. | Free con límite diario bajo (~25 req/día | no | no | opcional |
| Blockchair API | onchain | Activa | 1,000 calls/día, 30 req/min de límite du | no | no | opcional |
| CoinMarketCal API v2 | calendar | Activa (v2) | Free: 3k req/mes, solo próximos 7 días,  | no | no | opcional |
| CoinPaprika API | price | En uso. No re-verificado en esta sesión. | Free (cuota mensual; no verificada hoy) | sí | no | opcional |
| CryptoQuant API | onchain | Activa. La página de precios (JS) no se pudo leer. | No verificado (históricamente la API va  | no | no | opcional |
| GDELT 2.0 Event Database (exports cada 15 min) | news | Activa (formato estable desde 2015) | Gratis | no | no | opcional |
| Kalshi Trade API v2 (market data público) | prediction | Activa. Base nueva external-api.kalshi.com (api.elections.kalshi.com sigue válido). | Gratis | no | no | opcional |
| Santiment SanAPI (GraphQL) | sentiment | Activa. Tiene MCP oficial (api.santiment.net/mcp). | Free: 1,000 calls/mes, 500/h, 100/min. M | no | no | opcional |

Los servidores MCP (CoinGecko, Dune, Glassnode, FRED, Exa, etc.) sirven para que Claude investigue en una
sesión; el bot llama las APIs REST directo. Detalle completo: `data/context/sources/apis.json`.

## 8. Qué falta y límites honestos

- **Sin ventaja demostrada todavía.** El contexto se agregó para *no operar en los peores momentos*, no porque haya
  evidencia de que gane. Se queda solo si el backtest fuera de muestra lo justifica (`BACKTEST_V42.md`).
- **Historia corta por categoría.** Con 5–15 eventos por tipo, casi todo queda como evidencia "débil"; por eso
  el encogimiento al prior.
- **CPI/FOMC históricos completos** (todas las fechas desde 2013) mejorarían mucho el estudio: requieren FRED key
  (fechas de publicación) o el archivo histórico de la Fed. Pendiente.
- **CryptoPanic**: el plan gratis se reportó descontinuado en 2026; si tu key da 401/403 el sistema usa GDELT.
- **Consenso para sorpresas**: gratis solo la semana en curso (FairEconomy). Histórico de sorpresas → FMP (pago).
- **Flujos de ETF**: Farside (HTML) / SoSoValue (key) aún no conectados.
- **Patentes y licencias** casi no mueven a BTC; quedan con peso mínimo salvo que la evidencia diga otra cosa.
- Nada predice "sí o sí": el modelo da probabilidades y pesos, no certezas.
