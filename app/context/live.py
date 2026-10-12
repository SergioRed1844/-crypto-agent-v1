"""Contexto en vivo para el servidor de trading.

El servidor NO corre el refresco pesado: lee los archivos que generan GitHub Actions. Con CONTEXT_REMOTE_BASE
(p.ej. https://raw.githubusercontent.com/<usuario>/<repo>/v4.2-contexto/data/context/) los baja cada
CONTEXT_REFRESH_MIN minutos; si no, usa los del disco. Si la descarga falla se queda con la última copia buena
y la señal se marca 'vieja' (estado CAUTION a partir de 36 h): nunca se inventa contexto.
El blackout y las alertas se evalúan con la hora ACTUAL en cada llamada (no con la de la última corrida).
"""
import json
import logging
import os
import threading
import time
from pathlib import Path

import httpx

from . import ctx_dir, read_json, utcnow
from . import engine, onchain
from .pipeline import input_ages
from .schema import normalize

log = logging.getLogger("context.live")
FILES = ("calendar.json", "alerts_onchain.json", "macro.json", "news_events.json", "weights.json", "onchain_state.json")
_lock = threading.Lock()
_cache = {"t": 0.0, "files": {}, "errors": {}}


def _remote(name: str):
    base = os.environ.get("CONTEXT_REMOTE_BASE", "")
    if not base:
        return read_json(name)
    r = httpx.get(base.rstrip("/") + "/" + name, timeout=8, headers={"User-Agent": "cryptoagent-server"})
    r.raise_for_status()
    return r.json()


def load(force: bool = False) -> dict:
    every = 60 * float(os.environ.get("CONTEXT_REFRESH_MIN", "10"))
    with _lock:
        if not force and time.time() - _cache["t"] < every and _cache["files"]:
            return _cache["files"]
        _cache["t"] = time.time()  # otro hilo no repite la descarga mientras esta corre
    got, errs = {}, {}
    for n in FILES:  # descarga FUERA del candado: un GitHub lento no bloquea a quien lee el caché
        try:
            v = _remote(n)
            if v is not None:
                got[n] = v
        except Exception as e:
            errs[n] = f"{type(e).__name__}"
    with _lock:
        _cache["files"].update(got)
        for n in got:
            _cache["errors"].pop(n, None)
        _cache["errors"].update(errs)
        # alertas que detecta el propio servidor (vigía en vivo) se suman a las del repo
        local = read_json("alerts_live.json", {}) or {}
        if local.get("alerts"):
            base = (_cache["files"].get("alerts_onchain.json") or {}).get("alerts", [])
            ids = {a["id"] for a in base}
            _cache["files"]["alerts_onchain.json"] = {"alerts": base + [a for a in local["alerts"] if a["id"] not in ids]}
        return dict(_cache["files"])


def _recent(files: dict, now):
    from datetime import timedelta
    from . import iso
    lim, out = iso(now - timedelta(days=60)), []
    hist = read_json("sources/history_events.json", []) or []  # viaja con el código
    for e in hist + (files.get("news_events.json") or {}).get("events", []):
        try:
            e = normalize(e, "happened")
        except ValueError:
            continue
        if lim <= e["utc"] <= iso(now):
            out.append(e)
    return out


def signal(market: dict | None = None) -> dict:
    if os.environ.get("CONTEXT_ENABLED", "true").lower() not in ("1", "true", "yes"):
        return {"state": "NEUTRAL", "veto_entries": False, "exit_all": False, "exit_alert_ids": [], "size_mult": 1.0,
                "bias": 0.0, "event_risk": 0.0, "extra_confluence": 0, "vote": "FLAT", "confidence": 30,
                "reasons": ["Contexto desactivado (CONTEXT_ENABLED=false)"], "upcoming": [], "recent": [], "alerts": []}
    if os.environ.get("DATA_MODE", "live").lower() == "mock":
        return mock_signal(os.environ.get("CONTEXT_MOCK_STATE", "NEUTRAL"))
    now = utcnow()
    f = load()
    cal = (f.get("calendar.json") or {}).get("events") or []
    if not cal:
        from . import event_calendar
        cal = event_calendar.build(now)
    mac = f.get("macro.json") or {}
    age = input_ages(mac, f.get("news_events.json") or {}, f.get("onchain_state.json") or {}, now)
    sig = engine.compute(now, cal, _recent(f, now), (f.get("alerts_onchain.json") or {}).get("alerts", []), mac,
                         market, weights=f.get("weights.json"), inputs_age_h=999.0 if age is None else age)
    sig["fetch_errors"] = dict(_cache["errors"])
    return engine.apply_mode(sig, os.environ.get("CONTEXT_MODE", "completo").lower())


def mock_signal(state: str = "NEUTRAL") -> dict:
    """DATA_MODE=mock (pruebas sin red): señal fija. CONTEXT_MOCK_STATE fuerza un estado; EXIT simula alerta crítica."""
    st = state.upper()
    ex = st == "EXIT"
    st = "RISK_OFF" if ex else st if st in engine.STATE_SIZE else "NEUTRAL"
    return {"generated_utc": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "state": st,
            "veto_entries": st in ("BLACKOUT", "RISK_OFF"), "exit_all": ex,
            "exit_alert_ids": ["SATOSHI_ERA-mock"] if ex else [], "size_mult": engine.STATE_SIZE[st],
            "bias": {"RISK_ON": 0.4, "RISK_OFF": -0.6, "CAUTION": -0.25}.get(st, 0.0), "event_risk": 0.0,
            "extra_confluence": 2 if st == "CAUTION" else 0, "vote": "LONG" if st == "RISK_ON" else "FLAT",
            "confidence": 50, "reasons": [f"Contexto mock ({st})"], "upcoming": [], "recent": [], "alerts": [],
            "stale": False}


def live_onchain_scan(state_dir: str | None = None, max_blocks: int = 3) -> list:
    """Vigía on-chain dentro del servidor (CONTEXT_ONCHAIN_LIVE=true): reacción en minutos, no en una hora."""
    d = Path(state_dir or os.environ.get("CONTEXT_STATE_DIR", ctx_dir()))
    d.mkdir(parents=True, exist_ok=True)
    with onchain.EsploraClient() as c:
        new = onchain.scan(c, d / "onchain_state_live.json", ctx_dir() / "alerts_live.json", {"max_blocks": max_blocks})
    if new:
        load(force=True)
    return new


def summary(sig: dict) -> str:
    return json.dumps({k: sig.get(k) for k in ("state", "bias", "event_risk", "size_mult", "veto_entries", "exit_all")})
