# Contexto actual — CryptoAgent v4.2

Actualizado 2026-11-28T17:05:04Z UTC. Se recalcula cada hora; el calendario y los pesos cada 15 días.

**Estado: RISK_OFF** · sesgo -0.47 · riesgo de evento 0.24 · tamaño ×0.0 · VETO a compras

- Alerta on-chain alta: Ballena dormida movió 7,281 BTC con ≥5 años (0 con ≥10); el input más viejo tenía 7.1 años.
- Stablecoins -5.43% en 30 días (liquidez saliendo)

| Próximo evento | UTC | Categoría | Magnitud | Riesgo |
|---|---|---|---|---|
| España: elecciones generales anticipadas (convocadas por Sánchez el 5-oct-2026) | 2026-11-29T12:00:00Z | Elección | 0.235 | 0.235 |

| Evento reciente | Fecha | Postura | Aporte al sesgo |
|---|---|---|---|
| CZ reconoce complacencia en Binance tras hackeo de 6.300 millones de dólares | 2026-11-28 | anti | -0.361 |
| Turbulencia en Nvidia aumenta temores de Wall Street sobre el boom de la IA | 2026-11-25 | anti | -0.334 |
| Trump propone tope del 10% a tasas de tarjetas de crédito | 2026-11-28 | pro | +0.254 |
| El ETF de Bitcoin de BlackRock pierde 2.800 millones de dólares en 8 sesiones | 2026-11-28 | anti | -0.240 |
| El Departamento de Justicia busca recuperar 1.100 millones robados a Binance por | 2026-11-24 | pro | +0.234 |
| La SEC acusa a firmas cripto de usar registros oficiales en esquema de 130 millo | 2026-11-25 | anti | -0.192 |
| Desplome de mercados globales borra billones de dólares | 2026-11-21 | anti | -0.144 |
| EE.UU. presenta aranceles contra la UE, China y otros países | 2026-11-26 | anti | -0.141 |

Calendario completo: [CALENDARIO.md](CALENDARIO.md) · Pesos: [EVENTOS.md](EVENTOS.md) · Datos: `context_signal.json`, `calendar.json`, `weights.json`, `alerts_onchain.json`

<details><summary>Reporte de la última corrida</summary>

```json
{
 "modo": "watch",
 "inicio": "2026-11-28T17:05:04Z",
 "onchain": {
  "scanned": [
   977953,
   977956
  ],
  "calls": 79,
  "stopped": null,
  "nuevas": 0
 },
 "noticias": {
  "cryptopanic": "sin CRYPTOPANIC_API_KEY",
  "titulares": 30,
  "eventos": 3,
  "urgentes": 3,
  "metodo": "gemini",
  "agregados": 3
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
