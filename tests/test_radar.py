"""Radar EB (agente 2): matemáticas EB, setups, modelo, sin mirar al futuro, canales y corrida completa sin red.
Corre: python -m tests.test_radar"""
import json
import os
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone

import numpy as np

TMP = tempfile.mkdtemp()
os.environ.update(RADAR_CACHE=os.path.join(TMP, "cache"), RADAR_OUT=os.path.join(TMP, "out"),
                  RADAR_CHANNELS="issue,email,whatsapp")
for k in ("GITHUB_TOKEN", "RADAR_SMTP_USER", "RADAR_SMTP_PASS", "CALLMEBOT_PHONE", "CALLMEBOT_APIKEY", "GEMINI_API_KEY"):
    os.environ.pop(k, None)

from radar import config as C  # noqa: E402
from radar import data as D  # noqa: E402
from radar import eb  # noqa: E402
from radar import features as F  # noqa: E402
from radar import notify as N  # noqa: E402
from radar import report as R  # noqa: E402
from radar.model import Model, decide, outcome  # noqa: E402
from radar.setups import SETUPS, apply_cooldown, build_panel, raw_triggers, triggers  # noqa: E402

res = []
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or res.append(bool(c))


def days(n, cls, start=date(2016, 1, 4)):
    out, d = [], start
    while len(out) < n:
        if cls == "crypto" or d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def make(sym, n, seed, cls, vol, drift=0.0004, shocks=None, rebound=0.0):
    """Paseo aleatorio; en los días `shocks` cae ~4σ y (si rebound>0) recupera `rebound` repartido en 5 barras."""
    rng = np.random.default_rng(seed)
    r = rng.standard_t(5, n) * vol / 1.3 + drift
    for t in (shocks or []):
        if t < n:
            r[t] = -4.5 * vol
            for k in range(1, 6):
                if t + k < n:
                    r[t + k] += rebound / 5
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.002
    lo = np.minimum(o, c) * 0.998
    return D.from_rows(sym, list(zip(days(n, cls), o, h, lo, c, np.ones(n))), "synth")


# ── 1. matemáticas EB ───────────────────────────────────────────────────────────────────────────────────
rng = np.random.default_rng(5)
th = rng.beta(6, 14, 400)                         # μ = 0.3, c = 20
nn = rng.integers(20, 60, 400)
kk = rng.binomial(nn, th)
mu, c = eb.beta_binomial_mom(kk, nn)
ok(abs(mu - th.mean()) < 0.01 and 10 < c < 40, f"Beta-Binomial por momentos recupera μ≈0.30, c≈20 (μ={mu:.3f}, c={c:.1f})")
mu0, c0 = eb.beta_binomial_mom(rng.binomial(40, 0.4, 50), np.full(50, 40))
ok(c0 >= 1000, f"sin heterogeneidad real → pooling completo (c={c0:.0f})")
pg = eb.poisson_gamma(np.array([2, 0, 5, 1]), np.array([4.0, 4.0, 4.0, 4.0]))
ok(pg["pooled"] == 0.5 and all(p > 0 for p in pg["post"]), "Poisson-Gamma: tasa conjunta y posteriores > 0")
m, v, B = eb.normal_posterior(1.0, 1.0, 0.0, 1.0)
ok(abs(m - 0.5) < 1e-9 and abs(B - 0.5) < 1e-9, "Normal-Normal: mitad de encogimiento con igual varianza")
taus = [eb.tau2_between(list(rng.normal(0, 0.3, 6)), [0.09] * 6, cap=1.0) for _ in range(400)]
ok(np.mean(taus) < 0.03, f"DerSimonian-Laird bajo la nula ≈ 0 en promedio ({np.mean(taus):.4f})")
ok(eb.tau2_between([0.1, 2.0], [0.01, 0.01], cap=1.0) == 0.0, "con < 5 activos no se estima heterogeneidad")
ok(eb.tau2_across([0.0, 0.0, 0.0], [0.1, 0.1, 0.1], 0.0025, 1.0) == 0.0025, "τ entre setups respeta el piso")

# ── 2. variables sin mirar al futuro ────────────────────────────────────────────────────────────────────
x = np.r_[np.zeros(70), 10.0]
sd = F.roll_std(x, 60, shift=1)
ok(sd[-1] == 0.0, "σ60 del día del choque NO incluye el propio choque")
z = F.zscore_prev(np.r_[np.random.default_rng(1).normal(0, 1, 100), 50.0], 60)
ok(z[-1] > 20, "z del último dato contra su ventana previa")
ok(np.isnan(F.roll_mean(np.arange(10.0), 20)).all(), "media móvil sin datos suficientes → NaN")

