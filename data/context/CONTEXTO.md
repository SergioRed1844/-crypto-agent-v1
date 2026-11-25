# Contexto actual — CryptoAgent v4.2

Actualizado 2026-11-25T01:19:52Z UTC. Se recalcula cada hora; el calendario y los pesos cada 15 días.

**Estado: CAUTION** · sesgo -0.43 · riesgo de evento 0.30 · tamaño ×0.5 · compras permitidas

- Precaución: sesgo -0.43
- Stablecoins -5.89% en 30 días (liquidez saliendo)

| Próximo evento | UTC | Categoría | Magnitud | Riesgo |
|---|---|---|---|---|
| Ingreso y gasto personal / PCE EE.UU. (oct-2026) | 2026-11-25T13:30:00Z | Dato macro | 0.279 | 0.183 |
| PIB EE.UU. 3T-2026 (estimación segunda) | 2026-11-25T13:30:00Z | Dato macro | 0.205 | 0.134 |
| Vencimiento mensual de opciones BTC/ETH (Deribit) | 2026-11-27T08:00:00Z | Vencimiento de derivados | 0.1 | 0.011 |
| Vencimiento mensual de futuros de BTC en CME | 2026-11-27T16:00:00Z | Vencimiento de derivados | 0.05 | 0.004 |

| Evento reciente | Fecha | Postura | Aporte al sesgo |
|---|---|---|---|
| El Departamento de Justicia busca recuperar 1.100 millones robados a Binance por | 2026-11-24 | pro | +0.395 |
| Desplome de mercados globales borra billones de dólares | 2026-11-21 | anti | -0.375 |
| Se profundizan pérdidas de Bitcoin tras presunto hackeo a Binance | 2026-11-25 | anti | -0.270 |
| Acciones de EE.UU. suben 4,73% con rendimiento del Tesoro en 4,95% | 2026-11-24 | pro | +0.260 |
| Bitcoin cae por debajo de 70.000 dólares ante agitación de Nvidia | 2026-11-25 | anti | -0.233 |
| El Departamento de Justicia apunta a recuperar 1.100 millones de dólares del hac | 2026-11-23 | pro | +0.195 |
| Orden de congelamiento de $6.5B contra Binance | 2026-11-20 | anti | -0.187 |
| Previsión PCE de EE. UU.: inflación se proyecta en 3,8% antes de subida de la Fe | 2026-11-25 | anti | -0.184 |

Calendario completo: [CALENDARIO.md](CALENDARIO.md) · Pesos: [EVENTOS.md](EVENTOS.md) · Datos: `context_signal.json`, `calendar.json`, `weights.json`, `alerts_onchain.json`

<details><summary>Reporte de la última corrida</summary>

```json
{
 "modo": "watch",
 "inicio": "2026-11-25T01:19:52Z",
 "onchain": {
  "scanned": [
   977437,
   977444
  ],
  "calls": 64,
  "stopped": null,
  "nuevas": 0
 },
 "noticias": {
  "cryptopanic": "sin CRYPTOPANIC_API_KEY",
  "titulares": 40,
  "eventos": 10,
  "urgentes": 5,
  "metodo": "gemini",
  "agregados": 4
 },
 "gemini": {
  "model": "gemini-3.8-flash",
  "ok": 1,
  "errors": []
 },
 "macro_fuentes_ok": 2
}
```
</details>
