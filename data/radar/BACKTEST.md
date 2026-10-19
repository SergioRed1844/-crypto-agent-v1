# Radar EB — validación fuera de muestra

Entrenamiento: disparos **antes de 2022-01-01** · Prueba: **desde 2022-01-01**. Especificaciones probadas (setup × clase × horizonte): **48** — con tantas pruebas, algún resultado bueno puede ser azar (C11-009 B). Umbrales fijados el 18-oct-2026 antes de ver datos.

τ entre setups (logit, entrenamiento): 0.219

## 1. ¿El encogimiento EB predice mejor? (Brier, menor es mejor)

| Clase | Horizonte | Filas | Episodios | Acierto real | Brier EB | Brier tasa base | Brier crudo activo | Brier crudo setup | Skill vs base | Día cualquiera (prueba) |
|---|---|---|---|---|---|---|---|---|---|---|
| bmv | 7 d | 484 | 156 | 29.8% | 0.2110 | 0.2093 | 0.2204 | 0.2151 | -0.8% | 26.7% |
| bmv | 30 d | 479 | 154 | 42.2% | 0.2577 | 0.2622 | 0.2523 | 0.2408 | +1.7% | 32.3% |
| bmv | 90 d | 472 | 150 | 40.5% | 0.2527 | 0.2559 | 0.2545 | 0.2447 | +1.2% | 37.9% |
| crypto | 7 d | 291 | 90 | 28.9% | 0.2179 | 0.2165 | 0.2825 | 0.2737 | -0.6% | 38.3% |
| crypto | 30 d | 290 | 89 | 25.2% | 0.2180 | 0.2206 | 0.2799 | 0.2478 | +1.2% | 39.4% |
| crypto | 90 d | 289 | 88 | 33.2% | 0.2476 | 0.2517 | 0.2986 | 0.2656 | +1.6% | 39.5% |
| us | 7 d | 541 | 145 | 38.3% | 0.2349 | 0.2387 | 0.2421 | 0.2375 | +1.6% | 30.8% |
| us | 30 d | 540 | 144 | 45.0% | 0.2584 | 0.2638 | 0.2544 | 0.2466 | +2.1% | 37.8% |
| us | 90 d | 529 | 137 | 52.7% | 0.2549 | 0.2588 | 0.2598 | 0.2460 | +1.5% | 44.7% |

Skill > 0: el modelo le gana a 'la tasa base del activo' fuera de muestra. Si EB < crudo, el encogimiento sirvió (la promesa de James-Stein).

## 2. Calibración (todas las filas de prueba)

| Tramo predicho | n | Predicho | Real |
|---|---|---|---|
| 0%–40% | 2068 | 31.8% | 35.9% |
| 40%–50% | 1265 | 44.5% | 42.1% |
| 50%–60% | 488 | 53.9% | 41.0% |
| 60%–70% | 89 | 63.9% | 48.3% |
| 70%–100% | 5 | 71.7% | 20.0% |

## 3. Setups fuera de muestra vs comprar un día cualquiera

