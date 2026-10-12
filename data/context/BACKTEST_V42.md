# Backtest de variantes v4.2 — ¿suman las capas nuevas?

Periodo 2021-01-01 → 2026-10-11 · pares BTCUSDT, ETHUSDT, SOLUSDT · comisión 0.10%/lado · slippage 0.05% · generado 2026-10-12T04:05:46Z. Sin LLM; el contexto usa pesos a priori y solo eventos con fecha anterior a la señal (sin look-ahead).

| Variante | Señales | Trades | Ganadas | Expectativa R | PF | Máx DD R | Retorno % | IC95 R | Fuera de muestra: trades / exp. R / IC95 |
|---|---|---|---|---|---|---|---|---|---|
| A · v4.1 reglas actuales | 9056 | 407 | 0.349 | 0.148 | 1.22 | -20.45 | 15.66 | [-0.007, 0.306] | 163 / 0.081 / [-0.156, 0.321] |
| B · + ganancia neta | 8944 | 407 | 0.349 | 0.148 | 1.22 | -20.45 | 15.66 | [-0.007, 0.306] | 163 / 0.081 / [-0.156, 0.321] |
| C · + derivados (veto funding) | 8930 | 404 | 0.349 | 0.148 | 1.22 | -20.45 | 15.45 | [-0.007, 0.297] | 162 / 0.088 / [-0.139, 0.332] |
| C2 · + derivados estricto (F&G/funding) | 8033 | 385 | 0.351 | 0.152 | 1.23 | -21.08 | 14.68 | [-0.012, 0.307] | 154 / 0.103 / [-0.135, 0.352] |
| D · + contexto (calendario y eventos) | 8669 | 381 | 0.341 | 0.123 | 1.18 | -26.86 | 10.26 | [-0.027, 0.28] | 153 / 0.024 / [-0.211, 0.259] |
| E · + racha (pausa tras 5 pérdidas) | 9056 | 385 | 0.325 | 0.066 | 1.1 | -38.91 | 4.15 | [-0.09, 0.226] | 154 / 0.014 / [-0.24, 0.255] |
| F · v4.2 completo (B+C+D+E) | 8440 | 359 | 0.331 | 0.088 | 1.13 | -29.59 | 6.45 | [-0.069, 0.252] | 144 / -0.006 / [-0.256, 0.228] |

## Rejilla del filtro de ganancia neta

| Umbral | Trades | Ganadas | Expectativa R | PF | IC95 R |
|---|---|---|---|---|---|
| neta≥0.0% y R:R neto≥0.0 | 407 | 0.349 | 0.148 | 1.22 | [-0.007, 0.306] |
| neta≥1.0% y R:R neto≥1.5 | 407 | 0.349 | 0.148 | 1.22 | [-0.007, 0.306] |
| neta≥1.5% y R:R neto≥1.8 | 407 | 0.349 | 0.148 | 1.22 | [-0.007, 0.306] |
| neta≥2.5% y R:R neto≥2.0 | 397 | 0.348 | 0.145 | 1.22 | [-0.008, 0.302] |
| neta≥4.0% y R:R neto≥2.0 | 397 | 0.348 | 0.145 | 1.22 | [-0.008, 0.302] |

Estados de contexto al momento de las señales: {'NEUTRAL': 7301, 'RISK_ON': 1312, 'BLACKOUT': 163, 'CAUTION': 280}
Cobertura de datos: {'fear_greed_dias': 3172, 'funding': {'BTCUSDT': 7215, 'ETHUSDT': 7215, 'SOLUSDT': 6700}}

**Criterio:** Una capa SUMA si mejora la expectativa FUERA de muestra sin dejar < 30 trades, y el límite inferior del IC95 sube. Si solo mejora en muestra, es sobreajuste.
