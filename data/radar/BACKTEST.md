# Radar EB — validación fuera de muestra

Entrenamiento: disparos **antes de 2022-01-01** · Prueba: **desde 2022-01-01**. Especificaciones probadas (setup × clase × horizonte): **48** — con tantas pruebas, algún resultado bueno puede ser azar (C11-009 B). Umbrales fijados el 18-oct-2026 antes de ver datos.

τ entre setups (logit, entrenamiento): 0.139

## 1. ¿El encogimiento EB predice mejor? (Brier, menor es mejor)

| Clase | Horizonte | Filas | Episodios | Acierto real | Brier EB | Brier tasa base | Brier crudo activo | Brier crudo setup | Skill vs base | Día cualquiera (prueba) |
|---|---|---|---|---|---|---|---|---|---|---|
| bmv | 7 d | 489 | 113 | 30.3% | 0.2112 | 0.2099 | 0.2151 | 0.2163 | -0.6% | 26.7% |
| bmv | 30 d | 484 | 45 | 41.3% | 0.2487 | 0.2501 | 0.2501 | 0.2399 | +0.6% | 32.3% |
| bmv | 90 d | 477 | 43 | 41.3% | 0.2450 | 0.2451 | 0.2568 | 0.2471 | +0.0% | 37.9% |
| crypto | 7 d | 291 | 70 | 28.9% | 0.2385 | 0.2374 | 0.2828 | 0.2706 | -0.5% | 38.3% |
| crypto | 30 d | 290 | 32 | 25.2% | 0.2520 | 0.2550 | 0.2765 | 0.2377 | +1.2% | 39.4% |
| crypto | 90 d | 289 | 31 | 33.2% | 0.3048 | 0.3084 | 0.3096 | 0.2676 | +1.2% | 39.5% |
| us | 7 d | 541 | 103 | 38.3% | 0.2366 | 0.2405 | 0.2421 | 0.2382 | +1.6% | 30.8% |
| us | 30 d | 540 | 44 | 45.0% | 0.2612 | 0.2639 | 0.2563 | 0.2474 | +1.0% | 37.8% |
| us | 90 d | 529 | 42 | 52.7% | 0.2595 | 0.2612 | 0.2594 | 0.2453 | +0.7% | 44.7% |

Skill > 0: el modelo le gana a 'la tasa base del activo' fuera de muestra. Si EB < crudo, el encogimiento sirvió (la promesa de James-Stein).

## 2. Calibración (todas las filas de prueba)

| Tramo predicho | n | Predicho | Real |
|---|---|---|---|
| 0%–40% | 1804 | 32.6% | 38.7% |
| 40%–50% | 1352 | 44.5% | 41.3% |
| 50%–60% | 662 | 54.2% | 34.3% |
| 60%–70% | 57 | 65.4% | 31.6% |
| 70%–100% | 55 | 81.0% | 43.6% |

## 3. Setups fuera de muestra vs comprar un día cualquiera

