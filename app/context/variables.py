"""Registro formal de variables del modelo de contexto (fuente única: la doc se genera de aquí).

Roles:
  dependiente  → lo que queremos explicar/predecir (reacción de BTC)
  independiente→ atributos del evento y del mercado que explican Y
  moderadora   → cambian el TAMAÑO o el SIGNO del efecto X→Y (no lo causan)
  mediadora    → canal por el que X llega a Y (macro → bolsa/dólar → BTC)
  control      → se fijan o se descuentan para no confundir el efecto
  constante    → reglas fijas del sistema (no se estiman)
Tipos: continua | discreta_atributo (nominal) | discreta_conteo | ordinal | binaria
"""

V = []


def _v(key, role, kind, desc, source, freq, used_in, unit=""):
    V.append({"key": key, "role": role, "kind": kind, "desc": desc, "unit": unit, "source": source,
              "freq": freq, "used_in": used_in})


# ── Dependientes (Y) ──────────────────────────────────────────
_v("ar_z_h", "dependiente", "continua", "Retorno anormal de BTC a h días (1/3/7/30) desde el cierre previo al evento, "
   "menos el drift de 90 días, dividido entre la vol de 90 días·√h", "Coin Metrics (2010+) / Binance", "diaria",
   "event_study", "z")
_v("abs_ar_z_h", "dependiente", "continua", "Magnitud |z|: cuánto mueve, sin importar la dirección (riesgo)",
   "derivada", "diaria", "event_study → blackout y tamaño", "z")
_v("vol_ratio_7d", "dependiente", "continua", "Vol realizada 7 días después / 30 días antes", "derivada", "diaria",
   "event_study", "x")
_v("alt_ar_z_h", "dependiente", "continua", "Retorno anormal de ETH y SOL (beta de altcoins al evento)",
   "Binance 1d", "diaria", "event_study (secundario)", "z")
_v("trade_R", "dependiente", "continua", "Resultado por operación del modelo de trading en múltiplos de riesgo (Y final)",
   "store / backtest", "por trade", "backtest de variantes", "R")

# ── Independientes: atributos cualitativos discretos (X) ──────
_v("category", "independiente", "discreta_atributo", "Tipo de evento (18 categorías)", "calendario / clasificador",
   "por evento", "pesos por categoría")
_v("subcategory", "independiente", "discreta_atributo", "Subtipo (FOMC, CPI, PRESIDENTIAL, SATOSHI_ERA…)",
   "calendario / clasificador", "por evento", "dedup y reportes")
_v("country", "independiente", "discreta_atributo", "País o bloque (ISO-2, EU, GLOBAL)", "calendario", "por evento",
   "ponderación por PIB")
_v("crypto_stance", "independiente", "discreta_atributo", "Postura frente a cripto del resultado: pro / anti / neutral "
   "(da el SIGNO esperado)", "investigación / LLM", "por evento", "sesgo direccional")
_v("scheduled", "independiente", "binaria", "¿La fecha se conocía antes? (programado vs sorpresa)", "calendario",
   "por evento", "blackout solo aplica a programados")
_v("surprise", "independiente", "ordinal", "expected < partial < surprise", "investigación / LLM", "por evento",
   "event_study")
_v("status", "independiente", "ordinal", "confirmed > scheduled_estimate > expected > speculative → P(ocurra)",
   "calendario", "por evento", "riesgo de evento a futuro")
_v("prior_tier", "independiente", "ordinal", "Importancia a priori 1–5 (juicio experto)", "investigación",
   "por evento", "prior del encogimiento bayesiano")
_v("onchain_type", "independiente", "discreta_atributo", "SATOSHI_ERA / EARLY_MINER / DORMANT_WHALE", "vigía on-chain",
   "por bloque", "alertas")

# ── Independientes: conteos ───────────────────────────────────
_v("news_count_24h", "independiente", "discreta_conteo", "Titulares del tema en 24 h (intensidad de atención)",
   "GDELT / CryptoPanic", "horaria", "clasificador (urgencia)")
_v("important_votes", "independiente", "discreta_conteo", "Votos 'important' en CryptoPanic", "CryptoPanic",
   "horaria", "clasificador (urgencia)")
_v("events_30d_same_cat", "independiente", "discreta_conteo", "Eventos de la misma categoría en 30 días "
   "(acumulación de choques)", "historia", "diaria", "sesgo (decaimiento)")
_v("countries_affected", "independiente", "discreta_conteo", "Países afectados por el evento", "LLM", "por evento",
   "reporte")

# ── Independientes: cuantitativas continuas ───────────────────
_v("gdp_share_pct", "independiente", "continua", "Peso del país en el PIB mundial nominal", "FMI WEO", "anual",
   "tier de elecciones/gobiernos", "%")
_v("ex_ante_prob", "independiente", "continua", "Probabilidad del resultado ANTES del evento (evita sesgo de "
   "retrospectiva: lo 'evidente' ya estaba en el precio)", "Polymarket / Kalshi", "diaria", "sorpresa = resultado − prob", "0–1")
_v("surprise_z", "independiente", "continua", "(Dato − consenso) / desviación histórica de sorpresas",
   "FairEconomy (consenso) + FRED (dato)", "por publicación", "signo de MACRO_DATA", "z")
_v("rate_change_bps", "independiente", "continua", "Cambio de tasa decidido", "bancos centrales", "por reunión",
   "signo de MONETARY_POLICY", "pb")
_v("btc_years_moved", "independiente", "continua", "BTC movidos × años dormidos", "vigía on-chain", "por bloque",
   "severidad de alertas", "BTC·años")
