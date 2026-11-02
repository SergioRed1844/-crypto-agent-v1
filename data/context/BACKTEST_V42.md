# Backtest de variantes v4.2 — ¿suman las capas nuevas?

Periodo 2021-01-01 → 2026-11-02 · pares BTCUSDT, ETHUSDT, SOLUSDT · comisión 0.10%/lado · slippage 0.05% · generado 2026-11-02T11:51:38Z. Sin LLM; el contexto usa pesos a priori y solo eventos con fecha anterior a la señal (sin look-ahead).

Fuera de muestra = entradas desde 2024-07-02 (mismo corte para todas las variantes).

| Variante | Señales | Trades | Ganadas | Expectativa R | PF | Máx DD R | Retorno % | IC95 R | Fuera de muestra: trades / exp. R / IC95 |
|---|---|---|---|---|---|---|---|---|---|
| A · v4.1 reglas actuales | 9194 | 414 | 0.343 | 0.128 | 1.19 | -20.45 | 12.99 | [-0.025, 0.287] | 184 / 0.047 / [-0.169, 0.28] |
| B · + ganancia neta | 9082 | 414 | 0.343 | 0.128 | 1.19 | -20.45 | 13.0 | [-0.025, 0.287] | 184 / 0.047 / [-0.169, 0.281] |
| C · + derivados (veto funding) | 8171 | 392 | 0.344 | 0.132 | 1.2 | -21.08 | 12.01 | [-0.023, 0.292] | 172 / 0.083 / [-0.15, 0.308] |
| C2 · + derivados estricto (F&G/funding) | 8171 | 392 | 0.344 | 0.132 | 1.2 | -21.08 | 12.01 | [-0.023, 0.292] | 172 / 0.083 / [-0.15, 0.308] |
| D · + contexto (calendario y eventos) | 9119 | 407 | 0.337 | 0.107 | 1.16 | -20.45 | 9.0 | [-0.053, 0.267] | 179 / 0.004 / [-0.219, 0.226] |
| D1 · + solo blackout de eventos programados | 9143 | 407 | 0.337 | 0.107 | 1.16 | -20.45 | 9.08 | [-0.053, 0.266] | 179 / 0.003 / [-0.219, 0.225] |
| D2 · + solo sesgo por eventos recientes | 9170 | 414 | 0.343 | 0.128 | 1.19 | -20.45 | 12.99 | [-0.025, 0.287] | 184 / 0.047 / [-0.169, 0.28] |
| E · + racha (pausa tras 5 pérdidas) | 9194 | 392 | 0.319 | 0.047 | 1.07 | -38.91 | 1.48 | [-0.1, 0.198] | 168 / -0.012 / [-0.231, 0.244] |
| F · v4.2 completo (B+C+D+E) | 7994 | 383 | 0.305 | 0.001 | 1.0 | -38.91 | -5.42 | [-0.15, 0.159] | 161 / -0.03 / [-0.257, 0.216] |
| G · ganancia neta + derivados estricto (sin contexto ni pausa) | 8061 | 392 | 0.344 | 0.132 | 1.2 | -21.08 | 12.02 | [-0.023, 0.292] | 172 / 0.083 / [-0.15, 0.308] |

## Rejilla del filtro de ganancia neta

| Umbral | Trades | Ganadas | Expectativa R | PF | IC95 R |
|---|---|---|---|---|---|
| neta≥0.0% y R:R neto≥0.0 | 414 | 0.343 | 0.128 | 1.19 | [-0.025, 0.287] |
| neta≥1.0% y R:R neto≥1.5 | 414 | 0.343 | 0.128 | 1.19 | [-0.025, 0.287] |
| neta≥1.5% y R:R neto≥1.8 | 414 | 0.343 | 0.128 | 1.19 | [-0.025, 0.287] |
| neta≥2.5% y R:R neto≥2.0 | 404 | 0.342 | 0.125 | 1.19 | [-0.024, 0.28] |
| neta≥4.0% y R:R neto≥2.0 | 404 | 0.342 | 0.125 | 1.19 | [-0.024, 0.28] |

Estados de contexto al momento de las señales: {'NEUTRAL': 8953, 'BLACKOUT': 51, 'RISK_ON': 160, 'CAUTION': 30}
Cobertura de datos: {'fear_greed_dias': 3193, 'funding': {'BTCUSDT': 7308, 'ETHUSDT': 7308, 'SOLUSDT': 6793}}

**Criterio:** Una capa SUMA si mejora la expectativa FUERA de muestra sin dejar < 30 trades, y el límite inferior del IC95 sube. Si solo mejora en muestra, es sobreajuste.
