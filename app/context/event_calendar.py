"""Calendario maestro a 3 años: eventos curados (investigación verificada con fuente) + eventos por regla.

Archivos (data/context/):
  sources/calendar_curated.json  ← curado: bancos centrales, datos, elecciones, regulación, oferta (con fuente)
  calendar.json                  ← generado: curado + reglas, normalizado a UTC, ordenado
  CALENDARIO.md                  ← vista legible en GitHub
"""
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import ctx_dir, iso, read_json, recurring, utcnow, write_json
from .schema import TIER_LABEL, label, normalize, parse_day

MTY = ZoneInfo("America/Monterrey")
HORIZON_YEARS = 3


def load_curated() -> list[dict]:
    out, bad = [], []
    for e in read_json("sources/calendar_curated.json", []) or []:
        try:
            out.append(normalize(e))
        except ValueError as ex:
            bad.append(str(ex))
    if bad:
        import logging
        logging.getLogger("calendar").warning(f"{len(bad)} eventos curados inválidos: {bad[:3]}")
    return out


def is_dup(e: dict, curated: list[dict]) -> bool:
    """¿Ya está en el calendario curado? Misma categoría y país, fecha a ±2 días."""
    d = parse_day(e["date"])
    return any(c["category"] == e["category"] and c["country"] == e["country"] and
               abs((parse_day(c["date"]) - d).days) <= 2 for c in curated)


def load_proposed(curated: list[dict]) -> list[dict]:
    """Propuestas (auditoría Gemini / noticias) que aún no confirma una fuente curada. Nunca disparan blackout."""
    out = []
    for e in read_json("sources/calendar_proposed.json", []) or []:
        try:
            e = normalize(e, "proposed")
        except ValueError:
            continue
        if not is_dup(e, curated):
            e["status"] = "proposed"
            out.append(e)
    return out


def _dedup(events: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in sorted(events, key=lambda x: (x["utc"], -x["prior_tier"])):
        k = (e["category"], e.get("subcategory"), e["country"], e["utc"][:10])
        if k in seen or e["id"] in seen:
            continue
        seen.update({k, e["id"]})
        out.append(e)
    return out


def build(now: datetime | None = None, years: int = HORIZON_YEARS, keep_past_days: int = 45) -> list[dict]:
    now = now or utcnow()
    start, end = (now - timedelta(days=keep_past_days)).date(), date(now.year + years, now.month, min(now.day, 28))
    curated = load_curated()
    rules = [normalize(e) for e in recurring.generate(now.date(), end, curated)]
    cal = [e for e in curated + rules + load_proposed(curated) if start <= parse_day(e["date"]) <= end]
    return _dedup(cal)


def upcoming(cal: list[dict], now: datetime, hours: float, min_tier: int = 1) -> list[dict]:
    lim = now + timedelta(hours=hours)
    return [e for e in cal if e["prior_tier"] >= min_tier and
            now - timedelta(hours=1) <= datetime.fromisoformat(e["utc"].replace("Z", "+00:00")) <= lim]


def coverage(cal: list[dict], now: datetime) -> dict:
    """Auditoría de huecos: meses sin decisión de Fed, sin dato de inflación, etc. La usa el refresco."""
    months = {}
    for e in cal:
        months.setdefault(e["utc"][:7], Counter())[e.get("subcategory") or e["category"]] += 1
    gaps = []
    y, m = now.year, now.month
    for _ in range(HORIZON_YEARS * 12):
        ym = f"{y:04d}-{m:02d}"
        c = months.get(ym, Counter())
        if m in recurring.FOMC_MONTHS and not (c["FOMC"] or c["FOMC_SEP"]):
            gaps.append(f"{ym}: sin FOMC")
        if not c["CPI"]:
            gaps.append(f"{ym}: sin CPI")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    by_status = Counter(e["status"] for e in cal if e["utc"] >= iso(now))
    return {"eventos_a_futuro": sum(by_status.values()), "por_status": dict(by_status), "huecos": gaps[:40]}


def _mty(e: dict) -> str:
    if e["date_precision"] in ("exact",) and e.get("time_local"):
        dt = datetime.fromisoformat(e["utc"].replace("Z", "+00:00")).astimezone(MTY)
        return dt.strftime("%Y-%m-%d %H:%M")
    if e["date_precision"] == "month":
        return e["utc"][:7] + " (mes)"
    if e["date_precision"] in ("quarter", "year"):
        return e["utc"][:7] + f" ({e['date_precision']})"
    return e["utc"][:10]


STATUS_ES = {"confirmed": "confirmado", "scheduled_estimate": "estimado", "expected": "esperado",
             "speculative": "especulativo", "happened": "ocurrió", "proposed": "propuesto (revisar)"}


def render_md(cal: list[dict], now: datetime, weights: dict | None = None) -> str:
    fut = [e for e in cal if e["utc"] >= iso(now - timedelta(days=1))]
    cov = coverage(cal, now)
    hi = [e for e in fut if e["prior_tier"] >= 4][:25]
    L = ["# Calendario de contexto — 3 años", "",
         f"Generado {now.astimezone(MTY):%Y-%m-%d %H:%M} (Monterrey). {len(fut)} eventos a futuro "
         f"({', '.join(f'{STATUS_ES.get(k, k)} {v}' for k, v in cov['por_status'].items())}). "
         "Horas en Monterrey; 'mes' = fecha aún no publicada (estimado por regla).", "",
         "Importancia: ★ 1 (mínimo) … ★★★★★ 5 (crítico). Los pesos los recalibra el estudio de eventos "
         "(`weights.json`); la importancia aquí es la a priori de la investigación.", "",
         "## Próximos eventos de alto impacto (★4–5)", "",
         "| Fecha (MTY) | Evento | Categoría | País | Estado | ★ |", "|---|---|---|---|---|---|"]
    for e in hi:
        L.append(f"| {_mty(e)} | [{e['title_es']}]({e.get('source_url') or '#'}) | {label(e['category'])} | "
                 f"{e['country']} | {STATUS_ES.get(e['status'], e['status'])} | {'★' * e['prior_tier']} |")
    if cov["huecos"]:
        L += ["", "**Huecos detectados** (se llenan cuando la fuente oficial publique): " + "; ".join(cov["huecos"][:12])]
    cur = None
    for e in fut:
        ym = e["utc"][:7]
        if ym != cur:
            cur = ym
            L += ["", f"## {ym}", "", "| Fecha (MTY) | Evento | Categoría | País | Estado | ★ | Por qué importa |",
                  "|---|---|---|---|---|---|---|"]
        why = (e.get("why_es") or "").replace("|", "/")[:160]
        L.append(f"| {_mty(e)} | [{e['title_es']}]({e.get('source_url') or '#'}) | {label(e['category'])} | "
                 f"{e['country']} | {STATUS_ES.get(e['status'], e['status'])} | {'★' * e['prior_tier']} | {why} |")
    return "\n".join(L) + "\n"


def refresh_files(now: datetime | None = None) -> dict:
    now = now or utcnow()
    cal = build(now)
    write_json("calendar.json", {"generated_utc": iso(now), "horizon_years": HORIZON_YEARS, "events": cal})
    (ctx_dir() / "CALENDARIO.md").write_text(render_md(cal, now), encoding="utf-8")
    return {"events": len(cal), **coverage(cal, now)}


def load(now: datetime | None = None) -> list[dict]:
    """Calendario generado; si no existe (o está viejo), lo arma en memoria desde las fuentes."""
    j = read_json("calendar.json")
    if j and j.get("events"):
        return j["events"]
    return build(now)


TIER_TEXT = TIER_LABEL