| Setup | Horizonte | Disparos | Episodios | Acierto | Base local (predicción) | Día cualquiera real (prueba) | Predicho EB | Neto medio | Neto día cualquiera (prueba) |
|---|---|---|---|---|---|---|---|---|---|
| PANICO_SIN_DANO | 7 d | 192 | 27 | 34.9% | 32.6% | 32.9% | 36.6% | -2.3% | 0.0% |
| PANICO_SIN_DANO | 30 d | 192 | 27 | 41.7% | 38.0% | 37.8% | 39.7% | -0.9% | 1.3% |
| PANICO_SIN_DANO | 90 d | 192 | 27 | 47.4% | 45.2% | 42.4% | 45.7% | 3.7% | 4.7% |
| CAPITULACION | 7 d | 110 | 32 | 30.0% | 34.4% | 35.1% | 37.1% | -2.5% | -0.0% |
| CAPITULACION | 30 d | 110 | 32 | 30.0% | 35.9% | 38.4% | 38.2% | -4.5% | 1.3% |
| CAPITULACION | 90 d | 110 | 32 | 44.5% | 40.9% | 40.5% | 42.5% | 1.7% | 4.6% |
| CHOQUE_POLITICO | 7 d | 125 | 8 | 24.8% | 31.4% | 31.5% | 31.9% | -1.2% | -0.0% |
| CHOQUE_POLITICO | 30 d | 125 | 8 | 51.2% | 38.3% | 36.8% | 39.0% | 2.7% | 1.2% |
| CHOQUE_POLITICO | 90 d | 125 | 8 | 50.4% | 46.2% | 42.1% | 46.9% | 5.7% | 4.3% |
| MIEDO_HOGARES | 7 d | 99 | 8 | 44.4% | 23.9% | 26.2% | 24.2% | 1.8% | 0.0% |
| MIEDO_HOGARES | 30 d | 99 | 8 | 44.4% | 31.2% | 33.8% | 31.5% | 2.6% | 1.0% |
| MIEDO_HOGARES | 90 d | 99 | 8 | 52.5% | 39.6% | 41.2% | 39.8% | 6.4% | 3.6% |
| CHOQUE_PESO | 7 d | 144 | 27 | 29.2% | 27.3% | 27.7% | 31.9% | -0.8% | -0.4% |
| CHOQUE_PESO | 30 d | 139 | 25 | 48.2% | 34.7% | 32.9% | 38.8% | 1.8% | 0.3% |
| CHOQUE_PESO | 90 d | 139 | 25 | 38.8% | 43.0% | 37.9% | 44.7% | 2.1% | 2.0% |
| ATENCION_MOMENTUM | 7 d | 51 | 28 | 27.5% | 41.4% | 38.4% | 41.7% | -0.6% | 0.1% |
| ATENCION_MOMENTUM | 30 d | 51 | 28 | 39.2% | 45.6% | 39.6% | 45.4% | 4.1% | 2.1% |
| ATENCION_MOMENTUM | 90 d | 51 | 28 | 49.0% | 51.8% | 40.8% | 48.6% | 19.8% | 7.2% |
| PULLBACK_TENDENCIA | 7 d | 595 | 216 | 34.3% | 33.8% | 31.9% | 36.2% | 0.3% | -0.1% |
| PULLBACK_TENDENCIA | 30 d | 593 | 214 | 35.4% | 42.0% | 37.0% | 39.2% | 0.7% | 1.1% |
| PULLBACK_TENDENCIA | 90 d | 574 | 206 | 40.4% | 49.3% | 42.4% | 45.0% | 3.1% | 4.4% |

## 4. Regla de alerta Selectivo en el periodo de prueba

Alertas: **1** (1 episodios; ~0.2/año sin tope semanal) · acierto real **100.0%** vs predicho 71.8% · neto medio 3.1% · mediana 3.1% · peor caída durante la tenencia -13.4%.

Sin contexto v4.2 ni verificación de noticias (no existen hacia atrás): en vivo hay más filtros, no menos.

| Fecha | Activo | Setup | Horizonte | P | Ganó | Neto | Peor caída |
|---|---|---|---|---|---|---|---|
| 2026-03-09 | GMEXICOB.MX | CHOQUE_PESO | 30 d | 72% | sí | 3.1% | -13.4% |

## 5. Mejor día de compra

