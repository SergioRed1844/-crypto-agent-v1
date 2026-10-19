# Agente FX (agente 3) — intradía por datos macro en OANDA v20

Diseño de investigación, no recomendación de inversión. Hoy corre solo en **paper** o **practice** (cuenta demo).

## Qué hace, en cinco líneas

1. En cada **slot de anuncios** (8:30, 10:00 y 14:00 de Nueva York; BCE; BoE; Banxico 13:00 CDMX) mide cuánto se
   movió cada par en los primeros 15 minutos contra lo normal en ese minuto (**z**). Si |z| es grande, hubo sorpresa.
2. No compite por los primeros segundos (eso es de los bancos, F15-001/F14-016): entra en **T+15** a favor (o en
   contra, si los datos dicen reversión) de esa reacción, con **stop en el servidor del broker** y salida por tiempo.
3. Qué pares y slots se operan, en qué dirección y con qué horizonte lo decide un **Bayes empírico escéptico** en
   walk-forward con costos reales; si nada pasa el umbral, el agente **no opera**.
4. Un **motor de riesgo** limita cada evento a 0.35% del capital y aplica el **gobernador semanal −1.5%**.
5. TradingView es la capa visual y de control (FLATTEN/PAUSE/RESUME); la decisión y la orden no dependen de él.

**Lo que no puede prometer.** Ninguna estrategia garantiza ganar todas las semanas: entre 74% y 89% de las cuentas
minoristas de CFD pierden (ESMA, F00/F16). Lo que sí se puede garantizar por construcción es el **techo de pérdida
semanal** (−1.5%, salvo gaps) y que el agente no opere si los datos no muestran ventaja. El % de semanas positivas,
la peor semana y la racha de semanas negativas se reportan tal cual en `data/fx/BACKTEST.md`.

## Arquitectura (capas del corpus F15-014)

```
[1 DATOS]  OANDA stream de precios (practice/live) · calendario confirmado v4.2 · velas Dukascopy (backtest)
   │        cada precio con t_proveedor y t_recepción (UTC)
[2 SEÑAL]  MinuteBook (velas de 1 min) → en T0+15: ret15 = ln(P15/P0), z = ret15/σ_slot
[3 MODELO] model.json (EB): (par, slot) activos → dirección, horizonte, z mínimo; σ_slot y spread típico
[4 RIESGO] RiskEngine: tamaño por stop, tope semanal/diario, rachas, DD, apalancamiento, USD neto, blackouts
[5 EJECUCIÓN] OANDA v20: MARKET FOK + priceBound + stopLossOnFill (keep-alive) │ PaperBroker en paper
[6 MONITOR] proceso aparte: NAV del broker, salidas vencidas, KILL ─► el motor solo puede reducir/cerrar
[7 SUPERVISOR] (opcional, fuera del camino de la orden) lee la bitácora y propone cambios a revisión humana
```

TradingView → `POST /tv` (Caddy TLS → 127.0.0.1:8080): IP de TradingView + secreto + idempotencia, responde en
<1 ms y deja el intent en SQLite; el motor lo atiende en ≤250 ms.

## Estrategia A — definiciones exactas (las mismas en backtest y en vivo)

| Pieza | Definición |
|---|---|
| P0 | mid al cierre del minuto T0−1 (precio antes del dato) |
| P15 | mid al cierre del minuto T0+14 |
| σ_slot | 1.4826 × mediana \|ret15\| de los ~250 días hábiles **anteriores** en ese slot (≥120) |
| z | ln(P15/P0) / σ_slot; los días sin dato dan z≈0, los de sorpresa \|z\| ≫ 1 |
| Entrada | open del minuto T0+15 (ask si compra, bid si vende); ventana válida hasta T+20 |
| Dirección | momentum = signo de ret15; reversión = contrario (lo elige el EB por grupo) |
| Stop | 1.5 × σ esperada del horizonte (vol previa + exceso del evento con vida media 20 min), piso 3× spread y 6 pips (60 en MXN), fuera de la zona justo detrás de un "00" |
| Salida | lo primero entre T+15+horizonte, 16:50 NY (antes del rollover), viernes 15:55 NY o 5 min antes del siguiente evento confirmado |
| Costos | spread real cruzado + sobreprecio OANDA estimado + deslizamiento; prueba ×2 |
| Filtros | spread > 1.5× típico de ese minuto → no; blackouts (abajo); precio con >5 s de antigüedad → no |

