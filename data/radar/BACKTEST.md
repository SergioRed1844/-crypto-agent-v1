# Radar EB — validación fuera de muestra

Entrenamiento: disparos **antes de 2022-01-01** · Prueba: **desde 2022-01-01**. Especificaciones probadas (setup × clase × horizonte): **24** — con tantas pruebas, algún resultado bueno puede ser azar (C11-009 B). Umbrales fijados el 18-oct-2026 antes de ver datos.

τ entre setups (logit, entrenamiento): 0.050

## 1. ¿El encogimiento EB predice mejor? (Brier, menor es mejor)

| Clase | Horizonte | Filas | Episodios | Acierto real | Brier EB | Brier tasa base | Brier crudo activo | Brier crudo setup | Skill vs base | Día cualquiera (prueba) |
|---|---|---|---|---|---|---|---|---|---|---|
| crypto | 7 d | 291 | 90 | 28.9% | 0.2357 | 0.2355 | 0.2825 | 0.2737 | -0.1% | 38.3% |
| crypto | 30 d | 290 | 89 | 25.2% | 0.2447 | 0.2449 | 0.2799 | 0.2478 | +0.1% | 39.4% |
| crypto | 90 d | 289 | 88 | 33.2% | 0.2591 | 0.2596 | 0.2986 | 0.2656 | +0.2% | 39.5% |
| us | 7 d | 39 | 26 | 71.8% | 0.2281 | 0.2279 | 0.2453 | 0.2350 | -0.1% | 65.7% |
| us | 30 d | 29 | 19 | 89.7% | 0.1144 | 0.1143 | 0.1331 | 0.1108 | -0.0% | 91.7% |

Skill > 0: el modelo le gana a 'la tasa base del activo' fuera de muestra. Si EB < crudo, el encogimiento sirvió (la promesa de James-Stein).

## 2. Calibración (todas las filas de prueba)

| Tramo predicho | n | Predicho | Real |
|---|---|---|---|
| 0%–40% | 48 | 37.2% | 18.8% |
| 40%–50% | 433 | 45.5% | 27.7% |
| 50%–60% | 345 | 53.8% | 32.5% |
| 60%–70% | 60 | 62.9% | 45.0% |
| 70%–100% | 52 | 79.5% | 75.0% |

## 3. Setups fuera de muestra vs comprar un día cualquiera

| Setup | Horizonte | Disparos | Episodios | Acierto | Día cualquiera | Predicho EB | Neto medio | Neto día cualquiera |
|---|---|---|---|---|---|---|---|---|
| PANICO_SIN_DANO | 7 d | 78 | 15 | 20.5% | 47.6% | 47.7% | -8.3% | 3.0% |
| PANICO_SIN_DANO | 30 d | 78 | 15 | 26.9% | 50.2% | 50.1% | -3.3% | 15.9% |
| PANICO_SIN_DANO | 90 d | 75 | 14 | 40.0% | 52.5% | 52.3% | -1.7% | 51.6% |
| CAPITULACION | 7 d | 58 | 13 | 20.7% | 46.9% | 47.0% | -6.2% | 2.9% |
| CAPITULACION | 30 d | 58 | 13 | 13.8% | 48.7% | 48.6% | -10.8% | 16.8% |
| CAPITULACION | 90 d | 58 | 13 | 27.6% | 52.3% | 52.2% | -6.2% | 64.8% |
| CHOQUE_POLITICO | 7 d | 26 | 3 | 7.7% | 46.4% | 46.4% | -6.2% | 2.6% |
| CHOQUE_POLITICO | 30 d | 26 | 3 | 11.5% | 49.1% | 49.1% | -6.7% | 14.9% |
| CHOQUE_POLITICO | 90 d | 26 | 3 | 7.7% | 52.3% | 52.4% | -13.8% | 57.1% |
| ATENCION_MOMENTUM | 7 d | 51 | 28 | 27.5% | 46.2% | 46.3% | -0.6% | 2.6% |
| ATENCION_MOMENTUM | 30 d | 51 | 28 | 39.2% | 48.8% | 48.8% | 4.1% | 14.6% |
| ATENCION_MOMENTUM | 90 d | 51 | 28 | 49.0% | 52.0% | 51.8% | 19.8% | 51.7% |
| PULLBACK_TENDENCIA | 7 d | 117 | 65 | 58.1% | 54.1% | 54.2% | 4.1% | 4.6% |
| PULLBACK_TENDENCIA | 30 d | 106 | 58 | 44.3% | 56.9% | 56.9% | 8.5% | 22.7% |
| PULLBACK_TENDENCIA | 90 d | 79 | 42 | 29.1% | 52.6% | 52.4% | -3.4% | 72.6% |

## 4. Regla de alerta Selectivo en el periodo de prueba

Alertas: **0** (0 episodios; ~0.0/año sin tope semanal) · acierto real **—** vs predicho — · neto medio — · mediana — · peor caída durante la tenencia —.

Sin contexto v4.2 ni verificación de noticias (no existen hacia atrás): en vivo hay más filtros, no menos.


## 5. Mejor día de compra

