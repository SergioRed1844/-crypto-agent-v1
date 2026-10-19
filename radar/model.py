"""Modelo propio del Radar: Bayes empírico jerárquico sobre setups de compra del corpus.

Jerarquía (todo en ventaja sobre "comprar un día cualquiera de ese activo", escala logit):
  nivel 0  tasa base b_a,h de cada activo (todas las barras; n grande)
  nivel 1  ventaja del setup en la clase δ_s,g,h   ← episodios independientes (clusters de fecha entre activos)
           prior escéptico N(0, τ0²): τ² se estima con TODOS los setups (James-Stein) y el corpus lo reparte (w)
  nivel 2  ventaja del setup en el activo δ_a      ← encogida hacia δ_s,g,h con τ² entre activos por momentos
Rendimiento neto esperado: misma jerarquía en escala natural (exceso sobre el rendimiento medio del activo).
Ventana de entrada y día de la semana: Beta-Binomial por momentos con piso de escepticismo del corpus.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from . import config as C
from . import eb
from .setups import CAL_WEIGHT, SETUPS, Panel, risk_flags, triggers, vetoed

FLOOR_LOGIT = 0.05 ** 2      # τ mínimo ≈ ±1 pp alrededor de 50%
CAP_LOGIT = 1.0
FLOOR_RET = 0.002 ** 2
CAP_RET = 0.10 ** 2
WARMUP = 210                 # barras antes de evaluar (SMA200 y σ60 estables)
DOW_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _clip_bounds(nets: np.ndarray) -> tuple[float, float]:
    if len(nets) < 50:
        return -np.inf, np.inf
    return float(np.quantile(nets, 0.005)), float(np.quantile(nets, 0.995))


def outcome(p: Panel, i: int, lag: int, h: int) -> tuple[bool, float, float] | None:
    """Compra a la apertura de la barra i+lag, venta al cierre del horizonte. Ganancia NETA de costos."""
    H = C.bars_for(h, p.cls)
    e, x = i + lag, i + lag + H - 1
    if x >= len(p.close):
        return None
    entry = p.open[e] if np.isfinite(p.open[e]) and p.open[e] > 0 else p.close[e - 1]
    net = p.close[x] / entry - 1 - C.COST_RT[p.cls]
    mae = float(np.min(p.low[e:x + 1]) / entry - 1)
    return bool(net >= C.TARGET[h]), float(net), mae


def base_rates(p: Panel, h: int, lo: str = "0000", hi: str = "9999") -> dict:
    """Comprar un día cualquiera (entrada a la apertura siguiente) dentro del periodo [lo, hi)."""
    H = C.bars_for(h, p.cls)
    n = len(p.close)
    idx = np.arange(WARMUP, n - H)
    if len(idx) == 0:
        return {"b": np.nan, "m": np.nan, "n": 0, "nets": np.array([]), "dates": []}
    d = np.array(p.dates)[idx]
    keep = (d >= lo) & (d < hi)
    idx = idx[keep]
    entry = np.where(np.isfinite(p.open[idx + 1]) & (p.open[idx + 1] > 0), p.open[idx + 1], p.close[idx])
    net = p.close[idx + H] / entry - 1 - C.COST_RT[p.cls]
    succ = net >= C.TARGET[h]
    return {"b": float(succ.mean()) if len(succ) else np.nan, "m": float(net.mean()) if len(net) else np.nan,
            "n": int(len(net)), "nets": net, "succ": succ, "entry_dates": [p.dates[j + 1] for j in idx]}


K0_LOCAL = 4.0               # la tasa del último año pesa como n_eff ventanas; la histórica como 4


def local_base(p: Panel, h: int, b_full: float, m_full: float, clip: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """Tasa base LOCAL en cada barra i: compras de un día cualquiera del último año cuyo resultado ya se conoce en i
    (entradas t ∈ [i−año, i−H]), encogida hacia la tasa del periodo con peso K0_LOCAL. Así un setup en 2022 se compara
    contra 2022 (mercado bajista) y no contra 2021; y en vivo el comparador es lo que pasó en el último año."""
    H = C.bars_for(h, p.cls)
    W = 365 if p.cls == "crypto" else 252
    n = len(p.close)
    succ = np.zeros(n)
    net = np.zeros(n)
    has = np.zeros(n)
    t = np.arange(WARMUP, max(WARMUP, n - H))
    if len(t):
        entry = np.where(np.isfinite(p.open[t + 1]) & (p.open[t + 1] > 0), p.open[t + 1], p.close[t])
        nt = np.clip(p.close[t + H] / entry - 1 - C.COST_RT[p.cls], clip[0], clip[1])
        succ[t] = nt >= C.TARGET[h]
        net[t] = nt
        has[t] = 1
    cs, cn, cm = np.r_[0, np.cumsum(succ)], np.r_[0, np.cumsum(has)], np.r_[0, np.cumsum(net)]
    i = np.arange(n)
    hi = np.clip(i - H + 1, 0, n)            # entradas t ≤ i − H  → índice exclusivo i − H + 1
    lo = np.clip(i - W, 0, n)
    lo = np.minimum(lo, hi)
    cnt = cn[hi] - cn[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        bt = (cs[hi] - cs[lo]) / cnt
        mt = (cm[hi] - cm[lo]) / cnt
    neff = cnt / H
    bf = b_full if np.isfinite(b_full) else 0.5
    mf = m_full if np.isfinite(m_full) else 0.0
    bl = np.where(cnt > 0, (neff * np.nan_to_num(bt) + K0_LOCAL * bf) / (neff + K0_LOCAL), bf)
    ml = np.where(cnt > 0, (neff * np.nan_to_num(mt) + K0_LOCAL * mf) / (neff + K0_LOCAL), mf)
    return bl, ml


@dataclass
class Instance:
    sid: str
    sym: str
    cls: str
    i: int
    date: str
    out: dict = field(default_factory=dict)      # (h, lag) → (éxito, neto, mae)


def collect(panels: list[Panel], lo: str = "0000", hi: str = "9999") -> list[Instance]:
    inst = []
    for p in panels:
        for sid in SETUPS:
            tr = triggers(sid, p)
            for i in np.flatnonzero(tr):
                if i < WARMUP or not (lo <= p.dates[i] < hi):
                    continue
                it = Instance(sid, p.sym, p.cls, int(i), p.dates[i])
                for h in C.HORIZONS:
                    for lag in C.ENTRY_LAGS:
                        o = outcome(p, int(i), lag, h)
                        if o is not None:
                            it.out[(h, lag)] = o
                inst.append(it)
    return inst


def clusters(items: list[Instance], gap_days: int = 3) -> list[list[Instance]]:
    """Episodios independientes: disparos en distintos activos con ≤ gap_days entre sí son el mismo episodio."""
    items = sorted(items, key=lambda x: x.date)
    out, cur, start = [], [], None
    for it in items:
        d = date.fromisoformat(it.date)
        if cur and (d - start).days > gap_days:
            out.append(cur)
            cur = []
        if not cur:
            start = d
        cur.append(it)
    if cur:
        out.append(cur)
    return out


class Model:
    def __init__(self):
        self.base = {}          # sym → h → {b, m, n}
        self.clip = {}          # (cls, h) → (lo, hi)
        self.groups = {}        # (sid, cls, h) → dict
        self.tau2_all = FLOOR_LOGIT
        self.tau2r_all = FLOOR_RET
        self.dow = {}           # cls → tabla
        self.local = {}         # sym → h → (tasa base local, neto medio local) por barra
        self.period = ("0000", "9999")
        self.n_specs = 0

    # ── ajuste ──────────────────────────────────────────────────────────────────────────────────────────
    def fit(self, panels: list[Panel], lo: str = "0000", hi: str = "9999") -> "Model":
        self.period = (lo, hi)
        by_cls = defaultdict(list)
        for p in panels:
            by_cls[p.cls].append(p)
            self.base[p.sym] = {}
        for cls, ps in by_cls.items():
            for h in C.HORIZONS:
                br = {p.sym: base_rates(p, h, lo, hi) for p in ps}
                allnets = np.concatenate([b["nets"] for b in br.values() if len(b["nets"])] or [np.array([])])
                lo_c, hi_c = _clip_bounds(allnets)
                self.clip[(cls, h)] = (lo_c, hi_c)
                for sym, b in br.items():
                    m = float(np.clip(b["nets"], lo_c, hi_c).mean()) if b["n"] else np.nan
                    self.base[sym][h] = {"b": b["b"], "m": m, "n": b["n"]}
                for p in ps:
                    bb = self.base[p.sym][h]
                    self.local.setdefault(p.sym, {})[h] = local_base(p, h, bb["b"], bb["m"], (lo_c, hi_c))
            self.dow[cls] = self._dow_table(ps, br_h=7, lo=lo, hi=hi)
        inst = collect(panels, lo, hi)
        self._fit_groups(inst, panels)
        return self

    def _fit_groups(self, inst: list[Instance], panels: list[Panel]):
        years = {p.sym: max(0.0, (len(p.dates) - WARMUP) / (365.0 if p.cls == "crypto" else 252.0)) for p in panels}
        syms_cls = defaultdict(list)
        for p in panels:
            syms_cls[p.cls].append(p.sym)
        raw = {}
        by = defaultdict(list)
        for it in inst:
            by[(it.sid, it.cls)].append(it)
        for (sid, cls), items in by.items():
            for h in C.HORIZONS:
                usable = [it for it in items if (h, 1) in it.out and np.isfinite(self._lb(it.sym, h, it.i)[0])]
                if not usable:
                    continue
                cl = clusters(usable)
                s_c = [np.mean([it.out[(h, 1)][0] for it in c]) for c in cl]
                b_c = [np.mean([self._lb(it.sym, h, it.i)[0] for it in c]) for c in cl]
                lo_c, hi_c = self.clip[(cls, h)]
                x_c = [np.mean([np.clip(it.out[(h, 1)][1], lo_c, hi_c) - self._lb(it.sym, h, it.i)[1] for it in c])
                       for c in cl]
                n_eff, k_eff, b_bar = len(cl), float(np.sum(s_c)), float(np.mean(b_c))
                y, v = eb.logit_lift(k_eff, n_eff, b_bar)
                e_raw = float(np.mean(x_c))
                ve = float(np.var(x_c, ddof=1) / n_eff) if n_eff >= 3 else CAP_RET
                raw[(sid, cls, h)] = dict(items=usable, clusters=cl, n_inst=len(usable), n_eff=n_eff, k_eff=k_eff,
                                          b_bar=b_bar, y=y, v=v, e_raw=e_raw, ve=max(ve, 1e-8))
        self.n_specs = len(raw)
        eligible = [r for r in raw.values() if r["n_eff"] >= 5]
        self.tau2_all = eb.tau2_across([r["y"] for r in eligible], [r["v"] for r in eligible], FLOOR_LOGIT, CAP_LOGIT)
        self.tau2r_all = eb.tau2_across([r["e_raw"] for r in eligible], [r["ve"] for r in eligible], FLOOR_RET, CAP_RET)
        for (sid, cls, h), r in raw.items():
            w = SETUPS[sid].weight(cls)
            pv = eb.prior_var(self.tau2_all, w, FLOOR_LOGIT)
            d, dv, B = eb.normal_posterior(r["y"], r["v"], 0.0, pv)
            pvr = eb.prior_var(self.tau2r_all, w, FLOOR_RET)
            e, evar, Br = eb.normal_posterior(r["e_raw"], r["ve"], 0.0, pvr)
            g = dict(sid=sid, cls=cls, h=h, w=w, n_inst=r["n_inst"], n_eff=r["n_eff"], k_eff=round(r["k_eff"], 2),
                     raw_p=eb.jeffreys(r["k_eff"], r["n_eff"]), b_bar=r["b_bar"], delta_raw=r["y"], v=r["v"],
                     prior_var=pv, delta=d, delta_var=dv, B=B, e_raw=r["e_raw"], ve=r["ve"], prior_var_ret=pvr,
                     e=e, e_var=evar, B_ret=Br)
            # nivel 2: activos
            per = defaultdict(list)
            for it in r["items"]:
                per[it.sym].append(it)
            lo_c, hi_c = self.clip[(cls, h)]
            ys, vs, rs, rvs, stats = [], [], [], [], {}
            within = []
            for sym, its in per.items():
                k = sum(it.out[(h, 1)][0] for it in its)
                n = len(its)
                ya, va = eb.logit_lift(k, n, float(np.mean([self._lb(sym, h, it.i)[0] for it in its])))
                xs = np.array([np.clip(it.out[(h, 1)][1], lo_c, hi_c) - self._lb(sym, h, it.i)[1] for it in its])
                if n >= 2:
                    within.append(float(np.var(xs, ddof=1)))
                stats[sym] = dict(k=int(k), n=n, y=ya, v=va, xr=float(xs.mean()), xs=xs)
                if n >= 3:
                    ys.append(ya)
                    vs.append(va)
            s2w = float(np.median(within)) if within else max(r["ve"] * max(r["n_eff"], 1), 1e-4)
            for sym, st in stats.items():
                st["vr"] = max(float(np.var(st["xs"], ddof=1)) if st["n"] >= 3 else 0.0, s2w) / st["n"]
                if st["n"] >= 3:
                    rs.append(st["xr"])
                    rvs.append(st["vr"])
            t2 = eb.tau2_between(ys, vs, cap=max(pv, self.tau2_all))
            t2r = eb.tau2_between(rs, rvs, cap=max(pvr, self.tau2r_all))
            assets = {}
            for sym, st in stats.items():
                da, dva, Ba = eb.shrink_member(st["y"], st["v"], d, dv, t2)
                ea, eva, Bra = eb.shrink_member(st["xr"], st["vr"], e, evar, t2r)
                assets[sym] = dict(k=st["k"], n=st["n"], raw=st["k"] / st["n"], delta=da, var=dva, B=Ba,
                                   e=ea, e_var=eva, B_ret=Bra)
            g.update(tau2_assets=t2, tau2r_assets=t2r, assets=assets)
            # riesgo de caída durante la tenencia
            lim = C.MAE_LIMIT[cls]
            mae_c = [np.mean([it.out[(h, 1)][2] <= lim for it in c]) for c in r["clusters"]]
            g["mae_p"] = eb.jeffreys(float(np.sum(mae_c)), len(mae_c))
            # mejor día de compra: ventana de entrada t+L (Beta-Binomial por momentos entre ventanas)
            ks, ns = [], []
            for lag in C.ENTRY_LAGS:
                vals = [np.mean([it.out[(h, lag)][0] for it in c if (h, lag) in it.out])
                        for c in r["clusters"] if any((h, lag) in it.out for it in c)]
                ks.append(float(np.sum(vals)))
                ns.append(float(len(vals)))
            if sum(ns) > 0:
                tab = eb.beta_table(np.array(ks), np.array(ns), c_floor=50.0 * (1 - w))
                tab["lags"] = list(C.ENTRY_LAGS)
                g["lag_table"] = tab
            # frecuencia (Poisson-Gamma)
            syms = syms_cls[cls]
            x = np.array([len(per.get(s, [])) for s in syms], float)
            ex = np.array([years.get(s, 0.0) for s in syms], float)
            pg = eb.poisson_gamma(x, ex)
            g["freq"] = {s: round(v, 2) for s, v in zip(syms, pg["post"])}
            g["freq_pooled"] = round(pg["pooled"], 2)
            g["clusters_dates"] = [c[0].date for c in r["clusters"]][-12:]
            self.groups[(sid, cls, h)] = g

    def _dow_table(self, ps: list[Panel], br_h: int, lo: str, hi: str) -> dict:
        """¿Qué día de la semana conviene comprar? Entradas en un día cualquiera, horizonte 7 días.
        Un dato por fecha (promedio entre activos de la clase) → por día de la semana las entradas no se traslapan."""
        per_date = defaultdict(list)
        for p in ps:
            b = base_rates(p, br_h, lo, hi)
            for d, s in zip(b.get("entry_dates", []), b.get("succ", [])):
                per_date[d].append(bool(s))
        k = np.zeros(7)
        n = np.zeros(7)
        for d, vals in per_date.items():
            wd = date.fromisoformat(d).weekday()
            k[wd] += float(np.mean(vals))
            n[wd] += 1
        days = [i for i in range(7) if n[i] > 0]
        if not days:
            return {}
        tab = eb.beta_table(k[days], n[days], c_floor=2000.0 * (1 - CAL_WEIGHT))
        tab["dias"] = [DOW_ES[i] for i in days]
        tab["w"] = CAL_WEIGHT
        return tab

    def _lb(self, sym: str, h: int, i: int) -> tuple[float, float]:
        bl, ml = self.local[sym][h]
        return float(bl[i]), float(ml[i])

    # ── predicción ──────────────────────────────────────────────────────────────────────────────────────
    def predict(self, sid: str, cls: str, h: int, sym: str, i: int | None = None) -> dict | None:
        """i = barra del disparo: el comparador es la tasa base local (último año) en esa barra."""
        g = self.groups.get((sid, cls, h))
        b = self.base.get(sym, {}).get(h)
        if g is None or b is None or not np.isfinite(b["b"]):
            return None
        if i is not None and sym in self.local and h in self.local[sym]:
            bl, ml = self._lb(sym, h, i)
            b = {"b": bl, "m": ml, "n": b["n"]}
        a = g["assets"].get(sym)
        if a is None:
            d, dv = g["delta"], g["delta_var"] + g["tau2_assets"]
            e, ev = g["e"], g["e_var"] + g["tau2r_assets"]
            k = n = 0
        else:
            d, dv, e, ev, k, n = a["delta"], a["var"], a["e"], a["e_var"], a["k"], a["n"]
        pr = eb.prob_from_logit(b["b"], d, dv)
        sd = float(np.sqrt(max(ev, 0)))
        pr.update(base=b["b"], ret=b["m"] + e, ret_q10=b["m"] + e - eb.Z10 * sd, base_ret=b["m"], k=k, n=n,
                  n_eff=g["n_eff"], n_inst=g["n_inst"], raw_setup=g["raw_p"], B=g["B"], w=g["w"],
                  mae_p=g["mae_p"], h=h, sid=sid)
        return pr

    def best_lag(self, sid: str, cls: str, h: int) -> dict:
        g = self.groups.get((sid, cls, h)) or {}
        t = g.get("lag_table")
        if not t:
            return {"texto": "sin historia suficiente para comparar días de entrada", "lag": 1}
        i = int(np.argmax(t["post"]))
        lag = t["lags"][i]
        gain = t["post"][i] - t["post"][0]
        if lag != 1 and t["p_best"][i] >= 0.5 and gain >= 0.02:
            txt = (f"entrar el día t+{lag} (P de ser la mejor ventana {t['p_best'][i]:.0%}; "
                   f"+{gain * 100:.1f} pp vs entrar al día siguiente)")
        else:
            txt = (f"entrar en cuanto confirmes (t+1): esperar no mejora de forma probada "
                   f"(P mejor ventana t+1 = {t['p_best'][0]:.0%})")
        return {"texto": txt, "lag": lag if lag != 1 and t["p_best"][i] >= 0.5 and gain >= 0.02 else 1, "tabla": t}

    def best_dow(self, cls: str) -> dict:
        t = self.dow.get(cls) or {}
        if not t:
            return {"texto": "sin datos"}
        i = int(np.argmax(t["post"]))
        spread = (max(t["post"]) - min(t["post"])) * 100
        if spread < 0.5:
            return {"dia": None, "p_best": t["p_best"][i], "spread_pp": spread,
                    "texto": (f"ningún día de la semana destaca (diferencia encogida {spread:.1f} pp): compra el día "
                              "que se confirme la señal — el corpus da por erosionados los efectos de calendario "
                              "(C08-008, C11-006)")}
        return {"dia": t["dias"][i], "p_best": t["p_best"][i], "spread_pp": spread,
                "texto": (f"{t['dias'][i]} (P de ser el mejor {t['p_best'][i]:.0%}; diferencia máx. entre días "
                          f"{spread:.1f} pp tras encogimiento — efecto de calendario: el corpus lo da por erosionado, "
                          f"úsalo solo como desempate; C08-008, C11-006)")}

    # ── resumen serializable ────────────────────────────────────────────────────────────────────────────
    def summary(self) -> dict:
        gs = []
        for (sid, cls, h), g in sorted(self.groups.items()):
            gs.append({k: (round(v, 4) if isinstance(v, float) else v) for k, v in g.items()
                       if k not in ("assets", "freq", "lag_table")} |
                      {"lag_post": [round(x, 3) for x in (g.get("lag_table") or {}).get("post", [])],
                       "lag_p_best": [round(x, 3) for x in (g.get("lag_table") or {}).get("p_best", [])]})
        return {"period": self.period, "tau_all_logit": round(float(np.sqrt(self.tau2_all)), 4),
                "tau_all_ret": round(float(np.sqrt(self.tau2r_all)), 4), "n_specs": self.n_specs, "groups": gs,
                "dow": {c: {k: v for k, v in t.items()} for c, t in self.dow.items()}}


# ── decisión de alerta ──────────────────────────────────────────────────────────────────────────────────
def decide(pred: dict, flags: dict, ctx_state: str | None, cls: str, extra: float = 0.0) -> tuple[str, list[str]]:
    """ALERTA si pasa el umbral Selectivo y ningún veto; VIGILANCIA si es candidato pero no llega; VETADA si un veto."""
    A = C.ALERT
    why = []
    v = vetoed(flags, pred["h"])
    if v:
        return "VETADA", v
    bump = extra
    if cls == "crypto" and ctx_state == "CAUTION":
        bump += A["caution_extra"]
        why.append(f"contexto v4.2 en CAUTION: exigencia +{A['caution_extra'] * 100:.0f} pp")
    checks = [(pred["p"] >= A["p_min"] + bump, f"P {pred['p']:.0%} < {A['p_min'] + bump:.0%}"),
              (pred["q10"] >= A["q10_min"] + bump, f"cota baja {pred['q10']:.0%} < {A['q10_min'] + bump:.0%}"),
              (pred["lift"] >= A["lift_min"], f"ventaja vs día cualquiera {pred['lift'] * 100:+.1f} pp < "
                                              f"{A['lift_min'] * 100:.0f} pp"),
              (pred["ret"] >= A["ret_min"], f"rendimiento neto esperado {pred['ret']:.1%} < {A['ret_min']:.0%}"),
              (pred["n_eff"] >= A["neff_min"], f"solo {pred['n_eff']} episodios independientes (< {A['neff_min']})")]
    fails = [msg for ok, msg in checks if not ok]
    return ("ALERTA", why) if not fails else ("VIGILANCIA", why + fails)