Rejilla **fijada antes de ver datos** (19-oct-2026): z ∈ {2, 3}, horizonte ∈ {60, 120, 360} min, dirección ∈
{momentum, reversión} → 12 variantes por grupo. Cualquier cambio posterior se declara al final de este documento.

**Por qué detectar la sorpresa por el precio.** El consenso de analistas en tiempo real cuesta (Bloomberg,
Trading Economics de pago). La reacción de 15 min ya incorpora la sorpresa compuesta (titular + revisiones +
salario…), que es justo lo que el corpus pide medir para NFP. Se pierde el filtro "signo esperado por z del dato";
se compensa con el umbral de |z| y con el EB.

## Bayes empírico por (par, slot)

- Unidad: **R neto** por operación (P&L ÷ riesgo inicial), ya con costos.
- Errores estándar agrupados por **día**: los pares que reaccionan al mismo dato no son eventos independientes.
- Prior escéptico **N(0, τ²)** (paseo aleatorio), τ² por DerSimonian-Laird entre grupos de la misma variante (tope).
- Se activa un grupo con su mejor variante solo si **P(μ>0) ≥ 0.942** (= 1 − 0.2/√12 por elegir entre 12) y n ≥ 12.
- **Walk-forward anual expansivo**: para operar el año Y se entrena con todo lo anterior a Y. Primer año fuera de
  muestra: 2018.
- Validación extra: **DSR** (N=12 y N=60), **PBO** por CSCV con 16 bloques sobre las 12 variantes, y **signo
  aleatorio** (mismas entradas con dirección al azar, 2000 sorteos).

## Riesgo (capital de referencia US$2,000)

| Regla | Valor | Qué significa con US$2,000 |
|---|---|---|
| Riesgo por evento | 0.35% (techo inmutable 0.5%) | US$7 si saltan todos los stops del evento, repartidos entre los pares que disparan |
| Gobernador semanal | −1.5% (semana FX: domingo 17:00 NY → viernes) | al perder US$30 en la semana: todo plano hasta el domingo 17:00 NY |
| Presupuesto | cada operación ≤ 90% de lo que queda del tope, contando el riesgo abierto | una cadena de stops normales no puede pasar de −1.5% |
| Diario | −1% → sin entradas hasta el siguiente día FX | US$20 |
| Racha | 3 pérdidas seguidas → pausa 24 h | |
| Drawdown | 5% → tamaño a la mitad; 10% → apagado hasta revisión humana | US$100 / US$200 |
| Apalancamiento | ≤5× bruto; 1 posición por par; ≤4 abiertas; \|USD neto\| ≤ 3× | nocional ≤ US$10,000 |
| Gaps | se controlan con tamaño, no con stops (F15-017 C) | un gap puede rebasar el stop: por eso el riesgo es chico |

Solo tope de pérdida (sin candado de ganancia): las ganancias de la semana amplían el margen de esa semana.

## Blackouts y calendario

Sin entradas: fix de Londres 16:00 ±2.5 min · 16:50–17:10 NY (rollover; todo sale a las 16:50) · viernes desde
15:55 NY hasta el domingo 17:00 NY · 24-dic a 2-ene · T−5/T+5 de eventos **confirmados con hora** del calendario v4.2
(FOMC, Banxico, BCE, BoE, NFP/IPC cuando se curen). Eventos sin hora o propuestos no bloquean (regla v4.2).

## Latencia: dónde importa y cómo se cierra

- La entrada es en T+15 a propósito; ganar milisegundos ahí no agrega ventaja. Lo que sí importa: que el precio usado
  sea fresco (**>5 s → no se decide**), que la orden no se llene lejos (**priceBound**), que el stop exista desde el
  primer instante (**stopLossOnFill**, vive en OANDA aunque el VPS se caiga) y que el cierre forzado ocurra a tiempo.
