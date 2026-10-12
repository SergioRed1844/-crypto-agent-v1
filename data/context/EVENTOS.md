# Estudio de eventos — ¿qué mueve a BTC?

Generado 2026-10-12T04:44:24Z. Precios 2010-07-18 → 2026-10-11. 258 de 261 eventos históricos con precio suficiente.

Referencia: un día cualquiera mueve |z3| = 0.751 en promedio (4000 días al azar). Un tipo de evento **pesa** si mueve más que eso (p_abs < 0.05) y tiene **dirección** si el signo de su postura pro/anti acierta más del 50% (p_dir < 0.05).

| Categoría | n | \|z3\| | × azar | p | Efecto dir. | Acierto signo | p | Peso magnitud (exceso) | Peso dirección | Evidencia |
|---|---|---|---|---|---|---|---|---|---|---|
| Regulación cripto | 59 | 1.237 | 1.65 | 0.001 | 0.559 | 0.556 | 0.2483 | 0.46 | 0.511 | magnitud fuerte, dirección débil |
| Política monetaria | 42 | 0.962 | 1.28 | 0.07 | 0.27 | 0.562 | 0.2983 | 0.23 | 0.261 | magnitud moderada, dirección débil |
| Crisis financiera / quiebras | 20 | 1.65 | 2.2 | 0.0015 | 1.443 | 0.789 | 0.0096 | 0.766 | 1.095 | magnitud fuerte, dirección fuerte |
| Estructura cripto (halving, ETF, upgrades) | 19 | 1.076 | 1.43 | 0.0565 | 0.632 | 0.692 | 0.1334 | 0.285 | 0.444 | magnitud moderada, dirección débil |
| Adopción institucional | 18 | 1.082 | 1.44 | 0.0645 | 0.663 | 0.611 | 0.2403 | 0.35 | 0.536 | magnitud moderada, dirección débil |
| Oferta cripto (Mt. Gox, gobiernos, unlocks) | 15 | 1.175 | 1.57 | 0.045 | 0.161 | 0.7 | 0.1719 | 0.409 | 0.201 | magnitud fuerte, dirección débil |
| Comercio / aranceles | 13 | 0.635 | 0.85 | 0.6637 | 0.57 | 0.692 | 0.1334 | 0.107 | 0.463 | magnitud débil, dirección débil |
| Hackeo / seguridad | 13 | 1.33 | 1.77 | 0.0235 | 0.759 | 0.769 | 0.0461 | 0.436 | 0.527 | magnitud fuerte, dirección fuerte |
| Elección | 12 | 1.149 | 1.53 | 0.062 | 1.681 | 0.75 | 0.3125 | 0.371 | 0.702 | magnitud moderada, dirección débil |
| Geopolítica | 12 | 0.973 | 1.3 | 0.1559 | -0.154 | 0.364 | 0.8867 | 0.295 | 0.021 | magnitud débil, dirección débil |
| Cambio de gobierno | 9 | 0.852 | 1.13 | 0.3148 | 0.955 | 1.0 | 0.0625 | 0.174 | 0.437 | magnitud débil, dirección débil |
| Ballenas on-chain / era Satoshi | 8 | 0.452 | 0.6 | 0.8871 | — | — | 1.0 | 0.0 | 0.188 | magnitud débil, dirección sin datos |
| Fiscal / deuda | 6 | 2.421 | 3.22 | 0.0055 | 0.852 | 0.5 | 0.6875 | 0.84 | 0.386 | magnitud moderada, dirección débil |
| Dato macro | 5 | 1.201 | 1.6 | 0.1089 | 1.201 | 1.0 | 0.0312 | 0.309 | 0.56 | magnitud débil, dirección moderada |
| Pandemia / salud | 4 | 2.042 | 2.72 | 0.0135 | 2.671 | 1.0 | 0.125 | 0.639 | 0.885 | magnitud débil, dirección débil |
| Regulación tecnología / IA | 3 | 0.809 | 1.08 | 0.3653 | -0.27 | 0.667 | 0.5 | 0.258 | 0.091 | magnitud débil, dirección débil |
| Patentes / licencias | 0 | — | — | 1.0 | — | — | 1.0 | 0.0 | 0.03 | magnitud sin datos, dirección sin datos |
| Vencimiento de derivados | 0 | — | — | 1.0 | — | — | 1.0 | 0.1 | 0.08 | magnitud sin datos, dirección sin datos |

Pesos = encogimiento bayesiano hacia el prior (k = 8.0): con pocos eventos manda el juicio experto.

## Moderadora: régimen de BTC al momento del evento