# ── 3. universo y setups ────────────────────────────────────────────────────────────────────────────────
ok(not any(s.upper().startswith("BNB") for s in C.universe()), "BNB y BNB* fuera del universo")
ok(all(s.weight(c) <= 1 for s in SETUPS.values() for c in s.classes), "pesos de evidencia ≤ 1")
ok(SETUPS["PANICO_SIN_DANO"].weight("us") > SETUPS["CAPITULACION"].weight("us"),
   "E3 reciente pesa más que E4 de 1985 (decaimiento post-publicación)")
ok(apply_cooldown(np.array([1, 1, 1, 0, 0, 0, 0, 1], bool), 3).tolist() == [1, 0, 0, 0, 0, 0, 0, 1],
   "cooldown deja episodios independientes")

N0 = 1600
shocks = list(range(300, N0 - 20, 37))
btc = make("BTC", N0, 1, "crypto", 0.03, shocks=shocks, rebound=0.16)
fg = {d: 20.0 for d in btc.dates}
aux = {"vix": None, "mxn": None, "fg": fg, "events": []}
pb = build_panel(btc, "crypto", btc, aux)
tr = raw_triggers("PANICO_SIN_DANO", pb)
hit = np.mean([tr[t] for t in shocks if t > 260])
ok(hit > 0.8, f"PÁNICO dispara en los choques sembrados ({hit:.0%})")
aux_dmg = dict(aux, events=[{"date": btc.dates[shocks[10]], "category": "HACK_SECURITY", "status": "happened"}])
pb_d = build_panel(btc, "crypto", btc, aux_dmg)
ok(not raw_triggers("PANICO_SIN_DANO", pb_d)[shocks[10]], "evento de daño (hackeo) bloquea 'pánico sin daño'")

# ── 4. sin mirar al futuro en resultados ────────────────────────────────────────────────────────────────
t0 = shocks[5]
o = outcome(pb, t0, 1, 7)
manual = pb.close[t0 + 7] / pb.open[t0 + 1] - 1 - C.COST_RT["crypto"]
ok(o is not None and abs(o[1] - manual) < 1e-12, "resultado = apertura de t+1 → cierre de t+7, neto de costos")
ok(outcome(pb, len(pb.close) - 3, 1, 7) is None, "sin futuro suficiente → sin resultado (no se rellena)")

# ── 5. modelo: con efecto sembrado lo detecta; sin efecto encoge ────────────────────────────────────────
alts = [make(s, N0, 10 + k, "crypto", 0.04, shocks=shocks, rebound=0.20) for k, s in enumerate(["ETH", "SOL", "XRP", "ADA"])]
panels_eff = [pb] + [build_panel(s, "crypto", btc, aux) for s in alts]
m_eff = Model().fit(panels_eff)
g = m_eff.groups[("PANICO_SIN_DANO", "crypto", 7)]
ok(g["delta"] > 0.3 and g["n_eff"] >= 20, f"efecto real sembrado → ventaja encogida positiva (δ={g['delta']:.2f}, "
                                           f"episodios={g['n_eff']})")
pr = m_eff.predict("PANICO_SIN_DANO", "crypto", 7, "ETH")
ok(pr["p"] > pr["base"] and pr["q10"] <= pr["p"] <= pr["q90"], "predicción con IC ordenado y por encima de la base")
lvl, why = decide(pr, {"euforia": False, "gsy": "ok", "damage_event": False}, None, "crypto")
ok(lvl == "ALERTA", f"con ventaja grande y muchos episodios la regla Selectivo alerta ({lvl}: {why})")
lvl2, _ = decide(pr, {"euforia": True, "gsy": "ok"}, None, "crypto")
ok(lvl2 == "VETADA", "euforia (F&G ≥ 80) veta")
pr_c = dict(pr, p=C.ALERT["p_min"] + 0.02, q10=C.ALERT["q10_min"] + 0.02)
ok(decide(pr_c, {}, "CAUTION", "crypto")[0] == "VIGILANCIA", "contexto CAUTION sube la exigencia +5 pp")

btc0 = make("BTC", N0, 1, "crypto", 0.03, shocks=shocks, rebound=0.0)
panels_null = [build_panel(btc0, "crypto", btc0, aux)] + [
    build_panel(make(s, N0, 10 + k, "crypto", 0.04, shocks=shocks, rebound=0.0), "crypto", btc0, aux)
    for k, s in enumerate(["ETH", "SOL", "XRP", "ADA"])]
m_null = Model().fit(panels_null)
g0 = m_null.groups[("PANICO_SIN_DANO", "crypto", 7)]
ok(abs(g0["delta"]) < abs(g0["delta_raw"]) + 1e-12 and g0["B"] > 0.3,
   f"sin efecto: el estimado se encoge hacia cero (crudo {g0['delta_raw']:+.2f} → {g0['delta']:+.2f}, B={g0['B']:.2f})")