- Camino corto: un solo proceso asyncio; stream HTTP de precios (no polling); un cliente HTTP con keep-alive (sin
  handshake TLS por orden, OANDA permite 2 conexiones nuevas/s); sin LLM en el camino; webhook que responde en <1 ms.
- Medición: cada orden guarda t_evento, t_proveedor, t_recepción, t_decisión, t_envío, t_ack y t_fill
  (`python -m fx latency`). `python -m fx check` mide RTT REST y llegada del stream; `python -m fx smoke --yes`
  (solo practice) abre y cierra 1 unidad para medir envío→ack real.
- VPS: Linux pequeño (1 vCPU, 1 GB) siempre encendido con NTP (chrony). Elige la región con menor RTT medido con
  `fx check` (prueba en este VPS al menos dos regiones de EE. UU. del este). El corpus es claro: el VPS es por
  disponibilidad, no para competir con los primeros segundos.

## TradingView

1. Pega `pine/FX_Agente_Slots.pine` en el editor de Pine, agrégalo a gráficas de 1 minuto de `OANDA:EURUSD`,
   `OANDA:USDJPY`, `OANDA:GBPUSD`, `OANDA:USDCHF` y `OANDA:USDMXN`. En la configuración pon el secreto.
2. Alerta → condición "FX-Agente: Any alert() function call" → Webhook URL `https://<tu-dominio>/tv`. Llega como
   `SIGNAL` y solo se registra para comparar lo que vio TradingView con lo que hizo el motor.
3. Alerta manual de pánico: mensaje `{"secret":"…","action":"FLATTEN","id":"{{timenow}}"}` → cierra todo.
4. Los webhooks de TradingView requieren plan de pago y 2FA (⚠️ verificar en tu cuenta). El agente funciona igual
   sin TradingView.

## Operación

```bash
python -m fx check                 # cuenta, RTT y stream (sin órdenes)
python -m fx run                   # motor + webhook (FX_MODE=paper|practice)
python -m fx monitor               # kill-switch independiente (practice/live)
python -m fx status | latency      # bitácora y latencias
python -m fx backtest --bars bars  # reproducir el backtest con la rama fx-data
```

**Compuerta para pasar de práctica a dinero real (decisión humana, F15-017 B):** mismo código y parámetros en
fxPractice ≥ 3 meses o ≥ 100 operaciones; diferencia de fills práctica vs backtest dentro de tolerancia (si no, se
recalibra el sobreprecio de OANDA y se repite el backtest); kill-switch probado (cierre total < 1 min); ninguna
semana peor que −1.5%; reconciliación diaria sin diferencias. Solo entonces un humano pone `FX_MODE=live` y
`FX_LIVE_CONFIRM=SI-ENTIENDO-EL-RIESGO` en el VPS.

## Datos y automatización

- Velas de 1 minuto **bid y ask** de Dukascopy 2015 → ayer, rama `fx-data` (`bars/{PAR}_{AÑO}.npz.xz`, delta +
  LZMA). Workflow `fx-data.yml`: `[fx-probe]` sonda, `[fx-data]` descarga, `[fx-repair]` reintenta días faltantes.
- `fx-backtest.yml` corre pruebas → walk-forward → publica `data/fx/BACKTEST.md`, `backtest.json` y `model.json`
  en `fx-agente`; el VPS baja `model.json` cada 6 h (`FX_MODEL_URL`).

## Regulación e impuestos en México (⚠️ verificar con un contador)

CONDUSEF/CNBV no autorizan brokers de forex en línea; operar con uno extranjero no es ilegal pero no hay protección
local (F15-016). OANDA Global Markets (BVI) acepta residentes en México. Fiscalmente las ganancias se tratarían
como intereses o ganancia patrimonial, a la tarifa anual, declaradas en abril, convertidas con el FIX de Banxico;
la bitácora del agente (append-only, con P&L y financiamiento por operación) sirve de soporte.

## Cambios declarados después de ver datos

(ninguno todavía)
