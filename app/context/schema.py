"""Esquema único de eventos (calendario a futuro e historia) + normalización a UTC.

Un evento es un dict plano. Campos obligatorios: id, date, category, country, title_es.
Todo lo que entra (investigación, noticias, LLM) pasa por normalize() antes de guardarse.
"""
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

CATEGORIES = {
    # código: (etiqueta, cómo se obtiene la dirección del efecto)
    #   "stance"   → del atributo crypto_stance (pro/anti/neutral), conocido antes o al momento del evento
    #   "surprise" → solo se sabe al publicarse el dato (halcón/paloma, arriba/abajo del consenso)
    #   "none"     → solo mueve volatilidad, no dirección
    "MONETARY_POLICY": ("Política monetaria", "surprise"),
    "MACRO_DATA": ("Dato macro", "surprise"),
    "FISCAL": ("Fiscal / deuda", "stance"),
    "TRADE": ("Comercio / aranceles", "stance"),
    "ELECTION": ("Elección", "stance"),
    "GOV_TRANSITION": ("Cambio de gobierno", "stance"),
    "CRYPTO_REGULATION": ("Regulación cripto", "stance"),
    "TECH_AI_REGULATION": ("Regulación tecnología / IA", "stance"),
    "PATENT_LICENSE": ("Patentes / licencias", "stance"),
    "CRYPTO_STRUCTURAL": ("Estructura cripto (halving, ETF, upgrades)", "stance"),
    "CRYPTO_SUPPLY": ("Oferta cripto (Mt. Gox, gobiernos, unlocks)", "stance"),
    "INSTITUTIONAL_ADOPTION": ("Adopción institucional", "stance"),
    "GEOPOLITICAL": ("Geopolítica", "stance"),
    "FINANCIAL_CRISIS": ("Crisis financiera / quiebras", "stance"),
    "HACK_SECURITY": ("Hackeo / seguridad", "stance"),
    "ONCHAIN_WHALE": ("Ballenas on-chain / era Satoshi", "stance"),
    "PANDEMIC_HEALTH": ("Pandemia / salud", "stance"),
    "DERIVATIVES_EXPIRY": ("Vencimiento de derivados", "none"),
}
STANCE_SIGN = {"pro": 1, "anti": -1, "neutral": 0, "uncertain": 0, None: 0}
STATUSES = ("confirmed", "scheduled_estimate", "expected", "speculative", "happened", "proposed")
# probabilidad de que el evento ocurra en la fecha indicada (para ponderar riesgo a futuro)
P_OCCUR = {"confirmed": 1.0, "happened": 1.0, "scheduled_estimate": 0.8, "expected": 0.7,
           "proposed": 0.5, "speculative": 0.35}
PRECISIONS = ("exact", "day", "month", "quarter", "year")
TIER_LABEL = {1: "mínimo", 2: "bajo", 3: "medio", 4: "alto", 5: "crítico"}


def slug(s: str, n: int = 60) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:n] or "evento"


def parse_day(s) -> date:
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    return date.fromisoformat(str(s)[:10])


def event_utc(e: dict) -> datetime:
    """Instante UTC del evento. Con hora local + zona → conversión exacta (respeta horario de verano).
    Sin hora: mediodía UTC del día (marcador; las ventanas de día completo usan day_window())."""
    d = parse_day(e["date"])
    if e.get("time_local") and e.get("tz"):
        hh, mm = (int(x) for x in str(e["time_local"]).split(":")[:2])
        return datetime.combine(d, time(hh, mm), ZoneInfo(e["tz"])).astimezone(timezone.utc)
    return datetime.combine(d, time(12, 0), timezone.utc)


def day_window(e: dict) -> tuple[datetime, datetime]:
    """Ventana en la que 'pasa' el evento: el minuto exacto si hay hora; si no, el día completo UTC."""
    if e.get("time_local") and e.get("tz"):
        t = event_utc(e)
        return t, t
    d = parse_day(e["date"])
    start = datetime.combine(d, time(0, 0), timezone.utc)
    return start, start + timedelta(days=1)


def normalize(e: dict, default_status: str = "confirmed") -> dict:
    """Valida y completa un evento. Lanza ValueError si falta algo esencial (no se guardan eventos a medias)."""
    e = {k: v for k, v in e.items() if v is not None or k in ("time_local", "tz")}
    for k in ("date", "category", "title_es"):
        if not e.get(k):
            raise ValueError(f"evento sin {k}: {e.get('id') or e}")
    parse_day(e["date"])
    if e["category"] not in CATEGORIES:
        raise ValueError(f"categoría desconocida {e['category']} en {e.get('id')}")
    e.setdefault("country", "GLOBAL")
    e["country"] = str(e["country"]).upper()
    e.setdefault("status", default_status)
    if e["status"] not in STATUSES:
        raise ValueError(f"status inválido {e['status']} en {e.get('id')}")
    e.setdefault("date_precision", "exact" if e.get("time_local") else "day")
    if e["date_precision"] not in PRECISIONS:
        e["date_precision"] = "day"
    stance = e.get("crypto_stance") or "neutral"
    e["crypto_stance"] = stance if stance in STANCE_SIGN else "uncertain"
    try:
        e["prior_tier"] = max(1, min(5, int(e.get("prior_tier") or 2)))
    except (TypeError, ValueError):
        e["prior_tier"] = 2
    if "confidence" in e:
        try:
            c = float(e["confidence"])
            e["confidence"] = max(0.0, min(1.0, c / 100 if c > 1 else c))  # el LLM a veces responde 85 en vez de 0.85
        except (TypeError, ValueError):
            e["confidence"] = 0.5
    e.setdefault("subcategory", "")
    if e.get("time_local") and not e.get("tz"):
        e["tz"] = "UTC"
    if not e.get("id"):
        e["id"] = f"{slug(e['subcategory'] or e['category'], 30)}-{e['country'].lower()}-{e['date']}"
    e["id"] = slug(e["id"], 90)
    e["utc"] = event_utc(e).strftime("%Y-%m-%dT%H:%M:%SZ")
    return e


def sign(e: dict) -> int:
    return STANCE_SIGN.get(e.get("crypto_stance"), 0)


def label(cat: str) -> str:
    return CATEGORIES.get(cat, (cat, ""))[0]
