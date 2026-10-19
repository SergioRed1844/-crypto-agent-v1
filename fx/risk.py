"""Motor de riesgo del agente FX (capa 4/6 del corpus F15-014). Lógica pura con el tiempo inyectado: el mismo
objeto corre en el backtest, en el simulador y frente a OANDA. Solo puede negar, achicar o cerrar.

Reglas (config.Risk; techos en config.HARD):
  · Riesgo por evento 0.35% del capital si salta el stop, repartido entre los pares que disparan en el mismo slot
    (reaccionan al mismo dato: es una sola apuesta al USD, no cuatro).
  · Gobernador semanal: pérdida de la semana FX ≥ 1.5% → todo plano y sin entradas hasta el domingo 17:00 NY.
    Además cada operación arriesga como máximo el 90% de lo que queda del tope (contando el riesgo abierto), así
    que el tope solo se puede rebasar por gaps o deslizamiento, nunca por una cadena de stops normales.
  · Diario −1% → sin entradas hasta el siguiente día FX. 3 pérdidas seguidas → pausa 24 h.
  · Drawdown desde el máximo: 5% (1×σ*) → tamaño a la mitad; 10% (2×σ*) → apagado hasta revisión humana.
  · Apalancamiento bruto ≤ 5×, una posición por par, ≤ 4 abiertas, |USD neto| ≤ 3× capital.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import calendar as K
from . import config as C


@dataclass
class Position:
    sym: str
    side: int
    units: float
    entry: float
    stop: float
    risk_usd: float
    entry_m: int
    deadline_m: int
    notional_usd: float
    usd_dir: int
    ref: str = ""


@dataclass
class Decision:
    units: float = 0.0
    risk_usd: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.units > 0 and not self.reasons


def quote_to_usd(sym: str, price: float) -> float:
    return 1.0 if sym.endswith("USD") else 1.0 / price


def notional_usd(sym: str, units: float, price: float) -> float:
    return units * price if sym.endswith("USD") else units


class RiskEngine:
    def __init__(self, equity: float, risk: C.Risk = C.RISK):
        self.r = C.check_risk(risk)
        self.equity = float(equity)
        self.peak = float(equity)
        self.week = None
        self.week_start = float(equity)
        self.week_realized = 0.0
        self.day = None
        self.day_start = float(equity)
        self.day_realized = 0.0
        self.streak = 0
        self.pause_until = 0
        self.off: str | None = None
        self.open: dict[str, Position] = {}
        self.log: list[tuple[int, str]] = []

    # ── reloj ──────────────────────────────────────────────────────────────────────────────────────────────────
    def on_time(self, m: int) -> list[str]:
        """Cambia de día/semana FX y devuelve acciones obligatorias: 'flatten:<motivo>' o 'close:<sym>'."""
        acts = []
        w, d = K.fx_week(m), K.fx_day(m)
        if w != self.week:
            self.week, self.week_start, self.week_realized = w, self.equity, 0.0
        if d != self.day:
            self.day, self.day_start, self.day_realized = d, self.equity, 0.0
        for p in list(self.open.values()):
            if m >= p.deadline_m:
                acts.append(f"close:{p.sym}")
        if self.off and self.open:
            acts.append(f"flatten:{self.off}")
        return acts

    @property
    def drawdown(self) -> float:
        return 1.0 - self.equity / self.peak if self.peak > 0 else 0.0

    def open_risk(self) -> float:
        return sum(p.risk_usd for p in self.open.values())

    def week_room(self) -> float:
        """Pérdida que aún cabe en la semana (solo tope de pérdida: las ganancias de la semana amplían el margen)."""
        return self.r.weekly_loss_cap * self.week_start + self.week_realized - self.open_risk()

    def day_room(self) -> float:
        return self.r.daily_loss_cap * self.day_start + self.day_realized - self.open_risk()

    # ── tamaño ─────────────────────────────────────────────────────────────────────────────────────────────────
    def size(self, m: int, sym: str, side: int, price: float, stop_dist: float, n_in_event: int = 1,
             blackout: str | None = None) -> Decision:
        self.on_time(m)
        dec = Decision()
        R = self.r
        if self.off:
            dec.reasons.append(f"apagado: {self.off}")
        if m < self.pause_until:
            dec.reasons.append("pausa activa")
        if blackout:
            dec.reasons.append(f"blackout: {blackout}")
        if R.one_per_pair and sym in self.open:
            dec.reasons.append("ya hay posición en el par")
        if len(self.open) >= R.max_positions:
            dec.reasons.append("máximo de posiciones")
        if self.week_realized <= -R.weekly_loss_cap * self.week_start:
            dec.reasons.append("tope semanal alcanzado")
        if self.day_realized <= -R.daily_loss_cap * self.day_start:
            dec.reasons.append("tope diario alcanzado")
        if stop_dist <= 0 or price <= 0:
            dec.reasons.append("stop inválido")
        if dec.reasons:
            return dec
        risk_usd = R.risk_per_event / max(n_in_event, 1) * self.equity
        if self.drawdown >= R.dd_yellow:
            risk_usd *= 0.5
        room = min(self.week_room(), self.day_room()) * R.budget_safety
        if room <= 0:
            dec.reasons.append("sin presupuesto de pérdida esta semana/día")
            return dec
        risk_usd = min(risk_usd, room)
        units = risk_usd / (stop_dist * quote_to_usd(sym, price))
        gross = sum(p.notional_usd for p in self.open.values())
        cap = R.max_leverage * self.equity - gross
        n_usd = notional_usd(sym, units, price)
        if n_usd > cap:
            units *= max(cap, 0.0) / n_usd
            n_usd = notional_usd(sym, units, price)
        usd_dir = side * C.PAIRS[sym].usd_sign
        net = sum(p.usd_dir * p.notional_usd for p in self.open.values())
        lim = R.max_net_usd_x * self.equity
        if abs(net + usd_dir * n_usd) > lim and n_usd > 0:
            allowed = max(lim - usd_dir * net, 0.0)
            units *= min(allowed / n_usd, 1.0)
        units = float(int(units))          # OANDA acepta unidades enteras
        if units < 1:
            dec.reasons.append("tamaño menor a 1 unidad tras límites")
            return dec
        dec.units = units
        dec.risk_usd = units * stop_dist * quote_to_usd(sym, price)
        return dec

    # ── eventos de posición ───────────────────────────────────────────────────────────────────────────────────
    def on_open(self, p: Position):
        self.open[p.sym] = p

    def on_close(self, sym: str, pnl_usd: float, m: int) -> list[str]:
        """Registra el cierre y aplica las pausas; devuelve acciones (p. ej. 'flatten:tope semanal')."""
        self.on_time(m)
        self.open.pop(sym, None)
        self.equity += pnl_usd
        self.week_realized += pnl_usd
        self.day_realized += pnl_usd
        self.peak = max(self.peak, self.equity)
        acts = []
        self.streak = self.streak + 1 if pnl_usd < 0 else 0
        R = self.r
        if self.streak >= R.loss_streak_pause:
            self.pause_until = max(self.pause_until, m + 24 * 60)
            self.log.append((m, f"{self.streak} pérdidas seguidas: pausa 24 h"))
            self.streak = 0
        if self.day_realized <= -R.daily_loss_cap * self.day_start:
            nxt = K.local_min(K.fx_day(m), "17:00", "America/New_York")
            self.pause_until = max(self.pause_until, nxt)
            self.log.append((m, "tope diario: sin entradas hasta el siguiente día FX"))
        if self.week_realized <= -R.weekly_loss_cap * self.week_start:
            self.pause_until = max(self.pause_until, K.next_week_open_min(m))
            self.log.append((m, "tope semanal −1.5%: todo plano hasta el domingo 17:00 NY"))
            acts.append("flatten:tope semanal")
        if self.drawdown >= R.dd_red:
            self.off = f"drawdown {self.drawdown:.1%} ≥ {R.dd_red:.0%}"
            self.log.append((m, f"APAGADO: {self.off}"))
            acts.append(f"flatten:{self.off}")
        return acts

    def snapshot(self) -> dict:
        return {"equity": round(self.equity, 2), "peak": round(self.peak, 2), "drawdown": round(self.drawdown, 4),
                "week": self.week, "week_pnl": round(self.week_realized, 2), "day_pnl": round(self.day_realized, 2),
                "streak": self.streak, "pause_until": self.pause_until, "off": self.off,
                "open": {k: vars(v) for k, v in self.open.items()}}
