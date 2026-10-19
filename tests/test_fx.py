"""Agente FX (agente 3): relojes, datos, riesgo y gobernador semanal, eventos, EB, backtest, OANDA (simulado),
webhook, motor en vivo con repetición de velas y monitor. Sin red y sin dinero. Corre: python -m tests.test_fx"""
import asyncio
import json
import lzma
import os
import shutil
import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone

import numpy as np

TMP = tempfile.mkdtemp()
for k in ("OANDA_TOKEN", "OANDA_ACCOUNT_ID", "FX_LIVE_CONFIRM"):
    os.environ.pop(k, None)
os.environ["FX_MODE"] = "paper"

from fx import backtest as B  # noqa: E402
from fx import calendar as K  # noqa: E402
from fx import config as C  # noqa: E402
from fx import data_dukascopy as D  # noqa: E402
from fx import events as E  # noqa: E402
from fx import model as M  # noqa: E402
from fx.broker import OandaBroker, OrderRejected, PaperBroker, Quote, rfc3339  # noqa: E402
from fx.engine import Engine  # noqa: E402
from fx.monitor import Monitor, kill_active, write_kill  # noqa: E402
from fx.risk import Position, RiskEngine  # noqa: E402
from fx.store import Store  # noqa: E402
from tests import fx_synth as S  # noqa: E402

res = []


def ok(cond, msg):
    res.append(bool(cond))
    print(("✔ " if cond else "✘ ") + msg)


def utc(y, mo, d, h, mi):
    return K.to_min(datetime(y, mo, d, h, mi, tzinfo=timezone.utc))


SL = {s.name: s for s in C.SLOTS}

# ── relojes ────────────────────────────────────────────────────────────────────────────────────────────────────────
ok(K.slot_min(SL["US_0830"], date(2026, 1, 15)) == utc(2026, 1, 15, 13, 30) and
   K.slot_min(SL["US_0830"], date(2026, 7, 15)) == utc(2026, 7, 15, 12, 30), "8:30 NY = 13:30/12:30 UTC según DST")
ok(K.slot_min(SL["MX_1300"], date(2026, 7, 15)) == utc(2026, 7, 15, 19, 0) and
   K.slot_min(SL["MX_1300"], date(2021, 7, 15)) == utc(2021, 7, 15, 18, 0),
   "Banxico 13:00 CDMX: sin horario de verano desde 2022, con DST en 2021")
ok(K.slot_min(SL["EU_1415"], date(2026, 1, 15)) == utc(2026, 1, 15, 13, 15), "BCE 14:15 CET = 13:15 UTC en invierno")
sun_open = K.local_min(date(2026, 10, 18), "17:00", "America/New_York")
ok(K.fx_week(sun_open) == "2026-W43" and K.fx_week(sun_open - 1) == "2026-W42", "semana FX abre domingo 17:00 NY")
ok(K.week_open_min(sun_open + 3000) == sun_open and K.next_week_open_min(sun_open + 10) == sun_open + 7 * 1440,
   "apertura de semana actual y siguiente")
fri = K.local_min(date(2026, 10, 23), "09:00", "America/New_York")
ok(K.forced_exit_min(fri) == K.local_min(date(2026, 10, 23), "15:55", "America/New_York") and
   K.forced_exit_min(fri - 3 * 1440) == K.local_min(date(2026, 10, 20), "16:50", "America/New_York"),
   "salida forzada 16:50 NY (viernes 15:55)")
ny = lambda d, hm: K.local_min(d, hm, "America/New_York")  # noqa: E731
ok(K.entry_blackout(ny(date(2026, 10, 24), "10:00")) == "mercado cerrado" and
   K.entry_blackout(ny(date(2026, 10, 23), "16:00")).startswith("viernes") and
   K.entry_blackout(ny(date(2026, 12, 28), "08:45")) == "24-dic a 2-ene" and
   K.entry_blackout(ny(date(2026, 10, 20), "16:55")).startswith("rollover") and
   K.entry_blackout(K.local_min(date(2026, 10, 20), "16:01", "Europe/London")).startswith("fix") and
   K.entry_blackout(ny(date(2026, 10, 20), "08:45")) is None, "blackouts: cierre, viernes, fin de año, rollover, fix")
