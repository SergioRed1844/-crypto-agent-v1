---
name: radar-eb-model
description: Radar EB (agente 2, solo alertas) — setups de compra del corpus de microcomportamientos, modelo de Bayes empírico jerárquico (logit Normal-Normal + Beta-Binomial + Poisson-Gamma), regla de alerta (relativo por defecto), canales (issue/Gmail/CallMeBot) y validación fuera de muestra. Cárgala al editar radar/*, data/radar/*, los workflows radar-*.yml o al juzgar si el Radar "tiene ventaja".
---

# Radar EB — contrato

1. **Solo alerta, nunca opera.** Sin llaves de exchange. Lo que se cambie aquí no puede tocar `app/` (bot v4.2).
2. **Comparador honesto:** toda probabilidad se reporta contra "comprar un día cualquiera del último año" del mismo
   activo (`local_base`, encogida hacia la tasa del periodo con K0=4). Una P alta sin ventaja no es oportunidad.
3. **Prior escéptico centrado en cero** (McLean-Pontiff, C02-011): τ² entre setups por momentos con todos los
   setups (James-Stein) × w/w̄ del corpus (el corpus reparte, en promedio conserva la τ² de los datos). w = peso E (C11-004) × decaimiento (C11-006) × aplicabilidad (C11-007).
4. **Episodios independientes:** disparos en varios activos con ≤3 días de diferencia son UN episodio (`clusters`).
   Nunca contar instancias correlacionadas como n.
5. **Sin mirar al futuro:** setups con información ≤ cierre t; compra a la apertura de t+1; σ excluye el día t;
   Wikipedia con rezago 1 día; tasa base local solo con resultados realizados en t. Hay pruebas para cada cosa.
6. **Regla por defecto `relativo`:** q10 > base local, ventaja ≥5 pp, neto ≥3%, ≥8 episodios. Una P absoluta
   (selectivo, 65%) es casi inalcanzable con metas netas: no volver a ella sin re-validar.
7. **Todo veto/ajuste solo RESTA** (euforia, daño fundamental, GSY ≥150% a 90 d, CAUTION +5 pp, Gemini causa
   fundamental → VIGILANCIA). Nada sube una señal fuera del modelo.
8. **Calendario (día de la semana) se encoge fuerte** (w=0.16, piso 2000·(1−w)): solo desempate.
9. **Umbrales y setups fijados el 18-oct-2026 antes de ver datos.** Cambiarlos después de ver el backtest es
   data-mining (C11-009 B): si se cambia, se declara en docs/RADAR_EB.md con fecha y motivo, y se re-valida.
10. Yahoo con `range=max` devuelve barras mensuales en historias largas: usar `period1/period2` y `check_daily`.

## Archivos
`radar/setups.py` (setups/vetos) · `radar/eb.py` (matemáticas) · `radar/model.py` (jerarquía, decide) ·
`radar/backtest.py` (fuera de muestra) · `radar/pipeline.py` (corrida horaria, tope semanal, resumen) ·
`radar/report.py` (ficha C11-025) · `radar/notify.py` (canales; nunca registrar URLs con apikey) ·
`docs/RADAR_EB.md` (método) · `data/radar/BACKTEST.md` (resultados reales).

## Probar
`python -m tests.test_radar` (sin red) · `python -m radar backtest` / `python -m radar scan --dry` (con red, en Actions).