dw = m_null.best_dow("crypto")
ok(dw.get("spread_pp", 99) < 3, f"día de la semana sin efecto real → diferencia encogida pequeña ({dw.get('spread_pp'):.2f} pp)")
lag = m_eff.best_lag("PANICO_SIN_DANO", "crypto", 7)
ok("t+" in lag["texto"], "ventana de entrada reportada")

# ── 6. fichas y canales ─────────────────────────────────────────────────────────────────────────────────
from radar.pipeline import _candidate  # noqa: E402
cand = _candidate(m_eff, panels_eff[1], shocks[-3], "PANICO_SIN_DANO", {"state": "NEUTRAL", "reasons": []})
md = R.ficha_md(cand)
ok(all(s in md for s in ("QUÉ NO INFERIR", "MEJOR DÍA DE COMPRA", "CONFIANZA", "No es asesoría", "IC80")),
   "ficha con campos C11-025 + mejor día + aviso legal")
ok(len(R.short_txt(cand)) < 900, "texto corto para WhatsApp")
html = R.md_to_html(md)
ok("<table" in html and "<b>" in html, "correo HTML con tabla")
ok(N.channels() == [], "sin secrets no hay canales (no intenta enviar nada)")
os.environ.update(CALLMEBOT_PHONE="+520000000000", CALLMEBOT_APIKEY="SECRETO123")
import httpx  # noqa: E402
orig = httpx.get
httpx.get = lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("fallo con https://x?apikey=SECRETO123"))
N.LOG.clear()
N.whatsapp_send("hola")
httpx.get = orig
ok(not any("SECRETO123" in m for m in N.LOG), "falla de WhatsApp no deja la apikey en la bitácora")
os.environ.pop("CALLMEBOT_PHONE")
os.environ.pop("CALLMEBOT_APIKEY")

# ── 7. corrida completa sin red (caché sintética) ───────────────────────────────────────────────────────
from radar import pipeline as P  # noqa: E402
os.makedirs(C.CACHE_DIR, exist_ok=True)
today = datetime.now(timezone.utc).date()
n_st = 1300


def days_back(n, cls, end):
    out, d = [], end
    while len(out) < n:
        if cls == "crypto" or d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def recent(sym, cls, seed, vol, shocks_rel=(), rebound=0.0):
    s = make(sym, n_st, seed, cls, vol, shocks=[n_st + k for k in shocks_rel], rebound=rebound)
    ds = days_back(n_st, cls, today - timedelta(days=1))
    s = D.from_rows(sym, [(d, s.open[i], s.high[i], s.low[i], s.close[i], 1) for i, d in enumerate(ds)], "synth")
    D.save_cache(s)
    return s


cr_sh = list(range(-1200, -30, 41)) + [-1]
for k, (sym, cls, vol) in enumerate([("BTC", "crypto", 0.03), ("ETH", "crypto", 0.04), ("SOL", "crypto", 0.05),
                                     ("XRP", "crypto", 0.045), ("ADA", "crypto", 0.045)]):
    recent(sym, cls, 50 + k, vol, cr_sh, 0.2)
for k, (sym, cls, vol) in enumerate([("SPY", "us", 0.011), ("QQQ", "us", 0.014), ("^MXX", "bmv", 0.012),
                                     ("NAFTRACISHRS.MX", "bmv", 0.012), ("^VIX", "us", 0.05), ("MXN=X", "us", 0.007)]):
    recent(sym, cls, 80 + k, vol)
json.dump({d: 18.0 for d in days(n_st + 10, "crypto", today - timedelta(days=n_st + 5))},
          open(os.path.join(C.CACHE_DIR, "fear_greed.json"), "w"))
out = P.run(offline=True, force_digest=True, dry=True)
st = json.load(open(os.path.join(C.OUT_DIR, "state.json")))
ok(out["candidates"] >= 1 and os.path.exists(os.path.join(C.OUT_DIR, "README.md")),
   f"corrida sin red: {out['candidates']} candidatos, tablero escrito")
ok(os.path.exists(os.path.join(C.OUT_DIR, "ULTIMO_RESUMEN.md")) and st.get("last_digest_date"), "resumen diario escrito")
n_al = len(st["alerts"])
ok(n_al <= C.ALERT["max_week"], f"tope semanal respetado ({n_al} ≤ {C.ALERT['max_week']})")
out2 = P.run(offline=True, dry=True)
st2 = json.load(open(os.path.join(C.OUT_DIR, "state.json")))
ok(len(st2["alerts"]) == n_al and out2["digest"] is None, "segunda corrida: no repite alertas ni el resumen del día")
dg = open(os.path.join(C.OUT_DIR, "ULTIMO_RESUMEN.md")).read()
ok("Sigo vivo" in dg and "Mejor día de compra" in dg, "resumen con 'sigo vivo' y mejor día de compra")

shutil.rmtree(TMP, ignore_errors=True)
print(f"{sum(res)}/{len(res)} {'OK' if all(res) else 'FALLA'}")