| Setup | Clase | Horizonte | Disparos | Episodios | Acierto | Base local (predicción) | Día cualquiera real (prueba) | Predicho EB | Neto medio | Neto día cualquiera (prueba) |
|---|---|---|---|---|---|---|---|---|---|---|
| PANICO_SIN_DANO | bmv | 7 d | 15 | 4 | 40.0% | 26.6% | 26.6% | 28.6% | 1.4% | -0.4% |
| PANICO_SIN_DANO | bmv | 30 d | 15 | 3 | 73.3% | 34.1% | 31.7% | 35.8% | 7.5% | 0.4% |
| PANICO_SIN_DANO | bmv | 90 d | 15 | 3 | 40.0% | 43.1% | 37.6% | 43.3% | 4.6% | 2.4% |
| PANICO_SIN_DANO | crypto | 7 d | 75 | 11 | 21.3% | 46.9% | 38.3% | 47.5% | -7.8% | 0.0% |
| PANICO_SIN_DANO | crypto | 30 d | 75 | 9 | 24.0% | 50.8% | 39.9% | 49.5% | -7.3% | 1.7% |
| PANICO_SIN_DANO | crypto | 90 d | 75 | 9 | 40.0% | 60.7% | 40.7% | 60.0% | -1.7% | 5.8% |
| PANICO_SIN_DANO | us | 7 d | 102 | 16 | 44.1% | 28.0% | 29.8% | 32.9% | 1.2% | 0.1% |
| PANICO_SIN_DANO | us | 30 d | 102 | 14 | 50.0% | 35.6% | 37.1% | 40.1% | 2.6% | 1.2% |
| PANICO_SIN_DANO | us | 90 d | 102 | 14 | 53.9% | 43.1% | 44.4% | 45.7% | 7.6% | 4.3% |
| CAPITULACION | bmv | 7 d | 14 | 10 | 28.6% | 25.3% | 27.8% | 27.4% | -0.1% | -0.5% |
| CAPITULACION | bmv | 30 d | 14 | 7 | 28.6% | 33.5% | 33.5% | 35.2% | -1.7% | -0.3% |
| CAPITULACION | bmv | 90 d | 14 | 7 | 35.7% | 43.2% | 36.3% | 45.5% | 2.2% | 0.5% |
| CAPITULACION | crypto | 7 d | 58 | 12 | 20.7% | 47.4% | 38.2% | 47.7% | -6.2% | -0.0% |
| CAPITULACION | crypto | 30 d | 58 | 10 | 13.8% | 50.8% | 38.7% | 50.6% | -10.8% | 1.5% |
| CAPITULACION | crypto | 90 d | 58 | 10 | 27.6% | 62.4% | 37.9% | 62.2% | -6.2% | 5.1% |
| CAPITULACION | us | 7 d | 38 | 14 | 44.7% | 31.2% | 33.0% | 35.7% | 2.0% | 0.1% |
| CAPITULACION | us | 30 d | 38 | 8 | 55.3% | 37.7% | 39.6% | 40.4% | 4.3% | 1.5% |
| CAPITULACION | us | 90 d | 38 | 8 | 73.7% | 45.8% | 46.1% | 47.1% | 13.7% | 5.4% |
| CHOQUE_POLITICO | bmv | 7 d | 33 | 4 | 33.3% | 25.9% | 25.8% | 26.1% | 0.3% | -0.4% |
| CHOQUE_POLITICO | bmv | 30 d | 33 | 4 | 57.6% | 34.4% | 31.3% | 35.2% | 5.2% | 0.3% |
| CHOQUE_POLITICO | bmv | 90 d | 33 | 4 | 51.5% | 43.3% | 37.0% | 43.6% | 7.8% | 2.1% |
| CHOQUE_POLITICO | crypto | 7 d | 26 | 3 | 7.7% | 46.9% | 38.3% | 47.1% | -6.2% | 0.0% |
| CHOQUE_POLITICO | crypto | 30 d | 26 | 3 | 11.5% | 51.0% | 39.6% | 51.2% | -6.7% | 1.7% |
| CHOQUE_POLITICO | crypto | 90 d | 26 | 3 | 7.7% | 61.2% | 39.9% | 61.3% | -13.8% | 5.8% |
| CHOQUE_POLITICO | us | 7 d | 66 | 5 | 27.3% | 30.0% | 31.6% | 30.3% | 0.0% | 0.1% |
| CHOQUE_POLITICO | us | 30 d | 66 | 4 | 63.6% | 37.3% | 38.4% | 37.5% | 5.2% | 1.4% |
| CHOQUE_POLITICO | us | 90 d | 66 | 4 | 66.7% | 44.8% | 45.5% | 45.3% | 12.4% | 4.9% |
| MIEDO_HOGARES | bmv | 7 d | 1 | 1 | 100.0% | 15.7% | 15.5% | 15.7% | 4.0% | -0.5% |
| MIEDO_HOGARES | bmv | 30 d | 1 | 1 | 100.0% | 26.3% | 22.2% | 26.2% | 13.2% | 0.1% |
| MIEDO_HOGARES | bmv | 90 d | 1 | 1 | 100.0% | 34.5% | 30.7% | 34.5% | 14.1% | 1.5% |
| MIEDO_HOGARES | us | 7 d | 98 | 7 | 43.9% | 24.1% | 26.4% | 24.3% | 1.8% | 0.0% |
| MIEDO_HOGARES | us | 30 d | 98 | 6 | 43.9% | 31.2% | 33.9% | 31.4% | 2.5% | 1.0% |
| MIEDO_HOGARES | us | 90 d | 98 | 6 | 52.0% | 39.0% | 41.3% | 39.2% | 6.3% | 3.6% |
| CHOQUE_PESO | bmv | 7 d | 149 | 25 | 30.9% | 27.2% | 27.6% | 29.1% | -0.4% | -0.4% |
| CHOQUE_PESO | bmv | 30 d | 144 | 19 | 45.1% | 35.7% | 32.9% | 37.8% | 2.6% | 0.3% |
| CHOQUE_PESO | bmv | 90 d | 144 | 19 | 41.7% | 44.3% | 37.8% | 45.1% | 3.7% | 2.0% |
| ATENCION_MOMENTUM | crypto | 7 d | 51 | 25 | 27.5% | 46.7% | 38.4% | 46.4% | -0.6% | 0.1% |
| ATENCION_MOMENTUM | crypto | 30 d | 51 | 15 | 39.2% | 50.5% | 39.6% | 49.9% | 4.1% | 2.1% |
| ATENCION_MOMENTUM | crypto | 90 d | 51 | 15 | 49.0% | 60.2% | 40.8% | 59.1% | 19.8% | 7.2% |
| PULLBACK_TENDENCIA | bmv | 7 d | 277 | 104 | 28.9% | 29.1% | 28.6% | 34.4% | -0.1% | -0.4% |
| PULLBACK_TENDENCIA | bmv | 30 d | 277 | 44 | 36.1% | 37.5% | 34.2% | 38.1% | 1.0% | 0.5% |
| PULLBACK_TENDENCIA | bmv | 90 d | 270 | 42 | 40.0% | 46.0% | 40.1% | 45.8% | 2.9% | 2.6% |
| PULLBACK_TENDENCIA | crypto | 7 d | 81 | 34 | 49.4% | 47.8% | 38.3% | 48.2% | 1.8% | 0.0% |
| PULLBACK_TENDENCIA | crypto | 30 d | 80 | 20 | 30.0% | 51.3% | 38.7% | 50.5% | -1.6% | 1.8% |
| PULLBACK_TENDENCIA | crypto | 90 d | 79 | 19 | 29.1% | 63.3% | 37.7% | 62.1% | -3.4% | 6.2% |
| PULLBACK_TENDENCIA | us | 7 d | 237 | 99 | 35.4% | 31.8% | 33.5% | 35.6% | 0.2% | 0.2% |
| PULLBACK_TENDENCIA | us | 30 d | 236 | 43 | 36.4% | 38.6% | 39.7% | 39.6% | 1.1% | 1.7% |
| PULLBACK_TENDENCIA | us | 90 d | 225 | 41 | 44.9% | 44.6% | 46.8% | 46.2% | 5.7% | 5.9% |