ev = ny(date(2026, 10, 28), "14:00")
ok(K.entry_blackout(ev + 3, (ev,)) and K.entry_blackout(ev + 15, (ev,)) is None, "T−5/T+5 de evento conocido")
ecb = K.slot_min(SL["EU_1415"], date(2026, 1, 15)) + 15
ok(K.entry_blackout(ecb, K.slot_guards("EURUSD", date(2026, 1, 15), "EU_1415")) and
   K.ny(K.exit_cap_min("EU_1345", ecb - 30)).strftime("%H:%M") == "08:25" and
   K.ny(K.exit_cap_min("US_0830", ny(date(2026, 1, 15), "08:45"))).strftime("%H:%M") == "13:55",
   "BCE en invierno entra justo a las 8:30 NY → bloqueado; topes antes de 8:30 y de 14:00 NY")
cal = os.path.join(TMP, "cal.json")
json.dump({"events": [{"date": "2026-10-28", "time_local": "14:00", "tz": "America/New_York", "status": "confirmed",
                       "title_es": "Decisión FOMC", "source_url": "https://www.federalreserve.gov/x"},
                      {"date": "2026-11-05", "time_local": None, "tz": None, "status": "confirmed",
                       "title_es": "Banxico"}, {"date": "2026-11-06", "time_local": "08:30", "tz": "America/New_York",
                       "status": "proposed", "title_es": "NFP"}]}, open(cal, "w"))
ke = K.known_events(cal)
ok(len(ke) == 1 and ke[0]["minute"] == ev, "calendario en vivo: solo eventos confirmados con hora")

# ── datos ──────────────────────────────────────────────────────────────────────────────────────────────────────────
rec = np.zeros(1440, dtype=D.REC)
rec["t"] = np.arange(1440) * 60_000          # milisegundos
rec["o"] = rec["c"] = rec["l"] = rec["h"] = 110000
rec["v"] = 1.0
b1 = D.parse_bi5(lzma.compress(rec.tobytes(), format=lzma.FORMAT_ALONE), date(2024, 1, 2))
a1 = b1.copy(); a1[:, 1:5] += 3
mg = D.merge_sides(b1, a1)
back = D.decode(D.encode(mg))
ok(len(mg["t"]) == 1440 and mg["t"][0] == utc(2024, 1, 2, 0, 0) and
   all((np.asarray(back[k]) == np.asarray(mg[k])).all() for k in D.FIELDS),
   "bi5: tiempos en ms, unión bid/ask y codificación delta sin pérdida")
ok(D.url("USDJPY", date(2024, 1, 2), "ASK").endswith("/USDJPY/2024/00/02/ASK_candles_min_1.bi5"), "URL con mes base 0")
ok(D.check_scale("EURUSD", mg)["ok"] and not D.check_scale("USDMXN", mg)["ok"], "validación de escala por par")

# ── riesgo ─────────────────────────────────────────────────────────────────────────────────────────────────────────
try:
    C.check_risk(C.Risk(risk_per_event=0.01))
    ok(False, "techo de riesgo inmutable")
except ValueError:
    ok(True, "techo de riesgo inmutable (0.5% por evento)")
try:
    C.check_risk(C.Risk(weekly_loss_cap=0.03))
    ok(False, "tope semanal inmutable")
except ValueError:
    ok(True, "tope semanal no se puede relajar por encima de 1.5%")
os.environ["FX_MODE"] = "live"
try:
    C.mode()
    ok(False, "live sin confirmación")
except RuntimeError:
    ok(True, "FX_MODE=live sin FX_LIVE_CONFIRM se niega")
os.environ["FX_MODE"] = "paper"

tue = ny(date(2026, 10, 20), "08:45")
r = RiskEngine(2000)
d1 = r.size(tue, "EURUSD", 1, 1.10, 0.0010, n_in_event=2)
ok(d1.ok and abs(d1.risk_usd - 2000 * 0.0035 / 2) < 0.02, f"riesgo por evento repartido: {d1.risk_usd:.2f} USD")
d2 = r.size(tue, "EURUSD", 1, 1.10, 0.00001)
ok(d2.ok and d2.units * 1.10 <= 5 * 2000 + 1, f"apalancamiento ≤5× con stop diminuto ({d2.units:.0f} u)")
ok(r.size(tue, "USDJPY", 1, 150.0, 0.2, blackout="fix").reasons, "blackout bloquea")


