"""Bayes empírico para decidir qué (par, slot) se operan, en qué dirección y con qué horizonte.

Unidad: R neto por operación (después de costos). Para cada variante v = (dirección, horizonte, z mínimo) y cada
grupo g = (par, slot) con ≥ EB_MIN_N eventos en entrenamiento:
    m_g = media de R, v_g = varianza / n (errores estándar agrupados por día: los pares de un mismo slot comparten
    el dato, así que se cuentan como un solo evento independiente cuando caen el mismo día).
Prior escéptico centrado en CERO (paseo aleatorio, F14-016 "benchmark random walk"): μ_g ~ N(0, τ²_v), con τ²_v
estimado por DerSimonian-Laird entre grupos de la misma variante. Posterior normal-normal. Un grupo se activa con
la variante de mayor P(μ>0) si P ≥ p_adj = 1 − (1 − EB_P_MIN)/√k (k = 12 variantes, muy correlacionadas porque
usan los mismos eventos): elegir la mejor de 12 cuesta evidencia (0.80 → 0.942).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

import numpy as np

from . import config as C


def variants():
    return [(d, h, z) for d in ("mom", "rev") for h in C.HOLD_GRID for z in C.Z_GRID]


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def eligible(r: dict, z: float) -> bool:
    return abs(r["z"]) >= z and r["spread_ok"] and not r["blackout"]


def group_stats(rows: list[dict], cost_mult: float = 1.0) -> dict:
    """{(variante, sym, slot): (n_dias, media, var_media)} con R neto (cost_mult>1 = estrés de costos)."""
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for z in C.Z_GRID:
            if not eligible(r, z):
                continue
            R = r["R"] - (cost_mult - 1.0) * r["R_cost"]
            acc[((r["dir"], r["hold"], z), r["sym"], r["slot"])][r["day"]].append(R)
    out = {}
    for k, by_day in acc.items():
        x = np.array([np.mean(v) for v in by_day.values()])
        n = len(x)
        if n < 2:
            continue
        out[k] = (n, float(x.mean()), float(x.var(ddof=1) / n) if n > 1 else float("inf"))
    return out


def tau2_dl(ms: np.ndarray, vs: np.ndarray, cap: float = 0.25) -> float:
    """DerSimonian-Laird con tope (R es acotado: |μ| ≫ 0.5R por operación no es creíble)."""
    if len(ms) < 3:
        return 0.01
    w = 1 / vs
    mbar = (w * ms).sum() / w.sum()
    q = (w * (ms - mbar) ** 2).sum()
    c = w.sum() - (w ** 2).sum() / w.sum()
    t2 = max((q - (len(ms) - 1)) / c, 0.0) if c > 0 else 0.0
    return float(min(max(t2, 1e-4), cap))


def fit(rows: list[dict], p_min: float = C.EB_P_MIN, n_min: int = C.EB_MIN_N, cost_mult: float = 1.0) -> dict:
    st = group_stats(rows, cost_mult)
    V = variants()
    # Corrección por elegir la mejor de len(V) variantes muy correlacionadas (mismos eventos): α/√k.
    p_adj = 1 - (1 - p_min) / math.sqrt(len(V))
    post = {}
    for v in V:
        ks = [k for k in st if k[0] == v and st[k][0] >= n_min and np.isfinite(st[k][2]) and st[k][2] > 0]
        if not ks:
            continue
        ms = np.array([st[k][1] for k in ks]); vs = np.array([st[k][2] for k in ks])
        t2 = tau2_dl(ms, vs)
        for k, m, s2 in zip(ks, ms, vs):
            pv = 1 / (1 / t2 + 1 / s2)
            pm = pv * m / s2
            post[k] = {"n": st[k][0], "mean_raw": float(m), "post_mean": float(pm), "post_sd": float(math.sqrt(pv)),
                       "p_pos": _phi(pm / math.sqrt(pv)), "tau2": t2}
    groups = {}
    for (v, sym, slot), p in post.items():
        cur = groups.get((sym, slot))
        if cur is None or p["p_pos"] > cur["p_pos"]:
            groups[(sym, slot)] = {**p, "dir": v[0], "hold": v[1], "z": v[2]}
    active = {k: g for k, g in groups.items() if g["p_pos"] >= p_adj and g["post_mean"] > 0}
    return {"p_adj": p_adj, "groups": groups, "active": active, "posteriors": post}


def select(rows: list[dict], model: dict) -> list[dict]:
    """Filas que la regla del modelo operaría (una por par y día-slot)."""
    out = []
    for r in rows:
        g = model["active"].get((r["sym"], r["slot"]))
        if g and r["dir"] == g["dir"] and r["hold"] == g["hold"] and eligible(r, g["z"]):
            out.append(r)
    return out


def serializable(model: dict, trained_until: date, extra: dict | None = None) -> dict:
    return {"trained_until": trained_until.isoformat(), "p_adj": model["p_adj"],
            "active": {f"{s}|{sl}": g for (s, sl), g in model["active"].items()},
            "groups": {f"{s}|{sl}": g for (s, sl), g in model["groups"].items()}, **(extra or {})}
