"""Backtest de la Estrategia B (carry + momentum) exactamente como quedó pre-registrada en
docs/FX_CARRY_MOMENTUM.md. Simulación horaria: rebalanceo lunes 10:00 NY, recorte EM viernes 15:00 NY,
financiamiento diario, gobernador semanal −1.5% con marca a mercado horaria, topes diario y de drawdown.

Ningún parámetro se ajusta con estos datos: lo que se reporta es fuera de muestra respecto de la literatura.
Uso: python -m fx.carry.backtest <dir con *_H1.npz.xz, rates.csv, vix.csv> [salida]
"""
from __future__ import annotations

import bisect
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

from .. import calendar as K
from ..backtest import psr, dsr
from . import config as CC
from . import data as CD


# ── preparación ────────────────────────────────────────────────────────────────────────────────────────────────────
def ny_fields(t_min: np.ndarray):
    """Hora, día de la semana y fecha de Nueva York para cada minuto UTC (vectorizado por día UTC)."""
    days = t_min // 1440
    ud, inv = np.unique(days, return_inverse=True)
    off = np.array([K.NY.utcoffset(datetime(1970, 1, 1) + timedelta(days=int(d), hours=12)).total_seconds() / 60
                    for d in ud]).astype(np.int64)
    loc = t_min + off[inv]
    hour = (loc % 1440) // 60
    dnum = loc // 1440
    dow = (dnum + 3) % 7            # 1970-01-01 fue jueves → lunes = 0
    return hour, dow, dnum


class Panel:
    """Rejilla horaria común con mid de cierre, bid/ask de apertura y retornos de cada moneda contra USD."""

    def __init__(self, bars: dict[str, dict]):
        codes = [c.code for c in CC.UNIVERSE if c.code in bars]
        grid = np.unique(np.concatenate([np.asarray(bars[c]["t"]) for c in codes]))
        self.t = grid
        self.codes = codes
        n, k = len(grid), len(codes)
        self.mid = np.full((n, k), np.nan)
        self.half = np.full((n, k), np.nan)       # medio spread relativo al open (para costo)
        for j, c in enumerate(codes):
            b, p = bars[c], CC.BY_CODE[c].point
            idx = np.searchsorted(grid, b["t"])
            mid_c = (np.asarray(b["bc"]) + np.asarray(b["ac"])) / 2 * p
            mid_o = (np.asarray(b["bo"]) + np.asarray(b["ao"])) / 2 * p
            sp_o = (np.asarray(b["ao"]) - np.asarray(b["bo"])) * p
            self.mid[idx, j] = mid_c
            self.half[idx, j] = np.clip(sp_o / 2 / mid_o, 0, 0.01)
        # relleno hacia adelante (horas sin operaciones = sin cambio de precio)
        for j in range(k):
            col = self.mid[:, j]
            ok = ~np.isnan(col)
            fill = np.maximum.accumulate(np.where(ok, np.arange(n), 0))
            self.mid[:, j] = col[fill]
            h = self.half[:, j]
            okh = ~np.isnan(h)
            fh = np.maximum.accumulate(np.where(okh, np.arange(n), 0))
            self.half[:, j] = h[fh]
        sign = np.array([-1.0 if CC.BY_CODE[c].inv else 1.0 for c in codes])
        lr = np.vstack([np.zeros((1, k)), np.diff(np.log(self.mid), axis=0)]) * sign
        self.ret = np.nan_to_num(lr)              # retorno log de la MONEDA contra USD en cada hora
        self.hour, self.dow, self.dnum = ny_fields(grid)
        # cierre diario: vela que empieza 16:00 NY (cierra 17:00)
        self.close_idx = np.where(self.hour == CC.DAILY_CLOSE_HOUR - 1)[0]
        cum = np.cumsum(self.ret, axis=0)
        self.dclose_cum = cum[self.close_idx]                     # log precio índice por día
        self.ddates = [date(1970, 1, 1) + timedelta(days=int(d)) for d in self.dnum[self.close_idx]]
        self.dret = np.vstack([np.zeros((1, k)), np.diff(self.dclose_cum, axis=0)])


