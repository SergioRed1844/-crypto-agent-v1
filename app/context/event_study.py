"""Estudio de eventos: ¿cuánto y hacia dónde movió BTC cada tipo de evento desde 2010?

Por evento (día d, UTC):
  base   = cierre de d-1
  r_h    = ln(cierre(d+h-1) / base)                h = 1, 3, 7, 30 días
  z_h    = (r_h - h·μ) / (σ·√h)                    μ, σ = drift y vol diarios de los 90 días previos (control)
  vol_ratio = σ(d..d+6) / σ(d-30..d-1)
Por categoría: n, media de |z3| contra días al azar (p por permutación), efecto direccional con el signo
de crypto_stance (pro=+1, anti=−1) y tasa de acierto del signo. Pesos con ENCOGIMIENTO bayesiano:
  w = (n·empírico + k·prior) / (n + k)     → con pocos datos manda el prior; con muchos, la evidencia.
Moderadora estimada: régimen de BTC al momento del evento (precio vs media de 200 días).

Uso: python -m app.context.event_study [--fetch]   (--fetch baja precios; corre en GitHub Actions)
"""
import argparse
import csv
import json
import logging
import math
import random
import sys
from collections import defaultdict
from datetime import date, datetime, timezone

import httpx

from . import ctx_dir, iso, read_json, utcnow, write_json
from .schema import CATEGORIES, label, normalize, sign

log = logging.getLogger("event_study")
HS = (1, 3, 7, 30)
CM_URL = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets={a}&metrics=PriceUSD"
          "&frequency=1d&page_size=10000&paging_from=start")
BINANCE = "https://data-api.binance.vision/api/v3/klines"


# ── Precios ───────────────────────────────────────────────────
def fetch_coinmetrics(asset: str = "btc") -> dict[date, float]:
    out, url = {}, CM_URL.format(a=asset)
    with httpx.Client(timeout=60, headers={"User-Agent": "cryptoagent-context"}) as c:
        while url:
            j = c.get(url).raise_for_status().json()
            for r in j.get("data", []):
                if r.get("PriceUSD"):
                    out[date.fromisoformat(r["time"][:10])] = float(r["PriceUSD"])
            url = j.get("next_page_url")
    return out


def fetch_binance_daily(symbol: str, since: str = "2017-08-17") -> dict[date, float]:
    out, cur = {}, int(datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp() * 1000)
    with httpx.Client(timeout=60, headers={"User-Agent": "cryptoagent-context"}) as c:
        while True:
            rows = c.get(BINANCE, params={"symbol": symbol, "interval": "1d", "startTime": cur, "limit": 1000}
                         ).raise_for_status().json()
            for r in rows:
                if r[6] < utcnow().timestamp() * 1000:  # solo velas cerradas
                    out[datetime.fromtimestamp(r[0] / 1000, timezone.utc).date()] = float(r[4])
            if len(rows) < 1000:
                break
            cur = rows[-1][0] + 86_400_000
    return out


def save_prices(name: str, px: dict[date, float]):
    p = ctx_dir() / "cache" / f"{name}_1d.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        for d in sorted(px):
            w.writerow([d.isoformat(), f"{px[d]:.8g}"])


def load_prices(name: str = "btc") -> dict[date, float]:
    p = ctx_dir() / "cache" / f"{name}_1d.csv"
    if not p.exists():
        return {}
    with p.open() as f:
        return {date.fromisoformat(r["date"]): float(r["close"]) for r in csv.DictReader(f)}


def fetch_all() -> dict:
    res = {}
    try:
        btc = fetch_coinmetrics("btc")
        src = "Coin Metrics Community (PriceUSD, 2010+)"
    except Exception as e:
        log.warning(f"Coin Metrics falló ({e}); uso Binance (2017+)")
        btc, src = fetch_binance_daily("BTCUSDT"), "Binance BTCUSDT 1d (2017+)"
    if btc:
        save_prices("btc", btc)
        res["btc"] = {"n": len(btc), "source": src}
    for sym in ("ETHUSDT", "SOLUSDT"):
        try:
            px = fetch_binance_daily(sym)
            save_prices(sym[:-4].lower(), px)
            res[sym] = {"n": len(px)}
        except Exception as e:
            log.warning(f"{sym}: {e}")
    return res