### Ventana de entrada después del disparador
| Setup | Clase | Horizonte | Encogido entrenamiento (t+1,2,3,5,8) | P(mejor) | Crudo prueba |
|---|---|---|---|---|---|
| ATENCION_MOMENTUM | crypto | 7 d | 46% · 46% · 46% · 46% · 46% | 19% · 20% · 20% · 23% · 19% | 27% · 31% · 27% · 37% · 39% |
| ATENCION_MOMENTUM | crypto | 30 d | 49% · 49% · 49% · 49% · 49% | 19% · 20% · 20% · 23% · 18% | 39% · 37% · 33% · 37% · 39% |
| ATENCION_MOMENTUM | crypto | 90 d | 35% · 35% · 35% · 35% · 35% | 19% · 20% · 20% · 22% · 19% | 49% · 49% · 49% · 53% · 47% |
| CAPITULACION | crypto | 7 d | 51% · 51% · 51% · 51% · 51% | 19% · 20% · 20% · 23% · 19% | 21% · 29% · 40% · 47% · 52% |
| CAPITULACION | crypto | 30 d | 42% · 42% · 42% · 42% · 42% | 19% · 20% · 19% · 23% · 19% | 14% · 21% · 28% · 22% · 34% |
| CAPITULACION | crypto | 90 d | 40% · 40% · 40% · 40% · 40% | 19% · 20% · 20% · 22% · 19% | 28% · 31% · 34% · 38% · 43% |
| PANICO_SIN_DANO | crypto | 7 d | 48% · 48% · 48% · 48% · 48% | 19% · 20% · 19% · 23% · 19% | 21% · 23% · 23% · 36% · 67% |
| PANICO_SIN_DANO | crypto | 30 d | 34% · 34% · 34% · 34% · 34% | 19% · 19% · 20% · 22% · 20% | 24% · 20% · 20% · 35% · 33% |
| PANICO_SIN_DANO | crypto | 90 d | 34% · 34% · 34% · 34% · 34% | 19% · 20% · 19% · 22% · 19% | 40% · 37% · 37% · 41% · 55% |
| PULLBACK_TENDENCIA | crypto | 7 d | 43% · 43% · 43% · 43% · 43% | 20% · 19% · 19% · 23% · 19% | 49% · 42% · 40% · 39% · 31% |
| PULLBACK_TENDENCIA | crypto | 30 d | 46% · 46% · 46% · 46% · 46% | 19% · 20% · 19% · 23% · 19% | 30% · 26% · 26% · 32% · 28% |
| PULLBACK_TENDENCIA | crypto | 90 d | 50% · 50% · 50% · 50% · 50% | 19% · 19% · 19% · 23% · 19% | 29% · 25% · 24% · 23% · 24% |
| PULLBACK_TENDENCIA | us | 7 d | 56% · 56% · 56% · 56% · 56% | 20% · 20% · 19% · 22% · 19% | 78% · 71% · 65% · 61% · 66% |
| PULLBACK_TENDENCIA | us | 30 d | 78% · 78% · 78% · 78% · 78% | 20% · 20% · 19% · 21% · 19% | 88% · 92% · 83% · 100% · 95% |

### Día de la semana (comprar un día cualquiera, 7 días)

| Clase | Días | Encogido entrenamiento | P(mejor) | Crudo prueba |
|---|---|---|---|---|
| crypto | lunes · martes · miércoles · jueves · viernes · sábado · domingo | 44.2% · 44.2% · 44.2% · 44.2% · 44.2% · 44.2% · 44.2% | 15% · 14% · 14% · 15% · 14% · 13% · 16% | 37.6% · 38.2% · 39.3% · 38.8% · 39.5% · 37.6% · 37.0% |
| us | lunes · martes · miércoles · jueves · viernes · sábado · domingo | 74.0% · 74.0% · 74.0% · 74.0% · 74.0% · 74.0% · 74.0% | 14% · 14% · 14% · 16% · 13% · 14% · 15% | 72.1% · 59.3% · 66.7% · 70.3% · 67.3% · 69.2% · 54.8% |
| bmv |  |  |  | 43.0% |

Escepticismo de calendario: peso de evidencia 0.16 (E5 × 0.4 por publicación antigua, C08-008/C11-006) → concentración mínima del prior 2000·(1−w).

## Fuentes

