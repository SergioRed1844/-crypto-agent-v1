"""Orquestador del modelo de contexto (lo corren GitHub Actions; también se puede correr a mano).

  python -m app.context.pipeline refresh   # cada 15 días: noticias 15 d, auditoría de huecos, macro, estudio de
                                           # eventos, calendario 3 años, señal, Sheets
  python -m app.context.pipeline watch     # cada hora: vigía on-chain + noticias urgentes + señal
  python -m app.context.pipeline signal    # solo recalcula la señal con lo que hay
  python -m app.context.pipeline calendar  # solo regenera calendar.json y CALENDARIO.md

Jerarquía de agentes (ver docs/MODELO_CONTEXTO.md):
  Director (este archivo) → recolectores [calendario, noticias, on-chain, mercado] → analistas [clasificador,
  estudio de eventos] → auditor [cobertura con búsqueda web] → juez de contexto (engine.compute) → modelo de trading
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timedelta

from . import ctx_dir, iso, read_json, utcnow, write_json
from . import classifier, engine, event_calendar, macro, news, onchain, sheets
from .schema import normalize

log = logging.getLogger("pipeline")
KEEP_NEWS_DAYS = 120


def _age_h(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        return (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 3600
    except ValueError:
        return None


def recent_events(now: datetime, days: int = 60) -> list[dict]:
    lim = iso(now - timedelta(days=days))
    out = []
    for e in (read_json("sources/history_events.json", []) or []) + ((read_json("news_events.json", {}) or {}).get("events", [])):
        try:
            e = normalize(e, "happened")
        except ValueError:
            continue
        if lim <= e["utc"] <= iso(now + timedelta(hours=1)):
            out.append(e)
    return out


def input_ages(mac: dict, ne: dict, ocs: dict, now: datetime) -> float | None:
    """Edad (h) del insumo MÁS viejo: macro, noticias y vigía on-chain. Sin vigía reciente no hay contexto confiable."""
    ages = [a for a in (_age_h(mac.get("generated_utc"), now), _age_h(ne.get("updated_utc"), now),
                        _age_h(ocs.get("updated_utc"), now)) if a is not None]
    return max(ages) if ages else None


def build_signal(now: datetime | None = None, market: dict | None = None) -> dict:
    now = now or utcnow()
    cal = event_calendar.load(now)
    alerts = (read_json("alerts_onchain.json", {}) or {}).get("alerts", [])
    mac = read_json("macro.json", {}) or {}
    ne = read_json("news_events.json", {}) or {}
    ocs = read_json("onchain_state.json", {}) or {}
    return engine.compute(now, cal, recent_events(now), alerts, mac, market, inputs_age_h=input_ages(mac, ne, ocs, now))


def _step(rep: dict, name: str, fn, *a, **kw):
    """Cada recolector falla solo: el resto de la corrida sigue y el error queda en el reporte."""
    try:
        return fn(*a, **kw)
    except Exception as e:
        log.warning(f"{name}: {type(e).__name__}: {e}")
        rep.setdefault("errores", {})[name] = f"{type(e).__name__}: {e}"[:200]
        return None


def _macro(rep: dict, now: datetime):
    snap = macro.snapshot(event_calendar.load(now))
    if snap.get("n_ok"):
        write_json("macro.json", snap)
    rep["macro_fuentes_ok"] = snap.get("n_ok", 0)


def _merge_news_events(new: list[dict], now: datetime) -> int:
    cur = read_json("news_events.json", {}) or {}
    ev = {e["id"]: e for e in cur.get("events", [])}
    n0 = len(ev)
    for e in new:
        if e.get("status") == "happened":
            ev.setdefault(e["id"], e)
    lim = iso(now - timedelta(days=KEEP_NEWS_DAYS))
    keep = sorted((e for e in ev.values() if e["utc"] >= lim), key=lambda x: x["utc"])
    write_json("news_events.json", {"updated_utc": iso(now), "events": keep})
    return len(keep) - n0


def _merge_proposals(props: list[dict], now: datetime) -> int:
    cur = {e["id"]: e for e in (read_json("sources/calendar_proposed.json", []) or [])}
    n0 = len(cur)
    for p in props:
        if p.get("status") == "proposed":
            cur.setdefault(p["id"], p)
    keep = [e for e in cur.values() if e["date"] >= now.date().isoformat()]
    write_json("sources/calendar_proposed.json", sorted(keep, key=lambda e: e["date"])[:400])
    return len(keep) - n0


def _write_views(sig: dict, report: dict, now: datetime):
    write_json("context_signal.json", sig)
    rep = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    md = ["# Contexto actual — CryptoAgent v4.2", "",
          f"Actualizado {sig['generated_utc']} UTC. Se recalcula cada hora; el calendario y los pesos cada 15 días.", "",
          engine.explain_md(sig), "",
          "Calendario completo: [CALENDARIO.md](CALENDARIO.md) · Pesos: [EVENTOS.md](EVENTOS.md) · "
          "Datos: `context_signal.json`, `calendar.json`, `weights.json`, `alerts_onchain.json`", "",
          "<details><summary>Reporte de la última corrida</summary>", "", "```json", rep[:6000], "```", "</details>", ""]
    (ctx_dir() / "CONTEXTO.md").write_text("\n".join(md), encoding="utf-8")


def _notify(prev: dict | None, sig: dict, new_alerts: list[dict]):
    """Escribe notify.json si hay algo que avisar: el workflow lo convierte en un issue de GitHub (te llega correo)."""
    msgs = [f"Alerta on-chain {a['severity'].upper()}: {a.get('detail_es', '')} {a.get('url', '')}"
            for a in new_alerts if a.get("severity") in ("critica", "alta")]
    if prev and prev.get("state") != sig["state"] and sig["state"] in ("RISK_OFF", "BLACKOUT"):
        msgs.append(f"Contexto cambió a {sig['state']}: {sig['reasons'][0] if sig['reasons'] else ''}")
    p = ctx_dir() / "notify.json"
    if msgs:
        write_json("notify.json", {"title": f"[CryptoAgent contexto] {sig['state']} — {sig['generated_utc']}",
                                   "body": "\n\n".join(msgs) + "\n\nModo PAPEL: ninguna orden real.", "messages": msgs})
    elif p.exists():
        p.unlink()


def run_onchain(max_blocks: int = 8, max_calls: int = onchain.MAX_CALLS) -> dict:
    rep = {}
    try:
        with onchain.EsploraClient(max_calls=max_calls) as c:
            new = onchain.scan(c, ctx_dir() / "onchain_state.json", ctx_dir() / "alerts_onchain.json",
                               {"max_blocks": max_blocks}, rep)
        rep["new_alerts"] = new
    except Exception as e:
        rep = {"error": f"{type(e).__name__}: {e}"[:200], "new_alerts": []}
    return rep


def _watch_news(rep: dict, now: datetime):
    items = []
    cp = news.cryptopanic("important", pages=1)
    items += cp["items"]
    for tag in ("riesgo_cripto", "ballenas", "fed"):
        items += news.gdelt(news.GDELT_QUERIES[tag], "6h", 40)
    ev, method = classifier.classify(news.dedup(items))
    urgent = [e for e in ev if e["prior_tier"] >= 3]
    rep["noticias"] = {"cryptopanic": cp["status"], "titulares": len(items), "eventos": len(ev), "urgentes": len(urgent),
                       "metodo": method, "agregados": _merge_news_events(urgent, now)}


def watch() -> dict:
    now = utcnow()
    prev = read_json("context_signal.json")
    rep = {"modo": "watch", "inicio": iso(now)}
    oc = run_onchain()
    rep["onchain"] = {k: v for k, v in oc.items() if k != "new_alerts"} | {"nuevas": len(oc.get("new_alerts", []))}
    _step(rep, "noticias", _watch_news, rep, now)
    _step(rep, "macro", _macro, rep, now)
    sig = build_signal(now)
    _write_views(sig, rep, now)
    _notify(prev, sig, oc.get("new_alerts", []))
    rep["estado"] = sig["state"]
    return rep


def _refresh_news(rep: dict, now: datetime):
    nw = news.fetch_window(15)
    ev, method = classifier.classify(nw["items"])
    rep["noticias"] = {"cryptopanic": nw["cryptopanic"], "n_cryptopanic": nw["n_cryptopanic"], "n_gdelt": nw["n_gdelt"],
                       "titulares": len(nw["items"]), "eventos": len(ev), "metodo": method,
                       "agregados": _merge_news_events([e for e in ev if e["prior_tier"] >= 2], now),
                       "propuestas_de_noticias": _merge_proposals([e for e in ev if e["status"] == "proposed"], now)}


def _audit(rep: dict, now: datetime):
    au = classifier.coverage_audit(event_calendar.build(now), now)
    rep["auditoria"] = {"status": au["status"], "agregadas": _merge_proposals(au["proposals"], now)}


def _study(rep: dict):
    from . import event_study as es
    info = es.fetch_all()
    w, rows = es.run()
    w["price_source"] = info.get("btc", {}).get("source")
    write_json("weights.json", w)
    write_json("event_study_events.json", rows)
    (ctx_dir() / "EVENTOS.md").write_text(es.render_md(w, rows), encoding="utf-8")
    rep["estudio_eventos"] = {"eventos": w["n_events"], "base_azar": w["baseline"]}


def refresh(event_study: bool = True) -> dict:
    now = utcnow()
    prev = read_json("context_signal.json")
    rep = {"modo": "refresh", "inicio": iso(now)}
    _step(rep, "noticias", _refresh_news, rep, now)                       # 1) noticias 15 días
    rep["consenso_semana"] = _step(rep, "consenso", news.consensus_this_week) or []
    _step(rep, "auditoria", _audit, rep, now)                             # 2) huecos con búsqueda web
    rep["calendario"] = _step(rep, "calendario", event_calendar.refresh_files, now)
    _step(rep, "macro", _macro, rep, now)                                 # 3) mercado
    if event_study:
        _step(rep, "estudio_eventos", _study, rep)                        # 4) pesos
    oc = run_onchain()                                                    # 5) on-chain + señal + vistas + Sheets
    rep["onchain"] = {k: v for k, v in oc.items() if k != "new_alerts"} | {"nuevas": len(oc.get("new_alerts", []))}
    sig = build_signal(now)
    rep["sheets"] = _step(rep, "sheets", sheets.mirror, event_calendar.load(now), recent_events(now, 30),
                          read_json("weights.json"), (read_json("alerts_onchain.json", {}) or {}).get("alerts", []), sig)
    _write_views(sig, rep, now)
    _notify(prev, sig, oc.get("new_alerts", []))
    write_json("refresh_report.json", rep)
    rep["estado"] = sig["state"]
    return rep


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["refresh", "watch", "signal", "calendar"])
    ap.add_argument("--no-study", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "refresh":
        out = refresh(not a.no_study)
    elif a.cmd == "watch":
        out = watch()
    elif a.cmd == "calendar":
        out = event_calendar.refresh_files()
    else:
        sig = build_signal()
        _write_views(sig, {"modo": "signal"}, utcnow())
        out = {k: sig[k] for k in ("state", "bias", "event_risk", "size_mult", "veto_entries", "exit_all")}
    print(json.dumps(out, ensure_ascii=False, default=str)[:4000])


if __name__ == "__main__":
    sys.exit(main())
