# forward-test — CryptoAgent v4.1 en papel

Prueba hacia adelante **sin dinero**: reglas congeladas el 2026-10-11 (ver `forward/prerregistro.json`),
8 monedas × 3 escalas (swing 1D/4H/1H, intradía 4H/1H/15m, scalp 1H/15m/5m), cuenta hipotética de 1,000 USDT
por escala, 0.5% de riesgo por trade, comisión 0.1% y slippage 0.05% por lado.

- Ventana: desde 2026-10-12 00:00 UTC. Cortes: 12-oct, 13-oct y 14-oct a las 20:00 UTC (14:00 Monterrey).
- `forward/engine.js`: reglas en JS con paridad 100% contra `backtest.py` (3,766 señales y 286 trades idénticos).
- `forward/results/latest.json` se actualiza cada hora; `corte_*.json` se escriben una sola vez al pasar cada corte.
- `forward/baseline_historica.json`: las mismas reglas sobre datos reales de Binance antes de la ventana.

Esta rama no la usa Render (Render despliega `main`).
