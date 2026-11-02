# Backtest del agente FX — Estrategia A (reacción intradía a datos macro)

Generado 2026-11-02T16:48:26.316289+00:00 · filas de eventos 33400 · huella `72ba42244094`

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
| EURUSD · UK_1200 | rev 60m z≥3 | 54 | -0.019 | -0.21 | +0.048 | 0.94 | 0.084 |
| EURUSD · US_0830 | rev 360m z≥3 | 165 | +0.022 | 0.38 | -0.017 | -0.41 | 0.049 |
| EURUSD · US_1000 | mom 60m z≥3 | 80 | +0.102 | 1.30 | +0.032 | 0.80 | 0.043 |
| EURUSD · US_1400 | rev 60m z≥3 | 111 | +0.035 | 0.46 | -0.024 | -0.59 | 0.069 |
| GBPUSD · UK_1200 | mom 120m z≥3 | 93 | -0.054 | -0.75 | -0.008 | -0.19 | 0.079 |
| GBPUSD · US_0830 | rev 120m z≥3 | 141 | +0.036 | 0.54 | -0.029 | -0.71 | 0.057 |
| GBPUSD · US_1000 | mom 60m z≥3 | 60 | +0.104 | 1.05 | +0.049 | 1.32 | 0.051 |
| GBPUSD · US_1400 | mom 120m z≥3 | 129 | -0.039 | -0.64 | +0.009 | 0.27 | 0.085 |
| USDCHF · US_0830 | rev 360m z≥3 | 170 | +0.052 | 0.91 | -0.022 | -0.53 | 0.094 |
| USDCHF · US_1000 | mom 360m z≥3 | 75 | +0.018 | 0.27 | +0.088 | 2.20 | 0.084 |
| USDCHF · US_1400 | rev 120m z≥3 | 134 | -0.056 | -0.84 | +0.014 | 0.37 | 0.136 |
| USDJPY · US_0830 | mom 360m z≥3 | 169 | -0.009 | -0.15 | +0.026 | 0.49 | 0.054 |
| USDJPY · US_1000 | mom 360m z≥3 | 127 | +0.042 | 0.82 | -0.025 | -0.72 | 0.043 |
| USDJPY · US_1400 | rev 120m z≥3 | 153 | -0.041 | -0.67 | -0.048 | -1.28 | 0.068 |
| USDMXN · MX_1300 | rev 360m z≥3 | 93 | -0.054 | -0.77 | -0.016 | -0.35 | 0.129 |
| USDMXN · US_0830 | rev 360m z≥3 | 110 | +0.018 | 0.26 | -0.072 | -1.64 | 0.104 |
| USDMXN · US_1000 | mom 120m z≥2 | 234 | -0.022 | -0.53 | +0.068 | 1.62 | 0.091 |
| USDMXN · US_1400 | rev 120m z≥3 | 147 | -0.081 | -1.41 | -0.017 | -0.50 | 0.128 |

Lectura: la mejor de 12 variantes por grupo con t < 2 es lo que se espera por azar entre ~200 ensayos; el R bruto muestra si había drift antes de costos.

## Modelo vigente (entrenado con todo hasta 2026-10-30)

Umbral P(ventaja>0) ajustado por variantes: 0.942. Solo se activan grupos que además operaron fuera de muestra con R medio > 0.

| grupo | dirección | horizonte | z mín | P(ventaja>0) | R medio a posteriori | n |
|---|---|---|---|---|---|---|
| — ningún grupo pasa: el agente no opera | | | | | | |
