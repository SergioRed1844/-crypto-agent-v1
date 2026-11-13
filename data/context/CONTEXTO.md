# Contexto actual — CryptoAgent v4.2

Actualizado 2026-11-13T23:22:34Z UTC. Se recalcula cada hora; el calendario y los pesos cada 15 días.

**Estado: RISK_OFF** · sesgo -0.43 · riesgo de evento 0.00 · tamaño ×0.0 · VETO a compras

- Alerta on-chain alta: Minero temprano gastó 50.00 BTC P2PK (input más viejo: bloque 80723).
- Stablecoins -5.33% en 30 días (liquidez saliendo)

| Evento reciente | Fecha | Postura | Aporte al sesgo |
|---|---|---|---|
| Los precios al por mayor en EE.UU. suben menos de lo esperado en octubre | 2026-11-13 | pro | +0.337 |
| Wall Street enfrenta desplome de 5,7 billones de dólares por desinflado en IA | 2026-11-07 | anti | -0.284 |
| Ataque a Binance evidencia vulnerabilidades de seguridad cripto | 2026-11-12 | anti | -0.211 |
| Hackers de Binance blanquean fondos y renuncia el director financiero | 2026-11-13 | anti | -0.187 |
| La Fed evalúa acelerar alzas de tasas ante mayor inflación | 2026-11-12 | anti | -0.134 |
| China extiende por dos meses suspensión de aranceles del 24% a importaciones de  | 2026-11-09 | pro | +0.134 |
| Demócratas de la Cámara preparan ley cripto otorgando mayor rol a la SEC | 2026-11-06 | anti | -0.133 |
| Wall Street cae al alcanzar 100% probabilidad de subida de tasas por alta inflac | 2026-11-12 | anti | -0.122 |

Calendario completo: [CALENDARIO.md](CALENDARIO.md) · Pesos: [EVENTOS.md](EVENTOS.md) · Datos: `context_signal.json`, `calendar.json`, `weights.json`, `alerts_onchain.json`

<details><summary>Reporte de la última corrida</summary>

```json
{
 "modo": "watch",
 "inicio": "2026-11-13T23:22:34Z",
 "onchain": {
  "scanned": [
   975719,
   975723
  ],
  "calls": 121,
  "stopped": null,
  "nuevas": 0
 },
 "noticias": {
  "cryptopanic": "sin CRYPTOPANIC_API_KEY",
  "titulares": 15,
  "eventos": 4,
  "urgentes": 3,
  "metodo": "gemini",
  "agregados": 0
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
