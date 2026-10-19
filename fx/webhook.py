"""Receptor de alertas de TradingView para el agente FX. Responde en milisegundos (TradingView corta a los 3 s y no
garantiza la entrega, F15-001): valida IP de origen, tamaño y secreto, guarda el intent de forma idempotente y
regresa. El motor lo procesa en su siguiente ciclo (≤ 250 ms).

Acciones aceptadas: FLATTEN (cerrar todo), PAUSE, RESUME (solo quita la pausa manual), CHECK y SIGNAL (telemetría:
la señal que vio TradingView se compara con la del motor; nunca abre una operación por sí sola).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import config as C
from .store import Store

ACTIONS = {"FLATTEN", "PAUSE", "RESUME", "CHECK", "SIGNAL"}
MAX_BODY = 4096


def make_app(store: Store, secret: str, allow_ips=C.TRADINGVIEW_IPS, trust_proxy: bool = False,
             extra_ips: tuple[str, ...] = (), heartbeat: str | None = None, mode: str = "paper"):
    if not secret or len(secret) < 16:
        raise RuntimeError("FX_WEBHOOK_SECRET debe tener al menos 16 caracteres")
    allowed = set(allow_ips) | set(extra_ips)
    app = FastAPI(title="fx-agente", docs_url=None, redoc_url=None, openapi_url=None)

    def client_ip(req: Request) -> str:
        if trust_proxy:
            xff = req.headers.get("x-forwarded-for", "")
            if xff:
                return xff.split(",")[0].strip()
        return req.client.host if req.client else ""

    @app.post("/tv")
    async def tv(req: Request):
        t0 = time.time()
        ip = client_ip(req)
        if ip not in allowed:
            return JSONResponse({"ok": False, "error": "ip"}, status_code=403)
        raw = await req.body()
        if len(raw) > MAX_BODY:
            return JSONResponse({"ok": False, "error": "tamaño"}, status_code=413)
        try:
            body = json.loads(raw)
            assert isinstance(body, dict)
        except Exception:
            return JSONResponse({"ok": False, "error": "json"}, status_code=400)
        if not hmac.compare_digest(str(body.get("secret", "")), secret):
            return JSONResponse({"ok": False, "error": "secreto"}, status_code=401)
        action = str(body.get("action", "")).upper()
        if action not in ACTIONS:
            return JSONResponse({"ok": False, "error": "acción"}, status_code=422)
        clean = {k: v for k, v in body.items() if k != "secret"}
        clean["action"] = action
        clean["t_recv"] = t0
        # Sin "id", el mismo mensaje fijo (p. ej. un FLATTEN guardado en TradingView) solo se deduplica dentro del
        # mismo minuto: los reintentos de TradingView caen juntos y un FLATTEN de mañana no se pierde.
        iid = str(body.get("id") or f"{hashlib.sha1(raw).hexdigest()[:24]}-{int(t0 // 60)}")[:80]
        new = store.put_intent(iid, clean, ip)
        if action == "SIGNAL" and new:
            store.done_intent(iid, "telemetría")
            store.log("tv_signal", clean, clean.get("sym"), iid)
        return {"ok": True, "dup": not new, "ms": round(1000 * (time.time() - t0), 2)}

    @app.get("/health")
    async def health():
        age = None
        if heartbeat and os.path.exists(heartbeat):
            age = round(time.time() - os.path.getmtime(heartbeat), 1)
        return {"ok": True, "mode": mode, "engine_heartbeat_age_s": age}

    return app
