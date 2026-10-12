"""Eventos que siguen una REGLA y se pueden generar con años de anticipación (sin internet).

- Vencimientos de opciones de Deribit (último viernes del mes, 08:00 UTC; trimestrales mar/jun/sep/dic)
- Vencimiento mensual de futuros de BTC en CME (último viernes, 16:00 Londres)
- Estimados de FOMC / CPI / NFP / Jackson Hole para los meses SIN calendario oficial publicado
  (status scheduled_estimate: suben el riesgo de evento pero nunca disparan blackout; el refresco
  quincenal los reemplaza por la fecha oficial en cuanto se publica)
- Estimado del próximo halving a partir de la altura de bloque actual
"""
import calendar as _cal
from datetime import date, datetime, timedelta, timezone

FOMC_MONTHS = (1, 3, 4, 6, 7, 9, 10, 12)   # patrón 2025–2026 (8 reuniones: ene, mar, abr/may, jun, jul, sep, oct, dic)
HALVING_EVERY = 210_000


def last_friday(y: int, m: int) -> date:
    d = date(y, m, _cal.monthrange(y, m)[1])
    return d - timedelta(days=(d.weekday() - 4) % 7)


def first_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def _months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def derivatives_expiries(start: date, end: date) -> list[dict]:
    out = []
    for y, m in _months(start, end):
        d = last_friday(y, m)
        if not (start <= d <= end):
            continue
        q = m in (3, 6, 9, 12)
        out.append({"id": f"deribit-expiry-{d}", "date": str(d), "time_local": "08:00", "tz": "UTC",
                    "date_precision": "exact", "status": "confirmed", "category": "DERIVATIVES_EXPIRY",
                    "subcategory": "DERIBIT_QUARTERLY" if q else "DERIBIT_MONTHLY", "country": "GLOBAL",
                    "title_es": f"Vencimiento {'TRIMESTRAL' if q else 'mensual'} de opciones BTC/ETH (Deribit)",
                    "why_es": "Concentra open interest: el precio tiende a 'pegarse' al max pain antes y a moverse "
                              "fuerte después del vencimiento.",
                    "crypto_stance": "neutral", "prior_tier": 3 if q else 2, "source_url": "https://www.deribit.com",
                    "source_title": "Regla: último viernes del mes 08:00 UTC", "origin": "regla"})
        out.append({"id": f"cme-btc-expiry-{d}", "date": str(d), "time_local": "16:00", "tz": "Europe/London",
                    "date_precision": "exact", "status": "confirmed", "category": "DERIVATIVES_EXPIRY",
                    "subcategory": "CME_MONTHLY", "country": "US",
                    "title_es": "Vencimiento mensual de futuros de BTC en CME",
                    "why_es": "Rollover institucional; puede dejar 'gaps' de fin de semana.",
                    "crypto_stance": "neutral", "prior_tier": 1,
                    "source_url": "https://www.cmegroup.com/markets/cryptocurrencies/bitcoin/bitcoin.contractSpecs.html",
                    "source_title": "Regla CME: último viernes del mes, 16:00 Londres", "origin": "regla"})
    return out


def _has(curated: list, subcats: tuple, y: int, m: int) -> bool:
    return any(e.get("subcategory") in subcats and str(e["date"])[:7] == f"{y:04d}-{m:02d}" for e in curated)


