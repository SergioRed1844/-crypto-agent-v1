"""Calendario de resultados (Finnhub, opcional; requiere el secret FINNHUB_API_KEY, plan gratis de 60 llamadas/min).

Solo RESTA: si una acción de EUA reporta resultados en ≤ 3 días, la alerta baja a VIGILANCIA (comprar justo antes
del reporte es apostar al dato, no al setup). Sin llave, sin respuesta o para ETFs/BMV/cripto → no hace nada.
La llave va en un encabezado; nunca se registra ninguna URL.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from . import config as C

for _n in ("httpx", "httpcore"):
    logging.getLogger(_n).setLevel(logging.WARNING)

DAYS_BLOCK = int(os.getenv("RADAR_EARNINGS_BLOCK_DAYS", "3"))


def applies(sym: str) -> bool:
    return C.asset_class(sym) == "us" and sym not in C.BROAD


def next_earnings(sym: str, today: date | None = None, horizon_days: int = 30, client=None) -> dict | None:
    key = os.getenv("FINNHUB_API_KEY", "")
    if not key or not applies(sym):
        return None
    today = today or date.today()
    params = {"from": today.isoformat(), "to": (today + timedelta(days=horizon_days)).isoformat(), "symbol": sym}
    try:
        import httpx
        own = client is None
        client = client or httpx.Client(timeout=20)
        try:
            r = client.get("https://finnhub.io/api/v1/calendar/earnings", params=params,
                           headers={"X-Finnhub-Token": key})
            if r.status_code == 401:                 # algunas cuentas solo aceptan la llave como parámetro
                r = client.get("https://finnhub.io/api/v1/calendar/earnings", params=params | {"token": key})
        finally:
            if own:
                client.close()
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        rows = (r.json() or {}).get("earningsCalendar") or []
    except Exception as e:  # noqa: BLE001 — nunca la URL (lleva la llave en el respaldo)
        return {"error": type(e).__name__}
    dates = sorted(x.get("date") for x in rows if x.get("date") and x.get("symbol", sym) == sym)
    if not dates:
        return {"date": None}
    d0 = date.fromisoformat(dates[0])
    hour = next((x.get("hour") for x in rows if x.get("date") == dates[0]), "")
    return {"date": dates[0], "days": (d0 - today).days, "hour": hour or ""}


def blocks(info: dict | None) -> str | None:
    """Motivo para bajar a VIGILANCIA, o None."""
    if not info or info.get("date") is None or "days" not in info:
        return None
    if 0 <= info["days"] <= DAYS_BLOCK:
        when = {"bmo": "antes de la apertura", "amc": "después del cierre"}.get(info.get("hour"), "")
        return f"reporta resultados el {info['date']} {when}".strip() + f" (≤ {DAYS_BLOCK} días): riesgo de evento"
    return None
