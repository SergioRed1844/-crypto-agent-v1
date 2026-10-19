"""Motor en vivo del agente FX (paper / practice / live). Un proceso asyncio:

  stream de precios OANDA ─► MinuteBook (velas de 1 min) ─► en T0+15 de cada slot activo: z, dirección, stop,
  tamaño (RiskEngine) ─► orden MARKET FOK con stop en el broker ─► salida por tiempo/forzada ─► bitácora.

La señal NO depende de TradingView (timeout de 3 s, entregas que fallan, F15-001): el reloj del motor y el stream
de OANDA mandan; TradingView aporta visualización e "intents" (FLATTEN/PAUSE/RESUME/CHECK) por el webhook.
Cada decisión guarda los relojes: t_evento (programado), t_proveedor (precio usado), t_recepción, t_decisión,
t_envío, t_ack y t_fill (F15-014). El supervisor LLM, si se usa, queda fuera de este camino.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import numpy as np

from . import calendar as K
from . import config as C
from . import events as E
from .broker import OrderRejected, Quote
from .risk import Position, RiskEngine, notional_usd, quote_to_usd
from .store import Store

STALE_S = 5.0          # precio más viejo que esto respecto al reloj → no se decide (F14-016: pausa > 5 s)


class MinuteBook:
    """Velas de 1 minuto (mid) por par a partir de cotizaciones; solo velas cerradas cuentan."""

    def __init__(self, keep: int = 300):
        self.bars: dict[str, deque] = {}
        self.cur: dict[str, list] = {}
        self.last: dict[str, Quote] = {}
        self.keep = keep

    def on_quote(self, q: Quote):
        self.last[q.sym] = q
        m = int((q.t_provider or q.t_recv) // 60)
        c = self.cur.get(q.sym)
        if c is None or m > c[0]:
            if c is not None:
                self.bars.setdefault(q.sym, deque(maxlen=self.keep)).append(tuple(c))
            self.cur[q.sym] = [m, q.mid, q.mid, q.mid, q.spread]
        elif m == c[0]:
            c[1] = q.mid; c[2] = max(c[2], q.mid); c[3] = min(c[3], q.mid); c[4] = q.spread

    def roll(self, now_s: float):
        """Cierra la vela en curso si su minuto ya terminó (aunque no haya llegado otro precio)."""
        m = int(now_s // 60)
        for sym, c in list(self.cur.items()):
            if c[0] < m:
                self.bars.setdefault(sym, deque(maxlen=self.keep)).append(tuple(c))
                self.cur[sym] = [m, c[1], c[1], c[1], c[4]]

    def close_at(self, sym: str, m: int, max_age: int = 10) -> float | None:
        """Mid de cierre de la última vela cerrada con minuto ≤ m (no más vieja que max_age minutos)."""
        for b in reversed(self.bars.get(sym, ())):
            if b[0] <= m:
                return b[1] if m - b[0] <= max_age else None
        return None

    def mids(self, sym: str, m_from: int, m_to: int) -> np.ndarray:
        return np.array([b[1] for b in self.bars.get(sym, ()) if m_from <= b[0] <= m_to])


@dataclass
class Job:
    sym: str
    slot: str
    t0: int
    group: dict
    done: bool = False
    result: str = ""


@dataclass
class Live:
    pos: Position
    trade_id: str
    client_id: str
    meta: dict = field(default_factory=dict)


def load_model(path: str) -> dict:
    with open(path) as fh:
        m = json.load(fh)
    act = {}
    for k, g in m.get("active", {}).items():
        sym, slot = k.split("|")
        if sym in C.PAIRS and any(s.name == slot for s in C.SLOTS):
            act[(sym, slot)] = g
    m["_active"] = act
    return m


class Engine:
    def __init__(self, broker, model: dict, store: Store, equity: float, mode: str = "paper",
                 clock=time.time, known_events: list[dict] | None = None, risk: C.Risk = C.RISK,
                 kill_path: str | None = None):
        self.broker, self.model, self.store, self.mode, self.clock = broker, model, store, mode, clock
        self.kill_path = kill_path
        self.book = MinuteBook()
        self.risk = RiskEngine(equity, risk)
        self._restore()
        self.known = [e["minute"] for e in (known_events or [])]
        self.jobs: list[Job] = []
        self.planned_day: date | None = None
        self.live: dict[str, Live] = {}
        self.halt: str | None = None          # pausa manual o por reconciliación (solo humano la quita)
        self.kill: str | None = None          # bloqueo del monitor independiente (archivo KILL)
        self.status: dict = {"stream": "sin conectar"}

    # ── persistencia del gobernador ───────────────────────────────────────────────────────────────────────────
    def _restore(self):
        s = self.store.get("risk_state")
        if s:
            r = self.risk
            r.peak = max(s.get("peak", r.equity), r.equity)
            if s.get("week") == K.fx_week(int(self.clock() // 60)):
                r.week, r.week_start, r.week_realized = s["week"], s["week_start"], s["week_realized"]
            r.pause_until = s.get("pause_until", 0)
            r.off = s.get("off")
            r.streak = s.get("streak", 0)

    def _persist(self):
        r = self.risk
        self.store.set("risk_state", {"peak": r.peak, "week": r.week, "week_start": r.week_start,
                                      "week_realized": r.week_realized, "pause_until": r.pause_until, "off": r.off,
                                      "streak": r.streak, "equity": r.equity})

    # ── plan del día ──────────────────────────────────────────────────────────────────────────────────────────
    def plan(self, d: date):
        self.jobs = []
        for (sym, slot_name), g in self.model.get("_active", {}).items():
            slot = next(s for s in C.SLOTS if s.name == slot_name)
            if d.weekday() < 5:
                self.jobs.append(Job(sym, slot_name, K.slot_min(slot, d), g))
        self.planned_day = d
        self.store.log("plan", {"day": d.isoformat(), "jobs": [(j.sym, j.slot, j.t0) for j in self.jobs]})

    # ── precios y transacciones ───────────────────────────────────────────────────────────────────────────────
    def on_quote(self, q: Quote):
        self.book.on_quote(q)
        if hasattr(self.broker, "feed"):
            self.broker.feed(q)

    def on_tx(self, tx: dict):
        """Cierres del lado del broker (stop alcanzado). El P&L de OANDA ya viene en la moneda de la cuenta."""
        if tx.get("type") != "ORDER_FILL":
            return
        for tc in tx.get("tradesClosed", []) or []:
            tid = tc.get("tradeID")
            for sym, lv in list(self.live.items()):
                if lv.trade_id == tid:
                    pl = float(tc.get("realizedPL", 0)) + float(tc.get("financing", 0) or 0)
                    self._closed(sym, pl, f"broker:{tx.get('reason', '')}", float(tc.get("price", 0) or 0))

    def _closed(self, sym: str, pl: float, why: str, px: float = 0.0):
        lv = self.live.pop(sym, None)
        m = int(self.clock() // 60)
        acts = self.risk.on_close(sym, pl, m)
        self.store.log("close", {"why": why, "pl": pl, "price": px, "R": pl / lv.pos.risk_usd if lv and
                                 lv.pos.risk_usd else None, "risk": self.risk.snapshot()}, sym,
                       lv.client_id if lv else None)
        self._persist()
        for a in acts:
            if a.startswith("flatten"):
                asyncio.get_event_loop().create_task(self.flatten(a.split(":", 1)[1]))

    async def close(self, sym: str, why: str):
        lv = self.live.get(sym)
        if not lv:
            return
        try:
            res = await self.broker.close(lv.trade_id)
        except OrderRejected as e:
            self.store.log("close_error", {"why": why, "error": str(e)}, sym, lv.client_id)
            if "inexistente" in str(e) or "404" in str(e):
                self.live.pop(sym, None)
            return
        self._closed(sym, res["pl"] + res.get("financing", 0.0), why, res["price"])
        self.store.log("latency", {"what": "close", "t_sent": res["t_sent"], "t_ack": res["t_ack"],
                                   "t_fill": res["t_fill"]}, sym, lv.client_id)

    async def flatten(self, why: str):
        for sym in list(self.live):
            await self.close(sym, f"flatten:{why}")

    # ── decisión en T0+15 ─────────────────────────────────────────────────────────────────────────────────────
    def _signal(self, j: Job, now: float) -> dict:
        lag = C.ENTRY_LAG_MIN
        p0 = self.book.close_at(j.sym, j.t0 - 1)
        p15 = self.book.close_at(j.sym, j.t0 + lag - 1, max_age=2)
        sc = self.model.get("scales", {}).get(f"{j.sym}|{j.slot}", {})
        sig = sc.get("sigma_slot")
        if not p0 or not p15 or not sig:
            return {"ok": False, "why": "sin precios del slot o sin escala"}
        ret = math.log(p15 / p0)
        z = ret / sig
        if abs(z) < j.group["z"]:
            return {"ok": False, "why": f"|z|={abs(z):.2f} < {j.group['z']}", "z": z}
        side = (1 if ret > 0 else -1) * (1 if j.group["dir"] == "mom" else -1)
        return {"ok": True, "z": z, "ret15": ret, "side": side}

    async def evaluate(self, batch: list[Job], now: float):
        sigs = {id(j): self._signal(j, now) for j in batch}
        go = [j for j in batch if sigs[id(j)]["ok"]]
        for j in batch:
            if not sigs[id(j)]["ok"]:
                j.done, j.result = True, sigs[id(j)]["why"]
                self.store.log("signal", {"slot": j.slot, "t0": j.t0, **sigs[id(j)]}, j.sym)
        for j in go:
            j.done = True
            j.result = await self._enter(j, sigs[id(j)], len(go), now)

    async def _enter(self, j: Job, sg: dict, n_event: int, now: float) -> str:
        pair = C.PAIRS[j.sym]
        q = self.book.last.get(j.sym)
        t_dec = self.clock()
        m = int(now // 60)
        rec = {"slot": j.slot, "t0": j.t0, "z": round(sg["z"], 3), "side": sg["side"], "group": j.group}
        if self.halt or self.kill:
            return self._skip(j, rec, f"pausa: {self.halt or 'kill-switch: ' + str(self.kill)}")
        if q is None or not q.tradeable:
            return self._skip(j, rec, "sin cotización operable")
        if now - (q.t_provider or q.t_recv) > STALE_S:
            return self._skip(j, rec, f"precio viejo {now - q.t_provider:.1f} s")
        typ = self._spread_typ(j, q)
        if typ and q.spread > C.SPREAD_MAX_X * typ:
            return self._skip(j, rec, f"spread {q.spread / pair.pip:.1f} pips > {C.SPREAD_MAX_X}× típico "
                                      f"({typ / pair.pip:.1f})")
        pre = self.book.mids(j.sym, j.t0 - 60, j.t0 - 1)
        post = self.book.mids(j.sym, j.t0 + 4, j.t0 + C.ENTRY_LAG_MIN - 1)
        hold = int(j.group["hold"])
        sh = E.sigma_h_from(pre, post, hold)
        if sh is None:
            return self._skip(j, rec, "historia de 1 min insuficiente para σ")
        side = sg["side"]
        ref = q.ask if side > 0 else q.bid
        dist = E.stop_distance(sh, q.mid, q.spread, pair)
        stop = E.avoid_round(ref - side * dist, side, pair.pip, ref)
        dist = (ref - stop) * side
        black = K.entry_blackout(m, tuple(self.known) + K.slot_guards(j.sym, K.ny(m).date(), j.slot))
        dec = self.risk.size(m, j.sym, side, ref, dist, n_event, black)
        if not dec.ok:
            return self._skip(j, rec, "; ".join(dec.reasons))
        nxt = [e - C.EVENT_GUARD_MIN for e in self.known if e > m]
        deadline = min([m + hold, K.exit_cap_min(j.slot, m)] + nxt[:1])
        if deadline - m < 10:
            return self._skip(j, rec, "salida forzada o evento mayor a menos de 10 min")
        bound = ref + side * max(2 * q.spread, 2 * pair.pip)
        cid = f"fx-{j.slot}-{j.sym}-{j.t0}"
        try:
            fill = await self.broker.market(j.sym, side * dec.units, stop, bound, cid,
                                            f"{j.slot} z={sg['z']:.2f} {j.group['dir']} {hold}m")
        except OrderRejected as e:
            return self._skip(j, rec, f"broker: {e}")
        risk_usd = abs(fill.price - stop) * abs(fill.units) * quote_to_usd(j.sym, fill.price)
        pos = Position(j.sym, side, abs(fill.units), fill.price, stop, risk_usd, m, deadline,
                       notional_usd(j.sym, abs(fill.units), fill.price), side * pair.usd_sign, fill.trade_id)
        self.risk.on_open(pos)
        self.live[j.sym] = Live(pos, fill.trade_id, cid, rec)
        self._persist()
        lat = {"t_event": (j.t0 + C.ENTRY_LAG_MIN) * 60.0, "t_provider": q.t_provider, "t_recv": q.t_recv,
               "t_decision": t_dec, "t_sent": fill.t_sent, "t_ack": fill.t_ack, "t_fill": fill.t_fill}
        self.store.log("open", {**rec, "units": fill.units, "price": fill.price, "stop": stop, "risk_usd": risk_usd,
                                "deadline": deadline, "latency": lat}, j.sym, cid)
        self.store.log("latency", {"what": "open", **lat}, j.sym, cid)
        return f"abierta {side:+d} {abs(fill.units):.0f} u @ {fill.price}"

    def _spread_typ(self, j: Job, q: Quote) -> float | None:
        """Spread típico en ese minuto: el que este mismo broker mostró en los últimos 60 días del slot (≥20 obs);
        mientras no haya historia, el de Dukascopy + el sobreprecio estimado de OANDA."""
        key = f"spread:{j.sym}|{j.slot}"
        hist = self.store.get(key, [])
        typ = float(np.median(hist)) if len(hist) >= 20 else None
        self.store.set(key, (hist + [q.spread])[-60:])
        if typ is None:
            base = self.model.get("scales", {}).get(f"{j.sym}|{j.slot}", {}).get("spread_typ")
            pair = C.PAIRS[j.sym]
            typ = base + pair.oanda_markup_pips * pair.pip if base else None
        return typ

    def _skip(self, j: Job, rec: dict, why: str) -> str:
        self.store.log("skip", {**rec, "why": why}, j.sym)
        return f"no: {why}"

    # ── ciclo ─────────────────────────────────────────────────────────────────────────────────────────────────
    async def tick(self):
        now = self.clock()
        self.book.roll(now)
        m = int(now // 60)
        d = K.ny(m).date()
        if self.planned_day != d:
            self.plan(d)
        if self.kill_path:
            from .monitor import kill_active
            k = kill_active(self.kill_path, m)
            if k and self.kill != k:
                self.kill = k
                self.store.log("kill", {"why": k})
                await self.flatten(f"kill-switch: {k}")
            elif not k:
                self.kill = None
        for a in self.risk.on_time(m):
            if a.startswith("close:"):
                await self.close(a.split(":", 1)[1], "tiempo/salida forzada")
            elif a.startswith("flatten"):
                await self.flatten(a.split(":", 1)[1])
        due = [j for j in self.jobs if not j.done and now >= (j.t0 + C.ENTRY_LAG_MIN) * 60 + 0.2]
        late = [j for j in due if now > (j.t0 + 20) * 60]           # ventana de entrada T+5..T+20 (F14-016)
        for j in late:
            j.done, j.result = True, "fuera de ventana T+20"
            self.store.log("skip", {"slot": j.slot, "t0": j.t0, "why": j.result}, j.sym)
        due = [j for j in due if j not in late]
        by = {}
        for j in due:
            by.setdefault((j.slot, j.t0), []).append(j)
        for batch in by.values():
            await self.evaluate(batch, now)

    async def handle_intent(self, it: dict) -> str:
        act = str(it.get("action", "")).upper()
        if act == "FLATTEN":
            await self.flatten("intent TradingView/humano")
            return "plano"
        if act == "PAUSE":
            self.halt = "pausa manual"
            return "pausado"
        if act == "RESUME":
            if self.halt == "pausa manual":
                self.halt = None
                return "reanudado (las pausas del gobernador siguen vigentes)"
            return f"no se reanuda: {self.halt or 'no había pausa manual'}"
        if act == "CHECK":
            return json.dumps(self.snapshot(), default=str)[:500]
        return "ignorado: el webhook no puede abrir operaciones (solo FLATTEN/PAUSE/RESUME/CHECK)"

    async def reconcile(self):
        """Posiciones internas vs broker; cualquier diferencia detiene entradas nuevas (F15-017 E)."""
        try:
            trades = await self.broker.open_trades()
        except Exception as e:
            self.status["reconcile"] = f"error {type(e).__name__}"
            return
        mine = {t["id"] for t in trades if (t.get("client_id") or "").startswith("fx-")}
        local = {lv.trade_id for lv in self.live.values()}
        if mine != local:
            gone = local - mine
            for sym, lv in list(self.live.items()):
                if lv.trade_id in gone:
                    self.store.log("reconcile", {"trade": lv.trade_id, "why": "cerrada en broker sin aviso"}, sym)
            extra = mine - local
            if extra:
                self.halt = f"reconciliación: trades en broker no reconocidos {sorted(extra)}"
                self.store.log("reconcile", {"halt": self.halt})
        self.status["reconcile"] = "ok" if mine == local else "diferencias"

    def snapshot(self) -> dict:
        return {"mode": self.mode, "halt": self.halt, "kill": self.kill, "risk": self.risk.snapshot(), "status": self.status,
                "jobs": [(j.sym, j.slot, j.t0, j.done, j.result) for j in self.jobs],
                "live": {k: {"trade": v.trade_id, "deadline": v.pos.deadline_m} for k, v in self.live.items()}}

    async def run(self, stop: asyncio.Event, heartbeat: str | None = None, intents=None):
        last_rec = 0.0
        while not stop.is_set():
            try:
                await self.tick()
                if intents:
                    for it in intents():
                        res = await self.handle_intent(it)
                        self.store.done_intent(it["id"], res)
                        self.store.log("intent", {"id": it["id"], "action": it.get("action"), "result": res})
                if self.clock() - last_rec > 60:
                    last_rec = self.clock()
                    await self.reconcile()
                if heartbeat:
                    _touch(heartbeat, self.snapshot())
            except Exception as e:  # el motor no se cae por un error puntual; queda en bitácora
                self.store.log("error", {"error": f"{type(e).__name__}: {e}"[:300]})
            await asyncio.sleep(0.25)


def _touch(path: str, snap: dict):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"ts": time.time(), **snap}, fh, default=str)
    os.replace(tmp, path)