## 4. Reglas de alerta en el periodo de prueba

Regla activa: **relativo**. Sin contexto v4.2 ni verificación de noticias ni tope semanal (no existen hacia atrás): en vivo hay más filtros, no menos. Se reportan las tres reglas para que se vea el costo de cada una.

| Regla | Alertas | Episodios | Por año | Acierto | Día cualquiera (local) | Predicho | Neto medio | Mediana | Neto día cualquiera | % positivas | Peor caída |
|---|---|---|---|---|---|---|---|---|---|---|---|
| relativo | 17 | 10 | 3.5 | 58.8% | 30.8% | 36.8% | 2.2% | 3.2% | 0.5% | 65% | -12.3% |
| estricta | 0 | 0 | 0.0 | — | — | — | — | — | — | — | — |
| selectivo | 0 | 0 | 0.0 | — | — | — | — | — | — | — | — |

Alertas de la regla activa (relativo):

| Fecha | Activo | Setup | Horizonte | P | Base | Ganó | Neto | Peor caída |
|---|---|---|---|---|---|---|---|---|
| 2022-03-07 | DIA | PANICO_SIN_DANO | 30 d | 32% | 25% | sí | 5.5% | -0.7% |
| 2022-04-22 | DIA | PANICO_SIN_DANO | 30 d | 31% | 25% | no | -5.2% | -8.8% |
| 2022-04-22 | XLV | PANICO_SIN_DANO | 30 d | 35% | 28% | no | -2.0% | -6.0% |
| 2022-04-27 | NVDA | CAPITULACION | 7 d | 47% | 42% | sí | 7.0% | -3.0% |
| 2022-04-29 | XLP | PANICO_SIN_DANO | 30 d | 27% | 20% | no | -5.0% | -11.0% |
| 2022-09-01 | NVDA | CAPITULACION | 7 d | 45% | 40% | sí | 1.9% | -5.3% |
| 2022-10-07 | TSLA | CAPITULACION | 7 d | 48% | 42% | no | -8.7% | -8.8% |
| 2022-11-21 | TSLA | CAPITULACION | 7 d | 46% | 41% | sí | 7.0% | -1.5% |
| 2024-12-18 | DIA | PANICO_SIN_DANO | 30 d | 32% | 26% | sí | 3.4% | -1.8% |
| 2024-12-18 | XLP | PANICO_SIN_DANO | 30 d | 27% | 20% | no | -3.1% | -4.7% |
| 2025-03-10 | DIA | PANICO_SIN_DANO | 30 d | 33% | 27% | no | -10.1% | -12.3% |
| 2025-03-10 | TSLA | CAPITULACION | 7 d | 48% | 43% | sí | 5.4% | -3.7% |
| 2025-04-03 | DIA | PANICO_SIN_DANO | 30 d | 33% | 27% | sí | 4.2% | -7.2% |
| 2025-04-04 | NVDA | CAPITULACION | 7 d | 47% | 42% | sí | 26.6% | -1.0% |
| 2025-04-04 | XLP | PANICO_SIN_DANO | 30 d | 27% | 21% | sí | 6.0% | -1.3% |
| 2025-04-04 | XLV | PANICO_SIN_DANO | 30 d | 33% | 27% | no | 1.8% | -1.6% |
| 2025-10-10 | DIA | PANICO_SIN_DANO | 30 d | 34% | 28% | sí | 3.2% | -0.8% |

