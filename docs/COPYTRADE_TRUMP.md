# Copy-trade de las operaciones públicas de Donald J. Trump (pre-registro)

**Fijado el 25-oct-2026, antes de bajar o ver un solo precio.** Ya se vieron las transacciones (conteos, tipos,
montos) para poder diseñar, pero ningún retorno. Cualquier cambio posterior se anota al final con fecha y motivo y
cuenta como ensayo adicional.

Pregunta: **¿cuánto valdrían 50,000 si desde el inicio del segundo mandato (20-ene-2025) se hubieran replicado las
operaciones que Trump reporta a la Oficina de Ética Gubernamental (OGE)?** Y la pregunta útil para el sistema
multiagente: **¿copiarlas al publicarse tiene ventaja sobre comprar el índice?**

## Datos
- **Fuente primaria:** PDF de OGE (formatos 278-T y el anual 278e de 2026, que trae las operaciones de 2025 que
  nunca salieron en un 278-T). Lista en `data/copytrade/filings.csv`; copias y texto en la rama `copytrade-data`.
- **Filas:** dataset de Open Cabinet (MIT, commit `7864d1a`, 24-sep-2026), leído con LLM y revisado por ellos.
  Se verifica contra nuestro propio parser del texto OCR de cada PDF (conteos por reporte, coincidencia fila a fila
  en fecha, tipo, rango y nombre). Las operaciones de agosto-2026 (reporte `09.17.2026`, aún no en Open Cabinet) se
  leen solo con nuestro parser + OCR.
- **Universo:** operaciones con fecha ≥ 20-ene-2025. Fuera: `pre-service`, opciones, privados, cripto sin ticker y
  todo lo que no se pueda mapear (se reporta cuánto $ queda fuera).
- **Monto:** punto medio del rango (1,001–15,000 → 8,000.5; …; 25,000,001–50,000,000 → 37.5 M). Sensibilidad:
  límite inferior, media geométrica y "1 dólar por operación" (peso igual).
- **Fecha de publicación (para el modo replicable):** la fecha en que OGE publica el PDF (`oc_posted` de la lista;
  si falta, la que dé el índice de OGE o, en último caso, la prensa con fuente). Nunca antes que el sello
  "OGE Received".

## Mapeo de activos
- **Acciones, ETF y fondos con ticker:** su propio precio ajustado (dividendos + splits) de Yahoo.
  Nombre→ticker: resolución de Open Cabinet (reglas R1–R5 contra listas SEC/Nasdaq) + nuestras listas SEC/Nasdaq +
  revisión manual de los nombres grandes (`data/copytrade/overrides.csv`, con motivo).
- **Fondos de mercado de dinero (money market):** BIL.
- **Municipales:** vencimiento ≤ 3 años desde la operación → SUB; mayor o sin dato → MUB.
- **Corporativos:** ≤ 3 años → VCSH; 3–10 → VCIT; > 10 → VCLT; perpetuos/subordinados "PERP" → PFF.
- **Preferentes:** PFF. **Tesoros:** ≤ 1 año → BIL; 1–3 → SHY; 3–10 → IEF; > 10 → TLT.
- Los bonos se aproximan con ETF del mismo segmento: es un proxy de clase de activo, no del bono exacto (se dice así
  en el reporte).
- **Sin precio:** si la serie termina antes (fusión, deslistado) la posición pasa a BIL al último cierre; si empieza
  después de la operación, se usa el primer cierre dentro de 5 días hábiles; si no, queda fuera y se reporta.

## Cartera sombra y réplica
- **Cartera sombra (lo que Trump compró en el mandato):** por activo, acciones = Σ compras/precio − ventas/precio,
  nunca negativa. Las ventas de algo que no se compró en el mandato (tenencias previas) se ignoran: el copiador nunca
  lo tuvo. Mismo día: primero compras, luego ventas.
- **Copiador con 50,000:** sostiene la **misma composición** que la cartera sombra (rendimiento ponderado por tiempo;
  las aportaciones de Trump no son dinero del copiador). Rebalancea al cierre de cada día de ejecución. Sin cartera
  sombra todavía → BIL.
- **Modo E — espejo perfecto:** ejecuta al cierre del día de la operación (o el siguiente hábil). Imposible en la
  práctica: es el techo teórico.
- **Modo R — replicable (el principal):** ejecuta al cierre del **primer día hábil después de la publicación**.
  Sensibilidad: +5 días hábiles más.
- **Variantes:** cartera completa · solo acciones y ETF de renta variable · **Top-30** (las 30 posiciones más grandes
  de la cartera sombra, renormalizadas: lo que de verdad se puede comprar con 50k).
- **Costos por peso operado (rotación):** base 0.29% por lado (comisión tipo GBM 0.25% + IVA; verificar contra el
  contrato) y alterno 0.05% (bróker de EE. UU.). Sin impuestos.
- **Periodo:** cierre del 21-ene-2025 al último cierre disponible.

## Comparativos
SPY (S&P 500 con dividendos), 60/40 SPY/AGG con rebalanceo mensual, MUB, BIL (efectivo en dólares). En pesos:
los mismos convertidos con USD/MXN (Yahoo `MXN=X`) y **CETES aproximados con la tasa objetivo de Banxico** (BIS),
etiquetado como aproximación.

## Métricas
Valor final de 50,000 en USD y en MXN, retorno total, CAGR, volatilidad, Sharpe contra BIL, caída máxima, beta y
alfa CAPM contra SPY (errores HAC de Newey-West, 10 rezagos), contribución por clase de activo, 10 mejores y peores
posiciones, **costo del rezago = E − R**.

**Estudio por operación (¿hay información en lo que compra?):** para cada compra y venta de acción/ETF con precio,
retorno en exceso sobre SPY a 21, 63 y 126 días hábiles, (a) desde la fecha de operación y (b) desde la publicación
+1. Ventas con signo invertido (positivo = lo vendido luego lo hizo peor que el índice). Ponderado por monto y por
operación. IC 95% por bootstrap agrupado por fecha (2,000 réplicas), porque cientos de operaciones del mismo día no
son independientes. Solo operaciones con horizonte completo.

## Criterio (fijado hoy)
"Copiar a Trump" entra al sistema multiagente como señal **solo si se cumplen los tres**, en modo R, cartera completa,
punto medio y costos base:
1. retorno total mayor que SPY en el periodo;
2. alfa CAPM > 0 con t ≥ 2;
3. compras con exceso a 63 días desde la publicación con IC 95% por encima de 0.

Si no, se reporta tal cual y no se automatiza. Con ~21 meses de datos el poder estadístico es bajo; también se dice.
La variante principal es una sola; las demás (36 combinaciones) son sensibilidad, no se elige la mejor.

## Cambios posteriores
(ninguno)
