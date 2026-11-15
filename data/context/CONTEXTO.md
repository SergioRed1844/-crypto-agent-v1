# Contexto actual — CryptoAgent v4.2

Actualizado 2026-11-15T18:53:03Z UTC. Se recalcula cada hora; el calendario y los pesos cada 15 días.

**Estado: CAUTION** · sesgo -0.37 · riesgo de evento 0.00 · tamaño ×0.5 · compras permitidas

- Precaución: sesgo -0.37
- Stablecoins -5.28% en 30 días (liquidez saliendo)

| Evento reciente | Fecha | Postura | Aporte al sesgo |
|---|---|---|---|
| ETFs de Bitcoin al contado en EE.UU. registran 6.200 millones de dólares en entr | 2026-11-12 | pro | +0.283 |
| Wall Street enfrenta desplome de 5,7 billones de dólares por desinflado en IA | 2026-11-07 | anti | -0.250 |
| Bitcoin cae a mínimos de cuatro meses ante la aceleración de liquidaciones | 2026-11-15 | anti | -0.205 |
| Ataque a Binance evidencia vulnerabilidades de seguridad cripto | 2026-11-12 | anti | -0.163 |
| Los precios al por mayor en EE.UU. suben menos de lo esperado en octubre | 2026-11-13 | pro | +0.136 |
| EE.UU. extiende 178 exclusiones arancelarias a China hasta el 9 de enero | 2026-11-11 | pro | +0.124 |
| Demócratas de la Cámara preparan ley cripto otorgando mayor rol a la SEC | 2026-11-06 | anti | -0.117 |
| Bolsas mundiales caen arrastradas por pánico en tecnológicas tras elecciones de  | 2026-11-06 | anti | -0.104 |

Calendario completo: [CALENDARIO.md](CALENDARIO.md) · Pesos: [EVENTOS.md](EVENTOS.md) · Datos: `context_signal.json`, `calendar.json`, `weights.json`, `alerts_onchain.json`

<details><summary>Reporte de la última corrida</summary>

```json
{
 "modo": "refresh",
 "inicio": "2026-11-15T18:53:03Z",
 "noticias": {
  "cryptopanic": "sin CRYPTOPANIC_API_KEY",
  "n_cryptopanic": 0,
  "n_gdelt": 240,
  "titulares": 203,
  "eventos": 42,
  "metodo": "gemini",
  "agregados": 26,
  "propuestas_de_noticias": 0
 },
 "consenso_semana": [
  {
   "title": "Fed Chairman Warsh Speaks",
   "country": "USD",
   "date": "2026-11-16T12:00:00-05:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Average Earnings Index 3m/y",
   "country": "GBP",
   "date": "2026-11-17T02:00:00-05:00",
   "impact": "Medium",
   "forecast": "3.5%",
   "previous": "3.7%"
  },
  {
   "title": "Core Retail Sales m/m",
   "country": "USD",
   "date": "2026-11-17T08:30:00-05:00",
   "impact": "High",
   "forecast": "0.4%",
   "previous": "0.9%"
  },
  {
   "title": "Retail Sales m/m",
   "country": "USD",
   "date": "2026-11-17T08:30:00-05:00",
   "impact": "High",
   "forecast": "0.2%",
   "previous": "0.8%"
  },
  {
   "title": "CPI y/y",
   "country": "GBP",
   "date": "2026-11-18T02:00:00-05:00",
   "impact": "High",
   "forecast": "3.6%",
   "previous": "3.5%"
  },
  {
   "title": "BOE Gov Bailey Speaks",
   "country": "GBP",
   "date": "2026-11-18T02:30:00-05:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "ECB Financial Stability Review",
   "country": "EUR",
   "date": "2026-11-18T04:00:00-05:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "ECB President Lagarde Speaks",
   "country": "EUR",
   "date": "2026-11-18T09:25:00-05:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "BOE Gov Bailey Speaks",
   "country": "GBP",
   "date": "2026-11-18T10:00:00-05:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "FOMC Meeting Minutes",
   "country": "USD",
   "date": "2026-11-18T14:00:00-05:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "ECB President Lagarde Speaks",
   "country": "EUR",
   "date": "2026-11-19T08:30:00-05:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Philly Fed Manufacturing Index",
   "country": "USD",
   "date": "2026-11-19T08:30:00-05:00",
   "impact": "Medium",
   "forecast": "19.2",
   "previous": "20.9"
  },
  {
   "title": "Unemployment Claims",
   "country": "USD",
   "date": "2026-11-19T08:30:00-05:00",
   "impact": "Medium",
   "forecast": "199K",
   "previous": "200K"
  },
  {
   "title": "Retail Sales m/m",
   "country": "GBP",
   "date": "2026-11-20T02:00:00-05:00",
   "impact": "Medium",
   "forecast": "0.0%",
   "previous": "-0.4%"
  },
  {
   "title": "ECB President Lagarde Speaks",
   "country": "EUR",
   "date": "2026-11-20T03:15:00-05:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "FOMC Member Waller Speaks",
   "country": "USD",
   "date": "2026-11-20T08:25:00-05:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Revised UoM Consumer Sentiment",
   "country": "USD",
   "date": "2026-11-20T10:00:00-05:00",
   "impact": "Medium",
   "forecast": "52.1",
   "previous": "51.0"
  },
  {
   "title": "Revised UoM Inflation Expectations",
   "country": "USD",
   "date": "2026-11-20T10:00:00-05:00",
   "impact": "Medium",
   "forecast": "",
   "previous": "4.3%"
  }
 ],
 "auditoria": {
  "status": "13 propuestas",
  "agregadas": 2
 },
 "calendario": {
  "events": 357,
  "eventos_a_futuro": 328,
  "por_status": {
   "confirmed": 203,
   "proposed": 8,
   "speculative": 6,
   "expected": 37,
   "scheduled_estimate": 74
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
  "scanned": [
   976001,
   976004
  ],
  "calls": 62,
  "stopped": null,
  "nuevas": 0
 },
 "sheets": {
  "status": "sin SHEETS_WEBAPP_URL (opcional)"
 },
 "gemini": {
  "model": "gemini-3.8-flash",
  "ok": 8,
  "errors": []
 }
}
```
</details>
