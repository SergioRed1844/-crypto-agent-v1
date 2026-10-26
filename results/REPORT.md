# Rebotes — resultados

5230 acciones, 2005-01-03 → 2026-10-23; prueba desde 2019-01-01 (cartera hasta 2026-08-31). SPY en la misma ventana: 17.4% anual.

Por disparo (21 velas desde la entrada al open siguiente; neto = regla +30% / −15% / 21 velas con 0.39% por lado).

| setup | periodo | disparos | P(+30%) | P(+10%) | P(−20%) | neto medio | mediana | gana |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BASE | train | 365780 | 2.1% | 25.0% | 6.0% | -0.1% | 0.1% | 50.3% |
| BASE | test | 382242 | 5.2% | 35.0% | 9.4% | 0.1% | -0.3% | 48.5% |
| BASE golpeada (≤ −40%) | train | 29704 | 14.0% | 58.3% | 22.9% | 0.8% | -1.0% | 48.0% |
| BASE golpeada (≤ −40%) | test | 55040 | 15.9% | 57.5% | 23.0% | 0.4% | -2.4% | 45.4% |
| CAIDA_GIRO | train | 1683 | 23.2% | 69.9% | 20.2% | 3.9% | 3.0% | 54.1% |
| CAIDA_GIRO | test | 3472 | 18.8% | 60.9% | 29.1% | -0.2% | -4.6% | 42.6% |
| CAPITULACION | train | 1604 | 17.0% | 64.3% | 30.3% | 0.0% | -2.3% | 45.5% |
| CAPITULACION | test | 3098 | 22.6% | 63.2% | 36.4% | -0.7% | -8.5% | 40.4% |
| CATALIZADOR | train | 354 | 11.9% | 57.1% | 29.1% | -1.0% | -3.8% | 44.4% |
| CATALIZADOR | test | 1195 | 28.3% | 65.4% | 48.6% | -2.2% | -15.7% | 33.9% |

Compuerta (prueba). Exceso = neto medio del setup menos la base del mismo mes; t = el más bajo entre bootstrap por mes y por bloques de 3 meses.

| setup | exceso vs base [IC 95% bloques] | t mes / bloque | meses (efectivos) | exceso vs golpeada | lift P(+30%) | lift P(−20%) | cartera CAGR | caída máx. | meses ≥ +30% | placebo CAGR | placebo meses ≥ +30% | compuerta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CAIDA_GIRO | -1.3% [-2.7%, 0.0%] | -2.07 / -1.85 | 93 (49) | -2.0% | 3.62× | 3.11× | -15.0% | -89.4% | 1.1% | 2.1% | 0.0% | no (1/3) |
| CAPITULACION | 0.3% [-0.3%, 1.1%] | 0.82 / 0.92 | 93 (19) | -0.4% | 4.35× | 3.88× | -25.3% | -95.7% | 1.1% | -3.0% | 0.0% | no (1/3) |
| CATALIZADOR | -2.2% [-3.4%, -1.0%] | -3.75 / -3.45 | 93 (60) | -2.6% | 5.45× | 5.18× | -37.0% | -97.3% | 1.1% | -0.9% | 0.0% | no (1/3) |

Cartera con los 3 setups (prueba): CAGR -15.8%, caída máx. -91.3%, meses ≥ +30%: 2.2%, meses ≥ +10%: 17.4%, meses ≤ −20%: 5.4%, mediana mensual 0.2%; placebo CAGR -1.0%.

Operaciones con días sin cotizar dentro de la tenencia (se conservan; el día faltante repite el último cierre): CAIDA_GIRO 0/5155 (serie cortada 0); CAPITULACION 1/4702 (serie cortada 0); CATALIZADOR 0/1549 (serie cortada 0); BASE 2/748022 (serie cortada 0)

## Ejemplos pedidos

