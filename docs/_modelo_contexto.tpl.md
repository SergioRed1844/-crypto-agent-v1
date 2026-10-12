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
                                      └─ context    (live.py lee la señal; blackout y alertas con la hora actual;
                                                     solo veta o resta, nunca suma un voto a favor)
                                      → rules_gate ─(cualquier veto)→ NO_TRADE
                                      → sentiment ∥ methodology (LLM) → aggregate (≥3 votos LONG, confluencia
                                        5 + extra del contexto) → bull ∥ bear → judge → risk_gate → execute (papel)
```

## 2. Cómo se convierte el contexto en señales claras

| Estado | Cuándo | Qué hace el bot |
|---|---|---|
| **RISK_OFF + salida** | Se gastan ≥ 500 BTC de coinbases de la era Satoshi (bloques ≤ 60,000, P2PK) — alerta crítica | Vende todo lo del bot a USDT, activa el kill switch (reanudas tú con `/resume`); si la venta falla, reintenta cada minuto |
| **RISK_OFF** | Una coinbase suelta de 2009–2010 (puede ser otro minero, como el 20-may-2020), ballena dormida grande (alerta alta), sesgo de eventos ≤ −0.5, o contexto sin actualizar > 72 h | No compra nada nuevo; las posiciones abiertas siguen con su stop/objetivo |
| **BLACKOUT** | Dentro de la ventana de un evento programado *confirmado* de alto impacto (p.ej. FOMC: 6 h antes a 2 h después) | No compra nada nuevo |
| **CAUTION** | Sesgo ≤ −0.2, riesgo de evento ≥ 0.5 en 72 h, alerta media, o datos de contexto con más de 36 h | Tamaño ×0.5 y exige confluencia técnica ≥ 7 (en vez de 5) |
| **NEUTRAL** | Lo demás | Tamaño 1 − ½·riesgo de evento (mínimo 0.5) |
| **RISK_ON** | Sesgo ≥ +0.2 y riesgo de evento < 0.3 | Tamaño completo. El contexto **nunca vota a favor** de comprar: solo puede vetar o restar |

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

{{VARIABLES}}

**Por qué importa la probabilidad ex-ante:** que Trump ganara en 2024 "era evidente" solo en retrospectiva; antes
del 5-nov los mercados de predicción le daban cerca de 60%, y parte del rally ya estaba en el precio. El modelo
mide la **sorpresa** (resultado − probabilidad previa), no la narrativa. (Tampoco fue "la primera vez que subieron
las criptos": 2013, 2017 y 2020-21 fueron ciclos alcistas mayores.)

## 5. Calendario a 3 años y refresco cada 15 días

- `data/context/CALENDARIO.md` (vista) y `calendar.json` (datos), {{N_EVENTS}} eventos hasta {{LAST_DATE}}.
- Curado con fuente: FOMC, BCE, BoJ, BoE, Banxico; CPI, NFP, PCE, PIB de EE.UU.; plazos fiscales y arancelarios;
  elecciones de los {{N_COUNTRIES}} países con ≥1% del PIB mundial + cripto-relevantes (con su % de PIB);
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

{{APIS}}

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
