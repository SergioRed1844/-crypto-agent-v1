"""Estudio de eventos intradía (Estrategia A, F14-016) sobre velas de 1 minuto bid/ask.

Para cada día hábil y slot:
  · P0 = mid al cierre del minuto T0−1 (precio antes del dato) y P15 = mid al cierre del minuto T0+14.
  · ret15 = ln(P15/P0); escala del slot σ_slot = 1.4826·mediana|ret15| de los ~250 días hábiles PREVIOS (sin mirar
    el futuro); z = ret15/σ_slot. Los días sin dato dan z≈0; los días con sorpresa dan |z| grande. Así se detecta la
    sorpresa sin pagar consenso.
  · Si |z| ≥ z_min se simula la operación: entrada al OPEN del minuto T0+15 (ask si compra, bid si vende), stop
    = 1.5·σ esperada del horizonte (vol base previa + exceso del evento que decae con vida media de 20 min), salida
    por tiempo o a la hora forzada (16:50 NY; viernes 15:55 NY), lo que ocurra primero. Stop revisado con el mínimo
    bid / máximo ask de cada minuto; si el minuto abre más allá del stop se llena al open (gap).
  · Costos: spread real cruzado (bid/ask de Dukascopy) + sobreprecio estimado de OANDA + deslizamiento por lado.

Resultado en múltiplos de R (riesgo inicial = distancia al stop): eso hace comparable todo entre pares y fechas
y es exactamente lo que el motor de riesgo arriesga por operación.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from . import calendar as K
from . import config as C

HALF_LIFE_MIN = 20.0


@dataclass
class Bars:
    sym: str
    t: np.ndarray
    bo: np.ndarray; bh: np.ndarray; bl: np.ndarray; bc: np.ndarray
    ao: np.ndarray; ah: np.ndarray; al: np.ndarray; ac: np.ndarray

    @classmethod
    def from_raw(cls, sym: str, raw: dict) -> "Bars":
        p = C.PAIRS[sym].point
        f = lambda k: np.asarray(raw[k], dtype=np.float64) * p  # noqa: E731
        return cls(sym, np.asarray(raw["t"], dtype=np.int64), f("bo"), f("bh"), f("bl"), f("bc"),
                   f("ao"), f("ah"), f("al"), f("ac"))

    def mid_c(self, i):
        return (self.bc[i] + self.ac[i]) / 2

    @property
    def days(self) -> tuple[date, date]:
        return K.from_min(self.t[0]).date(), K.from_min(self.t[-1]).date()


@dataclass
class Event:
    sym: str
    slot: str
    day: date
    t0: int
    ret15: float
    z: float
    sigma_slot: float
    spread: float           # spread al momento de la entrada (precio)
    spread_typ: float       # mediana de los 60 días previos en ese mismo minuto
    blackout: str | None
    entry_m: int = 0
    sims: dict = field(default_factory=dict)   # (dir, hold) → dict(R, R_cost, why, exit_m, bps)

    @property
    def spread_ok(self) -> bool:
        return not (self.spread_typ > 0 and self.spread > C.SPREAD_MAX_X * self.spread_typ)


def _last_le(t: np.ndarray, m: int) -> int:
    return int(np.searchsorted(t, m, "right")) - 1


def _first_ge(t: np.ndarray, m: int) -> int:
    return int(np.searchsorted(t, m, "left"))


def slot_series(b: Bars, slot: C.Slot, start: date | None = None, end: date | None = None):
    """ret15 y spreads de entrada para todos los días hábiles del slot (incluye días sin dato)."""
    d0, d1 = b.days
    rows = []
    for d in K.weekdays(start or d0, end or d1):
        t0 = K.slot_min(slot, d)
        i0 = _last_le(b.t, t0 - 1)
        i15 = _last_le(b.t, t0 + C.ENTRY_LAG_MIN - 1)
        ie = _first_ge(b.t, t0 + C.ENTRY_LAG_MIN)
        if i0 < 0 or ie >= len(b.t) or i15 <= i0:
            continue
        if t0 - 1 - b.t[i0] > 10 or b.t[i15] < t0 + 5 or b.t[ie] - (t0 + C.ENTRY_LAG_MIN) > 3:
            continue   # festivo o hueco de datos
        ret = math.log(b.mid_c(i15) / b.mid_c(i0))
        rows.append((d, t0, ret, b.ao[ie] - b.bo[ie], i0, i15, ie))
    return rows


def robust_scale(x: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(x))) if len(x) else float("nan")


def sigma_h_from(pre_mids: np.ndarray, post_mids: np.ndarray, hold: int) -> float | None:
    """σ (log) esperada de T+15 a T+15+hold a partir de mids de 1 minuto: ``pre`` = T−60..T0, ``post`` =
    T+4..T+15. Varianza base previa + exceso del evento que decae con vida media HALF_LIFE_MIN (kernel F14-005)."""
    if len(pre_mids) < 20 or len(post_mids) < 5:
        return None
    s_base2 = float(np.var(np.diff(np.log(pre_mids))))
    s_post2 = float(np.var(np.diff(np.log(post_mids))))
    k = math.log(2) / HALF_LIFE_MIN
    excess = max(s_post2 - s_base2, 0.0) / math.exp(-k * 10)
    lag = C.ENTRY_LAG_MIN
    var = hold * s_base2 + excess / k * (math.exp(-k * lag) - math.exp(-k * (lag + hold)))
    return math.sqrt(max(var, 0.0))


def stop_distance(sigma_h: float, mid: float, spread: float, pair: C.Pair) -> float:
    """1.5·σ_h en precio, con piso de 3× el spread y 6 pips (60 en emergentes)."""
    return max(C.STOP_SIGMA * sigma_h * mid, 3 * spread, (60 if pair.em else 6) * pair.pip)


def _sigma_h(b: Bars, i0: int, i15: int, t0: int, hold: int) -> float | None:
    lo = _first_ge(b.t, t0 - 60)
    post_lo = _first_ge(b.t, t0 + 5)
    return sigma_h_from(b.mid_c(np.arange(lo, i0 + 1)), b.mid_c(np.arange(max(post_lo - 1, 0), i15 + 1)), hold)


def avoid_round(stop: float, side: int, pip: float, entry: float) -> float:
    """Aleja el stop de los niveles redondos ("00", cada 100 pips) donde se amontonan stops ajenos (Osler 2003).
    Si el stop queda 0–5 pips detrás de un 00, se coloca 3 pips del lado del precio de ese nivel (más cerca)."""
    big = 100 * pip
    level = (math.floor(stop / big) + (1 if side > 0 else 0)) * big
    gap = (level - stop) * side          # >0: el nivel está entre el stop y el precio
    if 0 <= gap <= 5 * pip:
        new = level + side * 3 * pip
        if (entry - new) * side > 2 * pip:   # sigue del lado correcto con margen
            return new
    return stop


def simulate(b: Bars, ie: int, side: int, stop_dist: float, exit_m: int, pair: C.Pair, cost_mult: float = 1.0):
    """Una operación: entrada al open de ``ie``. Devuelve R neto, R de costo, motivo, minuto de salida y bps."""
    entry = b.ao[ie] if side > 0 else b.bo[ie]
    mid_e = (b.ao[ie] + b.bo[ie]) / 2
    stop = avoid_round(entry - side * stop_dist, side, pair.pip, entry)
    risk = (entry - stop) * side
    ix = _first_ge(b.t, exit_m)
    # Sin vela en los 5 min posteriores a la salida (hueco o fin de ventana): se sale al cierre de la última vela
    # anterior, nunca al precio del día siguiente.
    use_close = ix >= len(b.t) or b.t[ix] - exit_m > 5
    why, px, jx = "tiempo", None, ix
    for j in range(ie, ix):
        if side > 0 and b.bl[j] <= stop:
            px, why, jx = min(stop, b.bo[j]), "stop", j
            break
        if side < 0 and b.ah[j] >= stop:
            px, why, jx = max(stop, b.ao[j]), "stop", j
            break
    if px is None:
        if use_close:
            jx = max(ix - 1, ie)
            px = b.bc[jx] if side > 0 else b.ac[jx]
        else:
            px = b.bo[ix] if side > 0 else b.ao[ix]
    xm = int(b.t[jx])
    half_e = (b.ao[ie] - b.bo[ie]) / 2
    at_close = why == "tiempo" and use_close
    half_x = max(((b.ac[jx] - b.bc[jx]) if at_close else (b.ao[jx] - b.bo[jx])) / 2, 0.0)
    extra = (pair.oanda_markup_pips + 2 * pair.slip_pips) * pair.pip
    cost = half_e + half_x + extra
    pnl = (px - entry) * side - extra - (cost_mult - 1.0) * cost
    return {"R": pnl / risk, "R_cost": cost / risk, "why": why, "exit_m": xm,
            "bps": 1e4 * pnl / mid_e, "risk_px": risk, "stop": stop, "entry": entry}


def build(b: Bars, slot: C.Slot, z_min: float | None = None, holds=C.HOLD_GRID, known: tuple[int, ...] = ()):
    """Eventos (|z| ≥ z_min) con simulaciones momentum (+1) y reversión (−1) para cada horizonte."""
    z_min = min(C.Z_GRID) if z_min is None else z_min
    pair = C.PAIRS[b.sym]
    rows = slot_series(b, slot)
    rets = np.array([r[2] for r in rows])
    spreads = np.array([r[3] for r in rows])
    out: list[Event] = []
    for k, (d, t0, ret, spread, i0, i15, ie) in enumerate(rows):
        if k < C.MIN_SCALE_OBS:
            continue
        sig = robust_scale(rets[max(0, k - C.SCALE_WINDOW_DAYS):k])
        if not sig or not np.isfinite(sig):
            continue
        z = ret / sig
        if abs(z) < z_min:
            continue
        entry_m = int(b.t[ie])
        guards = tuple(known) + K.slot_guards(b.sym, d, slot.name)
        ev = Event(b.sym, slot.name, d, t0, ret, z, sig, float(spread),
                   float(np.median(spreads[max(0, k - 60):k])), K.entry_blackout(entry_m, guards), entry_m)
        mom = 1 if ret > 0 else -1
        cut = K.exit_cap_min(slot.name, entry_m)
        for hold in holds:
            sh = _sigma_h(b, i0, i15, t0, hold)
            if sh is None:
                continue
            stop_dist = stop_distance(sh, (b.ao[ie] + b.bo[ie]) / 2, ev.spread, pair)
            exit_m = min(entry_m + hold, cut)
            if exit_m <= entry_m:
                continue
            for dname, dsign in (("mom", 1), ("rev", -1)):
                ev.sims[(dname, hold)] = simulate(b, ie, mom * dsign, stop_dist, exit_m, pair)
                ev.sims[(dname, hold)]["side"] = mom * dsign
        out.append(ev)
    return out


def to_rows(events: list[Event]) -> list[dict]:
    rows = []
    for e in events:
        for (dname, hold), s in e.sims.items():
            rows.append({"sym": e.sym, "slot": e.slot, "day": e.day.isoformat(), "t0": e.t0, "entry_m": e.entry_m,
                         "z": round(e.z, 3), "ret15": e.ret15, "spread_ok": e.spread_ok, "blackout": e.blackout,
                         "dir": dname, "hold": hold, **{k: s[k] for k in ("R", "R_cost", "why", "exit_m", "bps",
                                                                         "side", "risk_px", "entry", "stop")}})
    return rows