| Celda | n | Multiplicador | Prior |
|---|---|---|---|
| GREEN_pro | 62 | 0.664 | 1.2 |
| GREEN_anti | 60 | 1.182 | 0.8 |
| RED_pro | 33 | 1.12 | 0.8 |
| RED_anti | 51 | 1.121 | 1.3 |

## Los 20 eventos que más movieron (z a 3 días)

| Fecha | Evento | Categoría | Postura | z1 | z3 | z7 | z30 |
|---|---|---|---|---|---|---|---|
| 2020-03-12 | Jueves Negro: colapso global de mercados por COVID | Crisis financiera / quiebras | anti | -15.86 | -8.483 | -5.01 | -1.09 |
| 2013-04-11 | Mt. Gox suspende trading ('market cooldown') tras crash de abril | Hackeo / seguridad | anti | -14.189 | -7.006 | -5.934 | -4.662 |
| 2020-03-11 | OMS declara pandemia de COVID-19 | Pandemia / salud | anti | 0.092 | -6.665 | -4.899 | -0.673 |
| 2026-08-19 | Tesoro duplica recompras de bonos largos (~$4 mil mdd) | Fiscal / deuda | pro | 3.93 | 6.38 | 4.407 | 2.295 |
| 2019-10-25 | Xi Jinping pide acelerar el desarrollo de blockchain (difundido el 25-oct) | Regulación cripto | pro | 5.086 | 4.963 | 2.865 | 0.467 |
| 2013-03-18 | FinCEN emite guía: exchangers/mineros como transmisores de dinero | Regulación cripto | neutral | 2.279 | 4.949 | 4.031 | -0.336 |
| 2013-12-05 | PBoC prohíbe a instituciones financieras operar con bitcoin | Regulación cripto | anti | -1.882 | -4.837 | -2.46 | -2.944 |
| 2023-03-12 | Cierre de Signature; Tesoro/Fed/FDIC garantizan depósitos y crean BTFP | Política monetaria | pro | 2.848 | 4.365 | 4.104 | 2.388 |
| 2026-08-18 | SEC propone 'Regulation Crypto Assets' con safe harbor | Regulación cripto | pro | 0.358 | 4.341 | 4.679 | 2.422 |
| 2022-06-12 | Celsius congela retiros | Crisis financiera / quiebras | anti | -1.618 | -4.308 | -4.415 | -1.432 |
| 2026-06-01 | Strategy revela su primera venta de BTC desde 2022 | Adopción institucional | anti | -1.612 | -3.992 | -3.024 | -2.413 |
| 2026-08-20 | Trump presiona por el CLARITY Act en reunión cripto en la Casa Blanca | Regulación cripto | pro | 3.106 | 3.625 | 3.067 | 2.205 |
| 2026-06-02 | Mt. Gox mueve 10,422.65 BTC de cold storage (116.30 BTC a hot wallet) antes del plazo 2026 | Oferta cripto (Mt. Gox, gobiernos, unlocks) | neutral | -3.576 | -3.418 | -2.455 | -1.801 |
| 2022-11-08 | FTX congela retiros; Binance firma carta de intención de compra | Crisis financiera / quiebras | anti | -3.834 | -3.316 | -2.839 | -1.062 |
| 2020-11-03 | Elección presidencial de EE.UU. 2020 | Elección | neutral | 1.167 | 3.291 | 1.704 | 2.212 |
| 2020-11-03 | DOJ incauta y mueve ~69,370 BTC hackeados de Silk Road ('Individual X'); comunicado 2020-1 | Oferta cripto (Mt. Gox, gobiernos, unlocks) | anti | 1.167 | 3.291 | 1.704 | 2.212 |
| 2017-09-12 | Jamie Dimon (JPMorgan) llama 'fraude' a bitcoin | Adopción institucional | anti | -0.338 | -3.219 | -0.522 | -0.084 |
| 2022-11-06 | CZ anuncia que Binance liquidará sus FTT | Estructura cripto (halving, ETF, upgrades) | anti | -0.554 | -2.902 | -3.232 | -1.342 |
| 2017-12-19 | Youbit (Corea) se declara en quiebra tras hackeo | Hackeo / seguridad | anti | -1.819 | -2.874 | -3.21 | -3.877 |
| 2023-02-13 | NYDFS ordena a Paxos dejar de emitir BUSD | Regulación cripto | anti | -0.1 | 2.862 | 1.678 | 0.284 |

**Cuidado:** asociación ≠ causalidad. Varios eventos caen en días con otros choques; la muestra por categoría es chica; y la fecha es la del anuncio (el mercado pudo anticiparlo). Por eso los pesos se encogen al prior y la señal solo modula riesgo y tamaño: no abre posiciones por sí sola.
