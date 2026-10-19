# Radar EB — agente 2 (solo alertas)

**Qué es:** un vigía que corre cada hora sobre **cripto, EUA y BMV**. Busca "grandes oportunidades de compra"
definidas por el corpus *Microcomportamientos y mercados* (18-oct-2026) y estima con **Bayes empírico** qué tan
seguido funcionaron en la historia. Cuando una pasa el umbral **Selectivo**, te manda una ficha.
**No opera:** no tiene llaves de exchange, no envía órdenes y no toca el bot v4.2.

## Flujo

```
precios (Binance data-api · Yahoo · Stooq · FRED csv) + Fear&Greed + VIX + USD/MXN
+ atención y miedo de hogares (Wikipedia, proxy de Google/FEARS)
+ eventos curados v4.2 + context_signal.json v4.2
        │
        ▼
setups del corpus (radar/setups.py) ── vetos/avisos de riesgo (GSY, euforia, daño fundamental)
        │
        ▼
modelo EB (radar/model.py + radar/eb.py) → P(ganar ≥ meta neta), rendimiento neto esperado,
riesgo de caída, mejor ventana de entrada, día de la semana
        │
        ▼
regla Selectivo → ALERTA / VIGILANCIA / VETADA → verificación de noticias con Gemini (solo puede RESTAR)
        │
        ▼
issue de GitHub (te llega por correo) · Gmail SMTP · WhatsApp (CallMeBot) · resumen diario 8:00 CDMX
```

## Setups (fijados el 18-oct-2026, antes de ver datos)

| Setup | Disparo (cierre de la barra t, solo información ≤ t) | Corpus | E | Decaimiento | Aplicabilidad |
|---|---|---|---|---|---|
| Pánico sin daño real | activo ≤ −2.5σ60 **y** mercado ≤ −2σ60 **y** miedo (F&G ≤ 35 o −15 en 3 días; VIX ≥ 1.25× su media de 20 días) **y** ningún evento de quiebra/hackeo en [t−3, t] | C08-006, C12-013, C12-017, C12-008 | E3 | ×0.6 | EUA 1.0 · cripto 0.7 · BMV 0.7 |
| Capitulación | caída desde el máximo de 1 año (cripto −50%; ETF −20%; acción EUA −35%, BMV −30%) **y** RSI14 < 30 **y** miedo extremo (F&G ≤ 20; VIX > 25 o mercado −15%) | C12-013, C09-018, C13-014, C12-007 | E4 | ×0.4 (1985) | EUA 1.0 · cripto 0.7 · BMV 0.8 |
| Choque político/comercial | evento curado TRADE/GEOPOLITICAL/ELECTION/GOV_TRANSITION/FISCAL en [t−2, t] **y** mercado ≤ −1.5σ **y** activo ≤ −1.5σ | C13-016, C12-007, C13-014 | E4 | ×0.6 | EUA 1.0 · cripto 0.7 · BMV 0.8 |
| Miedo de hogares | FEARS-Wikipedia (en/es) z ≥ 2 contra 90 días **y** mercado −3% en la semana (solo índices/ETF) | C08-012, C12-013 | E5 | ×0.6 | EUA 0.7 · BMV 0.5 |
| Choque del peso | USD/MXN ≥ +2.5σ en el día o +4% en 5 días **y** la emisora −3% en 5 días | C13-016, C09-018, C11-007 | E5 | ×0.8 | BMV 1.0 |
| Atención + momentum (cripto) | retorno semanal z ≥ 1 **y** atención Wikipedia z ≥ 1 **y** F&G < 75 | C13-013, C16-006 | E4 | ×0.8 | cripto 0.8 |
| Retroceso en tendencia | precio > SMA200 y SMA50 > SMA200, −15/−8/−5/−6% desde el máximo de 20 días, sin romper la SMA50 | **fuera del corpus** (Moskowitz-Ooi-Pedersen 2012) | E4 | ×0.6 | 0.8 |

**Peso de evidencia** w = peso base E (C11-004: E1 .7, E2 .9, E3 .85, E4 .6, E5 .4, E6 .35, E7 .15) × decaimiento
post-publicación (C11-006) × aplicabilidad a la clase (C11-007). w **no** es una probabilidad: solo fija qué tan
escéptico es el prior.