| Serie | OK | Último dato | Nota |
|---|---|---|---|
| AAPL | sí | 2026-10-16 | yahoo |
| AC.MX | sí | 2026-10-16 | yahoo |
| ADA | sí | 2026-10-19 | binance |
| ALSEA.MX | sí | 2026-10-16 | yahoo |
| AMXB.MX | sí | 2026-10-16 | yahoo |
| AMZN | sí | 2026-10-16 | yahoo |
| ASURB.MX | sí | 2026-10-16 | yahoo |
| AVAX | sí | 2026-10-19 | binance |
| BBAJIOO.MX | sí | 2026-10-16 | yahoo |
| BCH | sí | 2026-10-19 | binance |
| BIMBOA.MX | sí | 2026-10-16 | yahoo |
| BTC | sí | 2026-10-19 | binance |
| CEMEXCPO.MX | sí | 2026-10-16 | yahoo |
| DIA | sí | 2026-10-16 | yahoo |
| DOGE | sí | 2026-10-19 | binance |
| DOT | sí | 2026-10-19 | binance |
| ETH | sí | 2026-10-19 | binance |
| FEMSAUBD.MX | sí | 2026-10-16 | yahoo |
| GAPB.MX | sí | 2026-10-16 | yahoo |
| GFNORTEO.MX | sí | 2026-10-16 | yahoo |
| GLD | sí | 2026-10-16 | yahoo |
| GMEXICOB.MX | sí | 2026-10-16 | yahoo |
| GOOGL | sí | 2026-10-16 | yahoo |
| GRUMAB.MX | sí | 2026-10-16 | yahoo |
| IWM | sí | 2026-10-16 | yahoo |
| JPM | sí | 2026-10-16 | yahoo |
| KIMBERA.MX | sí | 2026-10-16 | yahoo |
| KOFUBL.MX | sí | 2026-10-16 | yahoo |
| LINK | sí | 2026-10-19 | binance |
| LIVEPOLC-1.MX | sí | 2026-10-16 | yahoo |
| LTC | sí | 2026-10-19 | binance |
| META | sí | 2026-10-16 | yahoo |
| MSFT | sí | 2026-10-16 | yahoo |
| MXN=X | sí | 2026-10-19 | yahoo |
| NAFTRACISHRS.MX | sí | 2026-10-16 | yahoo |
| NVDA | sí | 2026-10-16 | yahoo |
| OMAB.MX | sí | 2026-10-16 | yahoo |
| ORBIA.MX | sí | 2026-10-16 | yahoo |
| PINFRA.MX | sí | 2026-10-16 | yahoo |
| QQQ | sí | 2026-10-16 | yahoo |
| SMH | sí | 2026-10-16 | yahoo |
| SOL | sí | 2026-10-19 | binance |
| SPY | sí | 2026-10-16 | yahoo |
| TRX | sí | 2026-10-19 | binance |
| TSLA | sí | 2026-10-16 | yahoo |
| WALMEX.MX | sí | 2026-10-16 | yahoo |
| WMT | sí | 2026-10-16 | yahoo |
| XLE | sí | 2026-10-16 | yahoo |
| XLF | sí | 2026-10-16 | yahoo |
| XLI | sí | 2026-10-16 | yahoo |
| XLK | sí | 2026-10-16 | yahoo |
| XLP | sí | 2026-10-16 | yahoo |
| XLU | sí | 2026-10-16 | yahoo |
| XLV | sí | 2026-10-16 | yahoo |
| XLY | sí | 2026-10-16 | yahoo |
| XOM | sí | 2026-10-16 | yahoo |
| XRP | sí | 2026-10-19 | binance |
| ^MXX | sí | 2026-10-16 | yahoo |
| ^VIX | sí | 2026-10-16 | yahoo |
| contexto_v42 | sí | 2026-10-19T02:32:35Z | CAUTION |
| fear_greed | sí | 2026-10-19 | alternative.me |
| wiki_en_Bankruptcy | sí | 2026-10-15 | wikimedia |
| wiki_en_Bitcoin | sí | 2026-10-15 | wikimedia |
| wiki_en_Cryptocurrency | sí | 2026-10-15 | wikimedia |
| wiki_en_Dogecoin | sí | 2026-10-15 | wikimedia |
| wiki_en_Ethereum | sí | 2026-10-15 | wikimedia |
| wiki_en_Financial_crisis | sí | 2026-10-15 | wikimedia |
| wiki_en_Inflation | sí | 2026-10-15 | wikimedia |
| wiki_en_Recession | sí | 2026-10-15 | wikimedia |
| wiki_en_Ripple_Labs | sí | 2026-10-15 | wikimedia |
| wiki_en_Solana__blockchain_platform_ | sí | 2026-10-15 | wikimedia |
| wiki_en_Stock_market_crash | sí | 2026-10-15 | wikimedia |
| wiki_en_Unemployment | sí | 2026-10-15 | wikimedia |
| wiki_es_Crisis_económica | sí | 2026-10-15 | wikimedia |
| wiki_es_Desempleo | sí | 2026-10-15 | wikimedia |
| wiki_es_Devaluación | sí | 2026-10-15 | wikimedia |
| wiki_es_Inflación | sí | 2026-10-15 | wikimedia |
| wiki_es_Recesión | sí | 2026-10-15 | wikimedia |


Activos sin historia suficiente o sin datos: IWM, SMH, GLD, AAPL, MSFT, GOOGL, META, TSLA, JPM, XOM, WMT, NAFTRACISHRS.MX, WALMEX.MX, GFNORTEO.MX, AMXB.MX, FEMSAUBD.MX, GMEXICOB.MX, CEMEXCPO.MX, BIMBOA.MX, GAPB.MX, ASURB.MX, OMAB.MX, AC.MX, ORBIA.MX, PINFRA.MX, ALSEA.MX, LIVEPOLC-1.MX, BBAJIOO.MX, GRUMAB.MX, KIMBERA.MX
