# CryptoAgent v4.1 — prueba en papel

> **Simulación con dinero hipotético.** No hay keys ni órdenes reales: el bot solo lee velas públicas de Binance y calcula qué habría hecho con las reglas congeladas.

**Actualizado:** mar 13 oct 15:29 (Monterrey) · velas hasta mar 13 oct 15:25 · fuente Binance (data-api.binance.vision)  
**Estado:** en curso — próximo corte: **Corte final, mié 14 oct 14:00** (Monterrey)  
**Ventana:** dom 11 oct 18:00 → mié 14 oct 14:00 (Monterrey) · 8 monedas × 3 escalas · cuenta de 1,000 USDT por escala · 0.5% de riesgo por trade (1R ≈ 5 USDT) · comisión y slippage incluidos

**Las 3 escalas juntas (3,000 hipotéticos): −35.83 USDT** — cerrado −33.76, flotante −2.07, 13 trades cerrados, 3 posiciones abiertas.

![P&L por escala](curva.svg)

## Resumen por escala

| Escala | Trades cerrados | Ganadas | Cerrado USDT | Flotante USDT | **Total USDT** | Abiertas | Señales de compra |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Swing (1D / 4H / 1H) | 2 | 0% | −7.70 | −0.82 | **−8.52** | 2 | 25 |
| Intradía (4H / 1H / 15m) | 3 | 0% | −8.99 | −1.25 | **−10.24** | 1 | 10 |
| Scalp (1H / 15m / 5m) | 8 | 0% | −17.07 | 0.00 | **−17.07** | 0 | 86 |

## Cortes

Cada corte se congela una sola vez al pasar su hora (no se reescribe).

| Corte | Hora (Monterrey) | Estado | Swing USDT | Intradía USDT | Scalp USDT | Trades cerrados |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Corte 1 | lun 12 oct 14:00 | guardado | −5.39 | −6.42 | −11.42 | 8 |
| Corte 2 | mar 13 oct 14:00 | guardado | −8.52 | −10.58 | −17.07 | 13 |
| Corte final | mié 14 oct 14:00 | pendiente | — | — | — | — |

## Posiciones abiertas

Lo flotante ya descuenta la comisión de entrada y de salida: una posición apenas arriba de su precio de entrada todavía sale negativa.

| Escala | Moneda | Entrada (Monterrey) | Precio entrada | Precio actual | Stop | Objetivo | R flotante | USDT flotante |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Swing | BTC | lun 12 oct 22:00 | 83,372.8 | 83,299.4 | 81,727.3 | 87,486.6 | −0.13 | −0.50 |
| Swing | ETH | lun 12 oct 22:00 | 2,509.99 | 2,508.46 | 2,438.37 | 2,689.06 | −0.09 | −0.32 |
| Intradía | BTC | mar 13 oct 04:00 | 83,665.8 | 83,415.3 | 82,689 | 86,107.9 | −0.36 | −1.25 |

## Operaciones cerradas

| Escala | Moneda | Entrada | Salida | Precio entrada → salida | Motivo | R | USDT |
| --- | --- | --- | --- | ---: | --- | ---: | ---: |
| Scalp | BTC | mar 13 oct 09:00 | mar 13 oct 11:45 | 83,571.8 → 83,057.2 | stop | −1.06 | −2.04 |
| Scalp | BTC | mar 13 oct 03:15 | mar 13 oct 04:45 | 83,600 → 83,200.3 | stop | −1.08 | −1.69 |
| Scalp | BTC | mar 13 oct 01:45 | mar 13 oct 03:00 | 83,897.3 → 83,421.6 | stop | −1.07 | −1.92 |
| Intradía | BTC | lun 12 oct 14:00 | lun 12 oct 16:00 | 82,903.2 → 82,216.6 | stop | −1.05 | −2.57 |
| Swing | ETH | dom 11 oct 18:00 | lun 12 oct 14:00 | 2,538.21 → 2,488.64 | stop | −1.02 | −3.84 |
| Scalp | ADA | dom 11 oct 22:00 | lun 12 oct 06:30 | 0.250925 → 0.248318 | stop | −1.04 | −3.09 |
| Swing | BTC | dom 11 oct 18:00 | lun 12 oct 06:00 | 83,815 → 82,614.9 | stop | −1.03 | −3.87 |
| Intradía | ADA | lun 12 oct 00:00 | lun 12 oct 06:00 | 0.253727 → 0.248453 | stop | −1.02 | −3.83 |
| Scalp | LINK | lun 12 oct 04:00 | lun 12 oct 05:45 | 13.3917 → 13.2873 | stop | −1.05 | −2.45 |
| Scalp | BTC | dom 11 oct 20:00 | lun 12 oct 03:15 | 83,709.8 → 83,394.3 | stop | −1.09 | −1.44 |
| Intradía | BTC | lun 12 oct 02:00 | lun 12 oct 03:00 | 84,033.5 → 83,330.9 | stop | −1.05 | −2.59 |
| Scalp | BTC | dom 11 oct 18:00 | dom 11 oct 19:45 | 83,815 → 83,555.9 | stop | −1.11 | −1.27 |
| Scalp | ADA | dom 11 oct 18:00 | dom 11 oct 19:45 | 0.252326 → 0.249637 | stop | −1.04 | −3.16 |


## Por moneda

Cada moneda corrida sola con su propia cuenta (por eso no suma igual que el portafolio). R incluye lo flotante.

| Moneda | Swing | Intradía | Scalp | Buy & hold desde el inicio |
| --- | ---: | ---: | ---: | ---: |
| BTC | 1 tr · −1.16R (abierta) | 2 tr · −2.46R (abierta) | 5 tr · −5.42R | −0.47% |
| ETH | 1 tr · −1.11R (abierta) | — (0 señ.) | 1 tr · −1.06R | −1.09% |
| SOL | 1 tr · −1.31R (abierta) | — (0 señ.) | — (0 señ.) | −3.89% |
| XRP | 1 tr · −1.02R | — (0 señ.) | — (0 señ.) | −2.96% |
| DOGE | — (0 señ.) | — (0 señ.) | — (0 señ.) | −2.62% |
| ADA | 1 tr · −1.01R | 1 tr · −1.02R | 2 tr · −2.08R | −6.23% |
| AVAX | — (0 señ.) | — (0 señ.) | — (0 señ.) | −6.39% |
| LINK | 1 tr · −1.06R (abierta) | — (0 señ.) | 2 tr · −2.09R | −3.30% |

## Línea base histórica (mismas reglas, antes de la ventana)

| Escala | Ventana | Trades | Ganadas | Expectativa | Profit factor | Retorno | IC95 expectativa |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Swing | 365 días | 24 | 25% | −0.187R | 0.75 | −1.85% | [−0.74, +0.38]R |
| Intradía | 90 días | 62 | 32% | 0.000R | 1 | −0.50% | [−0.35, +0.37]R |
| Scalp | 30 días | 116 | 33% | −0.105R | 0.85 | −2.17% | [−0.34, +0.14]R |

Ninguna escala mostró ventaja en el histórico: el intervalo de confianza de la expectativa incluye 0 en las tres. Con pocos trades, lo de esta ventana es sobre todo ruido; el corte final se lee contra esta tabla.

Reglas congeladas: `forward/prerregistro.json` (hash del código 1b7510f0d80a2b6c). Motor: `forward/engine.js`. Datos crudos: `latest.json`, `corte_*.json`, `equity.csv`.
