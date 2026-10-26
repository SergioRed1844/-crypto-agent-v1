# Rebotes de corto plazo (pre-registro)

**Fijado el 26-oct-2026, antes de bajar o ver un solo precio de este universo.** Cualquier cambio posterior se anota
al final con fecha y motivo.

Pregunta de Sergio: comprar empresas "en oportunidad" (caídas fuertes que rebotan, como META en 2022, Zscaler en 2026
o Virgin Galactic con la noticia de SpaceX), entrar y salir en un mes y repetir. **Meta declarada: +30% al mes.**
Este estudio no promete esa meta: mide qué tan seguido se da y cuánto cuesta cuando no se da.

## Universo y datos
- Acciones de EE. UU. del iShares Russell 3000 (IWV) a la fecha de descarga. Si el archivo no se puede bajar, se usan
  las acciones comunes de las listas Nasdaq/NYSE. Se agregan SPCE, RKLB, SPCX, ZS, META y CRWD aunque no estén.
- Velas diarias ajustadas (splits y dividendos) de Yahoo, del 1-ene-2005 al último cierre.
- **Elegible el día t** (solo con datos hasta t):
  - cierre ≥ US$3;
  - mediana de dinero operado en 20 días ≥ US$5 M;
  - ≥ 260 velas de historia.
- **Sesgo de sobrevivencia (conocido):** Yahoo no trae empresas que ya no cotizan y el universo es el de hoy. Las que
  quebraron después de caer, justo los rebotes que no llegaron, faltan. El sesgo infla los resultados y se reporta
  así; no hay corrección.

## Setups (se evalúan al cierre del día t; la entrada es al open de t+1)
1. **CAIDA_GIRO** (tipo META 2022, Zscaler 2026):
   - el cierre está ≥ 50% abajo de su máximo de 252 días;
   - el cierre supera el máximo de los 20 días previos, y el día anterior no lo hacía (el giro empieza hoy);
   - pausa de 60 velas por acción.
2. **CAPITULACION:**
   - caída ≥ 25% en 10 días;
   - volumen del día ≥ 3× la mediana de 50 días;
   - pausa de 30 velas.
3. **CATALIZADOR** (tipo Virgin + SpaceX):
   - sube ≥ 15% en el día con volumen ≥ 5× la mediana de 50 días;
   - el cierre previo estaba ≥ 40% abajo de su máximo de 252 días;
   - pausa de 30 velas.
- **BASE (placebo):** 1 de cada 10 días elegibles de cada acción (regla fija por posición), con los mismos resultados.
  Es "comprar cualquier acción en cualquier día".

## Resultados por disparo (21 velas desde la entrada)
- **Probabilidades:**
  - P(toca +30%) y P(toca +10%) con el máximo intradía;
  - P(toca −20%) con el mínimo intradía;
  - retorno al cierre de la vela 21.
- **Regla de operación fija:**
  - toma de ganancia +30% (límite);
  - stop −15%; si abre por debajo, se llena al open;
  - salida por tiempo al cierre de la vela 21;
  - si el mismo día toca la toma y el stop, cuenta el stop.
- **Costos:** 0.39% por lado = comisión tipo GBM 0.29% (0.25% + IVA) + 0.10% de deslizamiento.

## Cartera (la pregunta del 30% mensual)
- **Arranque:** US$50,000. Hasta 5 posiciones de 20% del valor al entrar; sin apalancamiento; el efectivo no rinde.
- **Orden de entrada:** por fecha. Si hay empate, entra primero el de mayor caída desde el máximo. No se repite una
  acción que ya está abierta.
- **Se reporta:**
  - retornos mensuales, **% de meses ≥ +30%**, % de meses ≤ −20%, CAGR y caída máxima;
  - lo mismo para una cartera placebo con entradas al azar, el mismo número de entradas por mes y las mismas reglas
    (mediana de 200 repeticiones).

## Periodos
- **Entrenamiento descriptivo:** 2005–2018. No se ajusta nada con él.
- **Prueba fuera de muestra:** 2019-01-01 → último cierre. **Los resultados principales son los de prueba.**

## Compuerta para entrar al Radar EB (solo alertas, papel)
Se exige todo, en prueba:
1. retorno neto medio por operación (regla fija) ≥ placebo + 2 pp, con t ≥ 2 (bootstrap agrupado por mes de entrada,
   ≥ 30 meses con disparos);
2. P(toca +30%) ≥ 1.5 × la de la base;
3. la cartera le gana al CAGR del SPY (con dividendos) en el mismo periodo, con caída máxima ≤ 35%.

Si ningún setup pasa, se reporta tal cual y no se automatiza. 3 setups × 1 regla = 3 ensayos.

## Cambios posteriores
(ninguno)
