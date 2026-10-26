"""Simulación de la réplica con 50,000 (pre-registro: docs/COPYTRADE_TRUMP.md).

Cartera sombra: acciones por activo = Σ compras/precio − ventas/precio (nunca < 0), procesando las operaciones en
orden de fecha de operación. El copiador sostiene la misma composición y rebalancea al cierre del día en que se
entera:
  · modo E (espejo perfecto): se entera el día de la operación (o el siguiente hábil);
  · modo R (replicable): se entera al cierre del primer día hábil DESPUÉS de la publicación; en ese momento
    reconstruye la cartera con TODAS las operaciones publicadas hasta entonces (en orden de fecha de operación).
Precio: cierre ajustado (dividendos + splits). Serie que termina antes → la posición rinde como BIL desde su último
cierre. Serie que empieza después de la operación → primer cierre si está a ≤ 5 días hábiles; si no, fuera.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import math
import re

import numpy as np
import pandas as pd

from .data import mid as range_mid

START = pd.Timestamp("2025-01-21")          # primer día hábil del mandato (20-ene-2025 fue feriado)
CAPITAL = 50_000.0
BACKFILL_DAYS = 5
NON_EQUITY_FUND = re.compile(r"bond|treasury|treas|corp|muni|income|gold|silver|commodit|short[- ]term|aggregate|"
                             r"tips|high yield|money|floating|mortgage|credit|duration|bitcoin|ether", re.I)
CASH = "BIL"


# ------------------------------------------------------------------------------------------------- precios
def load_prices(path: str) -> pd.DataFrame:
    px = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    px = px[~px.index.duplicated()]
    cal = px["SPY"].dropna().index                       # calendario = días con cierre del SPY
    return px.reindex(cal)


def extend(px: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Rellena huecos cortos, extiende con BIL tras el último cierre y hacia atrás 5 días antes del primero."""
    bil = px[CASH].ffill()
    out = {}
    info = {}
    for c in px.columns:
        s = px[c]
        fv, lv = s.first_valid_index(), s.last_valid_index()
        if fv is None:
            continue
        s = s.copy()
        s.loc[fv:lv] = s.loc[fv:lv].ffill(limit=5)
        if lv < px.index[-1]:
            s.loc[lv:] = s.loc[lv] * bil.loc[lv:] / bil.loc[lv]
        i0 = px.index.get_loc(fv)
        if i0 > 0:
            s.iloc[max(0, i0 - BACKFILL_DAYS):i0] = s.loc[fv]
        out[c] = s
        info[c] = (fv, lv)
    return pd.DataFrame(out, index=px.index), info


def exec_day(cal: pd.DatetimeIndex, d: pd.Timestamp, strictly_after: bool, lag: int = 0) -> pd.Timestamp | None:
    i = cal.searchsorted(d, side="right" if strictly_after else "left") + lag
    return cal[i] if i < len(cal) else None


# ------------------------------------------------------------------------------------------------- cartera sombra
@dataclasses.dataclass
class Spec:
    mode: str = "R"            # E | R
    lag: int = 0               # días hábiles extra en modo R
    sleeve: str = "full"       # full | equity
    amount: str = "mid"        # mid | lower | geo | equal
    cost: float = 0.0029       # por peso operado, por lado
    top: int = 0               # 0 = todas las posiciones; 30 = Top-30

    def name(self) -> str:
        m = "E" if self.mode == "E" else f"R+{self.lag}" if self.lag else "R"
        return f"{m}·{self.sleeve}·{self.amount}·{self.cost*100:.2f}%" + (f"·top{self.top}" if self.top else "")


def prepare(trades: pd.DataFrame, px: pd.DataFrame, info: dict) -> pd.DataFrame:
    t = trades[trades.ticker.fillna("") != ""].copy()
    t["date"] = pd.to_datetime(t["date"])
    t["pub"] = pd.to_datetime(t["pub"])
    cal = px.index
    t["xE"] = [exec_day(cal, d, False) for d in t["date"]]
    t["xR"] = [exec_day(cal, p, True) for p in t["pub"]]
    ok = t.ticker.isin(px.columns)
    t["price_ok"] = False
    t.loc[ok, "price_ok"] = [not math.isnan(px.at[x, k]) if x is not None else False
                             for x, k in zip(t.loc[ok, "xE"], t.loc[ok, "ticker"])]
    return t