**Cooldown por activo** (5–30 barras): cada disparo es un episodio independiente.

## Modelo (Bayes empírico jerárquico, skill de Vidakovic)

Éxito = ganancia **neta** de costos ≥ meta al cierre del horizonte: 7 días ≥ 1.5%, 30 días ≥ 3%, 90 días ≥ 5%.
Se compra a la **apertura del día siguiente** al disparo. Los costos de ida y vuelta son estimaciones: cripto 0.3%,
EUA 0.2%, BMV 0.6%.

1. **Nivel 0 — tasa base del activo** b_a,h: comprar un día cualquiera (todas las barras). Es el comparador honesto.
2. **Nivel 1 — ventaja del setup en la clase**, en escala logit: δ̂ = logit(p̂) − logit(b̄).
   - p̂ se calcula sobre **episodios independientes**: los disparos de varios activos con ≤ 3 días de diferencia
     cuentan como uno solo. Así el BTC y sus altcoins cayendo juntos no inflan n.
   - **Prior escéptico** N(0, τ0²) centrado en "sin ventaja" (McLean-Pontiff, C02-011).
   - τ² se estima por momentos con **todos** los setups (James-Stein, skill §4.4): τ² = mean(δ̂² − v).
   - El corpus lo reparte entre setups: τ0² = τ² · 2w.
   - Posterior Normal-Normal. B es la fracción encogida hacia cero.
3. **Nivel 2 — activo dentro del setup.** La heterogeneidad entre activos se estima con **DerSimonian-Laird**
   (momentos ponderados por precisión).
   - Exige ≥ 5 activos con ≥ 3 disparos.
   - Tiene un tope: un activo no puede desviarse más de lo que varían los setups entre sí.
   - Con pocos datos el activo hereda la ventaja del setup (pooling completo).
4. **Rendimiento neto esperado:** la misma jerarquía, en escala natural, sobre el exceso respecto al rendimiento
   medio del activo. Se winsoriza al 0.5% / 99.5% de la clase.
5. **Riesgo de caída:** P(peor punto durante la tenencia ≤ −15% cripto / −10% bolsa), con Jeffreys sobre episodios.
6. **Frecuencia:** Poisson-Gamma PEB por momentos (skill §4.2), en veces por año por activo.

### "Mejor día de compra"

- **Ventana de entrada t+1, t+2, t+3, t+5 o t+8 después del disparador.**
  - Se modela con Beta-Binomial por momentos entre ventanas, como el ejemplo del agua de la skill (§4.2).
  - El prior tiene un piso de concentración 50·(1−w).
  - Solo se recomienda esperar si esa ventana tiene P(mejor) ≥ 50% y ≥ +2 pp sobre entrar al día siguiente.
- **Día de la semana:** Beta-Binomial entre días.
  - Usa un dato por fecha (promedio entre activos de la clase), así que las entradas no se traslapan.
  - El corpus dice que los efectos de calendario están erosionados (C08-008, C11-006). Por eso
    w = E5 × 0.4 = 0.16 y el piso de concentración es 2000·(1−w) ≈ 1680, lo que da un encogimiento muy fuerte.
  - Si la diferencia encogida es < 0.5 pp, el Radar dice que ningún día destaca. **Solo sirve como desempate.**

## Regla de alerta (por defecto **relativo**; `RADAR_RULE=relativo|estricta|selectivo`)

- **relativo:** ALERTA si se cumplen todas:
  - la ventaja sobre comprar un día cualquiera es creíble: la cota baja de la probabilidad, con la tasa base fija, es
    ≥ base (≈ 90%);
  - la ventaja es de ≥ +5 pp;
  - el neto esperado supera al de un día cualquiera por ≥ 1 pp;
  - ≥ 8 episodios independientes;
  - ningún veto.
- **estricta:** como relativo, pero con neto esperado ≥ 3% absoluto. A 7 días casi nunca se cumple: 0 alertas en la
  prueba.
- **selectivo:** P ≥ 65% y q10 ≥ 55% absolutos. Es inalcanzable con metas netas, porque la tasa base es de 25–45%.

La probabilidad es de ganar **al menos la meta neta**, no solo "subir". Por eso se ve baja (30–50%). La ficha también
muestra cuántos episodios pasados terminaron con neto > 0 (dato crudo) y P(ventaja > 0).

