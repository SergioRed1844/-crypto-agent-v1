# Contexto actual — CryptoAgent v4.2

Actualizado 2026-11-01T17:56:26Z UTC. Se recalcula cada hora; el calendario y los pesos cada 15 días.

**Estado: NEUTRAL** · sesgo -0.20 · riesgo de evento 0.48 · tamaño ×0.761 · compras permitidas

- Contexto neutral: sesgo -0.20, riesgo de evento 0.48
- Stablecoins -2.68% en 30 días (liquidez saliendo)

| Próximo evento | UTC | Categoría | Magnitud | Riesgo |
|---|---|---|---|---|
| EE.UU.: elecciones de medio mandato (435 escaños de la Cámara, 35 del Senado, 39 | 2026-11-03T12:00:00Z | Elección | 0.435 | 0.338 |
| Elecciones intermedias de EE.UU.: definen la composición del Congreso que retoma | 2026-11-03T12:00:00Z | Regulación cripto | 0.356 | 0.168 |
| Anuncio trimestral de refinanciamiento (Quarterly Refunding) del Tesoro | 2026-11-04T13:30:00Z | Fiscal / deuda | 0.545 | 0.054 |

| Evento reciente | Fecha | Postura | Aporte al sesgo |
|---|---|---|---|
| Futuros caen por desplome de OPV tecnológica en Corea y ampliación de diferencia | 2026-10-20 | anti | -0.215 |
| Empresas luchan para pagar nóminas tras la quiebra de Silicon Valley Bank | 2026-10-18 | pro | +0.195 |
| Ramp solicita licencia de fideicomiso fiduciario ante la OCC para custodia cript | 2026-10-23 | pro | +0.158 |
| Los ETF de Bitcoin sufren su mayor día de salidas de capital desde junio | 2026-10-24 | anti | -0.136 |
| Salidas de ETF de Ether rondan 1.100 millones de dólares en octubre | 2026-10-21 | anti | -0.118 |
| CMCC Global, Tether y Bitfinex lanzan fondo tokenizado en El Salvador | 2026-10-22 | pro | +0.117 |
| Rebote global del sector de inteligencia artificial impulsa el sentimiento cript | 2026-10-21 | pro | +0.111 |
| Bancos podrían frenar stablecoins pagando más a ahorristas, según estudio del BP | 2026-10-17 | anti | -0.099 |

Calendario completo: [CALENDARIO.md](CALENDARIO.md) · Pesos: [EVENTOS.md](EVENTOS.md) · Datos: `context_signal.json`, `calendar.json`, `weights.json`, `alerts_onchain.json`

<details><summary>Reporte de la última corrida</summary>

```json
{
 "modo": "refresh",
 "inicio": "2026-11-01T17:56:26Z",
 "noticias": {
  "cryptopanic": "sin CRYPTOPANIC_API_KEY",
  "n_cryptopanic": 0,
  "n_gdelt": 240,
  "titulares": 210,
  "eventos": 35,
  "metodo": "gemini",
  "agregados": 12,
  "propuestas_de_noticias": -6
 },
 "consenso_semana": [
  {
   "title": "ISM Manufacturing PMI",
   "country": "USD",
   "date": "2026-11-02T10:00:00-05:00",
   "impact": "Medium",
   "forecast": "54.7",
   "previous": "54.5"
  },
  {
   "title": "JOLTS Job Openings",
   "country": "USD",
   "date": "2026-11-03T10:00:00-05:00",
   "impact": "Medium",
   "forecast": "7.11M",
   "previous": "7.08M"
  },
  {
   "title": "Congressional Elections",
   "country": "USD",
   "date": "2026-11-03T10:16:00-05:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Core CPI Flash Estimate y/y",
   "country": "EUR",
   "date": "2026-11-04T05:00:00-05:00",
   "impact": "Medium",
   "forecast": "2.5%",
   "previous": "2.5%"
  },
  {
   "title": "CPI Flash Estimate y/y",
   "country": "EUR",
   "date": "2026-11-04T05:00:00-05:00",
   "impact": "Medium",
   "forecast": "4.0%",
   "previous": "3.8%"
  },
  {
   "title": "ISM Services PMI",
   "country": "USD",
   "date": "2026-11-04T10:00:00-05:00",
   "impact": "Medium",
   "forecast": "54.9",
   "previous": "54.9"
  },
  {
   "title": "BOE Monetary Policy Report",
   "country": "GBP",
   "date": "2026-11-05T07:00:00-05:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Monetary Policy Summary",
   "country": "GBP",
   "date": "2026-11-05T07:00:00-05:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "MPC Official Bank Rate Votes",
   "country": "GBP",
   "date": "2026-11-05T07:00:00-05:00",
   "impact": "High",
   "forecast": "7-0-2",
   "previous": "3-0-6"
  },
  {
   "title": "Official Bank Rate",
   "country": "GBP",
   "date": "2026-11-05T07:00:00-05:00",
   "impact": "High",
   "forecast": "4.00%",
   "previous": "3.75%"
  },
  {
   "title": "BOE Gov Bailey Speaks",
   "country": "GBP",
   "date": "2026-11-05T07:30:00-05:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Unemployment Claims",
   "country": "USD",
   "date": "2026-11-05T08:30:00-05:00",
   "impact": "Medium",
   "forecast": "197K",
   "previous": "194K"
  },
  {
   "title": "ECB President Lagarde Speaks",
   "country": "EUR",
   "date": "2026-11-05T13:00:00-05:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Average Hourly Earnings m/m",
   "country": "USD",
   "date": "2026-11-06T08:30:00-05:00",
   "impact": "High",
   "forecast": "0.3%",
   "previous": "0.1%"
  },
  {
   "title": "Non-Farm Employment Change",
   "country": "USD",
   "date": "2026-11-06T08:30:00-05:00",
   "impact": "High",
   "forecast": "63K",
   "previous": "29K"
  },
  {
   "title": "Unemployment Rate",
   "country": "USD",
   "date": "2026-11-06T08:30:00-05:00",
   "impact": "High",
   "forecast": "4.2%",
   "previous": "4.2%"
  },
  {
   "title": "Prelim UoM Consumer Sentiment",
   "country": "USD",
   "date": "2026-11-06T10:00:00-05:00",
   "impact": "Medium",
   "forecast": "47.8",
   "previous": "46.3"
  },
  {
   "title": "Prelim UoM Inflation Expectations",
   "country": "USD",
   "date": "2026-11-06T10:00:00-05:00",
   "impact": "Medium",
   "forecast": "",
   "previous": "4.7%"
  },
  {
   "title": "BOJ Gov Ueda Speaks",
   "country": "JPY",
   "date": "2026-11-06T11:00:00-05:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  }
 ],
 "auditoria": {
  "status": "12 propuestas",
  "agregadas": 3
 },
 "calendario": {
  "events": 355,
  "eventos_a_futuro": 342,
  "por_status": {
   "confirmed": 212,
   "expected": 43,
   "proposed": 7,
   "speculative": 8,
   "scheduled_estimate": 72
  },
  "huecos": []
 },
 "macro_fuentes_ok": 2,
 "estudio_eventos": {
  "eventos": 258,
  "base_azar": {
   "mean_abs_z3_random": 0.75,
   "n_random": 4000
  }
 },
 "onchain": {
  "scanned": null,
  "calls": 1,
  "stopped": null,
  "nuevas": 0
 },
 "sheets": {
  "status": "sin SHEETS_WEBAPP_URL (opcional)"
 },
 "gemini": {
  "model": "gemini-3.8-flash",
  "ok": 8,
  "errors": [
   "ReadTimeout"
  ]
 }
}
```
</details>
