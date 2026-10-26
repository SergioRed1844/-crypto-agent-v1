---
name: copytrade-disclosures
description: Análisis y señales "copy-trade" de operaciones públicas de funcionarios (OGE 278-T / anual 278e de Donald J. Trump; extensible a Congreso/STOCK Act) — fuentes, verificación de filas contra los PDF, fecha de publicación sin mirar al futuro, mapeo nombre→ticker y proxies de bonos, cartera sombra, modos espejo vs replicable, estudio por operación y compuerta. Cárgala al editar copytrade/*, data/copytrade/*, tests/test_copytrade.py, el workflow copytrade.yml, o al juzgar si "copiar a X" tiene ventaja.
---

# Copy-trade de reportes públicos — contrato

1. **La fecha que manda es la de publicación, no la de operación.** El copiador solo sabe lo que OGE ya publicó.
   Publicación = la más tardía entre: fecha de Open Cabinet, sello "OGE Received", última firma digital de OGE y
   `Last-Modified` del PDF. Se ejecuta al cierre del primer día hábil DESPUÉS. El "espejo perfecto" (fecha de
   operación) solo se reporta como techo teórico, nunca como resultado alcanzable.
2. **El anual 278e importa.** El de 2026 trae ~20,900 operaciones de 2025 que nunca salieron en un 278-T y se
   publicaron hasta el 1-jul-2026. Ignorarlo cambia todo el resultado de 2025.
3. **Filas:** base Open Cabinet (MIT, `data/copytrade/oc_trump_rows.csv.gz`) verificada contra nuestro parser del texto
   OCR (`copytrade/verify.py`) y muestras visuales de páginas. Lo que Open Cabinet aún no tiene se lee nosotros:
   `copytrade/ocr.py` (300 dpi → borrar líneas de tabla → tesseract) o transcripción visual cotejada contra la capa
   de texto (`manual_*.csv`). Nunca inventar filas; lo ilegible se reporta.
4. **Montos en rangos:** punto medio por defecto; siempre sensibilidad con límite inferior, media geométrica y peso
   igual. Una conclusión que cambia de signo con el supuesto de monto no es conclusión.
5. **Cartera sombra:** acciones = Σ compras/precio − ventas/precio en orden de fecha de operación, nunca negativas;
   las ventas de tenencias previas al mandato se ignoran. El copiador sostiene la composición (ponderado por tiempo):
   las aportaciones del funcionario no son dinero del copiador.
6. **Mapeo:** overrides manuales con motivo → ticker impreso → resolución de Open Cabinet → listas Nasdaq/NYSE/SEC.
   Bonos/efectivo a ETF del segmento por vencimiento (SUB/MUB, VCSH/VCIT/VCLT, PFF, BIL/SHY/IEF/TLT). Reportar el $
   sin mapear y sin precio.
7. **Costos:** 0.29% por lado (GBM 0.25% + IVA, verificar contrato) y 0.05% alterno. Con 50k no se pueden comprar
   1,400 nombres: la variante Top-30 es la ejecutable.
8. **Compuerta (pre-registro `docs/COPYTRADE_TRUMP.md`):** en modo replicable, cartera completa, punto medio y costo
   base, debe (1) ganarle al SPY, (2) tener alfa CAPM > 0 con t ≥ 2 (Newey-West) y (3) compras con exceso a 63 días
   desde la publicación con IC 95% > 0 (bootstrap agrupado por fecha). Si no, no se automatiza. Con pocas fechas de
   publicación (≈20) el IC es ancho: decirlo.
9. **No es señal de compra automática.** Aunque pase, entra al Radar EB como un setup más (solo alertas) y con los
   límites duros del sistema; nunca abre operaciones por sí solo.

## Archivos
`copytrade/{fetch,prices,parse278t,ocr,verify,data,resolve,build,sim,events,__main__}.py` ·
`data/copytrade/{filings.csv,oc_trump_rows.csv.gz,manual_2026-09-17.csv,overrides.csv,tickers.txt,ref/}` ·
workflow `.github/workflows/copytrade.yml` (`[ct-fetch]`, `[ct-prices]`, `[ct-run]`) · datos en la rama
`copytrade-data` · pruebas `python -m tests.test_copytrade`.
