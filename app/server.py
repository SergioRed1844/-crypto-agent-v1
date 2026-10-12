"""Servidor FastAPI.

/webhook solo valida y GUARDA la señal (responde en ms; TradingView corta a los 3 s).
Un worker único (el "líder") consume la cola en orden y reconcilia posiciones. En un deploy de Render
conviven dos instancias unos segundos: el advisory lock de Postgres garantiza que solo una opere.
"""
import asyncio
import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from . import config, execution, store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("server")
_trade_lock = asyncio.Lock()  # serializa grafo, kill y flatten dentro del líder
_state = {"leader": False, "started": None}
H4_MS = 4 * 3_600_000


def _eq(a: str, b: str) -> bool:
    return bool(b) and hmac.compare_digest(str(a).encode(), str(b).encode())


async def _process(signal: dict):
    from .graph import run
    try:
        out = await run(signal)
        log.info(f"{signal['pair']}: {out.get('final_action')}")
    except Exception as e:
        log.exception(f"grafo falló para {signal['pair']}: {e}")
        store.finish_decision(signal["signal_id"], "ERROR", str(e)[:500], {"signal": signal})


async def _context_tick(st: dict | None = None):
    """Recalcula el contexto; con alerta CRÍTICA on-chain vende todo a USDT y deja el kill switch activo
    (reanudar con /resume después de revisar). Una alerta se marca atendida solo cuando ya no quedan posiciones
    abiertas: si la venta falló (UNPROTECTED), el siguiente tick lo vuelve a intentar."""
    from .context import live
    sig = await asyncio.to_thread(live.signal, None)
    store.put("context_last", {k: sig.get(k) for k in ("generated_utc", "state", "bias", "event_risk", "size_mult",
                                                         "veto_entries", "exit_all", "reasons")})
    if not (sig.get("exit_all") and config.CONTEXT_EXIT_ON_CRITICAL):
        return
    done = set(store.get("context_exit_done", []) or [])
    new = [i for i in sig.get("exit_alert_ids", []) if i not in done]
    if not new:
        return
    store.put("kill_switch", True)
    store.put("kill_reason", f"contexto: alerta crítica on-chain {new}")
    async with _trade_lock:
        res = await asyncio.to_thread(execution.emergency_flatten)
    left = store.open_positions()
    if not left:
        store.put("context_exit_done", sorted(done | set(new)))
    store.put("flatten_result", {"ts": store.now().isoformat(), "result": res, "reason": "context_exit"})
    log.critical(f"CONTEXTO: alerta crítica {new} → salida a USDT y kill switch: {res}"
                 f"{'' if not left else f' — quedan {len(left)} posiciones, se reintenta'}")


async def _context_loop():
    """Tarea propia (no frena al líder): cada minuto, si esta instancia es líder, evalúa el contexto."""
    while True:
        try:
            if config.CONTEXT_ENABLED and _state["leader"]:
                await _context_tick()
        except Exception as e:
            log.warning(f"contexto: {e}")
        await asyncio.sleep(60)


async def _onchain_loop():
    """CONTEXT_ONCHAIN_LIVE=true: vigía on-chain dentro del servidor cada 5 min, en su propia tarea."""
    from .context import live
    while True:
        try:
            if _state["leader"]:
                new = await asyncio.to_thread(live.live_onchain_scan)
                if new:
                    log.warning(f"vigía on-chain en vivo: {len(new)} alertas nuevas")
        except Exception as e:
            log.warning(f"vigía on-chain en vivo: {e}")
        await asyncio.sleep(300)


