# Backtest Estrategia B — carry + momentum (pre-registrada el 19-oct-2026)

Generado 2026-10-19T16:07:28.788538+00:00 · 13 monedas · datos 2015-01-01 → 2026-09-30 · tasas: AUD, CAD, CHF, EUR, GBP, HUF, JPY, MXN, NOK, NZD, PLN, SEK, USD, ZAR · VIX 9297 obs

## Veredicto: **NO pasa la compuerta pre-registrada → no se opera**

| criterio | ¿cumple? |
|---|---|
| Sharpe neto > 0.3 | no |
| PSR(SR>0) ≥ 0.80 | no |
| retorno > 0 con costos ×2 | no |
| drawdown máx. < 8% | sí |

DSR (N=3): 0.07

## Resultados (ene-2016 → hoy, capital inicial US$2,000, σ* 4%)

| métrica | combinado | combinado costos ×2 | solo carry | solo momentum |
|---|---|---|---|---|
| retorno total | -1.3% | -7.5% | +2.6% | -7.3% |
| anualizado | -0.1% | -0.7% | +0.2% | -0.7% |
| volatilidad anual | +2.5% | +1.0% | +2.7% | +0.9% |
| Sharpe | -0.04 | -0.71 | 0.10 | -0.80 |
| PSR | 0.45 | 0.01 | 0.63 | 0.00 |
| drawdown máx. | 7.3% | 8.1% | 5.5% | 8.1% |
| % semanas positivas | +52.8% | +8.7% | +53.1% | +15.0% |
| peor semana | -1.5% | -1.1% | -1.6% | -0.7% |
| semanas peores que −1.5% | 0 | 0 | 4 | 0 |
| racha máx. semanas negativas | 7 | 8 | 7 | 6 |
| veces que saltó el tope | 4 | 1 | 6 | 0 |
| costos de operación (US$) | 69 | 28 | 77 | 13 |
| financiamiento neto (US$) | +107 | -26 | +226 | -22 |
| ajustes | 3220 | 720 | 2569 | 1096 |

## Por era (combinado)

| era | semanas | retorno | % semanas + | peor semana | Sharpe |
|---|---|---|---|---|---|
| 2016-2019 | 208 | -5.9% | +47% | -1.0% | -0.63 |
| 2020-2021 | 105 | -0.4% | +54% | -1.1% | -0.08 |
| 2022-2024 | 156 | +5.5% | +60% | -1.5% | 0.54 |
| 2025-2026 | 92 | -0.2% | +52% | -0.6% | -0.11 |

Costos: spread real de Dukascopy + sobreprecio OANDA estimado; financiamiento con tasas de política y recargo estimado de 1%/año (verificar con OANDA). Nada aquí es garantía.
