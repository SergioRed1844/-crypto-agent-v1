"""Reinicio con señales en cola + posiciones sombra + candados. Corre: python -m tests.test_recovery"""
import asyncio
import os
import tempfile
from datetime import timedelta

db = os.path.join(tempfile.mkdtemp(), "rec.db")
os.environ.update(DATA_MODE="mock", LLM_PROVIDER="mock", TRADING_MODE="paper", DATABASE_URL=f"sqlite:///{db}",
                  WEBHOOK_SECRET="s", ADMIN_SECRET="a", MOCK_NOISE="0.003", RULES_ONLY_FALLBACK="false")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update  # noqa: E402

from app import data, store  # noqa: E402
from app.graph import run  # noqa: E402
from app.server import app  # noqa: E402
from tests.helpers import last_bar_open, wait_for  # noqa: E402

res = []
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or res.append(bool(c))

# 1) Sin LLM y RULES_ONLY_FALLBACK=false → no compra, pero abre SOMBRA para medir lo que se perdió
out = asyncio.run(run({"pair": "BTCUSDT", "signal_type": "BAR_CLOSE", "signal_id": "r1"}))
ok(out["final_action"] == "REJECTED", f"sin LLM no opera: {out['final_action']}")
ok(len(store.shadow_positions()) == 1 and not store.open_positions(), "posición sombra abierta, sin dinero")
ok(store.realized_pnl_since(24) == 0.0, "la sombra no cuenta para el drawdown")

# 2) Cola tras reinicio: PENDING reciente se procesa; PENDING viejo y PROCESSING colgado → EXPIRED
sig = {"pair": "ETHUSDT", "signal_type": "BAR_CLOSE", "signal_id": "r2", "timeframe": "240",
       "bar_time": last_bar_open(), "price": data.last_price("ETHUSDT")}
store.claim_signal("r2", "ETHUSDT", sig)
store.claim_signal("old", "SOLUSDT", {"pair": "SOLUSDT", "signal_id": "old"})
store.claim_signal("hung", "SOLUSDT", {"pair": "SOLUSDT", "signal_id": "hung"})
with store.engine.begin() as c:
    c.execute(update(store.decisions).where(store.decisions.c.signal_id == "old").values(ts=store.now() - timedelta(hours=2)))
    c.execute(update(store.decisions).where(store.decisions.c.signal_id == "hung").values(
        action="PROCESSING", ts=store.now() - timedelta(hours=1)))
with TestClient(app) as c:
    get = lambda: {d["signal_id"]: d["action"] for d in c.get("/decisions", headers={"x-admin-secret": "a"}).json()}
    ds = wait_for(lambda: (lambda d: d if d.get("r2") not in ("PENDING", "PROCESSING") else None)(get()))
ok(ds.get("r2") not in (None, "PENDING", "PROCESSING"), f"señal en cola procesada tras reinicio: {ds.get('r2')}")
ok(ds.get("old") == "EXPIRED", f"señal vieja → EXPIRED: {ds.get('old')}")
ok(ds.get("hung") == "EXPIRED", f"PROCESSING colgado → EXPIRED, no se re-ejecuta: {ds.get('hung')}")

# 3) Índice único (mode, pair): no puede haber dos posiciones vivas del bot en el mismo par
store.open_position(id="X1", decision_id="x", pair="SOLUSDT", mode="paper", qty=1, entry=1, stop=0.9, tp=1.3, risk_usdt=0.1)
try:
    store.open_position(id="X2", decision_id="y", pair="SOLUSDT", mode="paper", qty=1, entry=1, stop=0.9, tp=1.3, risk_usdt=0.1)
    ok(False, "índice único por par")
except Exception:
    ok(True, "índice único bloquea la 2a posición viva en el par")

# 4) Posiciones de otro modo (testnet) vivas → el servidor se niega a arrancar
store.open_position(id="T1", decision_id="t", pair="BTCUSDT", mode="testnet", qty=1, entry=1, stop=0.9, tp=1.3, risk_usdt=0.1)
try:
    with TestClient(app):
        pass
    ok(False, "arranque con posiciones de otro modo")
except RuntimeError as e:
    ok("otro modo" in str(e), "no arranca con posiciones vivas de otro modo")

# 5) Paper: posición de hace 5 días con el stop tocado hace 2 días se cierra (paginación sin tope de 3.5 días)
from app import execution  # noqa: E402
import app.data as D  # noqa: E402
with store.engine.begin() as c:
    c.execute(store.positions.delete().where(store.positions.c.mode.in_(["testnet", "paper"])))
store.open_position(id="OLD", decision_id="o", pair="BTCUSDT", mode="paper", qty=1, entry=100, stop=95, tp=120, risk_usdt=5)
with store.engine.begin() as c:
    c.execute(update(store.positions).where(store.positions.c.id == "OLD").values(opened_at=store.now() - timedelta(days=5)))
t0 = int((store.now() - timedelta(days=5)).timestamp() * 1000)
hit = t0 + 3 * 86_400_000
bars = [[t0 + i * 300_000, 100, 101, 94 if t0 + i * 300_000 >= hit else 99, 100, 1] for i in range(5 * 288)]
orig = D.fetch_ohlcv
D.fetch_ohlcv = lambda pair, tf, limit=300, since=None, closed_only=True: [b for b in bars if b[0] >= (since or 0)][:limit]
execution.reconcile()
D.fetch_ohlcv = orig
ok(not [p for p in store.open_positions() if p["id"] == "OLD"], "posición de 5 días cerrada al tocar el stop del día 3")

print(f"\n{sum(res)}/{len(res)} pruebas pasaron")
raise SystemExit(0 if all(res) else 1)