| setup | ticker | señal | entrada | máx. | mín. | día 21 | neto | salida |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CAPITULACION | CRWD | 2021-12-03 | 47.51 | 14.2% | -3.5% | -0.5% | -1.2% | tiempo |
| CAIDA_GIRO | CRWD | 2023-02-01 | 29.40 | 8.1% | -8.5% | 7.2% | 6.4% | tiempo |
| CAPITULACION | CRWD | 2024-07-22 | 67.25 | 3.0% | -25.4% | -0.9% | -15.7% | stop |
| CAPITULACION | META | 2022-02-07 | 218.75 | 6.4% | -15.7% | -10.1% | -15.7% | stop |
| CAIDA_GIRO | META | 2022-07-19 | 175.81 | 3.6% | -12.8% | -1.5% | -2.3% | tiempo |
| CAPITULACION | META | 2022-10-31 | 93.44 | 25.9% | -6.6% | 25.2% | 24.2% | tiempo |
| CAIDA_GIRO | META | 2022-11-30 | 118.07 | 4.6% | -5.7% | 1.0% | 0.2% | tiempo |
| CATALIZADOR | META | 2023-02-02 | 181.73 | 7.2% | -8.6% | 0.8% | -0.0% | tiempo |
| CAPITULACION | RKLB | 2022-05-18 | 4.68 | 10.2% | -16.0% | -10.7% | -15.7% | stop |
| CAIDA_GIRO | RKLB | 2022-07-20 | 4.37 | 66.8% | -9.2% | 37.3% | 29.0% | toma |
| CAIDA_GIRO | RKLB | 2022-10-25 | 4.58 | 25.8% | -8.3% | -3.9% | -4.7% | tiempo |
| CAIDA_GIRO | RKLB | 2023-04-11 | 4.13 | 1.9% | -9.4% | -0.2% | -1.0% | tiempo |
| CAPITULACION | RKLB | 2023-09-19 | 4.62 | 9.7% | -10.6% | -8.0% | -8.7% | tiempo |
| CATALIZADOR | RKLB | 2023-12-22 | 5.64 | 9.0% | -16.8% | -12.7% | -15.7% | stop |
| CAIDA_GIRO | RKLB | 2024-05-02 | 4.00 | 16.0% | -8.6% | 8.2% | 7.4% | tiempo |
| CAIDA_GIRO | RKLB | 2026-09-22 | 72.87 | 7.4% | -32.4% | -26.3% | -15.7% | stop |
| CAIDA_GIRO | SPCE | 2021-05-24 | 507.40 | 64.2% | -2.6% | 60.9% | 29.0% | toma |
| CATALIZADOR | SPCE | 2021-05-24 | 507.40 | 64.2% | -2.6% | 60.9% | 29.0% | toma |
| CAPITULACION | SPCE | 2021-07-12 | 806.80 | 3.0% | -29.4% | -22.3% | -15.7% | stop |
| CAPITULACION | SPCE | 2022-01-13 | 197.80 | 2.7% | -23.4% | -17.7% | -18.6% | stop |
| CAIDA_GIRO | SPCE | 2022-02-15 | 206.00 | 1.9% | -35.0% | -12.7% | -15.7% | stop |
| CATALIZADOR | SPCE | 2022-02-15 | 206.00 | 1.9% | -35.0% | -12.7% | -15.7% | stop |
| CAIDA_GIRO | SPCE | 2022-06-08 | 147.20 | 1.1% | -24.5% | -10.5% | -19.1% | stop |
| CAIDA_GIRO | SPCE | 2022-11-07 | 104.00 | 9.0% | -12.9% | -11.9% | -12.6% | tiempo |
| CAIDA_GIRO | SPCE | 2023-05-08 | 82.80 | 26.8% | -20.3% | 0.5% | -15.7% | stop |
| CATALIZADOR | SPCE | 2023-06-16 | 96.60 | 27.7% | -25.5% | -17.6% | -15.7% | stop |
| CAPITULACION | SPCE | 2024-06-17 | 11.50 | 0.0% | -43.3% | -43.0% | -15.7% | stop |
| CAIDA_GIRO | SPCE | 2024-09-16 | 6.81 | 3.8% | -16.0% | -0.6% | -15.7% | stop |
| CATALIZADOR | SPCE | 2024-11-11 | 7.37 | 11.1% | -15.8% | -11.9% | -15.7% | stop |
| CAIDA_GIRO | SPCE | 2025-07-14 | 3.24 | 42.9% | -9.9% | -7.7% | 29.0% | toma |
| CATALIZADOR | SPCE | 2025-07-17 | 3.69 | 25.5% | -20.9% | -19.0% | -15.7% | stop |
| CATALIZADOR | SPCE | 2026-05-22 | 3.34 | 166.5% | -18.9% | -18.3% | 29.0% | toma |
| CAPITULACION | SPCE | 2026-06-12 | 3.92 | 6.4% | -39.5% | -30.9% | -15.7% | stop |
| CAIDA_GIRO | SPCE | 2026-08-07 | 3.13 | 10.9% | -9.3% | 0.0% | -0.8% | tiempo |
| CAPITULACION | ZS | 2019-09-11 | 50.70 | 4.8% | -9.2% | -6.7% | -7.4% | tiempo |
| CAPITULACION | ZS | 2021-12-06 | 286.00 | 16.3% | -10.3% | -8.3% | -9.0% | tiempo |
| CAIDA_GIRO | ZS | 2022-06-07 | 162.00 | 6.1% | -17.7% | 3.0% | -15.7% | stop |
| CATALIZADOR | ZS | 2022-09-09 | 188.51 | 3.0% | -18.2% | -16.6% | -15.7% | stop |
| CAIDA_GIRO | ZS | 2023-01-20 | 117.71 | 22.0% | -2.8% | 8.6% | 7.8% | tiempo |
| CATALIZADOR | ZS | 2023-05-08 | 108.79 | 42.8% | -0.4% | 33.2% | 29.3% | toma |
| CAIDA_GIRO | ZS | 2026-04-22 | 136.69 | 33.9% | -6.5% | 25.1% | 29.0% | toma |
| CAIDA_GIRO | ZS | 2026-07-29 | 150.60 | 26.8% | -4.5% | 24.4% | 23.4% | tiempo |

