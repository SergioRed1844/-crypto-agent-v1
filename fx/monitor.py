"""Monitor independiente y kill-switch (capa 6, F15-014): otro proceso, otra conexión, solo puede cerrar.

Cada 5 s lee la cuenta en el broker (NAV con P&L flotante, no lo que cree el motor):
  · semana FX: NAV ≤ inicio de semana × (1 − 1.5%) → cierra todo y bloquea entradas hasta el domingo 17:00 NY;
  · día FX: NAV ≤ inicio del día × (1 − 1%) → cierra todo y bloquea hasta el siguiente día FX;
  · drawdown desde el máximo ≥ 10% → cierra todo y apaga (solo un humano borra el archivo KILL);
  · cualquier trade del agente abierto después de la salida forzada (16:50 NY; viernes 15:55) + 2 min → lo cierra;
  · si el motor no late en 60 s y hay trades abiertos, avisa en la bitácora (los stops siguen en el broker).
El bloqueo se comunica con un archivo KILL (JSON {until, why}) que el motor revisa cada ciclo.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from . import calendar as K
from . import config as C
from .store import Store


def write_kill(path: str, until: int, why: str):
    """until = minuto UTC hasta el que se bloquea; 0 = indefinido (apagado)."""
    cur = read_kill(path)
    if cur and (cur["until"] == 0 or cur["until"] >= until) and until != 0:
        return
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"until": until, "why": why, "ts": time.time()}, fh)
    os.replace(tmp, path)


def read_kill(path: str) -> dict | None:
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def kill_active(path: str, now_m: int) -> str | None:
    k = read_kill(path)
    if not k:
        return None
    if k.get("until", 0) == 0 or now_m < k["until"]:
        return k.get("why", "kill-switch")
    return None


class Monitor:
    def __init__(self, broker, store: Store, kill_path: str, engine_hb: str | None = None, clock=time.time,
                 risk: C.Risk = C.RISK):
        self.b, self.s, self.kill, self.hb, self.clock, self.r = broker, store, kill_path, engine_hb, clock, risk
        self.st = store.get("monitor_state", {}) or {}

    async def step(self) -> list[str]:
        acts = []
        now = self.clock()
        m = int(now // 60)
        acc = await self.b.summary()
        nav = acc["nav"]
        wk, dy = K.fx_week(m), K.fx_day(m).isoformat()
        st = self.st
        if st.get("week") != wk:
            st["week"], st["week_nav"] = wk, nav
        if st.get("day") != dy:
            st["day"], st["day_nav"] = dy, nav
        st["peak"] = max(st.get("peak", nav), nav)
        trades = [t for t in await self.b.open_trades() if (t.get("client_id") or "").startswith("fx-")]
        why = None
        if nav <= st["week_nav"] * (1 - self.r.weekly_loss_cap):
            why = (K.next_week_open_min(m), f"monitor: semana {nav / st['week_nav'] - 1:.2%}")
        elif nav <= st["day_nav"] * (1 - self.r.daily_loss_cap):
            why = (K.local_min(K.fx_day(m), "17:00", "America/New_York"), f"monitor: día {nav / st['day_nav'] - 1:.2%}")
        if nav <= st["peak"] * (1 - self.r.dd_red):
            why = (0, f"monitor: drawdown {1 - nav / st['peak']:.2%} — APAGADO")
        if why:
            cur = read_kill(self.kill)
            stronger = not cur or (cur.get("until", 0) != 0 and (why[0] == 0 or why[0] > cur["until"]))
            if stronger:
                acts.append(await self._kill(*why))
                trades = []
            elif trades:
                await self.b.close_all()
                acts.append(f"kill vigente: cerradas {len(trades)} abiertas")
                trades = []
        for t in trades:
            opened = int((t.get("open_time") or now) // 60)
            if m >= K.forced_exit_min(opened) + 2:
                try:
                    await self.b.close(t["id"])
                    acts.append(f"cerrado {t['sym']} por salida forzada vencida")
                except Exception as e:
                    acts.append(f"error al cerrar {t['sym']}: {type(e).__name__}")
        if self.hb and trades:
            age = now - os.path.getmtime(self.hb) if os.path.exists(self.hb) else 1e9
            if age > 60:
                acts.append(f"motor sin latido {age:.0f} s con {len(trades)} trades abiertos (stops en el broker)")
        st["nav"], st["ts"] = nav, now
        self.s.set("monitor_state", st)
        for a in acts:
            self.s.log("monitor", {"action": a, "nav": nav})
        return acts

    async def _kill(self, until: int, why: str) -> str:
        write_kill(self.kill, until, why)
        res = await self.b.close_all()
        return f"{why}: cerradas {len(res)}"

    async def run(self, stop: asyncio.Event, interval: float = 5.0, heartbeat: str | None = None):
        while not stop.is_set():
            try:
                await self.step()
                if heartbeat:
                    with open(heartbeat, "w") as fh:
                        fh.write(str(time.time()))
            except Exception as e:
                self.s.log("monitor_error", {"error": f"{type(e).__name__}: {e}"[:200]})
            await asyncio.sleep(interval)