def lose(r, m, sym, usd):
    r.on_open(Position(sym, 1, 1000, 1.1, 1.09, usd, m, m + 60, 1100, -1))
    return r.on_close(sym, -usd, m + 30)


r = RiskEngine(2000)
mon_ = ny(date(2026, 10, 19), "08:45")
lose(r, mon_, "EURUSD", 7.0); r.streak = 0
lose(r, mon_ + 1440, "EURUSD", 7.0); r.streak = 0
room = r.week_room() * 0.9
d3 = r.size(mon_ + 2 * 1440, "GBPUSD", 1, 1.3, 0.0010)
ok(d3.ok and d3.risk_usd <= room + 1e-6 and d3.risk_usd < 7.0, f"presupuesto semanal: arriesga {d3.risk_usd:.2f} ≤ "
   f"90% de lo que queda ({room:.2f})")
acts = lose(r, mon_ + 2 * 1440, "GBPUSD", 30 - 14 + 0.5)
ok(any(a.startswith("flatten") for a in acts) and r.pause_until == K.next_week_open_min(mon_) and
   r.size(mon_ + 3 * 1440, "USDJPY", 1, 150, 0.2).reasons, "−1.5% en la semana: plano y sin entradas hasta el domingo")
r2 = RiskEngine(2000)
for i in range(3):
    lose(r2, mon_ + i * 10, "EURUSD", 1.0)
ok(r2.pause_until == mon_ + 20 + 30 + 1440, "3 pérdidas seguidas → pausa 24 h")
r3 = RiskEngine(2000)
lose(r3, mon_, "EURUSD", 25.0)
ok(r3.pause_until > mon_ and r3.size(mon_ + 60, "USDJPY", 1, 150, 0.2).reasons, "−1% en el día → sin entradas hoy")
r4 = RiskEngine(2000)
r4.peak = 2300
lose(r4, mon_, "EURUSD", 1.0)
ok(r4.off and r4.size(mon_ + 9 * 1440, "USDJPY", 1, 150, 0.2).reasons, "drawdown 10% → apagado")
r5 = RiskEngine(2000)
r5.on_open(Position("EURUSD", 1, 1000, 1.1, 1.09, 3, tue, tue + 60, 5500, -1))
ok("ya hay posición en el par" in r5.size(tue, "EURUSD", -1, 1.1, 0.001).reasons, "una posición por par")

# ── eventos, stops y EB ────────────────────────────────────────────────────────────────────────────────────────────
ok(abs(E.avoid_round(1.0798, 1, 1e-4, 1.0830) - 1.0803) < 1e-9 and E.avoid_round(1.0790, 1, 1e-4, 1.0830) == 1.0790
   and abs(E.avoid_round(1.0802, -1, 1e-4, 1.0770) - 1.0797) < 1e-9, "stop fuera de la zona justo detrás de un 00")
slot = SL["US_0830"]
bd = E.Bars.from_raw("EURUSD", S.bars(drift=0.6, years=3, seed=1))
rows_d = E.to_rows(E.build(bd, slot))
mom = np.mean([x["R"] for x in rows_d if x["dir"] == "mom" and x["hold"] == 120])
rev = np.mean([x["R"] for x in rows_d if x["dir"] == "rev" and x["hold"] == 120])
ok(mom > 0.1 and rev < -0.3, f"drift sintético detectado: momentum {mom:+.2f}R, reversión {rev:+.2f}R")
ok(all(x["entry_m"] >= x["t0"] + 15 for x in rows_d) and all(x["exit_m"] <= K.forced_exit_min(x["entry_m"])
                                                              for x in rows_d), "entrada ≥ T+15 y salida ≤ forzada")
fm = M.fit(rows_d)
ok(("EURUSD", "US_0830") in fm["active"] and fm["active"][("EURUSD", "US_0830")]["dir"] == "mom",
   "EB activa el grupo con drift (momentum)")
bn = E.Bars.from_raw("EURUSD", S.bars(drift=0.0, years=3, seed=2))
rows_n = E.to_rows(E.build(bn, slot))
ok(not M.fit(rows_n)["active"], "EB no activa nada sin ventaja (paseo aleatorio + costos)")
# stop con hueco: precio abre más allá del stop → se llena al open (peor que −1R)
raw = S.bars(drift=0.0, years=1, seed=3, event_p=0)
bb = E.Bars.from_raw("EURUSD", raw)
ie = 5000
bb.bo[ie + 5:] -= 0.0100; bb.bl[ie + 5:] -= 0.0100; bb.ao[ie + 5:] -= 0.0100; bb.ah[ie + 5:] -= 0.0100
sim = E.simulate(bb, ie, 1, 0.0010, int(bb.t[ie + 60]), C.PAIRS["EURUSD"])
ok(sim["why"] == "stop" and sim["R"] < -5, f"gap atraviesa el stop: R {sim['R']:.1f} (el tamaño controla el gap)")