def asof(series: list[tuple[str, float]], d: date, lag_days: int = 1):
    """Último valor publicado al menos ``lag_days`` días antes de ``d``."""
    key = (d - timedelta(days=lag_days)).isoformat()
    keys = [x[0] for x in series]
    i = bisect.bisect_right(keys, key) - 1
    return series[i][1] if i >= 0 else None


class Asof:
    def __init__(self, series):
        self.keys = [x[0] for x in series]
        self.vals = [x[1] for x in series]

    def __call__(self, d: date, lag_days: int = 1):
        i = bisect.bisect_right(self.keys, (d - timedelta(days=lag_days)).isoformat()) - 1
        return self.vals[i] if i >= 0 else None


# ── señales ────────────────────────────────────────────────────────────────────────────────────────────────────────
def rank_weights(x: np.ndarray) -> np.ndarray:
    ok = ~np.isnan(x)
    w = np.zeros_like(x)
    if ok.sum() < 3:
        return w
    r = np.argsort(np.argsort(x[ok])).astype(float)
    r -= r.mean()
    s = np.abs(r).sum()
    w[ok] = r / s if s > 0 else 0
    return w


def norm1(w: np.ndarray) -> np.ndarray:
    s = np.abs(w).sum()
    return w / s if s > 0 else w


class Signals:
    def __init__(self, P: Panel, rates: dict, vix: list):
        self.P = P
        self.rate = {c: Asof(v) for c, v in rates.items()}
        self.vix = Asof(vix)
        self.vix_hist = np.array([v for _, v in vix])
        self.vix_dates = [d for d, _ in vix]
        k = len(P.codes)
        self.cov = np.eye(k) * 1e-5
        self.cov_upto = 0                    # índice diario hasta el que la covarianza está actualizada

    def update_cov(self, di: int):
        lam = CC.EWMA_LAMBDA
        while self.cov_upto < di:
            self.cov_upto += 1
            r = self.P.dret[self.cov_upto][:, None]
            self.cov = lam * self.cov + (1 - lam) * (r @ r.T)

    def vix_pct(self, d: date):
        i = bisect.bisect_right(self.vix_dates, (d - timedelta(days=1)).isoformat())
        if i < 250:
            return None, None
        hist = self.vix_hist[:i]
        v = hist[-1]
        return float(v), float((hist < v).mean())

    def targets(self, di: int, d: date, last_carry_week_ret: float | None) -> tuple[np.ndarray, dict]:
        """Pesos objetivo (nocional / capital) con datos hasta el cierre diario ``di``."""
        P = self.P
        self.update_cov(di)
        info = {}
        usd = self.rate.get("USD")
        rates = np.array([self.rate[c](d) if c in self.rate else np.nan for c in P.codes], dtype=float)
        r_usd = usd(d) if usd else None
        carry = rates - (r_usd if r_usd is not None else np.nan)
        w_c = rank_weights(carry)
        L, S = CC.MOM_XS
        if di < max(L, max(CC.MOM_TS)):
            return np.zeros(len(P.codes)), {"why": "calentamiento"}
        c = P.dclose_cum
        mom_xs = c[di - S] - c[di - L]
        w_xs = rank_weights(mom_xs)
        ts = np.mean([np.sign(c[di] - c[di - h]) for h in CC.MOM_TS], axis=0)
        w_ts = norm1(ts)
        w_m = 0.5 * w_xs + 0.5 * w_ts
        cov = self.cov * 252
        vol = lambda w: math.sqrt(max(w @ cov @ w, 1e-12))  # noqa: E731
        m_c = 1.0
        v, pct = self.vix_pct(d)
        if pct is not None and pct > CC.VIX_P[1]:
            m_c = 0.0
        elif pct is not None and pct > CC.VIX_P[0]:
            m_c = 0.5
        if last_carry_week_ret is not None and np.abs(w_c).sum() > 0:
            sig_w = vol(w_c) / math.sqrt(52)
            if last_carry_week_ret < -CC.CARRY_CRASH_SIGMA * sig_w:
                m_c = 0.0
                info["carry_crash"] = True
        w = (m_c * w_c / vol(w_c) if np.abs(w_c).sum() > 0 else 0) + (w_m / vol(w_m) if np.abs(w_m).sum() > 0 else 0)
        if np.abs(w).sum() == 0:
            return np.zeros(len(P.codes)), {"why": "sin señal"}
        w = w * (CC.SIGMA_TARGET / vol(w))
        w = np.clip(w, -CC.MAX_PER_CCY, CC.MAX_PER_CCY)
        g = np.abs(w).sum()
        if g > CC.MAX_GROSS:
            w *= CC.MAX_GROSS / g
        net_usd = abs(w.sum())
        if net_usd > CC.MAX_NET_USD:
            w *= CC.MAX_NET_USD / net_usd
        info.update({"vix": v, "vix_pct": pct, "m_carry": m_c, "w_carry": w_c, "w_mom": w_m,
                     "ex_ante_vol": vol(w)})
        return w, info


