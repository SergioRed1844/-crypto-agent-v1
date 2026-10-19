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
        """Cierra la vela en curso si su minuto ya terminó. Un minuto sin precios no genera vela (igual que
        Dukascopy, que omite los minutos sin operaciones), para que σ en vivo y en backtest se midan igual."""
        m = int(now_s // 60)
        for sym, c in list(self.cur.items()):
            if c is not None and c[0] < m:
                self.bars.setdefault(sym, deque(maxlen=self.keep)).append(tuple(c))
                self.cur[sym] = None

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


CLOSE_RETRY_S = 5.0


class Engine:
    def __init__(self, broker, model: dict, store: Store, equity: float, mode: str = "paper",
                 clock=time.time, known_events: list[dict] | None = None, risk: C.Risk = C.RISK,
                 kill_path: str | None = None):
        self.broker, self.model, self.store, self.mode, self.clock = broker, model, store, mode, clock
        self.kill_path = kill_path
        self.book = MinuteBook()
        if hasattr(broker, "load") and store.get("paper_broker"):
            broker.load(store.get("paper_broker"))
            equity = broker.balance
        self.risk = RiskEngine(equity, risk)
        self.known = [e["minute"] for e in (known_events or [])]
        self.jobs: list[Job] = []
        self.planned_day: date | None = None
        self.live: dict[str, Live] = {}
        self.halt: str | None = None          # pausa manual o por reconciliación (solo humano la quita)
        self.kill: str | None = None          # bloqueo del monitor independiente (archivo KILL)
        self.closed_ids: list[str] = []
        self.status: dict = {"stream": "sin conectar"}
        self._restore()

    # ── persistencia (sobrevive reinicios de systemd) ─────────────────────────────────────────────────────────
    def _restore(self):
        r = self.risk
        m = int(self.clock() // 60)
        s = self.store.get("risk_state")
        if s:
            if self.mode == "paper" and s.get("equity") and not hasattr(self.broker, "load"):
                r.equity = float(s["equity"])
            r.peak = max(s.get("peak", r.equity), r.equity)
            if s.get("week") == K.fx_week(m):
                r.week, r.week_start, r.week_realized = s["week"], s["week_start"], s["week_realized"]
            if s.get("day") == K.fx_day(m).isoformat():
                r.day, r.day_start, r.day_realized = K.fx_day(m), s["day_start"], s["day_realized"]
            r.pause_until = s.get("pause_until", 0)
            r.off = s.get("off")
            r.streak = s.get("streak", 0)
        self.halt = self.store.get("halt")
        self.closed_ids = self.store.get("closed_ids", []) or []
        for p in self.store.get("positions", []) or []:
            pos = Position(**p["pos"])
            self.live[pos.sym] = Live(pos, p["trade_id"], p["client_id"], p.get("meta", {}))
            r.on_open(pos)

    def _persist(self):
        r = self.risk
        self.store.set("risk_state", {"peak": r.peak, "week": r.week, "week_start": r.week_start,
                                      "week_realized": r.week_realized,
                                      "day": r.day.isoformat() if r.day else None, "day_start": r.day_start,
                                      "day_realized": r.day_realized, "pause_until": r.pause_until, "off": r.off,
                                      "streak": r.streak, "equity": r.equity})
        self.store.set("positions", [{"pos": vars(lv.pos), "trade_id": lv.trade_id, "client_id": lv.client_id,
                                      "meta": {k: v for k, v in lv.meta.items() if k != "next_try"}}
                                     for lv in self.live.values()])
        self.store.set("halt", self.halt)
        self.store.set("closed_ids", self.closed_ids[-300:])
        if hasattr(self.broker, "dump"):
            self.store.set("paper_broker", self.broker.dump())

    # ── plan del día ──────────────────────────────────────────────────────────────────────────────────────────
    def plan(self, d: date):
        """Un trabajo por (par, slot) del día. Los grupos inactivos también se miden (z, spread de ESTE broker):
        así la práctica calibra costos y escalas aunque el modelo no opere nada (F15-017 B)."""
        self.jobs = []
        act = self.model.get("_active", {})
        if d.weekday() < 5:
            for slot in C.SLOTS:
                for sym in C.PAIRS:
                    if slot.pairs and sym not in slot.pairs:
                        continue
                    self.jobs.append(Job(sym, slot.name, K.slot_min(slot, d), act.get((sym, slot.name))))
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
        for tc in (tx.get("tradesClosed") or []) + (tx.get("tradesReduced") or []):
            tid = tc.get("tradeID")
            for sym, lv in list(self.live.items()):
                if lv.trade_id == tid:
                    pl = float(tc.get("realizedPL", 0)) + float(tc.get("financing", 0) or 0)
                    self._closed(sym, tid, pl, f"broker:{tx.get('reason', '')}", float(tc.get("price", 0) or 0))

    def _closed(self, sym: str, trade_id: str, pl: float, why: str, px: float = 0.0):
        """Único punto que registra un cierre: idempotente por trade_id (el stream y el PUT pueden avisar ambos)."""
        if trade_id in self.closed_ids:
            return
        lv = self.live.get(sym)
        if lv is None or lv.trade_id != trade_id:
            self.store.log("close_unknown", {"trade": trade_id, "pl": pl, "why": why}, sym)
            return
        self.closed_ids.append(trade_id)
        self.live.pop(sym, None)
        m = int(self.clock() // 60)
        acts = self.risk.on_close(sym, pl, m)
        self.store.log("close", {"why": why, "pl": pl, "price": px, "trade": trade_id,
                                 "R": pl / lv.pos.risk_usd if lv.pos.risk_usd else None,
                                 "risk": self.risk.snapshot()}, sym, lv.client_id)
        self._persist()
        for a in acts:
            if a.startswith("flatten"):
                asyncio.get_event_loop().create_task(self.flatten(a.split(":", 1)[1]))

    async def _trade_info(self, trade_id: str) -> dict | None:
        try:
            return await self.broker.trade(trade_id)
        except Exception as e:
            self.store.log("trade_lookup_error", {"trade": trade_id, "error": f"{type(e).__name__}: {e}"[:200]})
            return None

    async def close(self, sym: str, why: str):
        lv = self.live.get(sym)
        if not lv or self.clock() < lv.meta.get("next_try", 0):
            return
        try:
            res = await self.broker.close(lv.trade_id)
        except Exception as e:
            self.store.log("close_error", {"why": why, "error": f"{type(e).__name__}: {e}"[:200]}, sym, lv.client_id)
            info = await self._trade_info(lv.trade_id)
            if info and info.get("state") == "CLOSED":
                self._closed(sym, lv.trade_id, info["pl"], f"{why} (ya cerrada en broker)", info.get("price", 0.0))
            else:
                lv.meta["next_try"] = self.clock() + CLOSE_RETRY_S     # mercado detenido: reintento sin spam
            return
        self._closed(sym, lv.trade_id, res["pl"] + res.get("financing", 0.0), why, res["price"])
        self.store.log("latency", {"what": "close", "t_sent": res["t_sent"], "t_ack": res["t_ack"],
                                   "t_fill": res["t_fill"]}, sym, lv.client_id)

    async def flatten(self, why: str):
        for sym in list(self.live):
            await self.close(sym, f"flatten:{why}")

    # ── escala y spread del slot (se actualizan en vivo con cada día, como en el backtest) ──────────────────────
    def _hist(self, kind: str, j: Job) -> list:
        return self.store.get(f"{kind}:{j.sym}|{j.slot}", []) or []

    def _sigma(self, j: Job) -> float | None:
        sc = self.model.get("scales", {}).get(f"{j.sym}|{j.slot}", {})
        base = [x for x in sc.get("abs_hist", [])]
        live = [v for d, v in self._hist("absret", j) if d > sc.get("last_day", "")]
        hist = (base + live)[-C.SCALE_WINDOW_DAYS:]
        if len(hist) >= C.MIN_SCALE_OBS:
            return float(1.4826 * np.median(hist))
        return sc.get("sigma_slot")

    def _record(self, j: Job, ret: float | None, spread: float | None):
        day = K.from_min(j.t0).date().isoformat()
        if ret is not None:
            h = [x for x in self._hist("absret", j) if x[0] != day]
            self.store.set(f"absret:{j.sym}|{j.slot}", (h + [[day, abs(ret)]])[-C.SCALE_WINDOW_DAYS:])
        if spread is not None:
            h = [x for x in self._hist("spread", j) if x[0] != day]
            self.store.set(f"spread:{j.sym}|{j.slot}", (h + [[day, spread]])[-60:])

    def _spread_typ(self, j: Job) -> float | None:
        """Mediana del spread de ESTE broker en ese minuto los últimos 60 días hábiles (todos los días, como el
        backtest); mientras haya <20, el de Dukascopy + el sobreprecio estimado de OANDA."""
        h = [v for _, v in self._hist("spread", j)]
        if len(h) >= 20:
            return float(np.median(h))
        base = self.model.get("scales", {}).get(f"{j.sym}|{j.slot}", {}).get("spread_typ")
        pair = C.PAIRS[j.sym]
        return base + pair.oanda_markup_pips * pair.pip if base else None

    # ── decisión en T0+15 ─────────────────────────────────────────────────────────────────────────────────────
    def _signal(self, j: Job, now: float) -> dict:
        lag = C.ENTRY_LAG_MIN
        p0 = self.book.close_at(j.sym, j.t0 - 1)
        p15 = self.book.close_at(j.sym, j.t0 + lag - 1, max_age=2)
        q = self.book.last.get(j.sym)
        sig = self._sigma(j)          # con días previos: el de hoy se agrega después
        ret = math.log(p15 / p0) if p0 and p15 else None
        typ = self._spread_typ(j)
        self._record(j, ret, q.spread if q else None)
        if ret is None or not sig:
            return {"ok": False, "why": "sin precios del slot o sin escala"}
        z = ret / sig
        if j.group is None:
            return {"ok": False, "why": "observación (grupo inactivo)", "z": z, "spread": q.spread if q else None}
        if abs(z) < j.group["z"]:
            return {"ok": False, "why": f"|z|={abs(z):.2f} < {j.group['z']}", "z": z}
        side = (1 if ret > 0 else -1) * (1 if j.group["dir"] == "mom" else -1)
        return {"ok": True, "z": z, "ret15": ret, "side": side, "spread_typ": typ, "sigma": sig}

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
        typ = sg.get("spread_typ")
        if typ and q.spread > C.SPREAD_MAX_X * typ:
            return self._skip(j, rec, f"spread {q.spread / pair.pip:.1f} pips > {C.SPREAD_MAX_X}× típico "
                                      f"({typ / pair.pip:.1f})")
        hold = int(j.group["hold"])
        nxt = [e - C.EVENT_GUARD_MIN for e in self.known if e > m]
        deadline = min([m + hold, K.exit_cap_min(j.slot, m)] + nxt[:1])
        if deadline - m < C.MIN_HOLD_MIN:
            return self._skip(j, rec, "salida forzada, otro slot o evento mayor a menos de 10 min")
        pre = self.book.mids(j.sym, j.t0 - 60, j.t0 - 1)
        post = self.book.mids(j.sym, j.t0 + 4, j.t0 + C.ENTRY_LAG_MIN - 1)
        sh = E.sigma_h_from(pre, post, deadline - m)
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
        bound = ref + side * max(2 * q.spread, 2 * pair.pip)
        cid = f"fx-{j.slot}-{j.sym}-{j.t0}"
        comment = f"{j.slot} z={sg['z']:.2f} {j.group['dir']} {hold}m"
        try:
            fill = await self.broker.market(j.sym, side * dec.units, stop, bound, cid, comment)
        except OrderRejected as e:
            return self._skip(j, rec, f"broker: {e}")
        except Exception as e:      # timeout de red con la orden quizá ya llenada: se busca por client id
            info = await self._trade_info(f"@{cid}")
            if not info or info.get("state") != "OPEN":
                return self._skip(j, rec, f"red: {type(e).__name__}; sin trade en broker")
            from .broker import Fill
            fill = Fill(info["id"], j.sym, info["units"], info["price"], info.get("open_time", 0.0), t_dec,
                        self.clock(), info.get("stop") or stop, cid)
            stop = fill.stop
        risk_usd = abs(fill.price - stop) * abs(fill.units) * quote_to_usd(j.sym, fill.price)
        pos = Position(j.sym, side, abs(fill.units), fill.price, stop, risk_usd, m, deadline,
                       notional_usd(j.sym, abs(fill.units), fill.price), side * pair.usd_sign, fill.trade_id)
        self.risk.on_open(pos)
        self.live[j.sym] = Live(pos, fill.trade_id, cid, rec)
        self._persist()
        lat = {"t_event": (j.t0 + C.ENTRY_LAG_MIN) * 60.0, "t_provider": q.t_provider, "t_recv": q.t_recv,
               "t_decision": t_dec, "t_sent": fill.t_sent, "t_ack": fill.t_ack, "t_fill": fill.t_fill}
        self.store.log("open", {**rec, "units": fill.units, "price": fill.price, "stop": stop, "risk_usd": risk_usd,
                                "deadline": deadline, "trade": fill.trade_id, "latency": lat}, j.sym, cid)
        self.store.log("latency", {"what": "open", **lat}, j.sym, cid)
        return f"abierta {side:+d} {abs(fill.units):.0f} u @ {fill.price}"

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
            elif not k:
                self.kill = None
            if self.kill and self.live:
                await self.flatten(f"kill-switch: {self.kill}")
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
            self._persist()
            return "pausado"
        if act == "RESUME":
            if self.halt == "pausa manual":
                self.halt = None
                self._persist()
                return "reanudado (las pausas del gobernador siguen vigentes)"
            return f"no se reanuda: {self.halt or 'no había pausa manual'}"
        if act == "CHECK":
            return json.dumps(self.snapshot(), default=str)[:500]
        if act == "SIGNAL":
            return "telemetría"
        return "ignorado: el webhook no puede abrir operaciones (solo FLATTEN/PAUSE/RESUME/CHECK)"

    async def reconcile(self):
        """Posiciones internas vs broker (F15-017 E). Las del agente que el broker ya cerró se liquidan con su P&L
        real; las del agente que el broker tiene y el motor no conoce se adoptan con stop y salida; cualquier otra
        diferencia detiene entradas nuevas."""
        try:
            trades = await self.broker.open_trades()
        except Exception as e:
            self.status["reconcile"] = f"error {type(e).__name__}"
            return
        mine = {t["id"]: t for t in trades if (t.get("client_id") or "").startswith("fx-")}
        for sym, lv in list(self.live.items()):
            if lv.trade_id in mine:
                continue
            info = await self._trade_info(lv.trade_id)
            if info and info.get("state") == "CLOSED":
                self._closed(sym, lv.trade_id, info["pl"], "reconciliación: cerrada en broker", info.get("price", 0.0))
            else:
                self.halt = f"reconciliación: {lv.trade_id} no aparece en el broker"
                self._persist()
        local = {lv.trade_id for lv in self.live.values()}
        for tid, t in mine.items():
            if tid in local:
                continue
            if not t.get("stop") or t["sym"] in self.live:
                self.halt = f"reconciliación: trade {tid} sin stop o duplicado"
                self.store.log("reconcile", {"halt": self.halt})
                self._persist()
                continue
            side = 1 if t["units"] > 0 else -1
            parts = t["client_id"].split("-")
            slot = parts[1] if len(parts) >= 4 else ""
            em = int((t.get("open_time") or self.clock()) // 60)
            q2u = quote_to_usd(t["sym"], t["price"])
            pos = Position(t["sym"], side, abs(t["units"]), t["price"], t["stop"],
                           abs(t["price"] - t["stop"]) * abs(t["units"]) * q2u, em, K.exit_cap_min(slot, em),
                           notional_usd(t["sym"], abs(t["units"]), t["price"]), side * C.PAIRS[t["sym"]].usd_sign, tid)
            self.risk.on_open(pos)
            self.live[t["sym"]] = Live(pos, tid, t["client_id"], {"adopted": True})
            self.store.log("reconcile", {"adopted": tid, "deadline": pos.deadline_m}, t["sym"])
            self._persist()
        self.status["reconcile"] = "ok" if set(mine) == {lv.trade_id for lv in self.live.values()} else "diferencias"

    def snapshot(self) -> dict:
        return {"mode": self.mode, "halt": self.halt, "kill": self.kill, "risk": self.risk.snapshot(),
                "status": self.status, "jobs": [(j.sym, j.slot, j.t0, j.done, j.result) for j in self.jobs],
                "live": {k: {"trade": v.trade_id, "deadline": v.pos.deadline_m} for k, v in self.live.items()}}

    async def run(self, stop: asyncio.Event, heartbeat: str | None = None, intents=None):
        await self.reconcile()                 # al arrancar: liquida o adopta lo que quedó del proceso anterior
        last_rec = self.clock()
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
