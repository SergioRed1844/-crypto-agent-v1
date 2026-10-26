# data/copytrade

- `filings.csv` — reportes de OGE de Donald J. Trump usados (278-T y anual 2026) con su URL.
- `oc_trump_rows.csv.gz` — filas de Trump del dataset público de **Open Cabinet** (https://github.com/tbrown034/open-cabinet,
  commit `7864d1a`, exportado 2026-09-25, licencia MIT © 2026 Trevor Brown), con la resolución de ticker de su
  `data/meta/asset-resolution.json`. Verificadas contra nuestro parser de los PDF (`copytrade/verify.py`).
- `manual_2026-09-17.csv` — las 517 operaciones del reporte `Donald-J-Trump.09.17.2026-278T.pdf` (agosto-2026; aún no
  está en Open Cabinet), **transcritas a mano de las imágenes del PDF** y cotejadas contra la capa de texto OCR
  (tipo 462/462, monto 456/460 y fecha 315/318 coinciden; las diferencias son errores del OCR).
- `overrides.csv` — mapeos nombre→ticker revisados a mano (con motivo).
- `ref/` — listas Nasdaq (`nasdaqlisted.txt`, `otherlisted.txt`) y SEC (`company_tickers_exchange.json`), copias de
  Open Cabinet (sep-2026).
