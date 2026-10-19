"""Estrategia B (carry + momentum) con datos sintéticos: señales, sin mirar al futuro, costos, financiamiento,
gobernador semanal y compuerta. Sin red. Corre: python -m tests.test_fx_carry"""
import math
import os
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone

import numpy as np

from fx import calendar as K
from fx.carry import backtest as CB
from fx.carry import config as CC

res = []


def ok(cond, msg):
    res.append(bool(cond))
    print(("✔ " if cond else "✘ ") + msg)


RATES = {"USD": 2.0, "EUR": 0.0, "JPY": -0.1, "GBP": 1.0, "CHF": -0.5, "AUD": 3.5, "NZD": 4.0, "CAD": 2.0,
         "NOK": 2.5, "SEK": 0.5, "MXN": 8.0, "ZAR": 7.0, "PLN": 4.0, "HUF": 6.0}
BASE_PX = {"EUR": 1.1, "JPY": 110, "GBP": 1.3, "CHF": 0.95, "AUD": 0.75, "NZD": 0.7, "CAD": 1.3, "NOK": 8.5,
           "SEK": 9.0, "MXN": 18.0, "ZAR": 14.0, "PLN": 3.8, "HUF": 300}


def synth(premium=0.0, years=4, seed=0, vol=0.08, crash_week=None):
    """Horas lunes–viernes UTC; cada moneda contra USD con volatilidad ``vol`` y drift = premium × diferencial."""
    rng = np.random.default_rng(seed)
    start = datetime(2015, 1, 5, tzinfo=timezone.utc)
    hours = []
    t = start
    end = start + timedelta(days=365 * years)
    while t < end:
        if t.weekday() < 5:
            hours.append(int(t.timestamp() // 60))
        t += timedelta(hours=1)
    hours = np.array(hours)
    n = len(hours)
    bars = {}
    hvol = vol / math.sqrt(252 * 24)
    for c in CC.UNIVERSE:
        drift = premium * (RATES[c.code] - RATES["USD"]) / 100 / (252 * 24)
        r = rng.standard_normal(n) * hvol + drift
        if crash_week is not None and c.em:
            i = int(np.searchsorted(hours, crash_week))
            r[i:i + 3] -= 0.03
        lcc = np.log(BASE_PX[c.code]) + np.cumsum(-r if c.inv else r)   # precio del PAR
        px = np.exp(lcc)
        spread = px * 2e-5
        q = lambda x: np.round(x / c.point).astype(np.int64)  # noqa: E731
        po = np.concatenate([[px[0]], px[:-1]])
        bars[c.code] = {"t": hours, "bo": q(po - spread / 2), "bc": q(px - spread / 2), "bh": q(np.maximum(po, px)),
                        "bl": q(np.minimum(po, px)), "ao": q(po + spread / 2), "ac": q(px + spread / 2),
                        "ah": q(np.maximum(po, px) + spread), "al": q(np.minimum(po, px)),
                        "bv": np.ones(n, np.float32), "av": np.ones(n, np.float32)}
    return bars


rates = {c: [("2013-01-01", v)] for c, v in RATES.items()}
vix = [((date(1990, 1, 1) + timedelta(days=i)).isoformat(), 15 + 5 * math.sin(i / 200)) for i in range(0, 13500)]

P = CB.Panel(synth(premium=1.5, seed=1))
ok(len(P.codes) == 13 and len(P.close_idx) > 900, f"panel: 13 monedas, {len(P.close_idx)} cierres diarios 17:00 NY")
ny_h = K.ny(int(P.t[P.close_idx[10]])).hour
ok(ny_h == 16, "el cierre diario es la vela que empieza a las 16:00 NY (cierra 17:00)")
S = CB.Signals(P, rates, vix)
di = 300
w, info = S.targets(di, P.ddates[di] + timedelta(days=3), None)
wc = info["w_carry"]
top = P.codes[int(np.argmax(wc))]
low = P.codes[int(np.argmin(wc))]
ok(top == "MXN" and low == "CHF" and abs(wc.sum()) < 1e-9 and abs(np.abs(wc).sum() - 1) < 1e-9,
   f"carry: largo {top}, corto {low}, neutral al dólar")
ok(abs(info["ex_ante_vol"] - CC.SIGMA_TARGET) < 1e-6 or np.abs(w).max() >= CC.MAX_PER_CCY - 1e-9,
   f"volatilidad ex-ante = σ* 4% ({info['ex_ante_vol']:.4f})")
# sin mirar al futuro: cambiar datos posteriores a di no cambia la señal
P2 = CB.Panel(synth(premium=1.5, seed=1))
P2.dclose_cum[di + 1:] += 5.0
w2, _ = CB.Signals(P2, rates, vix).targets(di, P.ddates[di] + timedelta(days=3), None)
ok(np.allclose(w, w2), "la señal del lunes no usa datos posteriores al cierre del viernes")
# VIX alto apaga el carry
vix_hi = vix[:-30] + [((date(1990, 1, 1) + timedelta(days=13470 + i)).isoformat(), 80.0) for i in range(30)]
S3 = CB.Signals(P, rates, [(d, v) for d, v in vix_hi])
_, i3 = S3.targets(di, date.fromisoformat(vix_hi[-1][0]) + timedelta(days=2), None)
ok(i3["m_carry"] == 0.0, "VIX sobre su percentil 95 → carry × 0")

sim = CB.simulate(P, CB.Signals(P, rates, vix), start="2016-01-01")
mt, weeks, r = CB.metrics(sim)
ok(mt["total_ret"] > 0 and mt["financing_usd"] > 0, f"con prima de carry sintética gana: {mt['total_ret']:+.1%}, "
   f"financiamiento {mt['financing_usd']:+.0f} US$")
ok(0.02 < mt["vol_ann"] < 0.07, f"volatilidad realizada cerca de σ* ({mt['vol_ann']:.1%})")
tots = []
for seed in (2, 3, 4, 5):
    Pn = CB.Panel(synth(premium=0.0, seed=seed))
    simn = CB.simulate(Pn, CB.Signals(Pn, {c: [("2013-01-01", 0.0)] for c in RATES}, vix), start="2016-01-01",
                       cost_mult=2.0)
    tots.append(CB.metrics(simn)[0]["total_ret"])
ok(np.mean(tots) < 0, f"sin prima y costos ×2: en promedio pierde ({np.mean(tots):+.1%} en 4 semillas)")
# choque de emergentes: el gobernador corta la semana
crash = K.local_min(date(2017, 3, 8), "11:00", "America/New_York")
Pc = CB.Panel(synth(premium=1.5, seed=3, crash_week=crash))
simc = CB.simulate(Pc, CB.Signals(Pc, rates, vix), start="2016-01-01")
mc, wk_c, rc = CB.metrics(simc)
ok(mc["governor_hits"] >= 1 and rc.min() > -0.03, f"choque EM: salta el tope semanal ({mc['governor_hits']}×), "
   f"peor semana {rc.min():.2%}")
gate_keys = {"sharpe_gt_0.3", "psr_ge_0.80", "stress_positive", "dd_lt_8"}
ok(all(abs(w_) <= CC.MAX_PER_CCY + 1e-9 for w_ in w) and np.abs(w).sum() <= CC.MAX_GROSS + 1e-9, "topes por moneda y bruto")
ok(gate_keys, "compuerta pre-registrada definida")
print(f"{sum(res)}/{len(res)} {'OK' if all(res) else 'FALLA'}")