_v("news_tone", "independiente", "continua", "Tono promedio de la cobertura", "GDELT", "diaria", "clasificador")
_v("fear_greed", "independiente", "continua", "Índice de miedo y codicia (también moderadora por zonas)",
   "alternative.me", "diaria", "agente derivados + moderadora", "0–100")
_v("funding_rate", "independiente", "continua", "Funding de perpetuos (apalancamiento de la multitud)",
   "Binance futures", "8 h", "agente derivados", "%/8h")
_v("open_interest_chg", "independiente", "continua", "Cambio de interés abierto 24 h", "Binance futures", "horaria",
   "agente derivados", "%")
_v("dxy_20d_pct", "independiente", "continua", "Cambio 20 días del dólar amplio", "FRED DTWEXBGS", "diaria",
   "sesgo de mercado", "%")
_v("vix", "independiente", "continua", "Volatilidad implícita del S&P 500", "FRED VIXCLS", "diaria",
   "estado CAUTION", "pts")
_v("nasdaq_20d_pct", "independiente", "continua", "Cambio 20 días del Nasdaq Composite", "FRED NASDAQCOM", "diaria",
   "sesgo de mercado", "%")
_v("us10y_20d_bps", "independiente", "continua", "Cambio 20 días del bono a 10 años", "FRED DGS10", "diaria",
   "sesgo de mercado", "pb")
_v("stablecoin_30d_pct", "independiente", "continua", "Cambio 30 días de la oferta total de stablecoins (liquidez cripto)",
   "DefiLlama", "diaria", "sesgo de mercado", "%")
_v("etf_flow_5d_usd", "independiente", "continua", "Flujo neto 5 días de ETFs spot de BTC", "Farside / SoSoValue",
   "diaria", "sesgo de mercado", "USD")

# ── Moderadoras (Z) ───────────────────────────────────────────
_v("btc_regime", "moderadora", "ordinal", "Tendencia diaria de BTC: GREEN / YELLOW / RED. En RED las malas noticias "
   "pegan más; en GREEN las buenas", "Binance 1d", "por vela", "multiplicador del sesgo")
_v("vol_regime", "moderadora", "ordinal", "Vol 30 d: LOW / NORMAL / HIGH / EXTREME", "Binance 1d", "diaria",
   "multiplicador del riesgo de evento")
_v("fear_greed_zone", "moderadora", "ordinal", "≤20 miedo extremo / 20–80 / ≥80 codicia extrema: con codicia extrema "
   "una noticia mala pega más", "alternative.me", "diaria", "multiplicador del sesgo")
_v("leverage_zone", "moderadora", "ordinal", "Funding alto = multitud apalancada (cascadas de liquidación)",
   "Binance futures", "8 h", "veto del agente derivados")
_v("halving_phase", "moderadora", "continua", "Días desde el último halving (fase del ciclo de 4 años)", "calendario",
   "diaria", "reporte (pendiente de evidencia)", "días")
_v("btc_nasdaq_corr_30d", "moderadora", "continua", "Correlación 30 d BTC–Nasdaq: si es alta, los eventos macro "
   "de EE.UU. pesan más", "Binance + FRED", "diaria", "reporte (pendiente de evidencia)", "ρ")
_v("weekend_liquidity", "moderadora", "binaria", "Fin de semana / feriado de EE.UU.: liquidez delgada", "reloj",
   "horaria", "reporte")

# ── Mediadoras (M) ────────────────────────────────────────────
_v("risk_assets_reaction", "mediadora", "continua", "Reacción del Nasdaq y del dólar el mismo día: canal por el que la "
   "Fed o los aranceles llegan a BTC", "FRED", "diaria", "estudio de eventos (diagnóstico)", "%")

# ── Controles y constantes (C) ────────────────────────────────
_v("baseline_drift_vol_90d", "control", "continua", "Drift y vol de 90 días previos (se restan para obtener el "
   "retorno ANORMAL)", "derivada", "diaria", "event_study")
_v("day_of_week", "control", "discreta_atributo", "Día de la semana del evento", "reloj", "diaria", "event_study")
_v("random_day_baseline", "control", "continua", "Distribución de |z| en días al azar: un evento solo 'pesa' si mueve "
   "más que un día cualquiera", "derivada", "por recálculo", "p-value por categoría")
_v("universe", "constante", "discreta_atributo", "BTC, ETH, SOL (spot, solo largos)", "config", "fija", "trading")
_v("fees_slippage", "constante", "continua", "Comisión 0.1% por lado + slippage 0.05%", "config", "fija",
   "filtro de ganancia neta", "%")
_v("hard_limits", "constante", "discreta_atributo", "Kill −3% día / −5% semana, ≤5% exposición, ≤0.5% riesgo, "
   "5 pérdidas seguidas, 1 posición por par, BNB bloqueado", "config", "inmutable", "risk_gate")
_v("event_windows", "constante", "discreta_atributo", "Base = cierre del día previo; h = 1, 3, 7, 30 días; UTC",
   "event_study", "fija", "event_study")


def by_role() -> dict:
    out = {}
    for v in V:
        out.setdefault(v["role"], []).append(v)
    return out


def markdown() -> str:
    rows = ["| Variable | Rol | Tipo | Qué mide | Fuente | Frecuencia | Dónde se usa |", "|---|---|---|---|---|---|---|"]
    for role in ("dependiente", "independiente", "moderadora", "mediadora", "control", "constante"):
        for v in by_role().get(role, []):
            u = f" ({v['unit']})" if v["unit"] else ""
            rows.append(f"| `{v['key']}`{u} | {role} | {v['kind']} | {v['desc']} | {v['source']} | {v['freq']} | {v['used_in']} |")
    return "\n".join(rows)
