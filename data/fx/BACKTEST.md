# Backtest del agente FX — Estrategia A (reacción intradía a datos macro)

Generado 2026-10-19T15:04:07.723473+00:00 · filas de eventos 31246 · huella `b2453f7f85f3`

Walk-forward: grupos (par, slot) activos por año de prueba → 2018: 0 · 2019: 0 · 2020: 0 · 2021: 0 · 2022: 0 · 2023: 0 · 2024: 0 · 2025: 0 · 2026: 0

## Veredicto: **sin ventaja neta — el agente no opera**

ningún (par, slot) pasó el umbral del EB en ningún año del walk-forward. Con costos reales ningún horario/par mostró un drift posterior creíble; el modelo
publicado tiene 0 grupos activos, así que el motor corre pero no abre posiciones.

## ¿Costo o señal? Mismo walk-forward con tres supuestos de costo

| supuesto | operaciones fuera de muestra | R medio fuera de muestra | grupos que el EB activó (año) |
|---|---|---|---|
| costos OANDA estimados (base) | 0 | — | — |
| solo spread real (cuenta ECN) | 30 | -0.239 | 2018: USDJPY · US_1400; 2023: EURUSD · US_1000; 2024: EURUSD · US_1000 |
| costo cero (límite teórico) | 24 | -0.201 | 2018: USDJPY · US_1400; 2023: EURUSD · US_1000 |

## Diagnóstico con toda la muestra (dentro de muestra: explica, no valida)

| grupo | mejor variante | n días | R neto | t | R bruto mom 120 min | t bruto | costo (R) |
|---|---|---|---|---|---|---|---|
| EURUSD · UK_1200 | rev 60m z≥3 | 47 | +0.039 | 0.42 | +0.018 | 0.35 | 0.084 |
| EURUSD · US_0830 | rev 360m z≥3 | 153 | +0.045 | 0.72 | -0.026 | -0.61 | 0.050 |
| EURUSD · US_1000 | mom 60m z≥3 | 74 | +0.133 | 1.64 | +0.035 | 0.84 | 0.043 |
| EURUSD · US_1400 | rev 60m z≥3 | 96 | +0.054 | 0.67 | -0.030 | -0.69 | 0.069 |
| GBPUSD · UK_1200 | rev 60m z≥3 | 91 | -0.008 | -0.11 | -0.020 | -0.45 | 0.079 |
| GBPUSD · US_0830 | rev 120m z≥3 | 128 | +0.045 | 0.65 | -0.042 | -0.98 | 0.057 |
| GBPUSD · US_1000 | mom 60m z≥3 | 55 | +0.098 | 0.98 | +0.027 | 0.69 | 0.051 |
| GBPUSD · US_1400 | mom 360m z≥3 | 109 | -0.013 | -0.20 | +0.010 | 0.29 | 0.085 |
| USDCHF · US_0830 | rev 360m z≥3 | 158 | +0.049 | 0.81 | -0.028 | -0.64 | 0.093 |
| USDCHF · US_1000 | mom 360m z≥3 | 70 | +0.016 | 0.23 | +0.087 | 1.98 | 0.084 |
| USDCHF · US_1400 | rev 120m z≥3 | 128 | -0.064 | -0.96 | +0.022 | 0.59 | 0.136 |
| USDJPY · US_0830 | mom 360m z≥3 | 163 | +0.007 | 0.11 | +0.042 | 0.76 | 0.054 |
| USDJPY · US_1000 | mom 360m z≥3 | 124 | +0.038 | 0.75 | -0.020 | -0.58 | 0.042 |
| USDJPY · US_1400 | rev 120m z≥2 | 310 | -0.023 | -0.62 | -0.060 | -1.63 | 0.068 |
| USDMXN · MX_1300 | rev 360m z≥3 | 87 | -0.067 | -0.89 | -0.015 | -0.31 | 0.129 |
| USDMXN · US_0830 | rev 360m z≥3 | 106 | +0.020 | 0.27 | -0.063 | -1.41 | 0.104 |
| USDMXN · US_1000 | mom 120m z≥2 | 220 | +0.003 | 0.07 | +0.095 | 2.11 | 0.092 |
| USDMXN · US_1400 | rev 120m z≥3 | 141 | -0.092 | -1.55 | -0.024 | -0.69 | 0.128 |

Lectura: la mejor de 12 variantes por grupo con t < 2 es lo que se espera por azar entre ~200 ensayos; el R bruto muestra si había drift antes de costos.

## Modelo vigente (entrenado con todo hasta 2026-10-16)

Umbral P(ventaja>0) ajustado por variantes: 0.942. Solo se activan grupos que además operaron fuera de muestra con R medio > 0.

| grupo | dirección | horizonte | z mín | P(ventaja>0) | R medio a posteriori | n |
|---|---|---|---|---|---|---|
| — ningún grupo pasa: el agente no opera | | | | | | |
