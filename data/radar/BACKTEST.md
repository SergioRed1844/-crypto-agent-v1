# Radar EB — validación fuera de muestra

Entrenamiento: disparos **antes de 2022-01-01** · Prueba: **desde 2022-01-01**. Especificaciones probadas (setup × clase × horizonte): **48** — con tantas pruebas, algún resultado bueno puede ser azar (C11-009 B). Umbrales fijados el 18-oct-2026 antes de ver datos.

τ entre setups (logit, entrenamiento): 0.219

## 1. ¿El encogimiento EB predice mejor? (Brier, menor es mejor)

| Clase | Horizonte | Filas | Episodios | Acierto real | Brier EB | Brier tasa base | Brier crudo activo | Brier crudo setup | Skill vs base | Día cualquiera (prueba) |
|---|---|---|---|---|---|---|---|---|---|---|
| bmv | 7 d | 484 | 156 | 29.8% | 0.2115 | 0.2093 | 0.2204 | 0.2151 | -1.1% | 26.7% |
| bmv | 30 d | 479 | 154 | 42.2% | 0.2569 | 0.2622 | 0.2523 | 0.2408 | +2.0% | 32.3% |
| bmv | 90 d | 472 | 150 | 40.5% | 0.2527 | 0.2559 | 0.2545 | 0.2447 | +1.2% | 37.9% |
| crypto | 7 d | 291 | 90 | 28.9% | 0.2189 | 0.2165 | 0.2825 | 0.2737 | -1.1% | 38.3% |
| crypto | 30 d | 290 | 89 | 25.2% | 0.2168 | 0.2206 | 0.2799 | 0.2478 | +1.7% | 39.4% |
| crypto | 90 d | 289 | 88 | 33.2% | 0.2460 | 0.2517 | 0.2986 | 0.2656 | +2.3% | 39.5% |
| us | 7 d | 541 | 145 | 38.3% | 0.2341 | 0.2387 | 0.2421 | 0.2375 | +1.9% | 30.8% |
| us | 30 d | 540 | 144 | 45.0% | 0.2575 | 0.2638 | 0.2544 | 0.2466 | +2.4% | 37.8% |
| us | 90 d | 529 | 137 | 52.7% | 0.2536 | 0.2588 | 0.2598 | 0.2460 | +2.0% | 44.7% |

Skill > 0: el modelo le gana a 'la tasa base del activo' fuera de muestra. Si EB < crudo, el encogimiento sirvió (la promesa de James-Stein).

## 2. Calibración (todas las filas de prueba)

| Tramo predicho | n | Predicho | Real |
|---|---|---|---|
| 0%–40% | 2064 | 32.0% | 35.8% |
| 40%–50% | 1271 | 44.5% | 41.9% |
| 50%–60% | 474 | 53.7% | 41.4% |
| 60%–70% | 101 | 63.4% | 50.5% |
| 70%–100% | 5 | 71.8% | 20.0% |

## 3. Setups fuera de muestra vs comprar un día cualquiera