# ── simulación ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _quarter_end_block(d: date, business_days: set) -> bool:
    if (d.month, d.day) >= (12, 24) or (d.month, d.day) <= (1, 2):
        return True
    if d.month in (3, 6, 9, 12):
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        left = [x for x in business_days if d <= x < nxt]
        return len(left) <= 2
    return False


def simulate(P: Panel, S: Signals, factors: str = "both", cost_mult: float = 1.0, fin_mult: float = 1.0,
             equity0: float = 2000.0, start: str = CC.EVAL_START):
    k = len(P.codes)
    cost_bp = np.array([CC.BY_CODE[c].cost_bp for c in P.codes]) * 1e-4
    em = np.array([CC.BY_CODE[c].em for c in P.codes])
    pos = np.zeros(k)                      # valor en USD de la posición en cada moneda (+ = larga la moneda)
    eq = peak = equity0
    week_start = day_start = equity0
    cur_week = cur_day = None
    flat_until_rebal = False
    off = False
    t0 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp() // 60)
    i0 = int(np.searchsorted(P.t, t0))
    day_index = {int(P.close_idx[j]): j for j in range(len(P.close_idx))}
    bdays = set(P.ddates)
    log, curve, costs, fin_total = [], [], 0.0, 0.0
    trades = 0
    last_close_j = None
    last_close_date = None
    carry_week_ret, carry_prev_w = None, None
    pending_carry = []
    w_target = np.zeros(k)

    def trade(new_pos, i, why):
        nonlocal pos, eq, costs, trades
        d = new_pos - pos
        c = float(np.sum(np.abs(d) * (P.half[i] * cost_mult + cost_bp * cost_mult)))
        eq -= c
        costs += c
        trades += int((np.abs(d) > 1e-9).sum())
        pos = new_pos
        if why:
            log.append((int(P.t[i]), why))

    for i in range(max(i0, 1), len(P.t)):
        # 1) marca a mercado de la hora (las posiciones se valúan con la moneda)
        g = np.expm1(P.ret[i])
        pnl = float(pos @ g)
        pos = pos * (1 + g)
        eq += pnl
        m = int(P.t[i])
        wk, dy = K.fx_week(m), K.fx_day(m)
        if wk != cur_week:
            cur_week, week_start = wk, eq
        if dy != cur_day:
            cur_day, day_start = dy, eq
        peak = max(peak, eq)
        # 2) financiamiento al cierre diario (17:00 NY): días calendario desde el cierre anterior
        if i in day_index:
            j = day_index[i]
            dd_ = P.ddates[j]
            ndays = (dd_ - last_close_date).days if last_close_date else 1
            last_close_date, last_close_j = dd_, j
            r_usd = S.rate["USD"](dd_, 0) if "USD" in S.rate else None
            if r_usd is not None:
                diff = np.array([(S.rate[c](dd_, 0) - r_usd) if c in S.rate and S.rate[c](dd_, 0) is not None else 0.0
                                 for c in P.codes]) / 100.0
                f = float(pos @ diff - np.abs(pos).sum() * CC.FIN_MARKUP * fin_mult) * ndays / 365.0
                eq += f
                fin_total += f
        # 3) gobernador semanal / diario y drawdown (marca a mercado horaria)
        if np.abs(pos).sum() > 0 and not flat_until_rebal:
            if eq <= week_start * (1 - CC.WEEKLY_CAP):
                trade(np.zeros(k), min(i + 1, len(P.t) - 1), f"tope semanal {eq / week_start - 1:.2%}")
                flat_until_rebal = True
            elif eq <= day_start * (1 - CC.DAILY_CAP):
                trade(np.zeros(k), min(i + 1, len(P.t) - 1), f"tope diario {eq / day_start - 1:.2%}")
                flat_until_rebal = True
        if not off and eq <= peak * (1 - CC.DD_RED):
            trade(np.zeros(k), min(i + 1, len(P.t) - 1), f"APAGADO drawdown {1 - eq / peak:.2%}")
            off = True
        # 4) viernes 15:00 NY: emergentes −25%
        if P.dow[i] == 4 and P.hour[i] == CC.FRIDAY_CUT_HOUR and np.abs(pos[em]).sum() > 0:
            new = pos.copy()
            new[em] *= 1 - CC.EM_FRIDAY_CUT
            trade(new, i, "")
        # 5) lunes 10:00 NY: rebalanceo
        if P.dow[i] == CC.REBAL_DOW and P.hour[i] == CC.REBAL_HOUR and last_close_j is not None and not off:
            d_today = date(1970, 1, 1) + timedelta(days=int(P.dnum[i]))
            # retorno semanal del factor carry con los pesos de la semana anterior (para el filtro de choque)
            if carry_prev_w is not None:
                carry_week_ret = float(carry_prev_w @ (P.dclose_cum[last_close_j] - P.dclose_cum[max(last_close_j - 5, 0)]))
            w, info = S.targets(last_close_j, d_today, carry_week_ret)
            wc = info.get("w_carry")
            if wc is not None:
                carry_prev_w = wc        # mismos pesos (Σ|w|=1) con los que targets() mide su σ semanal
            if factors == "carry" and wc is not None:
                w = _solo(info["w_carry"] * info["m_carry"], S)
            elif factors == "mom" and info.get("w_mom") is not None:
                w = _solo(info["w_mom"], S)
            dd = 1 - eq / peak
            if dd >= CC.DD_YELLOW:
                w = w * 0.5
            flat_until_rebal = False
            if not _quarter_end_block(d_today, bdays) or np.abs(pos).sum() == 0:
                tgt = w * eq
                new = pos.copy()
                for j_ in range(k):
                    diff = tgt[j_] - pos[j_]
                    if abs(tgt[j_]) < CC.MIN_POS * eq:
                        new[j_] = 0.0
                    elif abs(diff) > CC.BAND_REL * abs(tgt[j_]) and abs(diff) > CC.BAND_ABS * eq:
                        new[j_] = tgt[j_]
                    elif np.sign(tgt[j_]) != np.sign(pos[j_]):
                        new[j_] = tgt[j_]
                trade(new, i, "")
            w_target = w
        curve.append((m, eq))
    return {"curve": curve, "costs": costs, "financing": fin_total, "trades": trades, "log": log, "off": off,
            "final": eq}


