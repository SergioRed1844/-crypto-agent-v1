"""Grafo completo + servidor (cola + worker líder) en modo mock. Corre: python -m tests.test_smoke"""
import asyncio
import os
import tempfile
import time

db = os.path.join(tempfile.mkdtemp(), "smoke.db")
os.environ.update(DATA_MODE="mock", LLM_PROVIDER="mock", TRADING_MODE="paper", DATABASE_URL=f"sqlite:///{db}",
                  WEBHOOK_SECRET="s3cret", ADMIN_SECRET="adm1n", PAPER_EQUITY="1000", MOCK_NOISE="0.003",
                  TV_IP_ALLOWLIST="true", SIGNAL_MAX_AGE_MIN="300")

from fastapi.testclient import TestClient  # noqa: E402

from app import data  # noqa: E402
from app.graph import run  # noqa: E402
from app.server import app  # noqa: E402
from tests.helpers import last_bar_open, wait_for  # noqa: E402

res = []
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or res.append(bool(c))

out = asyncio.run(run({"pair": "BTCUSDT", "signal_type": "BAR_CLOSE", "signal_id": "t1"}))
ok(out["final_action"] == "BUY", f"grafo compra en tendencia: {out['portfolio']['consensus']}")
ok(out["risk"]["order"]["rr"] >= 2, f"R:R {out['risk']['order']['rr']}")
ok(out["risk"]["order"]["risk_usdt"] <= 1000 * 0.005 + 1e-9, f"riesgo {out['risk']['order']['risk_usdt']} USDT <= 0.5%")
out2 = asyncio.run(run({"pair": "BTCUSDT", "signal_type": "BAR_CLOSE", "signal_id": "t2"}))
ok(out2["final_action"] == "REJECTED" and "sin_posicion_en_par" in out2["risk"]["failed"], "2a compra en el mismo par bloqueada")

TV = {"x-forwarded-for": "9.9.9.9, 52.89.214.238"}  # izquierda: la inventa el cliente; derecha: la agrega Render
BT = last_bar_open()
body = {"secret": "s3cret", "pair": "ETHUSDT", "signal_type": "BAR_CLOSE", "timeframe": "240", "bar_time": BT,
        "price": data.last_price("ETHUSDT")}
adm = {"x-admin-secret": "adm1n"}
with TestClient(app) as c:
    t = time.time(); r = c.post("/webhook", json=body, headers=TV); ms = (time.time() - t) * 1000
    ok(r.json()["status"] == "accepted" and ms < 500, f"webhook aceptado en {ms:.0f} ms")
    ok(c.post("/webhook", json=body, headers=TV).json()["status"] == "duplicate", "duplicado detectado")
    ok(c.post("/webhook", json=body, headers={"x-forwarded-for": "52.89.214.238, 1.2.3.4"}).status_code == 403,
       "IP de TradingView falsificada a la izquierda → 403")
    ok(c.post("/webhook", json={**body, "secret": "x"}, headers=TV).status_code == 401, "secret malo → 401")
    ok(c.post("/webhook", json={**body, "bar_time": BT - 48 * 3_600_000}, headers=TV).json()["status"] == "rejected", "replay viejo rechazado")
    ok(c.post("/webhook", json={**body, "timeframe": "60"}, headers=TV).json()["status"] == "rejected", "alerta de 1H rechazada")
    ok(c.post("/webhook", json={**body, "pair": "BNBUSDT"}, headers=TV).json()["status"] == "ignored", "BNB ignorado")
    ok(c.get("/status").status_code == 401, "/status sin admin → 401")
    ok(c.get("/status", headers={"x-admin-secret": "s3cret"}).status_code == 401, "el secret del webhook no abre /status")
    s = wait_for(lambda: (lambda j: j if len(j["open_positions"]) == 2 else None)(c.get("/status", headers=adm).json()))
    ok(bool(s) and len(s["open_positions"]) == 2, "worker procesó la cola: BTC + ETH abiertas")
    ds = c.get("/decisions", headers=adm).json()
    ok(not [d for d in ds if d["action"] in ("PENDING", "PROCESSING")], f"cola vacía: {[(d['action'], d['reason'][:40]) for d in ds]}")
    r = c.post("/kill?flatten=true", headers=adm).json()
    ok(r["kill_switch"] and len(r["flattened"]) == 2, "kill switch cierra todo")
    r3 = c.post("/webhook", json={**body, "pair": "SOLUSDT", "price": data.last_price("SOLUSDT")}, headers=TV).json()
    ok(r3["status"] == "blocked", f"con kill switch no procesa: {r3['status']}")
    h = c.get("/health").json()
    ok(h["ok"] and h["leader"], "/health: líder y reconciliación al día")

print(f"\n{sum(res)}/{len(res)} pruebas pasaron")
raise SystemExit(0 if all(res) else 1)
