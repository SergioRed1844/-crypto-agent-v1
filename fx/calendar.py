"""Relojes del agente FX: horas de los slots en UTC (con horario de verano real de cada país), día y semana FX,
salidas forzadas y blackouts de entrada (F15-017 C, F14-016).

Convenciones: el día FX cierra a las 17:00 de Nueva York; la semana FX abre el domingo 17:00 NY y cierra el viernes
17:00 NY. Todo el código trabaja en "minutos UTC desde 1970" (enteros) para empatar con las velas.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from . import config as C

NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def to_min(dt: datetime) -> int:
    return int(dt.astimezone(UTC).timestamp() // 60)


def from_min(m: int) -> datetime:
    return datetime.fromtimestamp(int(m) * 60, UTC)


def local_min(d: date, hhmm: str, tz: str) -> int:
    return to_min(datetime.combine(d, _hm(hhmm), ZoneInfo(tz)))


def slot_min(slot: C.Slot, d: date) -> int:
    """Minuto UTC del anuncio del slot en la fecha local ``d``."""
    return local_min(d, slot.hhmm, slot.tz)


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def ny(m: int) -> datetime:
    return from_min(m).astimezone(NY)


def fx_day(m: int) -> date:
    """Día FX (cierra 17:00 NY): sumar 7 h a la hora de NY y tomar la fecha."""
    return (ny(m) + timedelta(hours=7)).date()


def fx_week(m: int) -> str:
    """Semana FX (abre domingo 17:00 NY) como 'AAAA-Www' ISO."""
    y, w, _ = fx_day(m).isocalendar()
    return f"{y}-W{w:02d}"


def week_open_min(m: int) -> int:
    """Minuto UTC del domingo 17:00 NY que abrió la semana FX de ``m``."""
    d = fx_day(m)
    monday = d - timedelta(days=d.weekday())
    return local_min(monday - timedelta(days=1), C.WEEK_OPEN_NY[1], "America/New_York")


def next_week_open_min(m: int) -> int:
    d = fx_day(m)
    monday = d - timedelta(days=d.weekday()) + timedelta(days=7)
    return local_min(monday - timedelta(days=1), C.WEEK_OPEN_NY[1], "America/New_York")


def forced_exit_min(entry_m: int) -> int:
    """Hora límite para estar plano: 16:50 NY del mismo día de NY (15:55 NY si es viernes)."""
    t = ny(entry_m)
    cut = C.FRIDAY_CUTOFF_NY if t.weekday() == 4 else C.FORCE_EXIT_NY
    return to_min(datetime.combine(t.date(), _hm(cut), NY))


@lru_cache(maxsize=4096)
def _london_fix(d: date) -> int:
    tz, hhmm, _ = C.LONDON_FIX
    return local_min(d, hhmm, tz)


def entry_blackout(m: int, events: tuple[int, ...] = ()) -> str | None:
    """Motivo por el que NO se puede abrir en el minuto UTC ``m`` (None = permitido)."""
    t = ny(m)
    wd, hm = t.weekday(), t.hour * 60 + t.minute
    if wd == 5 or (wd == 6 and hm < 17 * 60) or (wd == 4 and hm >= 17 * 60):
        return "mercado cerrado"
    if wd == 4 and hm >= _mins(C.FRIDAY_CUTOFF_NY):
        return "viernes después de 15:55 NY"
    if hm >= _mins(C.FORCE_EXIT_NY) and hm < _mins(C.ROLLOVER_NY[1]):
        return "rollover 16:50–17:10 NY"
    (m1, d1), (m2, d2) = C.YEAR_END_BLACKOUT
    if (t.month == m1 and t.day >= d1) or (t.month == m2 and t.day <= d2):
        return "24-dic a 2-ene"
    _, _, w = C.LONDON_FIX
    fix = _london_fix(from_min(m).astimezone(ZoneInfo("Europe/London")).date())
    if abs(m - fix) <= w:
        return "fix de Londres ±2.5 min"
    for e in events:
        if -C.EVENT_GUARD_MIN <= m - e <= C.EVENT_GUARD_MIN:
            return "T−5/T+5 de evento mayor"
    if hm >= 17 * 60:
        return "después de 17:00 NY (sin slots; la salida forzada sería del día siguiente)"
    return None


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


# ── Calendario en vivo: eventos mayores confirmados del modelo de contexto v4.2 (solo para restar riesgo) ──────────
HIGH_IMPACT = ("FOMC", "Banxico", "NFP", "nómina", "IPC", "CPI", "BCE", "ECB", "Banco de Inglaterra", "BoE")


def known_events(path: str = "data/context/calendar.json") -> list[dict]:
    """Eventos confirmados con hora (``time_local`` + ``tz``). Sin hora o sin confirmar → no se usan."""
    if not os.path.exists(path):
        return []
    try:
        raw = json.load(open(path))
    except Exception:
        return []
    ev = raw if isinstance(raw, list) else raw.get("events", [])
    out = []
    for e in ev:
        if e.get("status") != "confirmed" or not e.get("time_local") or not e.get("tz"):
            continue
        title = e.get("title_es", "")
        if not any(k.lower() in title.lower() for k in HIGH_IMPACT):
            continue
        try:
            m = local_min(date.fromisoformat(e["date"]), e["time_local"], e["tz"])
        except Exception:
            continue
        out.append({"minute": m, "title": title, "source": e.get("source_url", "")})
    return sorted(out, key=lambda x: x["minute"])