def _solo(w: np.ndarray, S: Signals) -> np.ndarray:
    if np.abs(w).sum() == 0:
        return w
    v = math.sqrt(max(w @ (S.cov * 252) @ w, 1e-12))
    w = w * CC.SIGMA_TARGET / v
    w = np.clip(w, -CC.MAX_PER_CCY, CC.MAX_PER_CCY)
    g = np.abs(w).sum()
    return w * (CC.MAX_GROSS / g) if g > CC.MAX_GROSS else w


# ── métricas ───────────────────────────────────────────────────────────────────────────────────────────────────────
def weekly_from_curve(curve, equity0: float = 2000.0):
    by = {}
    for m, e in curve:
        by[K.fx_week(m)] = e
    weeks = sorted(by)
    eqs = [equity0] + [by[w] for w in weeks]
    rets = [eqs[i + 1] / eqs[i] - 1 for i in range(len(weeks))]
    return weeks, np.array(rets)


def metrics(sim: dict, equity0: float = 2000.0) -> dict:
    weeks, r = weekly_from_curve(sim["curve"], equity0)
    eq = np.array([e for _, e in sim["curve"]])
    peak = np.maximum.accumulate(eq)
    yrs = len(r) / 52.18
    tot = eq[-1] / equity0 - 1
    streak = worst = 0
    for x in r:
        streak = streak + 1 if x < 0 else 0
        worst = max(worst, streak)
    sd = r.std(ddof=1)
    return {"weeks": len(r), "total_ret": float(tot), "cagr": float((1 + tot) ** (1 / yrs) - 1) if tot > -1 else -1,
            "vol_ann": float(sd * math.sqrt(52)), "sharpe": float(r.mean() / sd * math.sqrt(52)) if sd > 0 else 0,
            "psr0": psr(r) if len(r) > 3 else 0.5, "max_dd": float((1 - eq / peak).max()),
            "worst_week": float(r.min()), "best_week": float(r.max()), "pct_pos": float((r > 0).mean()),
            "pct_neg": float((r < 0).mean()), "weeks_below_cap": int((r < -CC.WEEKLY_CAP - 1e-9).sum()),
            "max_neg_streak": worst, "costs_usd": sim["costs"], "financing_usd": sim["financing"],
            "trades": sim["trades"], "off": sim["off"], "final_equity": sim["final"],
            "governor_hits": sum(1 for _, w in sim["log"] if w.startswith("tope"))}, weeks, r


