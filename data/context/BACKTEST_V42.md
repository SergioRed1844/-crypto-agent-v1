# Backtest de variantes v4.2 — ¿suman las capas nuevas?

Periodo 2021-01-01 → 2026-10-12 · pares BTCUSDT, ETHUSDT, SOLUSDT · comisión 0.10%/lado · slippage 0.05% · generado 2026-10-12T04:30:21Z. Sin LLM; el contexto usa pesos a priori y solo eventos con fecha anterior a la señal (sin look-ahead).

Fuera de muestra = entradas desde 2024-06-20 (mismo corte para todas las variantes).

| Variante | Señales | Trades | Ganadas | Expectativa R | PF | Máx DD R | Retorno % | IC95 R | Fuera de muestra: trades / exp. R / IC95 |
|---|---|---|---|---|---|---|---|---|---|
| A · v4.1 reglas actuales | 9059 | 407 | 0.349 | 0.148 | 1.22 | -20.45 | 15.66 | [-0.007, 0.306] | 180 / 0.089 / [-0.135, 0.331] |
| B · + ganancia neta | 8947 | 407 | 0.349 | 0.148 | 1.22 | -20.45 | 15.66 | [-0.007, 0.306] | 180 / 0.089 / [-0.135, 0.332] |
| C · + derivados (veto funding) | 8933 | 404 | 0.349 | 0.148 | 1.22 | -20.45 | 15.45 | [-0.007, 0.297] | 180 / 0.089 / [-0.135, 0.331] |
| C2 · + derivados estricto (F&G/funding) | 8036 | 385 | 0.351 | 0.152 | 1.23 | -21.08 | 14.68 | [-0.012, 0.307] | 168 / 0.129 / [-0.11, 0.366] |
| D · + contexto (calendario y eventos) | 8973 | 400 | 0.343 | 0.127 | 1.19 | -20.45 | 11.67 | [-0.031, 0.276] | 175 / 0.046 / [-0.183, 0.296] |
| D1 · + solo blackout de eventos programados | 9008 | 400 | 0.343 | 0.127 | 1.19 | -20.45 | 11.74 | [-0.031, 0.276] | 175 / 0.046 / [-0.183, 0.295] |
| D2 · + solo sesgo por eventos recientes | 9024 | 407 | 0.349 | 0.148 | 1.22 | -20.45 | 15.66 | [-0.007, 0.306] | 180 / 0.089 / [-0.135, 0.331] |
| E · + racha (pausa tras 5 pérdidas) | 9059 | 385 | 0.325 | 0.066 | 1.1 | -38.91 | 4.15 | [-0.09, 0.226] | 166 / 0.021 / [-0.198, 0.254] |
| F · v4.2 completo (B+C+D+E) | 8735 | 386 | 0.321 | 0.055 | 1.08 | -38.91 | 1.98 | [-0.091, 0.208] | 168 / 0.009 / [-0.209, 0.244] |
| G · ganancia neta + derivados estricto (sin contexto ni pausa) | 7926 | 385 | 0.351 | 0.152 | 1.23 | -21.08 | 14.68 | [-0.011, 0.307] | 168 / 0.129 / [-0.11, 0.366] |

## Rejilla del filtro de ganancia neta

| Umbral | Trades | Ganadas | Expectativa R | PF | IC95 R |
|---|---|---|---|---|---|
| neta≥0.0% y R:R neto≥0.0 | 407 | 0.349 | 0.148 | 1.22 | [-0.007, 0.306] |
| neta≥1.0% y R:R neto≥1.5 | 407 | 0.349 | 0.148 | 1.22 | [-0.007, 0.306] |
| neta≥1.5% y R:R neto≥1.8 | 407 | 0.349 | 0.148 | 1.22 | [-0.007, 0.306] |
| neta≥2.5% y R:R neto≥2.0 | 397 | 0.348 | 0.145 | 1.22 | [-0.008, 0.302] |
| neta≥4.0% y R:R neto≥2.0 | 397 | 0.348 | 0.145 | 1.22 | [-0.008, 0.302] |

Estados de contexto al momento de las señales: {'NEUTRAL': 8738, 'CAUTION': 41, 'BLACKOUT': 51, 'RISK_ON': 229}
Cobertura de datos: {'fear_greed_dias': 3172, 'funding': {'BTCUSDT': 7215, 'ETHUSDT': 7215, 'SOLUSDT': 6700}}

**Criterio:** Una capa SUMA si mejora la expectativa FUERA de muestra sin dejar < 30 trades, y el límite inferior del IC95 sube. Si solo mejora en muestra, es sobreajuste.