def equity_sleeve(t: pd.DataFrame, names: dict[str, str]) -> pd.Series:
    def is_eq(r) -> bool:
        if r.cls == "equity":
            return True
        if r.cls == "fund":
            return not NON_EQUITY_FUND.search(names.get(r.ticker, "") + " " + r.description)
        return False
    return t.apply(is_eq, axis=1)


def holdings(t: pd.DataFrame, px: pd.DataFrame, amount: str) -> pd.Series:
    """Acciones por ticker procesando `t` en orden de fecha de operación (compras antes que ventas el mismo día)."""
    sh: dict[str, float] = {}
    tt = t.sort_values(["xE", "type"], kind="stable")      # 'Purchase' < 'Sale'
    for r in tt.itertuples():
        p = px.at[r.xE, r.ticker]
        amt = range_mid(int(r.lower), amount)
        if r.type == "Purchase":
            sh[r.ticker] = sh.get(r.ticker, 0.0) + amt / p
        else:
            cur = sh.get(r.ticker, 0.0)
            if cur > 0:
                sh[r.ticker] = max(0.0, cur - amt / p)
    return pd.Series(sh, dtype=float)


def book_path(t: pd.DataFrame, px: pd.DataFrame, spec: Spec) -> dict[pd.Timestamp, pd.Series]:
    """{día de rebalanceo: acciones objetivo}."""
    t = t[t.price_ok]
    if spec.mode == "E":
        events = sorted(t["xE"].unique())
        out, sh = {}, {}
        tt = t.sort_values(["xE", "type"], kind="stable")
        for d, g in tt.groupby("xE", sort=True):
            for r in g.itertuples():
                p = px.at[d, r.ticker]
                amt = range_mid(int(r.lower), spec.amount)
                if r.type == "Purchase":
                    sh[r.ticker] = sh.get(r.ticker, 0.0) + amt / p
                elif sh.get(r.ticker, 0) > 0:
                    sh[r.ticker] = max(0.0, sh[r.ticker] - amt / p)
            out[d] = pd.Series(dict(sh), dtype=float)
        return out
    cal = px.index
    out = {}
    pubs = sorted(t["pub"].unique())
    for p in pubs:
        x = exec_day(cal, p, True, spec.lag)
        if x is None:
            continue
        known = t[t["pub"] <= p]
        out[x] = holdings(known, px, spec.amount)
    return out


def run(t: pd.DataFrame, px: pd.DataFrame, spec: Spec, start: pd.Timestamp = START) -> dict:
    cal = px.index[px.index >= start]
    books = book_path(t, px, spec)
    rets = px.pct_change(fill_method=None)
    nav = pd.Series(index=cal, dtype=float)
    nav.iloc[0] = CAPITAL
    w = pd.Series({CASH: 1.0})                    # pesos al cierre previo
    cost_paid = 0.0
    turnover = 0.0
    contrib: dict[str, float] = {}
    weights_log = {}
    for i, d in enumerate(cal):
        if i > 0:
            r = rets.loc[d, w.index].fillna(0.0)
            g = float((w * r).sum())
            v_prev = nav.iloc[i - 1]
            for k, x in (w * r).items():
                contrib[k] = contrib.get(k, 0.0) + x * v_prev
            nav.iloc[i] = v_prev * (1 + g)
            drift = w * (1 + r)
            w = drift / drift.sum()
        if d in books:
            b = books[d]
            val = (b * px.loc[d, b.index]).dropna()
            val = val[val > 0]
            if spec.top and len(val) > spec.top:
                val = val.sort_values(ascending=False).iloc[:spec.top]
            tgt = val / val.sum() if len(val) else pd.Series({CASH: 1.0})
            idx = w.index.union(tgt.index)
            to = float((tgt.reindex(idx, fill_value=0) - w.reindex(idx, fill_value=0)).abs().sum())
            c = to * spec.cost * nav.iloc[i]
            nav.iloc[i] -= c
            cost_paid += c
            turnover += to
            w = tgt
            weights_log[d] = tgt
    return {"spec": spec, "nav": nav, "cost": cost_paid, "turnover": turnover, "contrib": pd.Series(contrib),
            "weights": weights_log, "rebalances": len(books)}