## 5. Mejor día de compra

### Ventana de entrada después del disparador
| Setup | Clase | Horizonte | Encogido entrenamiento (t+1,2,3,5,8) | P(mejor) | Crudo prueba |
|---|---|---|---|---|---|
| ATENCION_MOMENTUM | crypto | 7 d | 45% · 45% · 45% · 45% · 45% | 19% · 20% · 20% · 23% · 19% | 27% · 31% · 27% · 37% · 39% |
| ATENCION_MOMENTUM | crypto | 30 d | 34% · 34% · 34% · 34% · 34% | 19% · 20% · 20% · 22% · 19% | 39% · 37% · 33% · 37% · 39% |
| ATENCION_MOMENTUM | crypto | 90 d | 38% · 38% · 38% · 38% · 38% | 19% · 20% · 20% · 22% · 19% | 49% · 49% · 49% · 53% · 47% |
| CAPITULACION | bmv | 7 d | 36% · 36% · 36% · 36% · 36% | 19% · 20% · 20% · 22% · 19% | 29% · 21% · 29% · 50% · 21% |
| CAPITULACION | bmv | 30 d | 52% · 52% · 52% · 52% · 52% | 19% · 20% · 20% · 22% · 19% | 29% · 29% · 21% · 21% · 29% |
| CAPITULACION | bmv | 90 d | 59% · 59% · 59% · 59% · 59% | 20% · 20% · 20% · 22% · 18% | 36% · 29% · 36% · 21% · 29% |
| CAPITULACION | crypto | 7 d | 51% · 51% · 51% · 51% · 51% | 19% · 20% · 20% · 23% · 19% | 21% · 29% · 40% · 47% · 52% |
| CAPITULACION | crypto | 30 d | 40% · 40% · 40% · 40% · 40% | 19% · 20% · 20% · 22% · 19% | 14% · 21% · 28% · 22% · 34% |
| CAPITULACION | crypto | 90 d | 44% · 44% · 44% · 44% · 44% | 19% · 20% · 20% · 23% · 19% | 28% · 31% · 34% · 38% · 43% |
| CAPITULACION | us | 7 d | 48% · 46% · 41% · 40% · 45% | 48% · 27% · 3% · 2% · 20% | 45% · 53% · 53% · 37% · 29% |
| CAPITULACION | us | 30 d | 51% · 51% · 51% · 51% · 51% | 20% · 20% · 19% · 22% · 19% | 55% · 50% · 53% · 58% · 53% |
| CAPITULACION | us | 90 d | 56% · 56% · 56% · 56% · 56% | 20% · 20% · 19% · 22% · 19% | 74% · 68% · 66% · 68% · 58% |
| CHOQUE_PESO | bmv | 7 d | 32% · 32% · 32% · 32% · 32% | 20% · 19% · 20% · 22% · 18% | 31% · 20% · 35% · 32% · 36% |
| CHOQUE_PESO | bmv | 30 d | 44% · 44% · 44% · 44% · 44% | 19% · 20% · 20% · 23% · 19% | 45% · 46% · 47% · 42% · 44% |
| CHOQUE_PESO | bmv | 90 d | 49% · 49% · 49% · 49% · 49% | 19% · 20% · 20% · 23% · 19% | 42% · 44% · 49% · 41% · 40% |
| PANICO_SIN_DANO | bmv | 7 d | 34% · 34% · 34% · 34% · 34% | 19% · 20% · 20% · 22% · 19% | 40% · 53% · 87% · 53% · 73% |
| PANICO_SIN_DANO | bmv | 30 d | 40% · 40% · 40% · 40% · 40% | 20% · 20% · 19% · 22% · 19% | 73% · 67% · 73% · 53% · 67% |
| PANICO_SIN_DANO | bmv | 90 d | 44% · 44% · 44% · 44% · 44% | 19% · 20% · 19% · 23% · 19% | 40% · 40% · 47% · 40% · 40% |
| PANICO_SIN_DANO | crypto | 7 d | 48% · 48% · 48% · 48% · 48% | 19% · 20% · 19% · 23% · 19% | 21% · 23% · 23% · 36% · 67% |
| PANICO_SIN_DANO | crypto | 30 d | 24% · 24% · 24% · 24% · 24% | 19% · 19% · 20% · 22% · 19% | 24% · 20% · 20% · 35% · 33% |
| PANICO_SIN_DANO | crypto | 90 d | 39% · 39% · 39% · 39% · 39% | 19% · 20% · 19% · 22% · 19% | 40% · 37% · 37% · 41% · 55% |
| PANICO_SIN_DANO | us | 7 d | 36% · 36% · 36% · 36% · 36% | 19% · 20% · 19% · 23% · 18% | 44% · 57% · 40% · 38% · 47% |
| PANICO_SIN_DANO | us | 30 d | 41% · 41% · 41% · 41% · 41% | 19% · 20% · 19% · 23% · 19% | 50% · 61% · 51% · 38% · 41% |
| PANICO_SIN_DANO | us | 90 d | 48% · 48% · 48% · 48% · 48% | 19% · 20% · 19% · 23% · 19% | 54% · 58% · 56% · 54% · 56% |
| PULLBACK_TENDENCIA | bmv | 7 d | 36% · 33% · 32% · 29% · 26% | 79% · 15% · 5% · 0% · 0% | 29% · 27% · 30% · 27% · 30% |
| PULLBACK_TENDENCIA | bmv | 30 d | 37% · 37% · 37% · 37% · 37% | 20% · 20% · 19% · 22% · 19% | 36% · 36% · 41% · 35% · 33% |
| PULLBACK_TENDENCIA | bmv | 90 d | 46% · 46% · 46% · 46% · 46% | 19% · 20% · 19% · 23% · 19% | 40% · 38% · 40% · 41% · 38% |
| PULLBACK_TENDENCIA | crypto | 7 d | 43% · 43% · 43% · 43% · 43% | 20% · 19% · 19% · 23% · 19% | 49% · 42% · 40% · 39% · 31% |
| PULLBACK_TENDENCIA | crypto | 30 d | 41% · 41% · 41% · 41% · 41% | 19% · 20% · 19% · 23% · 19% | 30% · 26% · 26% · 32% · 28% |
| PULLBACK_TENDENCIA | crypto | 90 d | 50% · 50% · 50% · 50% · 50% | 19% · 20% · 19% · 23% · 19% | 29% · 25% · 24% · 23% · 24% |
| PULLBACK_TENDENCIA | us | 7 d | 37% · 37% · 36% · 36% · 36% | 21% · 20% · 19% · 21% · 19% | 35% · 33% · 36% · 32% · 32% |
| PULLBACK_TENDENCIA | us | 30 d | 42% · 42% · 42% · 42% · 42% | 19% · 20% · 19% · 23% · 19% | 36% · 37% · 39% · 39% · 35% |
| PULLBACK_TENDENCIA | us | 90 d | 47% · 47% · 47% · 47% · 47% | 20% · 20% · 19% · 22% · 19% | 45% · 46% · 43% · 44% · 45% |

### Día de la semana (comprar un día cualquiera, 7 días)

| Clase | Días | Encogido entrenamiento | P(mejor) | Crudo prueba |
|---|---|---|---|---|
| crypto | lunes · martes · miércoles · jueves · viernes · sábado · domingo | 44.4% · 44.4% · 44.4% · 44.4% · 44.4% · 44.4% · 44.4% | 15% · 14% · 14% · 16% · 14% · 13% · 16% | 37.6% · 38.2% · 39.3% · 38.8% · 39.5% · 37.6% · 37.0% |
| us | lunes · martes · miércoles · jueves · viernes | 28.0% · 28.0% · 27.9% · 27.9% · 28.0% | 20% · 20% · 19% · 21% · 20% | 30.1% · 30.7% · 30.9% · 31.5% · 30.8% |
| bmv | lunes · martes · miércoles · jueves · viernes | 26.1% · 26.1% · 26.1% · 26.1% · 26.1% | 20% · 21% · 19% · 21% · 20% | 26.4% · 27.3% · 27.2% · 26.5% · 26.2% |

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
| contexto_v42 | sí | 2026-10-19T03:31:37Z | CAUTION |
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
