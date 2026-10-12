"""100 webhooks concurrentes (3 pares, duplicados, replays): límites intactos. Corre: python -m tests.test_stress"""
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

db = os.path.join(tempfile.mkdtemp(), "stress.db")
os.environ.update(DATA_MODE="mock", LLM_PROVIDER="mock", TRADING_MODE="paper", DATABASE_URL=f"sqlite:///{db}",
                  WEBHOOK_SECRET="s", ADMIN_SECRET="a", MOCK_NOISE="0.003", TV_IP_ALLOWLIST="false",
                  SIGNAL_MAX_AGE_MIN="300")

from fastapi.testclient import TestClient  # noqa: E402

from app import data  # noqa: E402
from app.server import app  # noqa: E402
from tests.helpers import last_bar_open, wait_for  # noqa: E402

pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
BT = last_bar_open()
bodies = [{"secret": "s", "pair": pairs[i % 3], "signal_type": "BAR_CLOSE", "timeframe": "240",
           "bar_time": BT - (4 * 3_600_000 if i % 10 == 0 else 0),  # 10% replays de la vela anterior
           "price": data.last_price(pairs[i % 3])} for i in range(100)]
with TestClient(app) as c:
    with ThreadPoolExecutor(25) as tp:
        st = [r.json()["status"] for r in tp.map(lambda b: c.post("/webhook", json=b), bodies)]
    adm = {"x-admin-secret": "a"}
    wait_for(lambda: not [d for d in c.get("/decisions", headers=adm).json() if d["action"] in ("PENDING", "PROCESSING")])
    s = c.get("/status", headers=adm).json()
opens = s["open_positions"]
uniq = len({(b["pair"], b["bar_time"]) for b in bodies})
print(f"aceptadas={st.count('accepted')} duplicadas={st.count('duplicate')} rechazadas={st.count('rejected')} "
      f"abiertas={len(opens)} pares={[p['pair'] for p in opens]}")
okk = (st.count("accepted") in (3, uniq) and st.count("accepted") + st.count("duplicate") + st.count("rejected") == 100
       and len(opens) <= 2
       and len({p["pair"] for p in opens}) == len(opens))
print("PASS" if okk else "FAIL", "1 decisión por (par, vela); nunca más de 2 posiciones ni 2 en un par")
raise SystemExit(0 if okk else 1)