# ------------------------------------------------------------------------------------------------- comparativos
def benchmark(px: pd.DataFrame, weights: dict[str, float], start: pd.Timestamp = START, monthly: bool = True
              ) -> pd.Series:
    cal = px.index[px.index >= start]
    r = px.loc[cal, list(weights)].pct_change(fill_method=None).fillna(0.0)
    w0 = pd.Series(weights, dtype=float)
    nav = [CAPITAL]
    w = w0.copy()
    for i in range(1, len(cal)):
        g = float((w * r.iloc[i]).sum())
        nav.append(nav[-1] * (1 + g))
        w = w * (1 + r.iloc[i])
        w = w / w.sum()
        if monthly and cal[i].month != cal[i - 1].month:
            w = w0.copy()
    return pd.Series(nav, index=cal)


def cetes_mxn(rates_csv: str, cal: pd.DatetimeIndex) -> pd.Series:
    """CETES aproximados con la tasa objetivo de Banxico (BIS), devengo act/360, en pesos."""
    r = pd.read_csv(rates_csv, parse_dates=["date"])
    r = r[r.ccy == "MXN"].set_index("date")["rate"].sort_index()
    r = r.reindex(r.index.union(cal)).ffill().reindex(cal)
    days = pd.Series(cal, index=cal).diff().dt.days.fillna(0)
    growth = (1 + r.shift(1).fillna(r.iloc[0]) / 100 * days / 360).cumprod()
    return CAPITAL * growth / growth.iloc[0]


# ------------------------------------------------------------------------------------------------- métricas
def newey_west(y: np.ndarray, x: np.ndarray, lags: int = 10) -> tuple[np.ndarray, np.ndarray]:
    X = np.column_stack([np.ones_like(x), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ beta
    n = len(y)
    xe = X * e[:, None]
    S = xe.T @ xe
    for L in range(1, lags + 1):
        wl = 1 - L / (lags + 1)
        G = xe[L:].T @ xe[:-L]
        S += wl * (G + G.T)
    XtX_inv = np.linalg.inv(X.T @ X)
    V = XtX_inv @ S @ XtX_inv
    return beta, np.sqrt(np.diag(V))


def metrics(nav: pd.Series, spy: pd.Series, bil: pd.Series) -> dict:
    nav = nav.dropna()
    r = nav.pct_change().dropna()
    rs = spy.reindex(nav.index).pct_change().dropna()
    rb = bil.reindex(nav.index).pct_change().dropna().reindex(r.index).fillna(0)
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    ex = r - rb
    exs = rs.reindex(r.index) - rb
    beta, se = newey_west(ex.values, exs.values)
    dd = nav / nav.cummax() - 1
    te = (r - rs.reindex(r.index)).std() * math.sqrt(252)
    return {"final": float(nav.iloc[-1]), "total": float(nav.iloc[-1] / nav.iloc[0] - 1),
            "cagr": float((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1), "vol": float(r.std() * math.sqrt(252)),
            "sharpe": float(ex.mean() / ex.std() * math.sqrt(252)) if ex.std() > 0 else 0.0,
            "maxdd": float(dd.min()), "beta": float(beta[1]), "alpha_ann": float(beta[0] * 252),
            "alpha_t": float(beta[0] / se[0]) if se[0] > 0 else 0.0, "te": float(te),
            "ir": float((r - rs.reindex(r.index)).mean() * 252 / te) if te > 0 else 0.0,
            "start": str(nav.index[0].date()), "end": str(nav.index[-1].date())}