| Setup | Clase | Horizonte | Disparos | Episodios | Acierto | Base local (predicción) | Día cualquiera real (prueba) | Predicho EB | Neto medio | Neto día cualquiera (prueba) |
|---|---|---|---|---|---|---|---|---|---|---|
| PANICO_SIN_DANO | bmv | 7 d | 15 | 4 | 40.0% | 26.3% | 26.6% | 30.5% | 1.4% | -0.4% |
| PANICO_SIN_DANO | bmv | 30 d | 15 | 4 | 73.3% | 30.0% | 31.7% | 31.5% | 7.5% | 0.4% |
| PANICO_SIN_DANO | bmv | 90 d | 15 | 4 | 40.0% | 37.1% | 37.6% | 36.5% | 4.6% | 2.4% |
| PANICO_SIN_DANO | crypto | 7 d | 75 | 14 | 21.3% | 39.4% | 38.3% | 41.0% | -7.8% | 0.0% |
| PANICO_SIN_DANO | crypto | 30 d | 75 | 14 | 24.0% | 40.0% | 39.9% | 37.6% | -7.3% | 1.7% |
| PANICO_SIN_DANO | crypto | 90 d | 75 | 14 | 40.0% | 45.7% | 40.7% | 43.3% | -1.7% | 5.8% |
| PANICO_SIN_DANO | us | 7 d | 102 | 18 | 44.1% | 28.6% | 29.8% | 36.5% | 1.2% | 0.1% |
| PANICO_SIN_DANO | us | 30 d | 102 | 18 | 50.0% | 37.8% | 37.1% | 42.7% | 2.6% | 1.2% |
| PANICO_SIN_DANO | us | 90 d | 102 | 18 | 53.9% | 46.1% | 44.4% | 48.7% | 7.6% | 4.3% |
| CAPITULACION | bmv | 7 d | 14 | 10 | 28.6% | 23.8% | 27.8% | 27.9% | -0.1% | -0.5% |
| CAPITULACION | bmv | 30 d | 14 | 10 | 28.6% | 25.2% | 33.5% | 29.6% | -1.7% | -0.3% |
| CAPITULACION | bmv | 90 d | 14 | 10 | 35.7% | 31.7% | 36.3% | 38.5% | 2.2% | 0.5% |
| CAPITULACION | crypto | 7 d | 58 | 13 | 20.7% | 39.2% | 38.2% | 40.2% | -6.2% | -0.0% |
| CAPITULACION | crypto | 30 d | 58 | 13 | 13.8% | 39.8% | 38.7% | 39.5% | -10.8% | 1.5% |
| CAPITULACION | crypto | 90 d | 58 | 13 | 27.6% | 44.8% | 37.9% | 43.8% | -6.2% | 5.1% |
| CAPITULACION | us | 7 d | 38 | 18 | 44.7% | 31.0% | 33.0% | 39.6% | 2.0% | 0.1% |
| CAPITULACION | us | 30 d | 38 | 18 | 55.3% | 33.9% | 39.6% | 41.5% | 4.3% | 1.5% |
| CAPITULACION | us | 90 d | 38 | 18 | 73.7% | 38.5% | 46.1% | 43.6% | 13.7% | 5.4% |
| CHOQUE_POLITICO | bmv | 7 d | 33 | 5 | 33.3% | 25.4% | 25.8% | 26.7% | 0.3% | -0.4% |
| CHOQUE_POLITICO | bmv | 30 d | 33 | 5 | 57.6% | 32.1% | 31.3% | 34.9% | 5.2% | 0.3% |
| CHOQUE_POLITICO | bmv | 90 d | 33 | 5 | 51.5% | 41.8% | 37.0% | 42.7% | 7.8% | 2.1% |
| CHOQUE_POLITICO | crypto | 7 d | 26 | 3 | 7.7% | 40.4% | 38.3% | 40.8% | -6.2% | 0.0% |
| CHOQUE_POLITICO | crypto | 30 d | 26 | 3 | 11.5% | 44.2% | 39.6% | 44.6% | -6.7% | 1.7% |
| CHOQUE_POLITICO | crypto | 90 d | 26 | 3 | 7.7% | 50.8% | 39.9% | 51.1% | -13.8% | 5.8% |
| CHOQUE_POLITICO | us | 7 d | 66 | 5 | 27.3% | 30.9% | 31.6% | 31.7% | 0.0% | 0.1% |
| CHOQUE_POLITICO | us | 30 d | 66 | 5 | 63.6% | 39.0% | 38.4% | 39.6% | 5.2% | 1.4% |
| CHOQUE_POLITICO | us | 90 d | 66 | 5 | 66.7% | 46.6% | 45.5% | 48.3% | 12.4% | 4.9% |
| MIEDO_HOGARES | bmv | 7 d | 1 | 1 | 100.0% | 12.6% | 15.5% | 12.6% | 4.0% | -0.5% |
| MIEDO_HOGARES | bmv | 30 d | 1 | 1 | 100.0% | 16.3% | 22.2% | 16.3% | 13.2% | 0.1% |
| MIEDO_HOGARES | bmv | 90 d | 1 | 1 | 100.0% | 25.2% | 30.7% | 25.4% | 14.1% | 1.5% |
| MIEDO_HOGARES | us | 7 d | 98 | 7 | 43.9% | 24.0% | 26.4% | 24.5% | 1.8% | 0.0% |
| MIEDO_HOGARES | us | 30 d | 98 | 7 | 43.9% | 31.4% | 33.9% | 31.8% | 2.5% | 1.0% |
| MIEDO_HOGARES | us | 90 d | 98 | 7 | 52.0% | 39.7% | 41.3% | 40.0% | 6.3% | 3.6% |
| CHOQUE_PESO | bmv | 7 d | 144 | 27 | 29.2% | 27.3% | 27.7% | 33.1% | -0.8% | -0.4% |
| CHOQUE_PESO | bmv | 30 d | 139 | 25 | 48.2% | 34.7% | 32.9% | 39.7% | 1.8% | 0.3% |
| CHOQUE_PESO | bmv | 90 d | 139 | 25 | 38.8% | 43.0% | 37.9% | 45.2% | 2.1% | 2.0% |
| ATENCION_MOMENTUM | crypto | 7 d | 51 | 28 | 27.5% | 41.4% | 38.4% | 41.8% | -0.6% | 0.1% |
| ATENCION_MOMENTUM | crypto | 30 d | 51 | 28 | 39.2% | 45.6% | 39.6% | 45.3% | 4.1% | 2.1% |
| ATENCION_MOMENTUM | crypto | 90 d | 51 | 28 | 49.0% | 51.8% | 40.8% | 46.9% | 19.8% | 7.2% |
| PULLBACK_TENDENCIA | bmv | 7 d | 277 | 139 | 28.9% | 30.8% | 28.6% | 35.2% | -0.1% | -0.4% |
| PULLBACK_TENDENCIA | bmv | 30 d | 277 | 139 | 36.1% | 40.0% | 34.2% | 36.7% | 1.0% | 0.5% |
| PULLBACK_TENDENCIA | bmv | 90 d | 270 | 135 | 40.0% | 48.4% | 40.1% | 42.4% | 2.9% | 2.6% |
| PULLBACK_TENDENCIA | crypto | 7 d | 81 | 44 | 49.4% | 42.1% | 38.3% | 43.1% | 1.8% | 0.0% |
| PULLBACK_TENDENCIA | crypto | 30 d | 80 | 43 | 30.0% | 45.2% | 38.7% | 43.0% | -1.6% | 1.8% |
| PULLBACK_TENDENCIA | crypto | 90 d | 79 | 42 | 29.1% | 49.9% | 37.7% | 45.4% | -3.4% | 6.2% |
| PULLBACK_TENDENCIA | us | 7 d | 237 | 132 | 35.4% | 34.5% | 33.5% | 35.8% | 0.2% | 0.2% |
| PULLBACK_TENDENCIA | us | 30 d | 236 | 131 | 36.4% | 43.4% | 39.7% | 39.8% | 1.1% | 1.7% |
| PULLBACK_TENDENCIA | us | 90 d | 225 | 124 | 44.9% | 50.3% | 46.8% | 46.5% | 5.7% | 5.9% |

