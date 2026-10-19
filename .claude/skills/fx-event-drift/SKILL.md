---
name: fx-event-drift
description: Agente FX (agente 3, opera en OANDA v20) — Estrategia A del corpus FX (reacción de 15 min a datos macro y drift posterior), detección de sorpresa por z del precio, Bayes empírico por (par, slot), motor de riesgo con gobernador semanal −1.5%, ejecución OANDA/paper, webhook de TradingView, latencia y monitor. Cárgala al editar fx/*, tests/test_fx.py, pine/FX_Agente_Slots.pine, deploy/fx/* o los workflows fx-*.yml, o al juzgar si el agente FX "tiene ventaja".
---

# Agente FX — contrato

1. **Modo.** `FX_MODE=paper` por defecto; `practice` = cuenta demo de OANDA. Claude nunca pone `live` ni
   `FX_LIVE_CONFIRM`: eso lo hace un humano tras la compuerta de práctica (≥100 operaciones o 3 meses, fills vs
   backtest dentro de tolerancia, F15-017 B). `OandaBroker("live")` y `config.mode()` lo vuelven a exigir.
2. **La señal no depende de TradingView.** El motor decide con su reloj y el stream de OANDA. El webhook solo acepta
   FLATTEN / PAUSE / RESUME / CHECK / SIGNAL (telemetría). Nunca agregar una acción que abra operaciones.
3. **Sin mirar al futuro.** σ_slot = 1.4826·mediana|ret15| de los 250 días hábiles PREVIOS; entrada al open del
   minuto T0+15; salida al open del minuto de salida; stop revisado con mínimo bid / máximo ask; gap → fill al open.
4. **Costos reales.** Spread bid/ask de Dukascopy cruzado + sobreprecio OANDA estimado (`Pair.oanda_markup_pips`)
   + deslizamiento por lado. Siempre reportar también ×2. Recalibrar el sobreprecio con fills de práctica.
5. **EB escéptico.** Prior N(0, τ²) por variante (DL con tope), errores agrupados por día (los pares de un slot
   comparten el dato), umbral P(μ>0) ≥ 1 − 0.2/√12 = 0.942 por elegir la mejor de 12 variantes.
6. **Rejilla fijada el 19-oct-2026 antes de ver datos:** z ∈ {2, 3}, horizonte ∈ {60, 120, 360} min, dirección
   ∈ {momentum, reversión}, slots de `config.SLOTS`. Cambiarla tras ver el backtest es data-mining: se declara en
   `docs/FX_AGENTE.md` con fecha y motivo, se sube N en el DSR y se re-valida.
7. **Límites duros (`config.HARD`) inmutables:** ≤0.5% por evento, semanal ≤1.5%, diario ≤2%, DD rojo ≤10%,
   apalancamiento ≤5×, pausa tras ≤3 pérdidas. El gobernador semanal además limita cada operación al 90% de lo que
   queda del tope contando el riesgo abierto: solo gaps/deslizamiento pueden rebasarlo.
8. **Blackouts:** fix de Londres ±2.5 min, rollover 16:50–17:10 NY (salida forzada 16:50), viernes 15:55 NY,
   24-dic a 2-ene, T−5/T+5 de eventos confirmados con hora del calendario v4.2. Solo restan.
9. **Latencia:** un cliente keep-alive, MARKET FOK con `priceBound`, `stopLossOnFill` en el broker, relojes
   t_evento/t_proveedor/t_recepción/t_decisión/t_envío/t_ack/t_fill en la bitácora (`python -m fx latency`).
   Precio > 5 s de viejo → no se decide. El VPS es por disponibilidad, no para ganar la carrera de los segundos.
10. **Monitor aparte** (`python -m fx monitor`): NAV del broker, solo cierra y escribe `KILL`; el motor lo respeta.
11. **Nunca prometer ganancia semanal.** Reportar % de semanas positivas, peor semana y DSR/PBO tal cual.

## Archivos
`fx/config.py` · `fx/calendar.py` · `fx/data_dukascopy.py` · `fx/events.py` · `fx/model.py` · `fx/risk.py` ·
`fx/backtest.py` · `fx/broker.py` · `fx/engine.py` · `fx/monitor.py` · `fx/webhook.py` · `fx/store.py` ·
`fx/__main__.py` · `pine/FX_Agente_Slots.pine` · `deploy/fx/*` · `docs/FX_AGENTE.md` · `data/fx/BACKTEST.md`.
Datos: rama `fx-data` (`bars/{PAR}_{AÑO}.npz.xz`, workflow `fx-data.yml`: `[fx-probe]`, `[fx-data]`, `[fx-repair]`).
Pruebas: `python -m tests.test_fx` (sin red).
