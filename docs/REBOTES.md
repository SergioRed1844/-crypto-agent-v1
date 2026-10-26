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
**26-oct-2026, después de la primera corrida** (que ya había fallado la compuerta: 0/3 setups; exceso vs base −1.4%,
−0.1% y −2.4% por operación; carteras de −7% a −42% anual). Una revisión independiente del código encontró fallas que
**favorecían a los setups**. Se corrigen y se vuelve a correr; la primera corrida queda registrada aquí.

1. **Operaciones borradas por datos futuros.** Antes se descartaba toda operación con un día sin cotizar dentro de las
   21 velas (suspensión, hueco de Yahoo). Eso depende del futuro y quita justo a las castigadas. Ahora solo se exige
   poder entrar. Un día sin cierre repite el último cierre, sin máximo ni mínimo propio. Si la serie se corta, se sale
   al último cierre conocido. Se reporta cuántas operaciones tienen huecos.
2. **Filtro de US$3 con splits futuros.** Los precios ajustados multiplican el pasado por los *reverse splits*
   posteriores: SPCE a US$0.80 aparecía como US$16. Ahora se baja de Yahoo sin auto-ajuste, con splits. El filtro de
   US$3 usa el precio al que se operó ese día y el dinero operado usa precio × volumen reales. Los retornos siguen
   usando OHLC ajustados por dividendos y splits.
3. **Precios en cero** de Yahoo cuentan como dato faltante, no como −100%. Además: máximo ≥ apertura y cierre,
   mínimo ≤ apertura y cierre.
4. **Vela de hoy incompleta.** Si se corre antes del cierre de NY, se quita la vela del día.
5. **Inferencia de la compuerta 1.** Se agrega un bootstrap por bloques de 3 meses, porque las tenencias cruzan de mes
   y los meses de pánico se agrupan. La compuerta usa el t más conservador de los dos. Se reportan los meses efectivos,
   (Σw)²/Σw².
6. **Cartera:**
   - el valor diario ya descuenta el costo de vender;
   - sin cierre ese día, se usa el último conocido;
   - la ventana termina en el último fin de mes con 21 velas después, para no terminar en efectivo ni contar un mes
     parcial;
   - el SPY se mide en la misma ventana.
7. **Candidatos vigentes:** se aplica la misma pausa por acción que en el estudio.
8. **Descriptivo nuevo, no es compuerta:** "BASE golpeada", días cualquiera de acciones ya ≥ 40% abajo de su máximo.
   La revisión mostró que la compuerta 2 (P(+30%) ≥ 1.5× base) se pasa con pura volatilidad: en un panel sintético sin
   ventaja dio 2–2.6×. La prueba de fondo es la compuerta 1. La compuerta 2 se deja como estaba pre-registrada.
9. **Descarga:** falla si llegan menos del 90% de los tickers o falta SPY, para no correr con un universo mutilado.

**Diferencias menores con el texto de arriba (sin efecto material, se dejan así):**
- la BASE toma 1 de cada 10 filas del calendario por acción con regla modular, no 1 de cada 10 días elegibles; la
  tasa es la misma;
- el placebo de cartera muestrea con reemplazo, con el número de disparos del setup por mes;
- el SPY está en el universo operable.

## Alerta de lunes y miércoles (papel, desde 26-oct-2026)
Sergio pidió las señales por correo y en su hoja. `rebotes/alerta.py` corre en `rebotes-alerta.yml` (rama main, lunes
6:47 y miércoles 16:17 de Monterrey). Calcula los mismos setups al último cierre y lleva una bitácora en papel con la
misma regla (`alertas/ledger.csv` en rebotes-data). Manda el correo por Gmail SMTP (sin SMTP, un issue) y escribe en
la hoja vía `sheets/rebotes_sheet.gs`. Son **señales del estudio, no recomendación de compra**. El dictamen solo dice
"pasó la compuerta" si el setup la pasó aquí; hoy ninguno. La bitácora es la prueba en vivo: si con el tiempo da
distinto que el backtest, se reporta; los parámetros no se tocan.