async def _leader_loop():
    """Nunca muere: cualquier error se registra y se reintenta. En cada vuelta confirma que sigue siendo
    líder; si perdió el lock (conexión caída), deja de operar hasta recuperarlo."""
    last_rec = 0.0
    loop = asyncio.get_running_loop()
    while True:
        try:
            if not await asyncio.to_thread(store.try_become_leader):
                if _state["leader"]:
                    log.critical("perdí el lock de líder; dejo de operar")
                _state["leader"] = False
                await asyncio.sleep(5)
                continue
            if not _state["leader"]:
                _state["leader"] = True
                log.info("esta instancia es LÍDER")
                await asyncio.to_thread(store.expire_stale_processing, 10)
            if store.get("flatten_requested", False):  # /kill?flatten pudo llegar a otra instancia
                async with _trade_lock:
                    res = await asyncio.to_thread(execution.emergency_flatten)
                store.put("flatten_result", {"ts": store.now().isoformat(), "result": res})
                store.put("flatten_requested", False)
                log.warning(f"flatten ejecutado: {res}")
            if loop.time() - last_rec >= 300 or last_rec == 0.0:
                async with _trade_lock:
                    res = await asyncio.to_thread(execution.reconcile)
                if res:
                    log.info(f"reconcile: {res}")
                last_rec = loop.time()
            sig = await asyncio.to_thread(store.next_pending_signal, 20)
            if sig:
                async with _trade_lock:
                    await _process(sig)
                continue
        except Exception as e:
            log.exception(f"loop líder: {e}")
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app):
    if config.TRADING_MODE != "paper":
        if not (config.BINANCE_API_KEY and config.BINANCE_SECRET):
            raise RuntimeError("TRADING_MODE testnet/live requiere BINANCE_API_KEY y BINANCE_SECRET")
        if store.IS_SQLITE:
            raise RuntimeError("testnet/live requiere Postgres en DATABASE_URL (el disco de Render se borra en cada deploy)")
        if store.POOLED_URL:
            raise RuntimeError("DATABASE_URL apunta a un pooler (PgBouncer/-pooler/6543): usa la conexión DIRECTA")
    foreign = store.foreign_live_positions()
    if foreign:
        raise RuntimeError(f"Hay posiciones vivas de otro modo: {foreign}. Ciérralas o usa otra base de datos.")
    if not config.ADMIN_SECRET or config.ADMIN_SECRET == config.WEBHOOK_SECRET:
        log.warning("ADMIN_SECRET vacío o igual a WEBHOOK_SECRET: /status, /decisions y /kill quedan bloqueados")
    _state["started"] = store.now()
    task = asyncio.create_task(_leader_loop())
    side = [asyncio.create_task(_context_loop())]
    if config.CONTEXT_ONCHAIN_LIVE:
        side.append(asyncio.create_task(_onchain_loop()))
    log.info(f"CryptoAgent {config.RELEASE_ID} | modo={config.TRADING_MODE} | llm={config.LLM_PROVIDER}:{config.GEMINI_MODEL}")
    yield
    task.cancel()
    for t in side:
        t.cancel()


