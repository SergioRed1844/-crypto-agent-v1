# CryptoAgent v4.1 — prueba en papel

> **Simulación con dinero hipotético.** No hay keys ni órdenes reales: el bot solo lee velas públicas de Binance y calcula qué habría hecho con las reglas congeladas.

**Actualizado:** dom 11 oct 18:34 (Monterrey) · velas hasta dom 11 oct 18:30 · fuente Binance (data-api.binance.vision)  
**Estado:** en curso — próximo corte: **Corte 1, lun 12 oct 14:00** (Monterrey)  
**Ventana:** dom 11 oct 18:00 → mié 14 oct 14:00 (Monterrey) · 8 monedas × 3 escalas · cuenta de 1,000 USDT por escala · 0.5% de riesgo por trade (1R ≈ 5 USDT) · comisión y slippage incluidos

**Las 3 escalas juntas (3,000 hipotéticos): −1.92 USDT** — cerrado 0.00, flotante −1.92, 0 trades cerrados, 2 posiciones abiertas.

![P&L por escala](curva.svg)

## Resumen por escala

| Escala | Trades cerrados | Ganadas | Cerrado USDT | Flotante USDT | **Total USDT** | Abiertas | Señales de compra |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Swing (1D / 4H / 1H) | 0 | — | 0.00 | 0.00 | **0.00** | 0 | 0 |
| Intradía (4H / 1H / 15m) | 0 | — | 0.00 | 0.00 | **0.00** | 0 | 0 |
| Scalp (1H / 15m / 5m) | 0 | — | 0.00 | −1.92 | **−1.92** | 2 | 4 |

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
| Scalp | BTC | dom 11 oct 18:00 | 83,815 | 83,848.2 | 83,597.7 | 84,358.4 | −0.35 | −0.40 |
| Scalp | ADA | dom 11 oct 18:00 | 0.252326 | 0.2513 | 0.249762 | 0.258737 | −0.50 | −1.52 |

## Operaciones cerradas

Todavía ninguna.


## Por moneda

Cada moneda corrida sola con su propia cuenta (por eso no suma igual que el portafolio). R incluye lo flotante.

| Moneda | Swing | Intradía | Scalp | Buy & hold desde el inicio |
| --- | ---: | ---: | ---: | ---: |
| BTC | — (0 señ.) | — (0 señ.) | 0 tr · −0.35R (abierta) | +0.09% |
| ETH | — (0 señ.) | — (0 señ.) | — (0 señ.) | +0.16% |
| SOL | — (0 señ.) | — (0 señ.) | — (0 señ.) | −0.04% |
| XRP | — (0 señ.) | — (0 señ.) | — (0 señ.) | −0.09% |
| DOGE | — (0 señ.) | — (0 señ.) | — (0 señ.) | +0.02% |
| ADA | — (0 señ.) | — (0 señ.) | 0 tr · −0.50R (abierta) | −0.36% |
| AVAX | — (0 señ.) | — (0 señ.) | — (0 señ.) | −0.53% |
| LINK | — (0 señ.) | — (0 señ.) | — (0 señ.) | −0.05% |

## Línea base histórica (mismas reglas, antes de la ventana)

| Escala | Ventana | Trades | Ganadas | Expectativa | Profit factor | Retorno | IC95 expectativa |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Swing | 365 días | 24 | 25% | −0.187R | 0.75 | −1.85% | [−0.74, +0.38]R |
| Intradía | 90 días | 62 | 32% | 0.000R | 1 | −0.50% | [−0.35, +0.37]R |
| Scalp | 30 días | 116 | 33% | −0.105R | 0.85 | −2.17% | [−0.34, +0.14]R |

Ninguna escala mostró ventaja en el histórico: el intervalo de confianza de la expectativa incluye 0 en las tres. Con pocos trades, lo de esta ventana es sobre todo ruido; el corte final se lee contra esta tabla.

Reglas congeladas: `forward/prerregistro.json` (hash del código 1b7510f0d80a2b6c). Motor: `forward/engine.js`. Datos crudos: `latest.json`, `corte_*.json`, `equity.csv`.
