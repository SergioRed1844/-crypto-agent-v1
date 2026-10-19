"""Orquestación del Radar: cargar datos → ajustar EB → buscar disparos → decidir → avisar → dar seguimiento.

Se corre cada hora (GitHub Actions + heartbeat). Idempotente: un disparo ya avisado no se repite; el resumen diario
sale una vez por día local. Nunca opera ni toca llaves de exchanges.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from . import config as C
from . import data as D
from . import notify as N
from . import report as R
from .model import WARMUP, Model, decide
from .setups import SETUPS, build_panel, risk_flags, triggers

log = logging.getLogger("radar")


def _state_path() -> str:
    return os.path.join(C.OUT_DIR, "state.json")


# ── carga ───────────────────────────────────────────────────────────────────────────────────────────────
def load(offline: bool = False):
    client = None if offline else D._client()
    try:
        syms = C.universe()
        need = sorted(set(syms) | set(C.BENCH.values()) | set(C.AUX))
        series = {}
        for s in need:
            if offline:
                series[s], _ = D.load_cache(s)
            else:
                series[s] = D.price(s, client)
        if offline:
            fg = _json(os.path.join(C.CACHE_DIR, "fear_greed.json"))
            fears = {lang: D.fears_index(lang, offline=True) for lang in ("en", "es")}
            attn = {k: D.wiki_views(lang, art, offline=True) for k, (lang, art) in C.WIKI_ATTENTION.items()}
        else:
            fg = D.fear_greed(client)
            fears = {lang: D.fears_index(lang, client) for lang in ("en", "es")}
            attn = {k: D.wiki_views(lang, art, client) for k, (lang, art) in C.WIKI_ATTENTION.items()}
        events = D.history_events()
        if not offline:
            ev_remote = _remote_events(client)
            if ev_remote:
                events = ev_remote
        ctx = {"state": "DESCONOCIDO"} if offline else D.context_signal(client)
    finally:
        if client is not None:
            client.close()
    # eventos curados recientes del contexto v4.2 (no noticias sueltas: misma regla que la historia)
    for e in ctx.get("recent", []) or []:
        if e.get("fuente") not in (None, "noticia") and e.get("category") and e.get("date"):
            events.append({"date": e["date"], "category": e["category"], "status": "happened"})
    base_aux = {"vix": _c(series.get("^VIX")), "mxn": _c(series.get("MXN=X")), "fg": fg,
                "fears_en": fears["en"], "fears_es": fears["es"], "events": events}
    panels, skipped = [], []
    for s in syms:
        ser = series.get(s)
        if ser is None or len(ser) < WARMUP + 120:
            skipped.append(s)
            continue
        cls = C.asset_class(s)
        bench = _c(series.get(C.BENCH[cls]))
        aux = dict(base_aux)
        if cls == "crypto":
            aux["attn"] = attn.get(s) or attn.get("_CRYPTO") or {}
        panels.append(build_panel(_c(ser), cls, bench, aux))
    return panels, series, ctx, skipped


def _c(s):
    return s.complete() if s is not None else None


def _json(p):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return {}


def _remote_events(client) -> list[dict]:
    url = C.CONTEXT_RAW.replace("context_signal.json", "sources/history_events.json")
    try:
        r = client.get(url, timeout=20)
        return r.json() if r.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return []


# ── estado ──────────────────────────────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    st = _json(_state_path())
    st.setdefault("alerts", [])
    st.setdefault("seen", {})
    st.setdefault("runs", [])
    return st


def save_state(st: dict) -> None:
    os.makedirs(C.OUT_DIR, exist_ok=True)
    st["alerts"] = st["alerts"][-500:]
    st["runs"] = st["runs"][-60:]
    if len(st["seen"]) > 3000:
        st["seen"] = dict(sorted(st["seen"].items(), key=lambda kv: kv[1].get("utc", ""))[-2000:])
    tmp = _state_path() + ".tmp"
    json.dump(st, open(tmp, "w"), ensure_ascii=False, indent=1, default=_np)
    os.replace(tmp, _state_path())


def _np(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))


# ── candidatos ──────────────────────────────────────────────────────────────────────────────────────────
def families(p, i, sid) -> list[str]:
    f = p.f
    fam = ["precio"]
    fear = False
    if p.cls == "crypto":
        fear = (np.isfinite(f["fg"][i]) and f["fg"][i] <= 35) or (np.isfinite(f["fg_chg3"][i]) and f["fg_chg3"][i] <= -15)
    else:
        fear = (np.isfinite(f["vix"][i]) and (f["vix"][i] >= 25 or
                                              (np.isfinite(f["vix_m20"][i]) and f["vix"][i] >= 1.25 * f["vix_m20"][i])))
    if fear:
        fam.append("miedo de mercado")
    att = (np.isfinite(f["fears_z"][i]) and f["fears_z"][i] >= 1.5) or (np.isfinite(f["attn_z"][i]) and f["attn_z"][i] >= 1.0)
    if att:
        fam.append("atención de hogares")
    return fam


def climate(panels, ctx) -> str:
    by = {p.sym: p for p in panels}
    parts = []
    btc, spy = by.get("BTC"), by.get("SPY")
    if btc is not None:
        i = len(btc.dates) - 1
        parts.append(f"BTC {btc.close[i]:,.0f} (caída desde máximo de 1 año {R.pct(btc.f['dd1y'][i], 0)}; "
                     f"Fear&Greed {int(btc.f['fg'][i]) if np.isfinite(btc.f['fg'][i]) else '—'})")
    if spy is not None:
        i = len(spy.dates) - 1
        vix = f"{spy.f['vix'][i]:.1f}" if np.isfinite(spy.f["vix"][i]) else "—"
        parts.append(f"S&P (SPY) {R.pct(spy.f['dd1y'][i], 1)} vs máximo de 1 año; VIX {vix}")
        if np.isfinite(spy.f["fears_z"][i]):
            parts.append(f"miedo de hogares (Wikipedia, EUA) z={spy.f['fears_z'][i]:+.1f}")
    mx = next((p for p in panels if p.cls == "bmv"), None)
    if mx is not None:
        i = len(mx.dates) - 1
        parts.append(f"peso 5 días {R.pct(mx.f['mxn_ret5'][i], 1, True)} (USD/MXN); IPC vs máximo 1 año "
                     f"{R.pct(mx.f['b_dd1y'][i], 1)}")
    parts.append(f"contexto v4.2: **{ctx.get('state', '—')}**" + (f" ({'; '.join(ctx.get('reasons', [])[:2])})"
                                                                   if ctx.get("reasons") else ""))
    return " · ".join(parts)


def ctx_text(ctx, cls) -> tuple[str, bool, list[str]]:
    """Texto de contexto, si limita la confianza y vetos duros (solo daño fundamental/alerta on-chain crítica)."""
    st = ctx.get("state", "DESCONOCIDO")
    reasons = "; ".join(ctx.get("reasons", [])[:3])
    txt = f"bot v4.2 en **{st}**" + (f" — {reasons}" if reasons else "")
    cap = cls == "crypto" and st in ("RISK_OFF", "BLACKOUT")
    hard = []
    if cls == "crypto" and (ctx.get("exit_all") or any((a or {}).get("severity") == "critica"
                                                         for a in ctx.get("alerts", []) or [])):
        hard.append("alerta on-chain crítica en v4.2 (monedas era Satoshi en movimiento)")
    rec = [e for e in (ctx.get("recent") or [])[:4]]
    if rec:
        txt += " · noticias recientes: " + " | ".join(f"{e.get('date')}: {e.get('title_es', '')[:80]}" for e in rec)
    return txt, cap, hard


def scan_candidates(model: Model, panels, ctx, today: date | None = None) -> list[dict]:
    today = today or datetime.now(timezone.utc).date()
    out = []
    for p in panels:
        n = len(p.dates)
        if n == 0:
            continue
        age = (today - date.fromisoformat(p.dates[-1])).days
        if age > C.STALE_DAYS[p.cls]:
            continue
        for sid, s in SETUPS.items():
            if p.cls not in s.classes:
                continue
            tr = triggers(sid, p)
            for i in (n - 1, n - 2):
                if i < WARMUP or not tr[i]:
                    continue
                out.append(_candidate(model, p, i, sid, ctx))
    return [c for c in out if c]


def _candidate(model, p, i, sid, ctx):
    preds = {h: model.predict(sid, p.cls, h, p.sym, i) for h in C.HORIZONS}
    preds = {h: v for h, v in preds.items() if v}
    if not preds:
        return None
    flags = risk_flags(p, i)
    ctx_txt, cap, hard = ctx_text(ctx, p.cls)
    best, best_key = None, None
    for h, pr in preds.items():
        level, why = decide(pr, flags, ctx.get("state"), p.cls)
        if hard:
            level, why = "VETADA", hard
        rank = {"ALERTA": 2, "VIGILANCIA": 1, "VETADA": 0}[level]
        key = (rank, pr["lift"], pr["ret"])
        if best_key is None or key > best_key:
            best, best_key = (h, level, why), key
    h, level, why = best
    pr = preds[h]
    if cap:
        why = why + [f"contexto v4.2 en {ctx.get('state')}: confianza máxima Media (decides tú)"]
    lag = model.best_lag(sid, p.cls, h)
    g = model.groups.get((sid, p.cls, h), {})
    r1 = p.f["r1"][i]
    sig = p.f["sig60"][i]
    lectura = {
        "PANICO_SIN_DANO": f"caída de {R.pct(np.expm1(r1), 1)} en el día ({r1 / sig:+.1f}σ) junto con el mercado y "
                           "miedo alto, sin evento de daño fundamental registrado",
        "CAPITULACION": f"{R.pct(p.f['dd1y'][i], 0)} desde el máximo de 1 año, RSI {p.f['rsi14'][i]:.0f} y miedo "
                        "extremo",
        "CHOQUE_POLITICO": f"caída de {R.pct(np.expm1(r1), 1)} con el mercado tras un evento político/comercial",
        "MIEDO_HOGARES": f"miedo de hogares (Wikipedia) z={p.f['fears_z'][i]:+.1f} con el mercado "
                         f"{R.pct(p.f['b_ret5'][i], 1, True)} en la semana",
        "CHOQUE_PESO": f"peso {R.pct(p.f['mxn_ret5'][i], 1, True)} en 5 días y la emisora "
                       f"{R.pct(p.f['ret5'][i], 1, True)}",
        "ATENCION_MOMENTUM": f"retorno semanal z={p.f['r7z'][i]:+.1f} con atención z={p.f['attn_z'][i]:+.1f}",
        "PULLBACK_TENDENCIA": f"retroceso a la media de 50 días ({R.pct(p.close[i] / p.f['max20'][i] - 1, 1)} desde "
                              "el máximo de 20) con tendencia de 200 días arriba",
    }[sid]
    return {"sym": p.sym, "cls": p.cls, "sid": sid, "date": p.dates[i], "i": i, "price": float(p.close[i]),
            "level": level, "why": why, "pred": pr, "preds": preds, "flags": flags, "lag_txt": lag["texto"],
            "dow_txt": model.best_dow(p.cls)["texto"], "ctx_txt": ctx_txt, "ctx_cap": cap,
            "families": families(p, i, sid), "freq": (g.get("freq") or {}).get(p.sym), "lectura": lectura,
            "r1": float(np.expm1(r1)) if np.isfinite(r1) else None,
            "b_r1": float(np.expm1(p.f["b_r1"][i])) if np.isfinite(p.f["b_r1"][i]) else None}


# ── seguimiento de alertas pasadas ──────────────────────────────────────────────────────────────────────
def track(st: dict, series: dict) -> str:
    from .model import outcome
    done, pend = [], 0
    for a in st["alerts"]:
        if a.get("outcome") is not None:
            done.append(a)
            continue
        s = series.get(a["sym"])
        if s is None:
            pend += 1
            continue
        s = s.complete()
        if a["date"] not in s.dates:
            pend += 1
            continue
        i = s.dates.index(a["date"])
        from .setups import Panel
        p = Panel(s.sym, a["cls"], s.dates, s.open, s.high, s.low, s.close, {})
        o = outcome(p, i, 1, a["h"])
        if o is None:
            pend += 1
            continue
        a["outcome"] = {"y": int(o[0]), "net": round(o[1], 4), "mae": round(o[2], 4)}
        done.append(a)
    if not done:
        return f"Aún no cierra ninguna alerta ({pend} en curso)."
    hit = np.mean([a["outcome"]["y"] for a in done])
    pred = np.mean([a["p"] for a in done])
    net = np.mean([a["outcome"]["net"] for a in done])
    return (f"{len(done)} alertas cerradas: acierto real {R.pct(hit, 0)} vs predicho {R.pct(pred, 0)} · neto medio "
            f"{R.pct(net, 1, True)} · {pend} en curso. (Con pocas alertas, la diferencia es ruido: se juzga el "
            "proceso, no el resultado.)")


# ── corrida ─────────────────────────────────────────────────────────────────────────────────────────────
def run(offline: bool = False, force_digest: bool = False, dry: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    st = load_state()
    panels, series, ctx, skipped = load(offline)
    model = Model().fit(panels)
    cands = scan_candidates(model, panels, ctx)
    # tope semanal y deduplicación ANTES de gastar la verificación de noticias
    from .narrative import check_cause
    import time as _time
    week_ago = (now - timedelta(days=7)).isoformat()
    sent_week = [a for a in st["alerts"] if a.get("sent_utc", "") >= week_ago]
    room = max(0, C.ALERT["max_week"] - len(sent_week))
    new_alerts = []
    cooldown_from = (now.date() - timedelta(days=C.ALERT["cooldown_days"])).isoformat()
    budget_end = _time.monotonic() + float(os.getenv("RADAR_NEWS_BUDGET_S", "180"))
    for c in sorted([c for c in cands if c["level"] == "ALERTA"], key=lambda c: (-c["pred"]["lift"], -c["pred"]["ret"])):
        key = f"{c['sym']}|{c['sid']}|{c['date']}"
        recent_same = any(a["sym"] == c["sym"] and a["sid"] == c["sid"] and a["date"] >= cooldown_from
                          for a in st["alerts"])
        if key in st["seen"] or recent_same:
            continue
        if room <= 0:
            c["level"] = "VIGILANCIA"
            c["why"] = c["why"] + [f"tope de {C.ALERT['max_week']} alertas por semana alcanzado"]
            continue
        # calendario de resultados (Finnhub, opcional): reportar en ≤ 3 días baja a VIGILANCIA
        if not (dry or offline):
            from .earnings import blocks, next_earnings
            ern = next_earnings(c["sym"])
            if ern:
                c["earnings"] = ern
                why_e = blocks(ern)
                if why_e:
                    c["level"] = "VIGILANCIA"
                    c["why"] = c["why"] + [why_e]
                    continue
        # Gemini con búsqueda SOLO para lo que está a punto de enviarse; solo puede BAJAR el nivel (nunca suma
        # familias ni confianza: un texto de internet no puede subir una señal)
        if not (dry or offline) and _time.monotonic() < budget_end:
            try:
                nws = check_cause(c["sym"], c["date"], c.get("r1") or 0.0, c.get("b_r1"))
            except Exception as e:  # noqa: BLE001
                nws = {"causa": "desconocida", "resumen": f"verificación de noticias falló ({type(e).__name__})",
                       "fuentes": []}
            if isinstance(nws, dict):
                c["news"] = nws
                if nws.get("causa") == "fundamental":
                    c["level"] = "VIGILANCIA"
                    c["why"] = c["why"] + ["la búsqueda de noticias sugiere causa fundamental propia del activo"]
                    continue
        room -= 1
        new_alerts.append(c)
        md = R.ficha_md(c)
        title = f"🟢 Radar EB: {c['sym']} — {SETUPS[c['sid']].nombre} (P {c['pred']['p']:.0%}, {c['pred']['h']} d)"
        sent = {} if dry else N.send_alert(title, md, R.short_txt(c))
        st["alerts"].append({"sym": c["sym"], "cls": c["cls"], "sid": c["sid"], "date": c["date"], "h": c["pred"]["h"],
                             "p": round(c["pred"]["p"], 4), "q10": round(c["pred"]["q10"], 4),
                             "base": round(c["pred"]["base"], 4), "ret": round(c["pred"]["ret"], 4),
                             "price": c["price"], "sent_utc": now.isoformat(timespec="seconds"), "sent": sent,
                             "outcome": None})
        st["seen"][key] = {"level": "ALERTA", "utc": now.isoformat(timespec="seconds")}
        _write_ficha(c, md)
        save_state(st)        # guardar tras CADA envío: si algo truena después, no se repite la alerta
    for c in cands:
        st["seen"].setdefault(f"{c['sym']}|{c['sid']}|{c['date']}",
                              {"level": c["level"], "utc": now.isoformat(timespec="seconds")})
    tracking = track(st, series)
    st["runs"].append(now.isoformat(timespec="seconds"))
    st["last_scan_utc"] = now.isoformat(timespec="seconds")
    st["health"] = D.HEALTH
    st["skipped"] = skipped
    st["last_candidates"] = [_slim(c) for c in cands]
    # resumen diario
    local = now.astimezone(ZoneInfo(C.TZ_LOCAL))
    digest_sent = None
    if force_digest or (local.hour >= C.DIGEST_HOUR_LOCAL and st.get("last_digest_date") != local.date().isoformat()):
        day_ago = (now - timedelta(hours=24)).isoformat()
        recent = [v for k, v in st["seen"].items() if v.get("utc", "") >= day_ago]
        dg = {"local_date": local.date().isoformat(), "runs_24h": sum(1 for r in st["runs"] if r >= day_ago),
              "last_scan_utc": st["last_scan_utc"], "n_assets": len(panels), "n_specs": model.n_specs,
              "candidates": cands, "climate": climate(panels, ctx), "tracking": tracking, "health": D.HEALTH,
              "dow": {cls: model.best_dow(cls)["texto"] for cls in ("crypto", "us", "bmv") if cls in model.dow}}
        md = R.digest_md(dg)
        title = f"📡 Radar EB {local.date().isoformat()}: {len(new_alerts)} alertas, {len(recent)} disparos en 24 h"
        digest_sent = {} if dry else N.send_digest(title, md, st, local.strftime("%Y-%m"))
        st["last_digest_date"] = local.date().isoformat()
        save_state(st)
        os.makedirs(C.OUT_DIR, exist_ok=True)
        open(os.path.join(C.OUT_DIR, "ULTIMO_RESUMEN.md"), "w").write(md)
    st["notify_log"] = N.LOG[-20:]
    save_state(st)
    _write_dashboard(st, model, panels, ctx, tracking)
    json.dump(model.summary(), open(os.path.join(C.OUT_DIR, "model.json"), "w"), ensure_ascii=False, indent=1,
              default=_np)
    return {"candidates": len(cands), "alerts": len(new_alerts), "digest": digest_sent, "skipped": skipped}


def _slim(c):
    return {k: c[k] for k in ("sym", "cls", "sid", "date", "level", "why")} | {
        "p": round(c["pred"]["p"], 3), "base": round(c["pred"]["base"], 3), "ret": round(c["pred"]["ret"], 4),
        "h": c["pred"]["h"]}


def _write_ficha(c, md):
    d = os.path.join(C.OUT_DIR, "fichas")
    os.makedirs(d, exist_ok=True)
    fn = f"{c['date']}_{c['sym'].replace('^', '').replace('.', '_')}_{c['sid']}.md"
    open(os.path.join(d, fn), "w").write(md + "\n")


def _write_dashboard(st, model, panels, ctx, tracking):
    L = ["# 📡 Radar EB — tablero", "",
         f"Última corrida: **{st.get('last_scan_utc')} UTC** · {len(panels)} activos · contexto v4.2: "
         f"**{ctx.get('state', '—')}** · último resumen: {st.get('last_digest_date', '—')}", "",
         "Agente 2: **solo alertas**, no opera. Modelo de Bayes empírico sobre setups del corpus de "
         "microcomportamientos. Detalle del método: `docs/RADAR_EB.md` · validación: `data/radar/BACKTEST.md`.", "",
         "## Candidatos de la última corrida", ""]
    if st.get("last_candidates"):
        L += ["| Nivel | Activo | Setup | Disparo | H | P | Día cualquiera | Neto esp. |", "|---|---|---|---|---|---|---|---|"]
        for c in st["last_candidates"]:
            L.append(f"| {c['level']} | {c['sym']} | {SETUPS[c['sid']].nombre} | {c['date']} | {c['h']} d | "
                     f"{R.pct(c['p'], 0)} | {R.pct(c['base'], 0)} | {R.pct(c['ret'], 1, True)} |")
    else:
        L.append("Ninguno.")
    L += ["", "## Alertas enviadas (últimas 15)", ""]
    if st["alerts"]:
        L += ["| Enviada | Activo | Setup | H | P | Resultado |", "|---|---|---|---|---|---|"]
        for a in st["alerts"][-15:][::-1]:
            o = a.get("outcome")
            res = "en curso" if not o else f"{'ganó' if o['y'] else 'no'} ({R.pct(o['net'], 1, True)})"
            L.append(f"| {a['sent_utc'][:16]} | {a['sym']} | {SETUPS[a['sid']].nombre} | {a['h']} d | "
                     f"{R.pct(a['p'], 0)} | {res} |")
    else:
        L.append("Todavía ninguna.")
    L += ["", f"**Seguimiento:** {tracking}", "", "## Setups (modelo con toda la historia)", "",
          "| Setup | Clase | H | Episodios | Crudo | Día cualquiera | Encogido | B (hacia 'sin ventaja') | Neto exceso |",
          "|---|---|---|---|---|---|---|---|---|"]
    from scipy.special import expit, logit
    for (sid, cls, h), g in sorted(model.groups.items()):
        shr = float(expit(logit(min(max(g["b_bar"], 1e-4), 1 - 1e-4)) + g["delta"]))
        L.append(f"| {SETUPS[sid].nombre} | {cls} | {h} d | {g['n_eff']} | {R.pct(g['raw_p'], 0)} | "
                 f"{R.pct(g['b_bar'], 0)} | {R.pct(shr, 0)} | {g['B'] * 100:.0f}% | {R.pct(g['e'], 1, True)} |")
    L += ["", "## Salud de fuentes", "", "| Serie | OK | Último | Nota |", "|---|---|---|---|"]
    for k, v in sorted((st.get("health") or {}).items()):
        L.append(f"| {k} | {'sí' if v.get('ok') else 'NO'} | {v.get('last') or '—'} | {v.get('nota', '')} |")
    L += ["", f"_{R.DISCLAIMER}_"]
    open(os.path.join(C.OUT_DIR, "README.md"), "w").write("\n".join(L) + "\n")


def backtest(offline: bool = False) -> dict:
    from .backtest import evaluate, render_md
    panels, series, ctx, skipped = load(offline)
    ev = evaluate(panels)
    os.makedirs(C.OUT_DIR, exist_ok=True)
    md = render_md(ev, health=D.HEALTH)
    if skipped:
        md += "\n\nActivos sin historia suficiente o sin datos: " + ", ".join(skipped) + "\n"
    open(os.path.join(C.OUT_DIR, "BACKTEST.md"), "w").write(md)
    slim = {k: v for k, v in ev.items() if k not in ("alerts",)}
    json.dump(slim, open(os.path.join(C.OUT_DIR, "backtest.json"), "w"), ensure_ascii=False, indent=1, default=_np)
    return ev