app = FastAPI(title="CryptoAgent v4", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def _validate(sig: dict) -> str | None:
    """Esquema + timeframe + frescura: rechaza replays, alertas de otro timeframe y payloads incoherentes."""
    try:
        price = float(sig.get("price", 0))
        bar_time = int(sig.get("bar_time", 0))
    except (TypeError, ValueError):
        return "price/bar_time no numéricos"
    if price <= 0:
        return "price inválido"
    if str(sig.get("timeframe")) != "240" or bar_time % H4_MS != 0:
        return f"timeframe {sig.get('timeframe')} no es 4H (las reglas solo se validaron en 4H)"
    since_close_min = (store.now().timestamp() * 1000 - (bar_time + H4_MS)) / 60_000  # bar_time = apertura
    if not (-1 <= since_close_min <= config.SIGNAL_MAX_AGE_MIN):
        return f"señal vieja o del futuro ({since_close_min:.0f} min desde el cierre de la vela)"
    if sig.get("signal_type") != "BAR_CLOSE":
        return "signal_type desconocido"
    return None


def _client_ip(request: Request) -> str:
    """Render AGREGA la IP real al final de X-Forwarded-For; lo de la izquierda lo puede inventar cualquiera.
    Se usa la entrada de la derecha (TV_XFF_INDEX=-1). Revisa el log 'xff' con una alerta real al desplegar."""
    xff = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
    if not xff:
        return request.client.host if request.client else ""
    try:
        return xff[config.TV_XFF_INDEX]
    except IndexError:
        return xff[-1]


@app.post("/webhook")
async def webhook(request: Request):
    ip = _client_ip(request)
    log.info(f"xff={request.headers.get('x-forwarded-for', '')!r} ip_usada={ip}")
    if config.TV_IP_ALLOWLIST and ip not in config.TV_IPS:
        raise HTTPException(403, "origen no permitido")
    try:
        sig = json.loads(await request.body())
    except Exception:
        raise HTTPException(400, "JSON inválido")
    if not isinstance(sig, dict) or not _eq(sig.pop("secret", ""), config.WEBHOOK_SECRET):
        raise HTTPException(401, "secret inválido")
    pair = str(sig.get("pair", "")).upper().replace("BINANCE:", "")
    if pair not in config.ALLOWED_PAIRS:
        return {"status": "ignored", "reason": f"{pair} fuera de ALLOWED_PAIRS"}
    sig["pair"] = pair
    if err := _validate(sig):
        return {"status": "rejected", "reason": err}
    # id estable: par + vela. Reintento o alerta duplicada → misma fila, no dos compras.
    sig["signal_id"] = hashlib.sha1(f"{pair}|{sig['bar_time']}".encode()).hexdigest()[:16]
    if not store.claim_signal(sig["signal_id"], pair, sig):  # atómico (UNIQUE), persiste antes del 200
        return {"status": "duplicate"}
    store.put("last_signal", {"pair": pair, "ts": store.now().isoformat()})
    if store.get("kill_switch", False):
        store.finish_decision(sig["signal_id"], "BLOCKED", "kill_switch activo", {"signal": sig})
        return {"status": "blocked", "reason": "kill_switch"}
    return {"status": "accepted", "signal_id": sig["signal_id"]}


@app.get("/health")
async def health():
    """Para el monitor de uptime. 503 si el líder no ha reconciliado en 15 min: el proceso vive pero
    nadie vigila las posiciones. Las instancias no líderes responden 200 con leader=false."""
    try:
        last = store.get("last_reconcile")
    except Exception:
        return JSONResponse({"ok": False, "error": "base de datos inaccesible"}, status_code=503)
    started = (store.now() - _state["started"]).total_seconds()
    stale = (not last and started > 120) or (
        bool(last) and (store.now() - store.as_utc(datetime.fromisoformat(last))).total_seconds() > 900)
    body = {"ok": not stale, "leader": _state["leader"], "release": config.RELEASE_ID,
            "mode": config.TRADING_MODE, "last_reconcile": last, "kill_switch": store.get("kill_switch", False)}
    # last_reconcile es global (BD): cualquier instancia reporta 503 si NADIE está reconciliando
    return JSONResponse(body, status_code=503 if stale else 200)


def _admin(req: Request):
    if config.ADMIN_SECRET == config.WEBHOOK_SECRET or not _eq(req.headers.get("x-admin-secret", ""), config.ADMIN_SECRET):
        raise HTTPException(401)


@app.get("/status")
async def status(request: Request):
    _admin(request)
    eq, free = await asyncio.to_thread(execution.equity)
    return {"release": config.RELEASE_ID, "mode": config.TRADING_MODE, "leader": _state["leader"],
            "llm": f"{config.LLM_PROVIDER}:{config.GEMINI_MODEL}", "equity_usdt": round(eq, 2),
            "usdt_free": round(free, 2), "kill_switch": store.get("kill_switch", False),
            "last_signal": store.get("last_signal"), "last_reconcile": store.get("last_reconcile"),
            "open_positions": store.open_positions(), "stats": store.stats(),
            "shadow_stats": store.stats(shadow=True), "pairs": config.ALLOWED_PAIRS,
            "context": store.get("context_last"), "losing_streak": store.consecutive_losses(),
            "kill_reason": store.get("kill_reason")}


@app.get("/context")
async def context_now(request: Request):
    """Señal de contexto en vivo (estado, sesgo, riesgo de evento, próximos eventos, alertas)."""
    _admin(request)
    from .context import live
    return await asyncio.to_thread(live.signal, None)


@app.post("/admin/reset-streak")
async def reset_streak(request: Request):
    """Reinicia la racha de pérdidas (después de revisar qué pasó). No toca ningún otro límite."""
    _admin(request)
    store.put("streak_reset_at", store.now().isoformat())
    return {"streak_reset_at": store.get("streak_reset_at"), "losing_streak": store.consecutive_losses()}


@app.get("/decisions")
async def decisions(request: Request, limit: int = 30):
    _admin(request)
    with store.engine.begin() as c:
        rows = c.execute(select(store.decisions).order_by(store.decisions.c.ts.desc()).limit(min(limit, 200))).mappings()
        return [{**dict(r), "payload": json.loads(r["payload"] or "{}")} for r in rows]


@app.post("/kill")
async def kill(request: Request, flatten: bool = False):
    """Activa el kill switch (lo respetan el webhook y la compra). ?flatten=true pide al LÍDER cerrar lo que
    abrió el bot (bajo su candado de trading, sin carreras con una compra en curso). Espera hasta 60 s."""
    _admin(request)
    store.put("kill_switch", True)
    if not flatten:
        return {"kill_switch": True}
    t0 = store.now()
    store.put("flatten_requested", True)
    for _ in range(120):
        await asyncio.sleep(0.5)
        r = store.get("flatten_result")
        if r and store.as_utc(datetime.fromisoformat(r["ts"])) >= t0:
            return {"kill_switch": True, "flattened": r["result"]}
    return {"kill_switch": True, "flattened": "solicitado; el líder lo ejecutará (revisa /status)"}


@app.post("/resume")
async def resume(request: Request):
    _admin(request)
    store.put("kill_switch", False)
    return {"kill_switch": False}