## 4. Reglas de alerta en el periodo de prueba

Regla activa: **relativo**. Sin contexto v4.2 ni verificación de noticias ni tope semanal (no existen hacia atrás): en vivo hay más filtros, no menos. Se reportan las tres reglas para que se vea el costo de cada una.

| Regla | Alertas | Episodios | Por año | Acierto | Día cualquiera (local) | Predicho | Neto medio | Mediana | Neto día cualquiera | % positivas | Peor caída |
|---|---|---|---|---|---|---|---|---|---|---|---|
| relativo | 27 | 20 | 5.6 | 55.6% | 41.2% | 47.2% | 8.4% | 5.5% | 2.7% | 70% | -54.5% |
| selectivo | 2 | 2 | 0.4 | 50.0% | 64.5% | 70.3% | 3.7% | 3.7% | 7.2% | 100% | -13.4% |
| moderado | 4 | 4 | 0.8 | 50.0% | 59.8% | 66.6% | 6.9% | 3.7% | 7.3% | 75% | -25.9% |

Alertas de la regla activa (relativo):

| Fecha | Activo | Setup | Horizonte | P | Base | Ganó | Neto | Peor caída |
|---|---|---|---|---|---|---|---|---|
| 2022-01-24 | CEMEXCPO.MX | CAPITULACION | 90 d | 46% | 38% | no | -21.9% | -27.4% |
| 2022-02-11 | META | CAPITULACION | 90 d | 58% | 52% | no | -9.0% | -22.9% |
| 2022-03-15 | KIMBERA.MX | CAPITULACION | 90 d | 31% | 25% | no | 2.7% | -1.0% |
| 2022-04-27 | META | CAPITULACION | 90 d | 46% | 41% | no | -21.8% | -24.0% |
| 2022-04-27 | NVDA | CAPITULACION | 90 d | 63% | 58% | no | -4.4% | -25.9% |
| 2022-05-05 | AMZN | CAPITULACION | 90 d | 42% | 36% | sí | 21.2% | -11.8% |
| 2022-06-17 | XLE | CAPITULACION | 90 d | 68% | 63% | no | 4.3% | -12.2% |
| 2022-07-07 | FEMSAUBD.MX | CAPITULACION | 90 d | 34% | 27% | sí | 5.5% | -2.2% |
| 2022-08-31 | ORBIA.MX | CAPITULACION | 90 d | 35% | 29% | no | 0.7% | -14.4% |
| 2022-09-01 | NVDA | CAPITULACION | 90 d | 48% | 42% | sí | 19.6% | -23.3% |
| 2022-09-23 | XLK | CAPITULACION | 90 d | 37% | 32% | no | 1.1% | -8.4% |
| 2022-09-26 | XLE | CAPITULACION | 30 d | 62% | 52% | sí | 24.8% | -1.2% |
| 2022-09-30 | GRUMAB.MX | CAPITULACION | 90 d | 44% | 37% | sí | 34.5% | -1.4% |
| 2022-10-07 | TSLA | CAPITULACION | 90 d | 47% | 41% | no | -47.1% | -54.5% |
| 2022-10-12 | XLU | CAPITULACION | 90 d | 43% | 38% | sí | 18.5% | -0.4% |
| 2022-11-01 | AMZN | CAPITULACION | 90 d | 45% | 40% | sí | 6.0% | -16.3% |
| 2022-11-21 | TSLA | CAPITULACION | 90 d | 45% | 39% | sí | 16.6% | -39.6% |
| 2023-03-17 | XLF | CAPITULACION | 90 d | 39% | 34% | sí | 7.1% | -2.2% |
| 2024-11-26 | LIVEPOLC-1.MX | CAPITULACION | 90 d | 45% | 37% | no | -1.6% | -5.9% |
| 2024-11-27 | ALSEA.MX | CAPITULACION | 90 d | 49% | 42% | no | -2.4% | -13.0% |
| 2024-12-18 | BIMBOA.MX | CAPITULACION | 90 d | 32% | 26% | no | -3.2% | -12.2% |
| 2025-04-03 | IWM | CAPITULACION | 90 d | 46% | 40% | sí | 21.3% | -6.0% |
| 2025-04-03 | SMH | CAPITULACION | 90 d | 44% | 39% | sí | 50.0% | -9.8% |
| 2025-04-04 | QQQ | CAPITULACION | 90 d | 52% | 46% | sí | 36.1% | -1.5% |
| 2025-04-04 | XLK | CAPITULACION | 90 d | 45% | 40% | sí | 47.4% | -1.4% |
| 2025-04-07 | XLY | CAPITULACION | 90 d | 56% | 51% | sí | 18.1% | -7.2% |
| 2026-03-09 | GMEXICOB.MX | CHOQUE_PESO | 30 d | 73% | 66% | sí | 3.1% | -13.4% |

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
| AAPL | sí | 2026-10-16 | caché yahoo |
| AC.MX | sí | 2026-10-16 | caché yahoo |
| ADA | sí | 2026-10-19 | caché binance |
| ALSEA.MX | sí | 2026-10-16 | caché yahoo |
| AMXB.MX | sí | 2026-10-16 | caché yahoo |
| AMZN | sí | 2026-10-16 | caché yahoo |
| ASURB.MX | sí | 2026-10-16 | caché yahoo |
| AVAX | sí | 2026-10-19 | caché binance |
| BBAJIOO.MX | sí | 2026-10-16 | caché yahoo |
| BCH | sí | 2026-10-19 | caché binance |
| BIMBOA.MX | sí | 2026-10-16 | caché yahoo |
| BTC | sí | 2026-10-19 | caché binance |
| CEMEXCPO.MX | sí | 2026-10-16 | caché yahoo |
| DIA | sí | 2026-10-16 | caché yahoo |
| DOGE | sí | 2026-10-19 | caché binance |
| DOT | sí | 2026-10-19 | caché binance |
| ETH | sí | 2026-10-19 | caché binance |
| FEMSAUBD.MX | sí | 2026-10-16 | caché yahoo |
| GAPB.MX | sí | 2026-10-16 | caché yahoo |
| GFNORTEO.MX | sí | 2026-10-16 | caché yahoo |
| GLD | sí | 2026-10-16 | caché yahoo |
| GMEXICOB.MX | sí | 2026-10-16 | caché yahoo |
| GOOGL | sí | 2026-10-16 | caché yahoo |
| GRUMAB.MX | sí | 2026-10-16 | caché yahoo |
| IWM | sí | 2026-10-16 | caché yahoo |
| JPM | sí | 2026-10-16 | caché yahoo |
| KIMBERA.MX | sí | 2026-10-16 | caché yahoo |
| KOFUBL.MX | sí | 2026-10-16 | caché yahoo |
| LINK | sí | 2026-10-19 | caché binance |
| LIVEPOLC-1.MX | sí | 2026-10-16 | caché yahoo |
| LTC | sí | 2026-10-19 | caché binance |
| META | sí | 2026-10-16 | caché yahoo |
| MSFT | sí | 2026-10-16 | caché yahoo |
| MXN=X | sí | 2026-10-19 | caché yahoo |
| NAFTRACISHRS.MX | sí | 2026-10-16 | caché yahoo |
| NVDA | sí | 2026-10-16 | caché yahoo |
| OMAB.MX | sí | 2026-10-16 | caché yahoo |
| ORBIA.MX | sí | 2026-10-16 | caché yahoo |
| PINFRA.MX | sí | 2026-10-16 | caché yahoo |
| QQQ | sí | 2026-10-16 | caché yahoo |
| SMH | sí | 2026-10-16 | caché yahoo |
| SOL | sí | 2026-10-19 | caché binance |
| SPY | sí | 2026-10-16 | caché yahoo |
| TRX | sí | 2026-10-19 | caché binance |
| TSLA | sí | 2026-10-16 | caché yahoo |
| WALMEX.MX | sí | 2026-10-16 | caché yahoo |
| WMT | sí | 2026-10-16 | caché yahoo |
| XLE | sí | 2026-10-16 | caché yahoo |
| XLF | sí | 2026-10-16 | caché yahoo |
| XLI | sí | 2026-10-16 | caché yahoo |
| XLK | sí | 2026-10-16 | caché yahoo |
| XLP | sí | 2026-10-16 | caché yahoo |
| XLU | sí | 2026-10-16 | caché yahoo |
| XLV | sí | 2026-10-16 | caché yahoo |
| XLY | sí | 2026-10-16 | caché yahoo |
| XOM | sí | 2026-10-16 | caché yahoo |
| XRP | sí | 2026-10-19 | caché binance |
| ^MXX | sí | 2026-10-16 | caché yahoo |
| ^VIX | sí | 2026-10-16 | caché yahoo |
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