# ── backtest y gobernador semanal ──────────────────────────────────────────────────────────────────────────────────
bars2 = {"EURUSD": bd}
cands, models = B.walk_forward(rows_d, first=2020)
tr, eng, _ = B.portfolio(cands, bars2)
wk = B.weekly(tr, min(c["entry_m"] for c in cands), max(c["exit_m"] for c in cands))
sm = B.summarize(tr, wk, eng)
ok(sm["trades"] > 20 and sm["avg_R"] > 0 and sm["worst_week"] >= -C.RISK.weekly_loss_cap - 1e-9,
   f"walk-forward sintético: {sm['trades']} ops, {sm['avg_R']:+.2f}R, peor semana {sm['worst_week']:.2%}")
bad = [dict(c, R=-1.0 - c["R_cost"], why="stop") for c in cands]
tr2, eng2, _ = B.portfolio(bad, None)
wk2 = B.weekly(tr2, min(c["entry_m"] for c in cands), max(c["exit_m"] for c in cands))
ok(min(w["ret"] for w in wk2) >= -C.RISK.weekly_loss_cap - 1e-9, "todas pierden: ninguna semana pasa de −1.5%")
pb = np.mean([B.pbo_cscv(np.random.default_rng(s).standard_normal((600, 12)), S=10)["pbo"] for s in range(6)])
Xe = np.random.default_rng(9).standard_normal((600, 12)); Xe[:, 3] += 0.25
pe = B.pbo_cscv(Xe, S=10)["pbo"]
xw = np.random.default_rng(1).standard_normal(300) * 0.01 + 0.001
ok(0.3 < pb < 0.7 and pe < 0.1 and B.dsr(xw, list(np.random.default_rng(2).normal(0, 0.05, 12)), 12) <= B.psr(xw),
   f"PBO: ruido ≈ 0.5 ({pb:.2f}), con ventaja real ≈ 0 ({pe:.2f}); DSR ≤ PSR")
rs = B.random_sign(cands, rows_d, 300)
ok(rs["p_value"] < 0.05, f"benchmark de signo aleatorio (p={rs['p_value']:.3f})")

# ── OANDA v20 (transporte simulado) ────────────────────────────────────────────────────────────────────────────────
import httpx  # noqa: E402

seen = []


def handler(req: httpx.Request):
    seen.append(req)
    if req.method == "POST" and req.url.path.endswith("/orders"):
        body = json.loads(req.content)
        if body["order"]["instrument"] == "USD_JPY":
            return httpx.Response(201, json={"orderCancelTransaction": {"reason": "BOUNDS_VIOLATION"}})
        return httpx.Response(201, json={"orderFillTransaction": {"id": "9", "time": "2026-10-19T12:45:00.123456789Z",
                                         "fullVWAP": "1.10012", "tradeOpened": {"tradeID": "77", "units": "1500"}}})
    if req.url.path.endswith("/close"):
        return httpx.Response(200, json={"orderFillTransaction": {"price": "1.10100", "pl": "1.32",
                                                                  "time": "2026-10-19T14:45:00Z"}})
    if req.url.path.endswith("/summary"):
        return httpx.Response(200, json={"account": {"currency": "USD", "balance": "2000.0", "NAV": "2001.5",
                                                     "unrealizedPL": "1.5", "openTradeCount": 1}})
    return httpx.Response(401, json={"errorMessage": "Insufficient authorization to perform request."})