## Disparos recientes (sin resultado aún)

| setup | ticker | fecha | precio | caída vs máx. 252d | P(+30%) hist. | P(−20%) hist. | neto medio hist. |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CAIDA_GIRO | KRMN | 2026-10-23 | 36.65 | -68.2% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | CRS | 2026-10-23 | 284.66 | -54.0% | 22.6% | 36.4% | -0.7% |
| CATALIZADOR | SAIQ | 2026-10-23 | 6.12 | -45.6% | 28.3% | 48.6% | -2.2% |
| CAPITULACION | KALU | 2026-10-23 | 107.28 | -44.6% | 22.6% | 36.4% | -0.7% |
| CAPITULACION | FIX | 2026-10-23 | 1160.86 | -43.8% | 22.6% | 36.4% | -0.7% |
| CAPITULACION | CORT | 2026-10-23 | 85.86 | -30.5% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | TTD | 2026-10-22 | 13.16 | -75.7% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | AVTX | 2026-10-22 | 7.45 | -67.4% | 22.6% | 36.4% | -0.7% |
| CAPITULACION | TTMI | 2026-10-22 | 73.89 | -66.6% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | CCB | 2026-10-22 | 44.90 | -62.3% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | OI | 2026-10-22 | 6.41 | -61.5% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | FISV | 2026-10-22 | 50.82 | -59.8% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | UTI | 2026-10-22 | 21.66 | -57.7% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | BSX | 2026-10-22 | 46.01 | -56.2% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | JBI | 2026-10-22 | 4.52 | -55.7% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | ACM | 2026-10-22 | 60.83 | -54.0% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | LULU | 2026-10-22 | 104.06 | -51.8% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | PATK | 2026-10-22 | 70.27 | -51.1% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | NVEC | 2026-10-22 | 68.36 | -48.6% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | JDZG | 2026-10-21 | 6.51 | -99.3% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | BETR | 2026-10-21 | 15.58 | -81.9% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | NUAI | 2026-10-21 | 3.32 | -58.8% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | LIF | 2026-10-21 | 44.39 | -55.3% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | FLEX | 2026-10-21 | 86.25 | -46.8% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | AGNT | 2026-10-20 | 4.08 | -64.4% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | TREE | 2026-10-20 | 26.53 | -61.0% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | REAX | 2026-10-20 | 17.14 | -59.9% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | RARE | 2026-10-20 | 16.02 | -56.2% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | TPB | 2026-10-20 | 64.43 | -54.8% | 18.8% | 29.1% | -0.2% |
| CATALIZADOR | MYGN | 2026-10-20 | 5.54 | -32.3% | 28.3% | 48.6% | -2.2% |
| CAIDA_GIRO | CELH | 2026-10-19 | 29.72 | -54.2% | 18.8% | 29.1% | -0.2% |
| CATALIZADOR | SLN | 2026-10-19 | 19.58 | 0.0% | 28.3% | 48.6% | -2.2% |
| CAPITULACION | ALMU | 2026-10-16 | 7.95 | -74.8% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | BRBR | 2026-10-16 | 9.43 | -71.8% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | FUN | 2026-10-16 | 8.11 | -69.7% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | FNGD | 2026-10-16 | 26.73 | -68.8% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | PODD | 2026-10-16 | 141.10 | -59.3% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | CRWV | 2026-10-16 | 61.39 | -56.7% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | PLNT | 2026-10-16 | 50.92 | -54.5% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | VXX | 2026-10-16 | 18.38 | -54.0% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | GHM | 2026-10-16 | 68.48 | -44.7% | 22.6% | 36.4% | -0.7% |
| CAPITULACION | IESC | 2026-10-16 | 251.96 | -36.5% | 22.6% | 36.4% | -0.7% |
| CATALIZADOR | BETR | 2026-10-15 | 10.76 | -87.5% | 28.3% | 48.6% | -2.2% |
| CAPITULACION | FMC | 2026-10-15 | 5.62 | -81.2% | 22.6% | 36.4% | -0.7% |
| CAPITULACION | TNXP | 2026-10-15 | 6.42 | -68.5% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | GTM | 2026-10-15 | 4.08 | -65.4% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | Z | 2026-10-15 | 31.46 | -59.7% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | XRPN | 2026-10-15 | 16.07 | -59.2% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | CSGP | 2026-10-15 | 32.00 | -59.1% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | ZG | 2026-10-15 | 32.43 | -56.5% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | COLL | 2026-10-15 | 23.18 | -53.5% | 18.8% | 29.1% | -0.2% |
| CAIDA_GIRO | INTU | 2026-10-15 | 330.17 | -51.0% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | DFH | 2026-10-14 | 7.42 | -69.3% | 22.6% | 36.4% | -0.7% |
| CATALIZADOR | LQDA | 2026-10-14 | 33.94 | -62.7% | 28.3% | 48.6% | -2.2% |
| CAPITULACION | GRRR | 2026-10-14 | 8.20 | -62.4% | 22.6% | 36.4% | -0.7% |
| CAPITULACION | IDR | 2026-10-14 | 20.58 | -60.9% | 22.6% | 36.4% | -0.7% |
| CAPITULACION | SKYD | 2026-10-14 | 7.06 | -58.7% | 22.6% | 36.4% | -0.7% |
| CAPITULACION | CIFR | 2026-10-13 | 11.34 | -61.1% | 22.6% | 36.4% | -0.7% |
| CAIDA_GIRO | UPWK | 2026-10-13 | 8.64 | -60.9% | 18.8% | 29.1% | -0.2% |
| CAPITULACION | SRZN | 2026-10-13 | 23.51 | -31.1% | 22.6% | 36.4% | -0.7% |
| CATALIZADOR | GRML | 2026-10-12 | 6.02 | -81.8% | 28.3% | 48.6% | -2.2% |
| CAPITULACION | CTNM | 2026-10-12 | 8.56 | -51.3% | 22.6% | 36.4% | -0.7% |
| CATALIZADOR | BMBL | 2026-10-12 | 3.80 | -35.4% | 28.3% | 48.6% | -2.2% |
