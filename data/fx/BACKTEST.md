# Backtest del agente FX — Estrategia A (reacción intradía a datos macro)

Generado 2026-10-19T16:01:06.159289+00:00 · filas de eventos 33274 · huella `7e658114797a`

Walk-forward: grupos (par, slot) activos por año de prueba → 2018: 0 · 2019: 0 · 2020: 0 · 2021: 0 · 2022: 0 · 2023: 0 · 2024: 0 · 2025: 0 · 2026: 0

## Veredicto: **sin ventaja neta — el agente no opera**

ningún (par, slot) pasó el umbral del EB en ningún año del walk-forward. Con costos reales ningún horario/par mostró un drift posterior creíble; el modelo
publicado tiene 0 grupos activos, así que el motor corre pero no abre posiciones.

## ¿Costo o señal? Mismo walk-forward con tres supuestos de costo

| supuesto | operaciones fuera de muestra | R medio fuera de muestra | grupos que el EB activó (año) |
|---|---|---|---|
| costos OANDA estimados (base) | 0 | — | — |
| solo spread real (cuenta ECN) | 0 | — | — |
| costo cero (límite teórico) | 0 | — | — |

## Diagnóstico con toda la muestra (dentro de muestra: explica, no valida)

| grupo | mejor variante | n días | R neto | t | R bruto mom 120 min | t bruto | costo (R) |
|---|---|---|---|---|---|---|---|
| EURUSD · UK_1200 | rev 60m z≥3 | 52 | -0.043 | -0.46 | +0.052 | 1.01 | 0.083 |
| EURUSD · US_0830 | rev 360m z≥3 | 165 | +0.022 | 0.38 | -0.017 | -0.42 | 0.049 |
| EURUSD · US_1000 | mom 60m z≥3 | 80 | +0.102 | 1.30 | +0.032 | 0.80 | 0.043 |
| EURUSD · US_1400 | rev 60m z≥3 | 111 | +0.035 | 0.46 | -0.028 | -0.66 | 0.069 |
| GBPUSD · UK_1200 | mom 120m z≥3 | 93 | -0.054 | -0.75 | -0.006 | -0.15 | 0.079 |
| GBPUSD · US_0830 | rev 120m z≥3 | 141 | +0.036 | 0.54 | -0.031 | -0.74 | 0.057 |
| GBPUSD · US_1000 | mom 60m z≥3 | 60 | +0.095 | 0.96 | +0.049 | 1.32 | 0.051 |
| GBPUSD · US_1400 | mom 120m z≥3 | 129 | -0.039 | -0.64 | +0.009 | 0.27 | 0.085 |
| USDCHF · US_0830 | rev 360m z≥3 | 170 | +0.052 | 0.91 | -0.025 | -0.60 | 0.094 |
| USDCHF · US_1000 | mom 360m z≥3 | 74 | +0.018 | 0.27 | +0.089 | 2.22 | 0.084 |
| USDCHF · US_1400 | rev 120m z≥3 | 132 | -0.063 | -0.94 | +0.017 | 0.46 | 0.137 |
| USDJPY · US_0830 | mom 360m z≥3 | 168 | -0.003 | -0.05 | +0.029 | 0.54 | 0.054 |
| USDJPY · US_1000 | mom 360m z≥3 | 127 | +0.042 | 0.82 | -0.025 | -0.72 | 0.043 |
| USDJPY · US_1400 | rev 120m z≥3 | 152 | -0.043 | -0.69 | -0.047 | -1.26 | 0.068 |
| USDMXN · MX_1300 | rev 360m z≥3 | 93 | -0.054 | -0.77 | -0.016 | -0.36 | 0.129 |
| USDMXN · US_0830 | rev 360m z≥3 | 111 | +0.014 | 0.20 | -0.074 | -1.70 | 0.104 |
| USDMXN · US_1000 | mom 120m z≥2 | 232 | -0.022 | -0.51 | +0.069 | 1.61 | 0.091 |
| USDMXN · US_1400 | rev 120m z≥3 | 146 | -0.078 | -1.35 | -0.010 | -0.29 | 0.127 |

Lectura: la mejor de 12 variantes por grupo con t < 2 es lo que se espera por azar entre ~200 ensayos; el R bruto muestra si había drift antes de costos.

## Modelo vigente (entrenado con todo hasta 2026-10-16)

Umbral P(ventaja>0) ajustado por variantes: 0.942. Solo se activan grupos que además operaron fuera de muestra con R medio > 0.

| grupo | dirección | horizonte | z mín | P(ventaja>0) | R medio a posteriori | n |
|---|---|---|---|---|---|---|
| — ningún grupo pasa: el agente no opera | | | | | | |