async def oanda_case():
    b = OandaBroker("practice", token="tok-SECRETO-123456", account="101-001-1234567-001",
                    transport=httpx.MockTransport(handler))
    f = await b.market("EURUSD", 1500, 1.09876, 1.10030, "fx-US_0830-EURUSD-1", "z=2.5")
    sent = json.loads(seen[-1].content)["order"]
    ok(sent["type"] == "MARKET" and sent["timeInForce"] == "FOK" and sent["priceBound"] == "1.10030" and
       sent["stopLossOnFill"]["price"] == "1.09876" and sent["clientExtensions"]["id"] == "fx-US_0830-EURUSD-1" and
       sent["units"] == "1500" and sent["positionFill"] == "OPEN_ONLY", "orden v20: MARKET FOK + priceBound + stop")
    ok(seen[-1].url.host == "api-fxpractice.oanda.com" and seen[-1].headers["authorization"].startswith("Bearer "),
       "practice host y Bearer")
    ok(f.trade_id == "77" and f.price == 1.10012 and abs(f.t_fill - rfc3339("2026-10-19T12:45:00.123456Z")) < 1e-6,
       "fill: trade, VWAP y hora con nanosegundos")
    try:
        await b.market("USDJPY", -100, 151.234, 150.9, "fx-x", "")
        ok(False, "cancelación por priceBound")
    except OrderRejected as e:
        ok("BOUNDS_VIOLATION" in str(e), "cancelación por priceBound → OrderRejected")
    try:
        await b.open_trades()
    except OrderRejected as e:
        ok("tok-SECRETO" not in str(e) and "1234567" not in str(e), "errores sin token ni cuenta")
    ok(sent["instrument"] == "EUR_USD" and (await b.close("77"))["pl"] == 1.32 and (await b.summary())["nav"] == 2001.5,
       "cierre y resumen de cuenta")
    await b.aclose()
    try:
        OandaBroker("live", token="x", account="y")
        ok(False, "live bloqueado")
    except RuntimeError:
        ok(True, "OandaBroker live exige la doble confirmación humana")


asyncio.run(oanda_case())

# ── webhook ────────────────────────────────────────────────────────────────────────────────────────────────────────
from fastapi.testclient import TestClient  # noqa: E402

from fx.webhook import make_app  # noqa: E402

st = Store(os.path.join(TMP, "wh.db"))
SEC = "s" * 24
cl = TestClient(make_app(st, SEC))
ok(cl.post("/tv", content=json.dumps({"secret": SEC, "action": "PAUSE"})).status_code == 403, "IP fuera de lista → 403")
cl = TestClient(make_app(st, SEC, extra_ips=("testclient",)))
ok(cl.post("/tv", content=json.dumps({"secret": "x", "action": "PAUSE"})).status_code == 401, "secreto malo → 401")
ok(cl.post("/tv", content=json.dumps({"secret": SEC, "action": "BUY"})).status_code == 422, "acción no permitida → 422")
r1 = cl.post("/tv", content=json.dumps({"secret": SEC, "action": "pause", "id": "a1"})).json()
r2 = cl.post("/tv", content=json.dumps({"secret": SEC, "action": "pause", "id": "a1"})).json()
ok(r1["ok"] and not r1["dup"] and r2["dup"] and r1["ms"] < 50, f"idempotente y rápido ({r1['ms']} ms)")
ok(len(st.pending_intents()) == 1 and "secret" not in json.dumps(st.pending_intents()), "intent guardado sin secreto")
try:
    st.db.execute("UPDATE journal SET kind='x'")
    st.log("x", {})
    st.db.execute("UPDATE journal SET kind='x'")
    ok(False, "bitácora solo anexar")
except sqlite3.DatabaseError:
    ok(True, "bitácora solo anexar (UPDATE bloqueado)")

# ── motor en vivo: repetición de velas con broker simulado ─────────────────────────────────────────────────────────
final = M.fit(rows_d)
sc = B.scales_now({"EURUSD": bd})
model = {**M.serializable(final, date(2021, 12, 31), {"scales": sc}), "_active": final["active"]}


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


async def replay():
    clk = Clock()
    pb = PaperBroker(2000)
    eng = Engine(pb, model, Store(os.path.join(TMP, "eng.db")), 2000, "paper", clock=clk,
                 kill_path=os.path.join(TMP, "KILL"))
    pb.on_tx = eng.on_tx
    days = [r for r in rows_d if r["dir"] == "mom" and r["hold"] == 120 and abs(r["z"]) >= 3][-6:]
    for r in days:
        t0 = r["t0"]
        i0 = int(np.searchsorted(bd.t, t0 - 75)); i1 = int(np.searchsorted(bd.t, t0 + 200))
        for i in range(i0, i1):
            m = int(bd.t[i])
            for sec, (bid, ask) in ((1, (bd.bo[i], bd.ao[i])), (58, (bd.bc[i], bd.ac[i]))):
                clk.t = m * 60 + sec
                eng.on_quote(Quote("EURUSD", float(bid), float(ask), clk.t, clk.t))
            clk.t = m * 60 + 59.5
            await eng.tick()
            clk.t = (m + 1) * 60 + 0.3
            await eng.tick()
    return eng, pb


