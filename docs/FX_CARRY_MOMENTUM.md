# Estrategia B — carry + momentum (pre-registro)

**Fijado el 19-oct-2026, antes de bajar o ver ningún dato de esta estrategia.** Cualquier cambio posterior se anota
al final con fecha y motivo, y cuenta como ensayo adicional en el DSR. Diseño de investigación, no recomendación.

Fuente: corpus FX F14-017 (Menkhoff et al. 2012; Asness-Moskowitz-Pedersen 2013; Lustig-Roussanov-Verdelhan 2011;
Moskowitz-Ooi-Pedersen 2012; Moreira-Muir 2017; BNP 2008). Las primas se publicaron antes de 2013, así que
2016–2026 es una prueba **posterior a la publicación**: ningún parámetro se ajusta con estos datos.

## Universo (13 monedas contra USD)
- **G10:** EUR, JPY, GBP, CHF, AUD, NZD, CAD, NOK, SEK.
- **Emergentes líquidos que flotan:** MXN, ZAR, PLN, HUF.
- **Fuera:**
  - pegs y bandas: HKD, SAR, DKK, CNH, SGD;
  - "freely falling": TRY, ARS;
  - CZK, que tuvo piso de 2013 a 2017.

## Datos
- **Precios:** velas de 1 hora bid/ask de Dukascopy, 2015 → último mes completo. Cierre diario = cierre de la vela
  que termina a las 17:00 NY.
- **Tasas:** tasas de política de cada banco central (BIS, diarias). Si BIS no responde: interbancaria a 3 meses
  de la OCDE vía FRED (mensual). Siempre se usa el dato publicado al menos 1 día hábil antes de la señal.
- **VIX:** FRED `VIXCLS`. Los percentiles se calculan con ventana expansiva desde 1990, solo con el pasado.

## Señales (con datos hasta el lunes 09:00 NY; ejecución al open de la vela de las 10:00 NY)
- **Carry transversal:**
  - carry_i = tasa_i − tasa_USD;
  - pesos ∝ (rango_i − rango medio), con Σ|w| = 1. Es neutral al dólar.
- **Momentum transversal (MOM2-12):**
  - retorno de la moneda contra USD de t−252 a t−21 días hábiles;
  - pesos por rango, igual que el carry.
- **Momentum en serie de tiempo:**
  - promedio de los signos de los retornos a 63, 126 y 252 días;
  - normalizado a Σ|w| = 1.
- **Momentum total:** 0.5 transversal + 0.5 serie de tiempo.
- **Combinación:** carry y momentum se escalan a la misma volatilidad ex-ante (covarianza EWMA, λ = 0.97, de
  retornos diarios) y se suman.

## Filtros de riesgo (solo restan)
- **Carry según el VIX:**
  - por encima de su percentil 80 → carry × 0.5;
  - por encima del 95 → carry × 0.
- **Carry tras una mala semana:** si el factor carry perdió más de 2σ semanales la semana previa → carry × 0.
- **Emergentes en fin de semana:** el viernes a las 15:00 NY, las posiciones en MXN/ZAR/PLN/HUF bajan 25%. Se
  restauran en el rebalanceo del lunes.
- **Calendario:** no se rebalancea del 24-dic al 2-ene ni en los 2 últimos días hábiles de cada trimestre. Se
  mantiene lo que había.

## Tamaño y límites
- **Volatilidad objetivo del portafolio σ\* = 4% anual** (covarianza EWMA λ = 0.97).
  - Va por debajo del 8–10% del corpus por el tope semanal de Sergio. Con σ\* = 4%, una pérdida de −1.5% en la
    semana equivale a ~2.6σ.
- **Topes de exposición:** apalancamiento bruto ≤ 5×, |posición por moneda| ≤ 1.0× capital y |USD neto| ≤ 3×.
- **Banda de no-operar:** solo se ajusta una moneda si el cambio es > 20% de su objetivo y > 10% del capital en
  nocional. Las posiciones menores a 2% del capital se cierran.
- **Gobernador semanal −1.5%:**
  - marca a mercado cada hora;
  - si se toca, todo se cierra al open de la vela siguiente;
  - queda plano hasta el rebalanceo del lunes siguiente.
- **Tope diario:** −1% en el día FX → todo plano hasta el lunes siguiente.
- **Drawdown desde el máximo:** 4% (1σ\*) → objetivo × 0.5; 8% (2σ\*) → apagado.
- **Sin stops por operación:** el carry pierde por saltos y el control es por tamaño y drawdown (F14-017).

## Costos
- **Spread real:** bid/ask de Dukascopy en la vela de ejecución.
- **Sobreprecio OANDA estimado por lado:**
  - EUR, JPY, GBP, CHF: 0.5 pb;
  - AUD, NZD, CAD: 0.8 pb;
  - NOK, SEK: 2 pb;
  - MXN, ZAR, PLN, HUF: 3 pb.
- **Financiamiento diario:** (tasa_moneda − tasa_USD) × posición, menos un recargo OANDA estimado de 1.0% anual
  sobre el nocional. Hay que verificarlo contra las tasas de financiamiento que muestra OANDA.
- **Estrés:** costos × 2 y recargo × 2.

## Evaluación y criterio de uso (fijados hoy)
- **Periodo:** ene-2016 → último mes completo (2015 es calentamiento del momentum de 12 meses).
- **Se reporta:**
  - por semana: % de semanas positivas, peor semana, racha negativa y semanas peores que −1.5%;
  - Sharpe, PSR y drawdown;
  - por eras: 2016–2019, 2020–2021, 2022–2024, 2025–2026;
  - cada factor por separado;
  - DSR con N = 3 (combinado, solo carry, solo momentum) más los cambios que se declaren.
- **Se opera en práctica solo si se cumplen todos:**
  - Sharpe neto con costos base > 0.3 y PSR(SR > 0) ≥ 0.80;
  - retorno positivo con costos × 2;
  - drawdown máximo < 8%.
- **Si no se cumple:** no se opera y se reporta tal cual.

## Cambios posteriores
(ninguno)
