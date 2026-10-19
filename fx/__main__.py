"""CLI del agente FX.

  python -m fx backtest --bars <fx-data>/bars       walk-forward + reporte + model.json
  python -m fx run                                   motor + webhook (FX_MODE=paper|practice; live exige confirmación)
  python -m fx monitor                               kill-switch independiente (otro proceso)
  python -m fx check                                 conectividad y latencia contra OANDA (sin órdenes)
  python -m fx smoke --yes                           practice: abre y cierra 1 unidad EUR/USD y mide latencia
  python -m fx latency | status                      reportes de la bitácora

Variables: FX_MODE, OANDA_TOKEN, OANDA_ACCOUNT_ID, FX_WEBHOOK_SECRET, FX_PORT (8080), FX_STATE_DIR (state),
FX_MODEL_PATH (data/fx/model.json), FX_MODEL_URL (opcional, se refresca cada 6 h), FX_CALENDAR_PATH,
FX_CALENDAR_URL (opcional), FX_PAPER_EQUITY (2000), FX_HOST (127.0.0.1; detrás de Caddy) y FX_TRUST_PROXY (1 si
un proxy local pone X-Forwarded-For).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import statistics
import sys
import time

from . import calendar as K
from . import config as C

STATE = os.environ.get("FX_STATE_DIR", "state")
MODEL_PATH = os.environ.get("FX_MODEL_PATH", os.path.join(C.DATA_DIR, "model.json"))
CAL_PATH = os.environ.get("FX_CALENDAR_PATH", "data/context/calendar.json")


def _paths():
    os.makedirs(STATE, exist_ok=True)
    return (os.path.join(STATE, "fx.db"), os.path.join(STATE, "engine.heartbeat.json"),
            os.path.join(STATE, "KILL"), os.path.join(STATE, "monitor.heartbeat"))


def _download(url: str, dest: str, kind: str = "model") -> bool:
    """Baja un JSON público (modelo o calendario) y lo reemplaza de forma atómica solo si es válido."""
    import httpx
    try:
        r = httpx.get(url, timeout=20)
        if r.status_code != 200:
            return False
        d = r.json()
        if kind == "model" and ("active" not in d or "scales" not in d):
            return False
        if kind == "calendar" and not (isinstance(d, list) or "events" in d):
            return False
        tmp = dest + ".tmp"
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(tmp, "w") as fh:
            json.dump(d, fh)
        os.replace(tmp, dest)
        return True
    except Exception:
        return False


async def _run():
    from .broker import OandaBroker, PaperBroker
    from .engine import Engine, load_model
    from .store import Store
    mode = C.mode()
    if mode == "backtest":
        raise SystemExit("FX_MODE=backtest no corre el motor; usa: python -m fx backtest")
    db, hb, kill, _ = _paths()
    store = Store(db)
    url = os.environ.get("FX_MODEL_URL")
    cal_url = os.environ.get("FX_CALENDAR_URL")
    if url:
        _download(url, MODEL_PATH)
    if cal_url:
        _download(cal_url, CAL_PATH, "calendar")
    model = load_model(MODEL_PATH)
    events = K.known_events(CAL_PATH)
    feed = OandaBroker("live" if mode == "live" else "practice")
    if mode == "paper":
        broker = PaperBroker(float(os.environ.get("FX_PAPER_EQUITY", "2000")))
        equity = broker.balance
    else:
        broker = feed
        acc = await feed.summary()
        if acc["currency"] != "USD":
            raise SystemExit(f"La cuenta está en {acc['currency']}: el motor calcula riesgo y topes en USD. Abre la "
                             "cuenta (o subcuenta) de OANDA en USD.")
        equity = acc["nav"]
    eng = Engine(broker, model, store, equity, mode, known_events=events, kill_path=kill)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sg in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sg, stop.set)
    syms = list(C.PAIRS)        # todos: si el modelo activa un par nuevo en el refresco, ya tiene precios

    def st(msg):
        eng.status["stream"] = msg
        store.log("stream", {"status": msg})

    tasks = [asyncio.create_task(feed.stream_prices(syms, eng.on_quote, stop, st)),
             asyncio.create_task(eng.run(stop, hb, store.pending_intents))]
    if mode == "paper":
        broker.on_tx = eng.on_tx
    else:
        tasks.append(asyncio.create_task(feed.stream_transactions(eng.on_tx, stop)))
    secret = os.environ.get("FX_WEBHOOK_SECRET")
    if secret:
        import uvicorn
        from .webhook import make_app
        app = make_app(store, secret, trust_proxy=os.environ.get("FX_TRUST_PROXY") == "1", heartbeat=hb, mode=mode)
        server = uvicorn.Server(uvicorn.Config(app, host=os.environ.get("FX_HOST", "127.0.0.1"),
                                               port=int(os.environ.get("FX_PORT", "8080")),
                                               log_level="warning", access_log=False))
        server.install_signal_handlers = lambda: None
        tasks.append(asyncio.create_task(server.serve()))

    async def refresh():
        while not stop.is_set():
            await asyncio.sleep(6 * 3600)
            if url and _download(url, MODEL_PATH):
                eng.model = load_model(MODEL_PATH)
                eng.planned_day = None
                store.log("model", {"refreshed": True, "trained_until": eng.model.get("trained_until")})
            if cal_url:
                _download(cal_url, CAL_PATH, "calendar")
            eng.known = [e["minute"] for e in K.known_events(CAL_PATH)]
    tasks.append(asyncio.create_task(refresh()))
    store.log("start", {"mode": mode, "equity": equity, "active": [list(k) for k in model["_active"]],
                        "trained_until": model.get("trained_until")})
    print(f"fx-agente {mode}: {len(model['_active'])} grupos activos; webhook {'sí' if secret else 'no'}",
          flush=True)
    await stop.wait()
    for t in tasks:
        t.cancel()
    await feed.aclose()


async def _monitor():
    from .broker import OandaBroker
    from .monitor import Monitor
    from .store import Store
    mode = C.mode()
    if mode == "paper":
        raise SystemExit("En paper el kill-switch vive dentro del motor; el monitor es para practice/live")
    db, hb, kill, mhb = _paths()
    b = OandaBroker("live" if mode == "live" else "practice")
    mon = Monitor(b, Store(db), kill, hb)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sg in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sg, stop.set)
    await mon.run(stop, heartbeat=mhb)
    await b.aclose()


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else float("nan")


async def _check():
    from .broker import OandaBroker
    mode = C.mode()
    b = OandaBroker("live" if mode == "live" else "practice")
    s = await b.summary()
    print(f"cuenta OK ({b.mode}): moneda {s['currency']}, NAV {s['nav']:.2f}, trades abiertos {s['open_trades']}")
    rtt, skew = [], []
    for _ in range(20):
        t0 = time.perf_counter()
        q = await b.pricing(["EURUSD"])
        rtt.append(1000 * (time.perf_counter() - t0))
        if "EURUSD" in q and q["EURUSD"].t_provider:
            skew.append(1000 * (q["EURUSD"].t_recv - q["EURUSD"].t_provider))
        await asyncio.sleep(0.2)
    print(f"REST pricing RTT ms: p50 {_pct(rtt, 50):.1f} · p90 {_pct(rtt, 90):.1f} · máx {max(rtt):.1f}")
    if skew:
        print(f"edad del precio al llegar (incluye desfase de reloj) ms: p50 {_pct(skew, 50):.0f}")
    stop = asyncio.Event()
    first = {}
    t0 = time.time()

    def on_q(q):
        first.setdefault("t", time.time() - t0)
        first.setdefault("lag", q.t_recv - q.t_provider)
        stop.set()
    try:
        await asyncio.wait_for(b.stream_prices(["EURUSD"], on_q, stop), timeout=15)
    except asyncio.TimeoutError:
        pass
    print(f"stream: primer precio en {first.get('t', float('nan')):.2f} s" if first else "stream: sin precio en 15 s")
    await b.aclose()


async def _smoke():
    from .broker import OandaBroker
    if C.mode() != "practice":
        raise SystemExit("smoke solo corre con FX_MODE=practice (cuenta demo)")
    b = OandaBroker("practice")
    q = (await b.pricing(["EURUSD"]))["EURUSD"]
    cid = f"fx-smoke-{int(time.time())}"
    f = await b.market("EURUSD", 1, q.bid - 0.0100, q.ask + 0.0005, cid, "prueba de latencia")
    c = await b.close(f.trade_id)
    print(json.dumps({"open": {"envio_a_ack_ms": round(1000 * (f.t_ack - f.t_sent), 1),
                               "fill": f.price, "trade": f.trade_id},
                      "close": {"envio_a_ack_ms": round(1000 * (c["t_ack"] - c["t_sent"]), 1), "pl": c["pl"]}}))
    await b.aclose()


def _latency():
    from .store import Store
    db, *_ = _paths()
    rows = [r for r in Store(db).journal("latency", 2000) if r.get("what") == "open"]
    if not rows:
        print("sin operaciones con latencia registrada")
        return
    def d(a, b):
        return [1000 * (r[b] - r[a]) for r in rows if r.get(a) and r.get(b)]
    for lab, a, b in (("precio→llegada (incl. reloj)", "t_provider", "t_recv"), ("llegada→decisión", "t_recv",
                      "t_decision"), ("decisión→envío", "t_decision", "t_sent"), ("envío→ack", "t_sent", "t_ack"),
                      ("programado→envío", "t_event", "t_sent")):
        xs = d(a, b)
        if xs:
            print(f"{lab:32s} p50 {_pct(xs, 50):8.1f} ms · p90 {_pct(xs, 90):8.1f} ms · n {len(xs)}")


def _status():
    from .store import Store
    db, hb, kill, mhb = _paths()
    if os.path.exists(hb):
        snap = json.load(open(hb))
        print(json.dumps({k: snap.get(k) for k in ("mode", "halt", "kill", "status", "live")}, indent=1,
                         default=str))
        print("riesgo:", json.dumps(snap.get("risk", {}), default=str)[:600])
        print(f"latido hace {time.time() - snap.get('ts', 0):.0f} s")
    for r in Store(db).journal(limit=15):
        print(time.strftime("%m-%d %H:%M:%S", time.gmtime(r["ts"])), r["kind"], r.get("sym") or "",
              json.dumps({k: v for k, v in r.items() if k not in ("ts", "kind", "sym", "ref")}, default=str,
                         ensure_ascii=False)[:160])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m fx")
    ap.add_argument("cmd", choices=["backtest", "run", "monitor", "check", "smoke", "latency", "status"])
    ap.add_argument("--bars", default=os.environ.get("FX_BARS_DIR", "bars"))
    ap.add_argument("--out", default=C.DATA_DIR)
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "backtest":
        from .backtest import run
        run(a.bars, a.out)
        print(open(os.path.join(a.out, "BACKTEST.md")).read())
        return 0
    if a.cmd == "run":
        asyncio.run(_run())
    elif a.cmd == "monitor":
        asyncio.run(_monitor())
    elif a.cmd == "check":
        asyncio.run(_check())
    elif a.cmd == "smoke":
        if not a.yes:
            raise SystemExit("agrega --yes: abre y cierra 1 unidad en la cuenta DEMO")
        asyncio.run(_smoke())
    elif a.cmd == "latency":
        _latency()
    elif a.cmd == "status":
        _status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