def macro_estimates(start: date, end: date, curated: list) -> list[dict]:
    """Solo para meses SIN fecha oficial en el calendario curado."""
    out = []
    last_fomc = max((str(e["date"]) for e in curated if e.get("subcategory") in ("FOMC", "FOMC_SEP")), default="")
    last_cpi = max((str(e["date"]) for e in curated if e.get("subcategory") == "CPI"), default="")
    last_nfp = max((str(e["date"]) for e in curated if e.get("subcategory") == "NFP"), default="")
    for y, m in _months(start, end):
        ym = f"{y:04d}-{m:02d}"
        if m in FOMC_MONTHS and ym > last_fomc[:7] and not _has(curated, ("FOMC", "FOMC_SEP"), y, m):
            out.append({"id": f"fomc-estimado-{ym}", "date": f"{ym}-15", "date_precision": "month",
                        "status": "scheduled_estimate", "category": "MONETARY_POLICY", "subcategory": "FOMC",
                        "country": "US", "title_es": f"FOMC (fecha por confirmar, {ym})",
                        "why_es": "Decisión de tasas de la Fed: reprecia liquidez global; la Fed publica el calendario "
                                  "del año siguiente a mediados de año.",
                        "crypto_stance": "uncertain", "prior_tier": 4,
                        "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        "source_title": "Estimado por patrón de 8 reuniones/año", "origin": "regla"})
        if ym > last_cpi[:7] and not _has(curated, ("CPI",), y, m):
            out.append({"id": f"cpi-estimado-{ym}", "date": f"{ym}-12", "date_precision": "month",
                        "status": "scheduled_estimate", "category": "MACRO_DATA", "subcategory": "CPI",
                        "country": "US", "title_es": f"CPI EE.UU. (fecha por confirmar, {ym})",
                        "why_es": "Inflación vs consenso: mueve la expectativa de tasas en minutos.",
                        "crypto_stance": "uncertain", "prior_tier": 3,
                        "source_url": "https://www.bls.gov/schedule/news_release/cpi.htm",
                        "source_title": "Estimado: BLS publica a mediados de mes", "origin": "regla"})
        if ym > last_nfp[:7] and not _has(curated, ("NFP",), y, m):
            d = first_friday(y, m)
            out.append({"id": f"nfp-estimado-{ym}", "date": str(d), "time_local": "08:30", "tz": "America/New_York",
                        "date_precision": "day", "status": "scheduled_estimate", "category": "MACRO_DATA",
                        "subcategory": "NFP", "country": "US", "title_es": f"Empleo EE.UU. / NFP (estimado {d})",
                        "why_es": "Empleo vs consenso: cambia la probabilidad de recortes/alzas de la Fed.",
                        "crypto_stance": "uncertain", "prior_tier": 3,
                        "source_url": "https://www.bls.gov/schedule/news_release/empsit.htm",
                        "source_title": "Estimado: primer viernes del mes", "origin": "regla"})
        if m == 8 and not _has(curated, ("JACKSON_HOLE",), y, m):
            out.append({"id": f"jackson-hole-estimado-{y}", "date": f"{y}-08-22", "date_precision": "month",
                        "status": "scheduled_estimate", "category": "MONETARY_POLICY", "subcategory": "JACKSON_HOLE",
                        "country": "US", "title_es": f"Simposio de Jackson Hole {y} (fecha por confirmar)",
                        "why_es": "Discurso del presidente de la Fed: históricamente marca giros de política.",
                        "crypto_stance": "uncertain", "prior_tier": 3,
                        "source_url": "https://www.kansascityfed.org/research/jackson-hole-economic-symposium/",
                        "source_title": "Estimado: finales de agosto", "origin": "regla"})
    return [e for e in out if start <= date.fromisoformat(e["date"]) <= end]


def halving_estimate(height: int, at: datetime, minutes_per_block: float = 10.0) -> dict:
    """Fecha estimada del próximo halving desde una altura de bloque observada."""
    nxt = (height // HALVING_EVERY + 1) * HALVING_EVERY
    eta = at + timedelta(minutes=(nxt - height) * minutes_per_block)
    return {"id": f"btc-halving-{nxt}", "date": eta.date().isoformat(), "date_precision": "day",
            "status": "scheduled_estimate", "category": "CRYPTO_STRUCTURAL", "subcategory": "HALVING",
            "country": "GLOBAL", "title_es": f"Halving de Bitcoin (bloque {nxt:,}) — estimado",
            "why_es": "La emisión nueva baja a la mitad; históricamente precede ciclos alcistas (con rezago de meses).",
            "crypto_stance": "pro", "prior_tier": 4, "source_url": "https://mempool.space",
            "source_title": f"Estimado desde el bloque {height:,} a {minutes_per_block} min/bloque", "origin": "regla",
            "block": nxt}


def generate(start: date, end: date, curated: list) -> list[dict]:
    return derivatives_expiries(start, end) + macro_estimates(start, end, curated)


def utc_today() -> date:
    return datetime.now(timezone.utc).date()