En todas las reglas:
- Máximo 3 alertas por semana. Las demás pasan al resumen como VIGILANCIA.
- La misma combinación de activo y setup no se repite antes de 7 días.

**Vetos y ajustes. Todos restan; ninguno suma:**

- euforia cripto (F&G ≥ 80; C16-006, el semáforo rojo);
- evento curado de quiebra o hackeo;
- run-up ≥ 150% neto en 2 años, solo para el horizonte de 90 días (GSY 2019, C15-011);
- alerta on-chain crítica del v4.2.
- Si el v4.2 está en CAUTION, se exigen +5 pp.
- Si el v4.2 está en RISK_OFF o BLACKOUT, la confianza máxima es Media. **No es veto:** el Radar busca
  precisamente pánicos, y la decisión es tuya.
- **Gemini con búsqueda** solo revisa los candidatos que ya pasaron los números. Si la causa probable es
  fundamental y propia del activo, la alerta baja a VIGILANCIA. Nunca sube nada.

**Confianza** (C11-008 y C11-025, con la cuenta visible en la ficha):

- **Alta:** ≥ 3 familias independientes (precio, miedo de mercado, atención de hogares, noticias sin daño),
  w ≥ 0.45, ≥ 30 episodios y q10 por encima de la base.
- **Media:** w ≥ 0.25 y ≥ 15 episodios.
- **Baja:** todo lo demás.

## Canales (todos gratis; tú pones los secrets, el código nunca los imprime)

| Canal | Secrets | Nota |
|---|---|---|
| Issue de GitHub → correo | ninguno (usa el token de Actions) | Activo por defecto. El repo es público: las alertas se ven ahí |
| Gmail privado | `RADAR_SMTP_USER`, `RADAR_SMTP_PASS` (contraseña de aplicación), `RADAR_EMAIL_TO` (opcional) | HTML con tablas |
| WhatsApp | `CALLMEBOT_PHONE`, `CALLMEBOT_APIKEY` | Texto corto; la ficha completa va por correo |
| Noticias | `GEMINI_API_KEY` (ya existe) | Solo puede bajar el nivel de una alerta |
| Resultados trimestrales | `FINNHUB_API_KEY` (gratis, 60 llamadas/min) | Acción de EUA que reporta en ≤ 3 días → VIGILANCIA; si no, se informa la fecha |

## Límites conocidos (honestos)

- Wikipedia es **proxy** de Google Trends/FEARS. Para México es una hipótesis (C08-012).
- Las vistas se usan con rezago de 1 día.
- No hay flujos de ETF. El calendario de resultados solo existe para acciones de EUA y solo si se agrega
  `FINNHUB_API_KEY`; en la BMV revísalo tú (está en "siguiente verificación").
- Los eventos políticos históricos son los ~260 curados del v4.2, así que el setup de choque político tiene pocos
  episodios. Por eso sale ancho y encogido.
- 7 setups × 3 clases × 3 horizontes ≈ 50 especificaciones probadas. Algún "ganador" puede ser azar
  (C11-009 B), y la validación fuera de muestra (`data/radar/BACKTEST.md`) es la que manda.
- El tope semanal no se simula en el backtest.
- Las vistas de USD/MXN de Yahoo cierran ~2 h después que la BMV (fuga menor, irrelevante a 30–90 días).
- **No es asesoría financiera.** Son frecuencias históricas encogidas, no garantías.

## Archivos

- `radar/` contiene el código:
  - `config.py`: universo, costos, metas, umbrales;
  - `data.py`: fuentes y caché;
  - `setups.py`: setups y vetos;
  - `eb.py`: matemáticas;
  - `model.py`: jerarquía y decisión;
  - `backtest.py`: validación fuera de muestra;
  - `report.py`: fichas y resumen;
  - `notify.py`: canales;
  - `narrative.py`: Gemini;
  - `pipeline.py`: corrida.
- `data/radar/` contiene:
  - `README.md`: tablero;
  - `state.json`: alertas, seguimiento y salud;
  - `fichas/`;
  - `ULTIMO_RESUMEN.md`;
  - `model.json`;
  - `BACKTEST.md`.