def eras(weeks, r):
    out = {}
    for name, (a, b) in {"2016-2019": (2016, 2019), "2020-2021": (2020, 2021), "2022-2024": (2022, 2024),
                         "2025-2026": (2025, 2026)}.items():
        x = np.array([v for w, v in zip(weeks, r) if a <= int(w[:4]) <= b])
        if len(x):
            out[name] = {"weeks": len(x), "ret": float(np.prod(1 + x) - 1), "pct_pos": float((x > 0).mean()),
                         "worst": float(x.min()), "sharpe": float(x.mean() / x.std(ddof=1) * math.sqrt(52))
                         if x.std() > 0 else 0}
    return out


def run(d: str, out: str = "data/fx") -> dict:
    bars = {c.code: CD.load(c.code, d) for c in CC.UNIVERSE if os.path.exists(os.path.join(d, f"{c.sym}_H1.npz.xz"))}
    P = Panel(bars)
    rates, vix = CD.load_rates(d), CD.load_vix(d)
    res = {"generated": datetime.now(timezone.utc).isoformat(), "codes": P.codes,
           "hours": int(len(P.t)), "first": K.from_min(int(P.t[0])).isoformat(),
           "last": K.from_min(int(P.t[-1])).isoformat(),
           "rates_ccys": sorted(rates), "vix_obs": len(vix)}
    runs = {}
    for name, fac, cm, fm in (("combinado", "both", 1, 1), ("combinado_estres_x2", "both", 2, 2),
                              ("solo_carry", "carry", 1, 1), ("solo_momentum", "mom", 1, 1)):
        S = Signals(P, rates, vix)
        sim = simulate(P, S, fac, cm, fm)
        mt, weeks, r = metrics(sim)
        runs[name] = {**mt, "eras": eras(weeks, r), "log_tail": sim["log"][-8:]}
        if name == "combinado":
            base_r = r
    srs = [v["sharpe"] / math.sqrt(52) for k, v in runs.items() if "estres" not in k]
    res["runs"] = runs
    res["dsr_n3"] = dsr(base_r, srs, 3)
    c = runs["combinado"]
    res["gate"] = {"sharpe_gt_0.3": c["sharpe"] > 0.3, "psr_ge_0.80": c["psr0"] >= 0.80,
                   "stress_positive": runs["combinado_estres_x2"]["total_ret"] > 0, "dd_lt_8": c["max_dd"] < 0.08}
    res["pass"] = all(res["gate"].values())
    os.makedirs(out, exist_ok=True)
    json.dump(res, open(os.path.join(out, "carry_backtest.json"), "w"), indent=1, default=str)
    open(os.path.join(out, "CARRY_BACKTEST.md"), "w").write(report(res))
    return res