### Ventana de entrada después del disparador
| Setup | Clase | Horizonte | Encogido entrenamiento (t+1,2,3,5,8) | P(mejor) | Crudo prueba |
|---|---|---|---|---|---|
| ATENCION_MOMENTUM | crypto | 7 d | 46% · 46% · 46% · 46% · 46% | 19% · 20% · 20% · 23% · 19% | 27% · 31% · 27% · 37% · 39% |
| ATENCION_MOMENTUM | crypto | 30 d | 49% · 49% · 49% · 49% · 49% | 19% · 20% · 20% · 23% · 18% | 39% · 37% · 33% · 37% · 39% |
| ATENCION_MOMENTUM | crypto | 90 d | 35% · 35% · 35% · 35% · 35% | 19% · 20% · 20% · 22% · 19% | 49% · 49% · 49% · 53% · 47% |
| CAPITULACION | bmv | 7 d | 36% · 36% · 36% · 36% · 36% | 19% · 20% · 20% · 22% · 19% | 29% · 21% · 29% · 50% · 21% |
| CAPITULACION | bmv | 30 d | 47% · 47% · 47% · 47% · 47% | 18% · 20% · 20% · 23% · 19% | 29% · 29% · 21% · 21% · 29% |
| CAPITULACION | bmv | 90 d | 54% · 54% · 54% · 54% · 54% | 20% · 20% · 20% · 22% · 18% | 36% · 29% · 36% · 21% · 29% |
| CAPITULACION | crypto | 7 d | 51% · 51% · 51% · 51% · 51% | 19% · 20% · 20% · 23% · 19% | 21% · 29% · 40% · 47% · 52% |
| CAPITULACION | crypto | 30 d | 42% · 42% · 42% · 42% · 42% | 19% · 20% · 19% · 23% · 19% | 14% · 21% · 28% · 22% · 34% |
| CAPITULACION | crypto | 90 d | 40% · 40% · 40% · 40% · 40% | 19% · 20% · 20% · 22% · 19% | 28% · 31% · 34% · 38% · 43% |
| CAPITULACION | us | 7 d | 43% · 43% · 41% · 41% · 43% | 34% · 26% · 9% · 8% · 23% | 45% · 53% · 53% · 37% · 29% |
| CAPITULACION | us | 30 d | 46% · 46% · 46% · 46% · 46% | 19% · 19% · 19% · 22% · 20% | 55% · 50% · 53% · 58% · 53% |
| CAPITULACION | us | 90 d | 50% · 50% · 50% · 50% · 50% | 19% · 20% · 19% · 22% · 20% | 74% · 68% · 66% · 68% · 58% |
| CHOQUE_PESO | bmv | 7 d | 34% · 34% · 34% · 34% · 34% | 20% · 20% · 20% · 22% · 18% | 29% · 28% · 22% · 39% · 37% |
| CHOQUE_PESO | bmv | 30 d | 43% · 43% · 43% · 43% · 43% | 20% · 20% · 19% · 22% · 19% | 48% · 43% · 41% · 40% · 45% |
| CHOQUE_PESO | bmv | 90 d | 47% · 47% · 47% · 47% · 47% | 19% · 20% · 20% · 23% · 18% | 39% · 37% · 40% · 42% · 40% |
| PANICO_SIN_DANO | bmv | 7 d | 35% · 35% · 35% · 35% · 35% | 19% · 20% · 20% · 22% · 19% | 40% · 53% · 87% · 53% · 73% |
| PANICO_SIN_DANO | bmv | 30 d | 35% · 35% · 35% · 35% · 35% | 20% · 20% · 19% · 22% · 19% | 73% · 67% · 73% · 53% · 67% |
| PANICO_SIN_DANO | bmv | 90 d | 44% · 44% · 44% · 44% · 44% | 19% · 20% · 19% · 23% · 19% | 40% · 40% · 47% · 40% · 40% |
| PANICO_SIN_DANO | crypto | 7 d | 48% · 48% · 48% · 48% · 48% | 19% · 20% · 19% · 23% · 19% | 21% · 23% · 23% · 36% · 67% |
| PANICO_SIN_DANO | crypto | 30 d | 34% · 34% · 34% · 34% · 34% | 19% · 19% · 20% · 22% · 20% | 24% · 20% · 20% · 35% · 33% |
| PANICO_SIN_DANO | crypto | 90 d | 34% · 34% · 34% · 34% · 34% | 19% · 20% · 19% · 22% · 19% | 40% · 37% · 37% · 41% · 55% |
| PANICO_SIN_DANO | us | 7 d | 35% · 35% · 35% · 35% · 35% | 19% · 20% · 19% · 23% · 19% | 44% · 57% · 40% · 38% · 47% |
| PANICO_SIN_DANO | us | 30 d | 38% · 38% · 38% · 38% · 38% | 20% · 20% · 19% · 22% · 19% | 50% · 61% · 51% · 38% · 41% |
| PANICO_SIN_DANO | us | 90 d | 45% · 45% · 45% · 45% · 45% | 19% · 20% · 20% · 23% · 19% | 54% · 58% · 56% · 54% · 56% |
| PULLBACK_TENDENCIA | bmv | 7 d | 35% · 32% · 31% · 29% · 27% | 79% · 15% · 5% · 1% · 0% | 29% · 27% · 30% · 27% · 30% |
| PULLBACK_TENDENCIA | bmv | 30 d | 36% · 36% · 36% · 36% · 36% | 22% · 20% · 19% · 22% · 17% | 36% · 36% · 41% · 35% · 33% |
| PULLBACK_TENDENCIA | bmv | 90 d | 45% · 45% · 45% · 45% · 45% | 18% · 20% · 20% · 23% · 20% | 40% · 38% · 40% · 41% · 38% |
| PULLBACK_TENDENCIA | crypto | 7 d | 43% · 43% · 43% · 43% · 43% | 20% · 19% · 19% · 23% · 19% | 49% · 42% · 40% · 39% · 31% |
| PULLBACK_TENDENCIA | crypto | 30 d | 46% · 46% · 46% · 46% · 46% | 19% · 20% · 19% · 23% · 19% | 30% · 26% · 26% · 32% · 28% |
| PULLBACK_TENDENCIA | crypto | 90 d | 50% · 50% · 50% · 50% · 50% | 19% · 19% · 19% · 23% · 19% | 29% · 25% · 24% · 23% · 24% |
| PULLBACK_TENDENCIA | us | 7 d | 34% · 34% · 34% · 34% · 34% | 21% · 20% · 18% · 22% · 19% | 35% · 33% · 36% · 32% · 32% |
| PULLBACK_TENDENCIA | us | 30 d | 39% · 39% · 39% · 39% · 39% | 20% · 19% · 18% · 23% · 20% | 36% · 37% · 39% · 39% · 35% |
| PULLBACK_TENDENCIA | us | 90 d | 44% · 44% · 44% · 44% · 44% | 21% · 19% · 19% · 22% · 19% | 45% · 46% · 43% · 44% · 45% |

### Día de la semana (comprar un día cualquiera, 7 días)

| Clase | Días | Encogido entrenamiento | P(mejor) | Crudo prueba |
|---|---|---|---|---|
| crypto | lunes · martes · miércoles · jueves · viernes · sábado · domingo | 44.2% · 44.2% · 44.2% · 44.2% · 44.2% · 44.2% · 44.2% | 15% · 14% · 14% · 15% · 14% · 13% · 16% | 37.6% · 38.2% · 39.3% · 38.8% · 39.5% · 37.6% · 37.0% |
| us | lunes · martes · miércoles · jueves · viernes | 27.9% · 27.9% · 27.9% · 27.9% · 27.9% | 20% · 20% · 19% · 21% · 20% | 30.1% · 30.7% · 30.9% · 31.5% · 30.8% |
| bmv | lunes · martes · miércoles · jueves · viernes | 26.1% · 26.1% · 26.1% · 26.1% · 26.1% | 19% · 21% · 19% · 21% · 20% | 26.4% · 27.3% · 27.2% · 26.5% · 26.2% |

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