- Workflows:
  - `radar-scan.yml`: cada hora, más el heartbeat;
  - `radar-backtest.yml`: al cambiar el modelo y una vez al mes.
- `tests/test_radar.py` tiene 36 pruebas sin red: matemáticas, sin mirar al futuro, efecto sembrado vs nulo,
  canales y corrida completa.
- `radar/corpus_refs.json` es un índice mínimo del corpus (solo títulos y etiquetas). **El corpus completo no se
  publica** porque el repo es público.

## Cambios declarados después de ver datos (regla anti data-mining, C11-009 B)

Los setups y sus umbrales se fijaron el 18-oct-2026, antes de ver resultados. El 19-oct, después del primer backtest
con datos reales, hubo estos cambios:

1. **Corrección de datos, no de modelo.**
   - Yahoo con `range=max` devolvía barras mensuales en historias largas: AAPL, BMV y otros quedaban fuera, y los
     ETF de EUA salían mensuales.
   - Ahora se usan `period1/period2` y `check_daily`.
2. **Comparador.** Se pasó de la tasa base de todo el periodo a la tasa base local del último año, encogida hacia la
   del periodo con K0 = 4.
   - Motivo: los setups se agrupan en ciertos regímenes. Las capitulaciones caen en mercados bajistas, y compararlas
     contra la tasa de un mercado alcista mezclaba régimen con setup.
3. **Prior del corpus.** Se pasó de τ²·2w a τ²·w/w̄, que es lo que dice este documento: el corpus reparte, no encoge
   de más. Con w̄ ≈ 0.29, la versión 2w encogía todo hacia cero.
4. **Regla por defecto.** Se pasó de "selectivo" a "relativo". La meta neta hace inalcanzable una P absoluta de 65%.

Para llegar aquí se probaron 2 variantes de prior × 3 reglas sobre el mismo periodo de prueba, así que hay riesgo de
sobreajuste. Las tres reglas se siguen reportando en `BACKTEST.md`, y el seguimiento en vivo de las alertas
(`state.json`) es la prueba que de verdad cuenta.

### Segunda ronda (19-oct, después de la revisión independiente)

Correcciones de sobre-confianza:

- **Tasa base local.** La mezcla del último año con el largo plazo ya no usa K0 = 4 fijo. Ahora λ se **estima** con el
  periodo de ajuste: cuánto de la desviación del último año se sostiene en el semestre siguiente.
  - Resultado: λ ≈ 0 en cripto, 0–0.3 en EUA y 0.06–0.47 en BMV. La tasa reciente casi no se sostiene.
  - La varianza de ese pronóstico entra al intervalo que se muestra. **No entra a la decisión**, que solo mira la
    incertidumbre de la ventaja.
- **Episodios independientes.** Los disparos a menos de min(h, 30) días son un solo episodio, en la clase y también
  dentro de cada activo. Antes eran 3 días, y las tenencias de 30 y 90 días se traslapaban.
- **Purga en el corte.** El entrenamiento solo usa resultados cuya salida es anterior al corte.
- **Activo sin disparos propios.** Hereda la ventaja del setup, con varianza extra.
- **USD/MXN.** Va con rezago de un día de mercado, porque su barra cierra a medianoche de Londres, después de la BMV.
- **Caché.** La descarga completa ahora es diaria de verdad (`full_utc`), y se repite si el traslape no empata
  (splits).
- **Gemini.** Ya no suma "familias" ni confianza, y sus enlaces se eliminan.

Con eso, la regla "relativo" con neto ≥ 3% absoluto ya no daba ninguna alerta. Se cambió a **neto ≥ +1 pp sobre un
día cualquiera** (la misma lógica relativa). En la prueba (2022–oct 2026) quedó así:

- 17 alertas en 10 episodios, ~3.5 al año, casi todas acciones/ETF de EUA (pánico sin daño a 30 días y capitulación a
  7 días);
- 59% llegaron a la meta, contra 31% de un día cualquiera;
- neto medio +2.2% contra +0.5%, mediana +3.2%;
- 65% terminaron en positivo;
- peor caída durante la tenencia −12%.

Es la segunda vez que se elige una regla mirando el mismo periodo de prueba. Esas cifras son optimistas: el juez real
es el seguimiento en vivo.