def _p(x, d=1):
    return f"{100 * x:+.{d}f}%"


def report(res: dict) -> str:
    L = ["# Backtest Estrategia B — carry + momentum (pre-registrada el 19-oct-2026)", "",
         f"Generado {res['generated']} · {len(res['codes'])} monedas · datos {res['first'][:10]} → {res['last'][:10]} · "
         f"tasas: {', '.join(res['rates_ccys'])} · VIX {res['vix_obs']} obs", "",
         f"## Veredicto: **{'PASA la compuerta pre-registrada → se puede operar en práctica' if res['pass'] else 'NO pasa la compuerta pre-registrada → no se opera'}**",
         "", "| criterio | ¿cumple? |", "|---|---|"]
    lab = {"sharpe_gt_0.3": "Sharpe neto > 0.3", "psr_ge_0.80": "PSR(SR>0) ≥ 0.80",
           "stress_positive": "retorno > 0 con costos ×2", "dd_lt_8": "drawdown máx. < 8%"}
    for k, v in res["gate"].items():
        L.append(f"| {lab[k]} | {'sí' if v else 'no'} |")
    L += ["", f"DSR (N=3): {res['dsr_n3']:.2f}", "",
          "## Resultados (ene-2016 → hoy, capital inicial US$2,000, σ* 4%)", "",
          "| métrica | combinado | combinado costos ×2 | solo carry | solo momentum |", "|---|---|---|---|---|"]
    R = res["runs"]
    rows = (("total_ret", "retorno total", _p), ("cagr", "anualizado", _p), ("vol_ann", "volatilidad anual", _p),
            ("sharpe", "Sharpe", lambda x: f"{x:.2f}"), ("psr0", "PSR", lambda x: f"{x:.2f}"),
            ("max_dd", "drawdown máx.", lambda x: f"{100 * x:.1f}%"), ("pct_pos", "% semanas positivas", _p),
            ("worst_week", "peor semana", _p), ("weeks_below_cap", "semanas peores que −1.5%", str),
            ("max_neg_streak", "racha máx. semanas negativas", str), ("governor_hits", "veces que saltó el tope", str),
            ("costs_usd", "costos de operación (US$)", lambda x: f"{x:.0f}"),
            ("financing_usd", "financiamiento neto (US$)", lambda x: f"{x:+.0f}"), ("trades", "ajustes", str))
    for k, lab_, f in rows:
        L.append(f"| {lab_} | " + " | ".join(f(R[n][k]) for n in ("combinado", "combinado_estres_x2", "solo_carry",
                                                                     "solo_momentum")) + " |")
    L += ["", "## Por era (combinado)", "", "| era | semanas | retorno | % semanas + | peor semana | Sharpe |",
          "|---|---|---|---|---|---|"]
    for k, v in R["combinado"]["eras"].items():
        L.append(f"| {k} | {v['weeks']} | {_p(v['ret'])} | {_p(v['pct_pos'], 0)} | {_p(v['worst'])} | {v['sharpe']:.2f} |")
    L += ["", "Costos: spread real de Dukascopy + sobreprecio OANDA estimado; financiamiento con tasas de política y "
          "recargo estimado de 1%/año (verificar con OANDA). Nada aquí es garantía."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    r = run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data/fx")
    print(open(os.path.join(sys.argv[2] if len(sys.argv) > 2 else "data/fx", "CARRY_BACKTEST.md")).read())
