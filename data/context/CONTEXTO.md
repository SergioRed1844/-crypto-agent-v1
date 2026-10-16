# Contexto actual — CryptoAgent v4.2

Actualizado 2026-10-16T17:43:20Z UTC. Se recalcula cada hora; el calendario y los pesos cada 15 días.

**Estado: RISK_OFF** · sesgo -0.84 · riesgo de evento 0.05 · tamaño ×0.0 · VETO a compras

- Sesgo de eventos muy negativo (-0.84)

| Próximo evento | UTC | Categoría | Magnitud | Riesgo |
|---|---|---|---|---|
| GENIUS Act: cierra el periodo de comentarios de la propuesta del Tesoro (18-ago- | 2026-10-19T12:00:00Z | Regulación cripto | 0.28 | 0.048 |

| Evento reciente | Fecha | Postura | Aporte al sesgo |
|---|---|---|---|
| Rendimientos de bonos del Tesoro de EE. UU. asimilan datos elevados de inflación | 2026-10-16 | anti | -0.328 |
| ETF spot de Bitcoin en EE. UU. registran salidas por 261 millones de dólares | 2026-10-14 | anti | -0.309 |
| Ledger suspende ventas tras investigación por robo de 86 millones de dólares | 2026-10-15 | anti | -0.300 |
| Firma de asesor cripto de la Casa Blanca se benefició de la Ley GENIUS | 2026-10-15 | anti | -0.292 |
| Ethereum cae 5% tras efímero rebote de sus ETF | 2026-10-15 | anti | -0.288 |
| Ethereum lidera casi mil millones de dólares en liquidaciones de criptomonedas | 2026-10-16 | anti | -0.277 |
| Tailandia endurece normas para nuevos ETF spot de criptomonedas | 2026-10-16 | anti | -0.271 |
| Zcash sube 8% tras entradas netas en sus ETF por primera vez desde septiembre | 2026-10-16 | pro | +0.256 |

Calendario completo: [CALENDARIO.md](CALENDARIO.md) · Pesos: [EVENTOS.md](EVENTOS.md) · Datos: `context_signal.json`, `calendar.json`, `weights.json`, `alerts_onchain.json`

<details><summary>Reporte de la última corrida</summary>

```json
{
 "modo": "refresh",
 "inicio": "2026-10-16T17:43:20Z",
 "noticias": {
  "cryptopanic": "sin CRYPTOPANIC_API_KEY",
  "n_cryptopanic": 0,
  "n_gdelt": 180,
  "titulares": 130,
  "eventos": 55,
  "metodo": "gemini",
  "agregados": 50,
  "propuestas_de_noticias": 0
 },
 "consenso_semana": [
  {
   "title": "ECB President Lagarde Speaks",
   "country": "EUR",
   "date": "2026-10-13T22:10:00-04:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "BOE Gov Bailey Speaks",
   "country": "GBP",
   "date": "2026-10-14T01:30:00-04:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "ECB President Lagarde Speaks",
   "country": "EUR",
   "date": "2026-10-14T04:30:00-04:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "EU Economic Summit",
   "country": "EUR",
   "date": "2026-10-14T06:15:00-04:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Core CPI m/m",
   "country": "USD",
   "date": "2026-10-14T08:30:00-04:00",
   "impact": "High",
   "forecast": "0.2%",
   "previous": "0.3%"
  },
  {
   "title": "Core CPI y/y",
   "country": "USD",
   "date": "2026-10-14T08:30:00-04:00",
   "impact": "High",
   "forecast": "2.5%",
   "previous": "2.4%"
  },
  {
   "title": "CPI m/m",
   "country": "USD",
   "date": "2026-10-14T08:30:00-04:00",
   "impact": "High",
   "forecast": "0.6%",
   "previous": "0.4%"
  },
  {
   "title": "CPI y/y",
   "country": "USD",
   "date": "2026-10-14T08:30:00-04:00",
   "impact": "High",
   "forecast": "3.6%",
   "previous": "3.4%"
  },
  {
   "title": "GDP m/m",
   "country": "GBP",
   "date": "2026-10-15T02:00:00-04:00",
   "impact": "High",
   "forecast": "-0.1%",
   "previous": "0.4%"
  },
  {
   "title": "BOE Gov Bailey Speaks",
   "country": "GBP",
   "date": "2026-10-15T03:30:00-04:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "EU Economic Summit",
   "country": "EUR",
   "date": "2026-10-15T06:15:00-04:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Core PPI m/m",
   "country": "USD",
   "date": "2026-10-15T08:30:00-04:00",
   "impact": "High",
   "forecast": "0.3%",
   "previous": "0.2%"
  },
  {
   "title": "Core Retail Sales m/m",
   "country": "USD",
   "date": "2026-10-15T08:30:00-04:00",
   "impact": "High",
   "forecast": "0.6%",
   "previous": "1.4%"
  },
  {
   "title": "PPI m/m",
   "country": "USD",
   "date": "2026-10-15T08:30:00-04:00",
   "impact": "High",
   "forecast": "0.6%",
   "previous": "0.4%"
  },
  {
   "title": "Retail Sales m/m",
   "country": "USD",
   "date": "2026-10-15T08:30:00-04:00",
   "impact": "High",
   "forecast": "0.3%",
   "previous": "1.2%"
  },
  {
   "title": "Philly Fed Manufacturing Index",
   "country": "USD",
   "date": "2026-10-15T08:30:00-04:00",
   "impact": "Medium",
   "forecast": "28.2",
   "previous": "37.8"
  },
  {
   "title": "Unemployment Claims",
   "country": "USD",
   "date": "2026-10-15T08:30:00-04:00",
   "impact": "Medium",
   "forecast": "199K",
   "previous": "197K"
  },
  {
   "title": "BOE Gov Bailey Speaks",
   "country": "GBP",
   "date": "2026-10-15T22:00:00-04:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "Fed Chairman Warsh Speaks",
   "country": "USD",
   "date": "2026-10-15T23:30:00-04:00",
   "impact": "High",
   "forecast": "",
   "previous": ""
  },
  {
   "title": "BOE Gov Bailey Speaks",
   "country": "GBP",
   "date": "2026-10-17T02:45:00-04:00",
   "impact": "Medium",
   "forecast": "",
   "previous": ""
  }
 ],
 "auditoria": {
  "status": "11 propuestas",
  "agregadas": 11
 },
 "calendario": {
  "events": 356,
  "eventos_a_futuro": 353,
  "por_status": {
   "confirmed": 222,
   "proposed": 9,
   "expected": 42,
   "speculative": 8,
   "scheduled_estimate": 72
  },
  "huecos": []
 },
 "macro_fuentes_ok": 2,
 "estudio_eventos": {
  "eventos": 258,
  "base_azar": {
   "mean_abs_z3_random": 0.751,
   "n_random": 4000
  }
 },
 "onchain": {
  "scanned": [
   971745,
   971746
  ],
  "calls": 20,
  "stopped": null,
  "nuevas": 0
 },
 "noticias": {
  "cryptopanic": "sin CRYPTOPANIC_API_KEY",
  "titulares": 14,
  "eventos": 0,
  "urgentes": 0,
  "metodo": "palabras-clave",
  "agregados": 0
 },
 "gemini": {
  "model": "gemini-3.8-flash",
  "ok": 6,
  "errors": []
 }
}
```
</details>