# ── Cálculo ───────────────────────────────────────────────────
class Series:
    def __init__(self, px: dict[date, float]):
        self.days = sorted(px)
        self.idx = {d: i for i, d in enumerate(self.days)}
        self.close = [px[d] for d in self.days]
        self.lr = [0.0] + [math.log(self.close[i] / self.close[i - 1]) for i in range(1, len(self.close))]
        self.ma200 = []
        s = 0.0
        for i, c in enumerate(self.close):
            s += c
            if i >= 200:
                s -= self.close[i - 200]
            self.ma200.append(s / min(i + 1, 200))

    def _stats(self, a: int, b: int):
        xs = self.lr[a:b]
        if len(xs) < 20:
            return None
        mu = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))
        return mu, sd

    def reaction(self, d: date) -> dict | None:
        i = self.idx.get(d)
        if i is None or i < 92:
            return None
        st = self._stats(i - 91, i - 1)
        if not st or st[1] <= 0:
            return None
        mu, sd = st
        base = self.close[i - 1]
        out = {"regime": "GREEN" if base >= self.ma200[i - 1] else "RED"}
        for h in HS:
            j = i + h - 1
            if j >= len(self.close):
                out[f"z{h}"] = None
                continue
            r = math.log(self.close[j] / base)
            out[f"r{h}"] = round(r, 5)
            out[f"z{h}"] = round((r - h * mu) / (sd * math.sqrt(h)), 3)
        post, pre = self._sd(i, i + 7), self._sd(i - 30, i)
        out["vol_ratio"] = round(post / pre, 3) if post is not None and pre else None
        return out

    def _sd(self, a: int, b: int):
        xs = self.lr[max(1, a):min(b, len(self.lr))]
        if len(xs) < 5:
            return None
        m = sum(xs) / len(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

    def random_abs_z3(self, n: int = 4000, seed: int = 7) -> list[float]:
        rng, out = random.Random(seed), []
        lo, hi = 92, len(self.days) - 3
        for _ in range(n):
            r = self.reaction(self.days[rng.randint(lo, hi - 1)])
            if r and r.get("z3") is not None:
                out.append(abs(r["z3"]))
        return out


def _perm_p(obs_mean: float, pool: list[float], n: int, draws: int = 2000, seed: int = 11) -> float:
    if n == 0 or not pool:
        return 1.0
    rng = random.Random(seed)
    ge = sum(1 for _ in range(draws) if sum(rng.choice(pool) for _ in range(n)) / n >= obs_mean)
    return round((ge + 1) / (draws + 1), 4)


def _sign_p(hits: int, n: int) -> float:
    """Prueba binomial de una cola (H0: acierto del signo = 50%)."""
    if n == 0:
        return 1.0
    return round(sum(math.comb(n, k) for k in range(hits, n + 1)) / 2 ** n, 4)


def _evidence(n, p):
    if n < 3:
        return "sin datos"
    if n >= 10 and p < 0.05:
        return "fuerte"
    if n >= 5 and p < 0.10:
        return "moderada"
    return "débil"


def run(history: list[dict] | None = None, px: dict | None = None, priors: dict | None = None) -> dict:
    priors = priors or read_json("priors.json", {})
    history = history if history is not None else read_json("sources/history_events.json", [])
    px = px if px is not None else load_prices("btc")
    if len(px) < 200:
        raise RuntimeError("sin precios de BTC: corre con --fetch (en GitHub Actions)")
    S = Series(px)
    pool = S.random_abs_z3()
    base_mean = sum(pool) / len(pool)
    k = float(priors.get("k_prior", 8))
    tz_abs, tz_dir = priors.get("tier_excess_abs_z", {}), priors.get("tier_dir_z", {})
    rows, by = [], defaultdict(list)
    for e in history:
        try:
            e = normalize(e, "happened")
        except ValueError:
            continue
        r = S.reaction(date.fromisoformat(e["date"][:10]))
        if not r or r.get("z3") is None:
            continue
        row = {"id": e["id"], "date": e["date"][:10], "category": e["category"], "stance": e["crypto_stance"],
               "tier": e["prior_tier"], "title_es": e["title_es"], **r}
        rows.append(row)
        by[e["category"]].append(row)
    cats = {}
    for cat in CATEGORIES:
        rs = by.get(cat, [])
        n = len(rs)
        tiers = [r["tier"] for r in rs] or [priors.get("categories", {}).get(cat, {}).get("default_tier", 2)]
        prior_abs = sum(tz_abs.get(str(t), 0.1) for t in tiers) / len(tiers)
        prior_dir = sum(tz_dir.get(str(t), 0.08) for t in tiers) / len(tiers)
        mean_abs = sum(abs(r["z3"]) for r in rs) / n if n else None
        p_abs = _perm_p(mean_abs, pool, n) if n else 1.0
        sg = [(sign({"crypto_stance": r["stance"]}), r["z3"]) for r in rs]
        sg = [(s, z) for s, z in sg if s != 0]
        ns = len(sg)
        mean_signed = sum(s * z for s, z in sg) / ns if ns else None
        hits = sum(1 for s, z in sg if s * z > 0)
        p_dir = _sign_p(hits, ns)
        # |z| empírico se expresa como EXCESO sobre un día cualquiera (un evento "pesa" si mueve más que el azar)
        emp_abs = (mean_abs - base_mean) if mean_abs is not None else prior_abs
        w_abs = max(0.0, (n * emp_abs + k * prior_abs) / (n + k)) if n else prior_abs
        w_dir = (ns * mean_signed + k * prior_dir) / (ns + k) if ns else prior_dir
        cats[cat] = {"label": label(cat), "n": n, "mean_abs_z3": None if mean_abs is None else round(mean_abs, 3),
                     "ratio_vs_random": None if mean_abs is None else round(mean_abs / base_mean, 2),
                     "excess_abs_z3": None if mean_abs is None else round(mean_abs - base_mean, 3),
                     "p_abs": p_abs, "n_signed": ns,
                     "mean_signed_z3": None if mean_signed is None else round(mean_signed, 3),
                     "hit_rate": round(hits / ns, 3) if ns else None, "p_dir": p_dir,
                     "prior_abs": round(prior_abs, 3), "prior_dir": round(prior_dir, 3),
                     "w_abs": round(w_abs, 3), "w_dir": round(max(0.0, w_dir), 3),
                     "evidence_abs": _evidence(n, p_abs), "evidence_dir": _evidence(ns, p_dir)}
    # moderadora: régimen (GREEN/RED) sobre el efecto direccional de noticias pro/anti
    mods = {}
    pm = priors.get("moderators", {}).get("btc_regime", {})
    for reg in ("GREEN", "RED"):
        for st, sgn_ in (("pro", 1), ("anti", -1)):
            xs = [sgn_ * r["z3"] for r in rows if r["regime"] == reg and r["stance"] == st]
            allx = [sign({"crypto_stance": r["stance"]}) * r["z3"] for r in rows if r["stance"] in ("pro", "anti")]
            base = sum(allx) / len(allx) if allx else 0
            prior = pm.get(reg, {}).get(st, 1.0)
            if xs and base > 0:
                emp = max(0.3, min(2.5, (sum(xs) / len(xs)) / base))
                m = (len(xs) * emp + 15 * prior) / (len(xs) + 15)
            else:
                m = prior
            mods[f"{reg}_{st}"] = {"n": len(xs), "mult": round(m, 3), "prior": prior}
    out = {"generated_utc": iso(utcnow()), "n_events": len(rows), "n_history": len(history),
           "price_range": [S.days[0].isoformat(), S.days[-1].isoformat()],
           "baseline": {"mean_abs_z3_random": round(base_mean, 3), "n_random": len(pool)},
           "k_prior": k, "categories": cats, "moderators": {"btc_regime": mods}}
    return out, rows


def render_md(w: dict, rows: list[dict]) -> str:
    L = ["# Estudio de eventos — ¿qué mueve a BTC?", "",
         f"Generado {w['generated_utc']}. Precios {w['price_range'][0]} → {w['price_range'][1]}. "
         f"{w['n_events']} de {w['n_history']} eventos históricos con precio suficiente.", "",
         f"Referencia: un día cualquiera mueve |z3| = {w['baseline']['mean_abs_z3_random']} en promedio "
         f"({w['baseline']['n_random']} días al azar). Un tipo de evento **pesa** si mueve más que eso "
         "(p_abs < 0.05) y tiene **dirección** si el signo de su postura pro/anti acierta más del 50% (p_dir < 0.05).", "",
         "| Categoría | n | \\|z3\\| | × azar | p | Efecto dir. | Acierto signo | p | Peso magnitud (exceso) | Peso dirección | Evidencia |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    cats = sorted(w["categories"].items(), key=lambda kv: -(kv[1]["n"]))
    for c, v in cats:
        f = lambda x: "—" if x is None else x
        L.append(f"| {v['label']} | {v['n']} | {f(v['mean_abs_z3'])} | {f(v['ratio_vs_random'])} | {v['p_abs']} | "
                 f"{f(v['mean_signed_z3'])} | {f(v['hit_rate'])} | {v['p_dir']} | {v['w_abs']} | {v['w_dir']} | "
                 f"magnitud {v['evidence_abs']}, dirección {v['evidence_dir']} |")
    L += ["", "Pesos = encogimiento bayesiano hacia el prior (k = %s): con pocos eventos manda el juicio experto." % w["k_prior"],
          "", "## Moderadora: régimen de BTC al momento del evento", "",
          "| Celda | n | Multiplicador | Prior |", "|---|---|---|---|"]
    for k_, v in w["moderators"]["btc_regime"].items():
        L.append(f"| {k_} | {v['n']} | {v['mult']} | {v['prior']} |")
    big = sorted(rows, key=lambda r: -abs(r["z3"]))[:20]
    L += ["", "## Los 20 eventos que más movieron (z a 3 días)", "", "| Fecha | Evento | Categoría | Postura | z1 | z3 | z7 | z30 |",
          "|---|---|---|---|---|---|---|---|"]
    for r in big:
        L.append(f"| {r['date']} | {r['title_es'][:90]} | {label(r['category'])} | {r['stance']} | {r.get('z1')} | "
                 f"{r['z3']} | {r.get('z7')} | {r.get('z30')} |")
    L += ["", "**Cuidado:** asociación ≠ causalidad. Varios eventos caen en días con otros choques; la muestra por "
          "categoría es chica; y la fecha es la del anuncio (el mercado pudo anticiparlo). Por eso los pesos se encogen "
          "al prior y la señal solo modula riesgo y tamaño: no abre posiciones por sí sola."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="descarga precios (Coin Metrics + Binance)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    info = fetch_all() if a.fetch else {}
    w, rows = run()
    w["price_source"] = info.get("btc", {}).get("source") or "cache"
    write_json("weights.json", w)
    write_json("event_study_events.json", rows)
    (ctx_dir() / "EVENTOS.md").write_text(render_md(w, rows), encoding="utf-8")
    print(json.dumps({"events": w["n_events"], "baseline": w["baseline"],
                      "fuertes": [c for c, v in w["categories"].items() if v["evidence_abs"] == "fuerte"]}))


if __name__ == "__main__":
    sys.exit(main())
