# CryptoAgent v4.1 — prueba en papel

> **Simulación con dinero hipotético.** No hay keys ni órdenes reales: el bot solo lee velas públicas de Binance y calcula qué habría hecho con las reglas congeladas.

**Actualizado:** lun 12 oct 01:04 (Monterrey) · velas hasta lun 12 oct 01:00 · fuente Binance (data-api.binance.vision)  
**Estado:** en curso — próximo corte: **Corte 1, lun 12 oct 14:00** (Monterrey)  
**Ventana:** dom 11 oct 18:00 → mié 14 oct 14:00 (Monterrey) · 8 monedas × 3 escalas · cuenta de 1,000 USDT por escala · 0.5% de riesgo por trade (1R ≈ 5 USDT) · comisión y slippage incluidos

**Las 3 escalas juntas (3,000 hipotéticos): −2.95 USDT** — cerrado −4.43, flotante +1.48, 2 trades cerrados, 5 posiciones abiertas.

![P&L por escala](curva.svg)

## Resumen por escala

| Escala | Trades cerrados | Ganadas | Cerrado USDT | Flotante USDT | **Total USDT** | Abiertas | Señales de compra |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Swing (1D / 4H / 1H) | 0 | — | 0.00 | −0.80 | **−0.80** | 2 | 5 |
| Intradía (4H / 1H / 15m) | 0 | — | 0.00 | −0.62 | **−0.62** | 1 | 1 |
| Scalp (1H / 15m / 5m) | 2 | 0% | −4.43 | +2.90 | **−1.53** | 2 | 44 |

## Cortes

Cada corte se congela una sola vez al pasar su hora (no se reescribe).

| Corte | Hora (Monterrey) | Estado | Swing USDT | Intradía USDT | Scalp USDT | Trades cerrados |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Corte 1 | lun 12 oct 14:00 | pendiente | — | — | — | — |
| Corte 2 | mar 13 oct 14:00 | pendiente | — | — | — | — |
| Corte final | mié 14 oct 14:00 | pendiente | — | — | — | — |

## Posiciones abiertas

Lo flotante ya descuenta la comisión de entrada y de salida: una posición apenas arriba de su precio de entrada todavía sale negativa.

| Escala | Moneda | Entrada (Monterrey) | Precio entrada | Precio actual | Stop | Objetivo | R flotante | USDT flotante |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Swing | BTC | dom 11 oct 18:00 | 83,815 | 83,613.1 | 82,656.3 | 86,711.8 | −0.28 | −1.05 |
| Swing | ETH | dom 11 oct 18:00 | 2,538.21 | 2,546.72 | 2,489.88 | 2,659.03 | +0.06 | +0.24 |
| Intradía | ADA | lun 12 oct 00:00 | 0.253727 | 0.2533 | 0.248578 | 0.2666 | −0.17 | −0.62 |
| Scalp | BTC | dom 11 oct 20:00 | 83,709.8 | 84,224 | 83,436 | 84,394.3 | +0.79 | +1.03 |
| Scalp | ADA | dom 11 oct 22:00 | 0.250925 | 0.2533 | 0.248442 | 0.257133 | +0.63 | +1.86 |

## Operaciones cerradas

| Escala | Moneda | Entrada | Salida | Precio entrada → salida | Motivo | R | USDT |
| --- | --- | --- | --- | ---: | --- | ---: | ---: |
| Scalp | BTC | dom 11 oct 18:00 | dom 11 oct 19:45 | 83,815 → 83,555.9 | stop | −1.11 | −1.27 |
| Scalp | ADA | dom 11 oct 18:00 | dom 11 oct 19:45 | 0.252326 → 0.249637 | stop | −1.04 | −3.16 |


## Por moneda

Cada moneda corrida sola con su propia cuenta (por eso no suma igual que el portafolio). R incluye lo flotante.

| Moneda | Swing | Intradía | Scalp | Buy & hold desde el inicio |
| --- | ---: | ---: | ---: | ---: |
| BTC | 0 tr · −0.28R (abierta) | — (0 señ.) | 1 tr · −0.33R (abierta) | +0.54% |
| ETH | 0 tr · +0.06R (abierta) | — (0 señ.) | — (0 señ.) | +1.36% |
| SOL | 0 tr · +0.03R (abierta) | — (0 señ.) | — (0 señ.) | +1.19% |
| XRP | 0 tr · −0.19R (abierta) | — (0 señ.) | — (0 señ.) | +0.30% |
| DOGE | — (0 señ.) | — (0 señ.) | — (0 señ.) | +0.94% |
| ADA | 0 tr · −0.17R (abierta) | 0 tr · −0.17R (abierta) | 1 tr · −0.41R (abierta) | +0.44% |
| AVAX | — (0 señ.) | — (0 señ.) | — (0 señ.) | +0.46% |
| LINK | — (0 señ.) | — (0 señ.) | 1 tr · −1.09R (abierta) | +0.58% |

## Línea base histórica (mismas reglas, antes de la ventana)

| Escala | Ventana | Trades | Ganadas | Expectativa | Profit factor | Retorno | IC95 expectativa |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Swing | 365 días | 24 | 25% | −0.187R | 0.75 | −1.85% | [−0.74, +0.38]R |
| Intradía | 90 días | 62 | 32% | 0.000R | 1 | −0.50% | [−0.35, +0.37]R |
| Scalp | 30 días | 116 | 33% | −0.105R | 0.85 | −2.17% | [−0.34, +0.14]R |

Ninguna escala mostró ventaja en el histórico: el intervalo de confianza de la expectativa incluye 0 en las tres. Con pocos trades, lo de esta ventana es sobre todo ruido; el corte final se lee contra esta tabla.

Reglas congeladas: `forward/prerregistro.json` (hash del código 1b7510f0d80a2b6c). Motor: `forward/engine.js`. Datos crudos: `latest.json`, `corte_*.json`, `equity.csv`.