eng, pb = asyncio.run(replay())
opens = eng.store.journal("open")
closes = eng.store.journal("close")
ok(len(opens) >= 3 and len(closes) == len(opens) and not eng.live, f"motor: {len(opens)} entradas y todas cerradas")
o = opens[-1]
ok(o["latency"]["t_sent"] >= o["latency"]["t_event"] and o["latency"]["t_recv"] <= o["latency"]["t_decision"],
   "relojes de latencia completos y ordenados")
risk_by = {o["ref"]: o["risk_usd"] for o in opens}
ok(all(abs(c["pl"] / c["R"] - risk_by[c["ref"]]) < 1e-6 for c in closes if c.get("R")) and
   abs(pb.balance - eng.risk.equity) < 1e-6,
   f"P&L del simulador = P&L del gobernador ({pb.balance:.2f} USD)")


async def kill_case():
    clk = Clock()
    pb = PaperBroker(2000)
    kp = os.path.join(TMP, "KILL2")
    eng = Engine(pb, model, Store(os.path.join(TMP, "eng2.db")), 2000, "paper", clock=clk, kill_path=kp)
    r = [x for x in rows_d if x["dir"] == "mom" and x["hold"] == 120 and abs(x["z"]) >= 3][-1]
    write_kill(kp, r["t0"] + 1000, "prueba")
    i0 = int(np.searchsorted(bd.t, r["t0"] - 75)); i1 = int(np.searchsorted(bd.t, r["t0"] + 30))
    for i in range(i0, i1):
        m = int(bd.t[i]); clk.t = m * 60 + 30
        eng.on_quote(Quote("EURUSD", float(bd.bc[i]), float(bd.ac[i]), clk.t, clk.t))
        clk.t = (m + 1) * 60 + 0.3
        await eng.tick()
    return eng


ek = asyncio.run(kill_case())
ok(not ek.store.journal("open") and any("kill" in s.get("why", "") for s in ek.store.journal("skip")),
   "archivo KILL del monitor bloquea entradas")


class FakeBroker:
    def __init__(self):
        self.nav, self.closed, self.trades = 2000.0, 0, []

    async def summary(self):
        return {"nav": self.nav, "balance": self.nav, "currency": "USD", "open_trades": len(self.trades)}

    async def open_trades(self):
        return self.trades

    async def close(self, tid):
        self.trades = [t for t in self.trades if t["id"] != tid]
        self.closed += 1
        return {}

    async def close_all(self):
        n = len(self.trades); self.trades = []; self.closed += n
        return [{}] * n


async def monitor_case():
    clk = Clock()
    fb = FakeBroker()
    kp = os.path.join(TMP, "KILL3")
    mon = Monitor(fb, Store(os.path.join(TMP, "mon.db")), kp, clock=clk)
    clk.t = ny(date(2026, 10, 20), "09:00") * 60
    await mon.step()
    fb.trades = [{"id": "1", "sym": "EURUSD", "client_id": "fx-a", "open_time": clk.t}]
    fb.nav = 2000 * (1 - 0.016)
    clk.t += 600
    acts = await mon.step()
    k1 = kill_active(kp, int(clk.t // 60))
    fb.nav = 2000.0
    fb.trades = [{"id": "2", "sym": "USDJPY", "client_id": "fx-b", "open_time": ny(date(2026, 10, 21), "10:00") * 60}]
    clk.t = (ny(date(2026, 10, 21), "16:53")) * 60
    acts2 = await mon.step()
    return fb, acts, k1, acts2


fb, acts, k1, acts2 = asyncio.run(monitor_case())
ok(k1 and "semana" in k1 and fb.closed >= 1, "monitor: NAV −1.6% en la semana → cierra todo y escribe KILL")
ok(any("salida forzada" in a for a in acts2), "monitor cierra trades vencidos (16:50 NY + 2 min)")

shutil.rmtree(TMP, ignore_errors=True)
print(f"{sum(res)}/{len(res)} {'OK' if all(res) else 'FALLA'}")
