"""Señal de contexto: lo que el modelo de trading recibe del modelo contextual.

Contrato (context_signal.json):
  state        RISK_ON | NEUTRAL | CAUTION | BLACKOUT | RISK_OFF
  veto_entries True → ninguna compra nueva (BLACKOUT, RISK_OFF)
  exit_all     True → salir a USDT ya (solo alerta on-chain CRÍTICA: era Satoshi). Lo ejecuta el líder, una vez.
  size_mult    0..1 multiplica el riesgo por trade
  bias         -1..1 sesgo direccional por eventos recientes ponderados (y mercado)
  event_risk   0..1 probabilidad ponderada de un choque programado en las próximas 72 h
  extra_confluence  puntos extra de confluencia técnica que exige el comité (CAUTION)
  vote/confidence   informativos: en el comité el contexto solo puede vetar o restar (nunca suma un voto a favor)

Fórmulas (pesos de weights.json si existe; si no, de priors.json):
  magnitud_e  = ½·w_abs[categoría] + ½·exceso_prior[tier_e]        (exceso de |z3| sobre un día cualquiera)
  dirección_e = ½·w_dir[categoría] + ½·dir_prior[tier_e]
  riesgo_e    = min(1, magnitud_e) · P(ocurra | status) · cercanía   (cercanía = 1 dentro de la ventana, e^(−h/24) antes)
  event_risk  = 1 − Π(1 − riesgo_e)                                  (× 1.3 con volatilidad EXTREMA)
  aporte_e    = signo(postura)·dirección_e·e^(−edad/decaimiento)·confianza·moderadora(régimen, F&G)
  bias        = tanh(Σ aporte / escala) + ajustes de mercado (VIX, dólar, Nasdaq, stablecoins)
"""
import math
from datetime import datetime, timedelta

from . import iso, read_json, utcnow
from .schema import P_OCCUR, day_window, label, sign

STATE_SIZE = {"RISK_ON": 1.0, "NEUTRAL": 1.0, "CAUTION": 0.5, "BLACKOUT": 0.0, "RISK_OFF": 0.0}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _weights(priors: dict, weights: dict | None) -> dict:
    cats = (weights or {}).get("categories") or {}
    out = {}
    for c, cfg in priors.get("categories", {}).items():
        t = str(cfg.get("default_tier", 2))
        w = cats.get(c) or {}
        out[c] = {"w_abs": w.get("w_abs", priors["tier_excess_abs_z"][t]),
                  "w_dir": w.get("w_dir", priors["tier_dir_z"][t]), "evidence": w.get("evidence_abs", "prior"), **cfg}
    return out


def magnitude(e: dict, W: dict, priors: dict) -> float:
    c = W.get(e["category"], {})
    return 0.5 * c.get("w_abs", 0.1) + 0.5 * priors["tier_excess_abs_z"][str(e["prior_tier"])]


def direction(e: dict, W: dict, priors: dict) -> float:
    c = W.get(e["category"], {})
    return 0.5 * c.get("w_dir", 0.08) + 0.5 * priors["tier_dir_z"][str(e["prior_tier"])]


def _moderator(e: dict, market: dict, priors: dict, weights: dict | None = None) -> float:
    st = e.get("crypto_stance")
    if st not in ("pro", "anti"):
        return 1.0
    m = 1.0
    reg = market.get("btc_regime")
    if reg:
        est = ((weights or {}).get("moderators") or {}).get("btc_regime", {}).get(f"{reg}_{st}")
        m *= est["mult"] if est else priors["moderators"]["btc_regime"].get(reg, {}).get(st, 1.0)
    fg = market.get("fear_greed")
    if fg is not None:
        if fg >= 80:
            m *= priors["moderators"]["fear_greed"]["greed_80"][st]
        elif fg <= 20:
            m *= priors["moderators"]["fear_greed"]["fear_20"][st]
    return m


def compute(now: datetime | None = None, calendar: list | None = None, recent: list | None = None,
            alerts: list | None = None, macro: dict | None = None, market: dict | None = None,
            priors: dict | None = None, weights: dict | None = None, inputs_age_h: float | None = None) -> dict:
    now = now or utcnow()
    priors = priors or read_json("priors.json", {})
    weights = weights if weights is not None else read_json("weights.json")
    market = dict(market or {})
    macro = macro or {}
    if market.get("fear_greed") is None:
        market["fear_greed"] = (macro.get("fear_greed") or {}).get("value")
    S = priors["signal"]
    W = _weights(priors, weights)
    reasons, upcoming, recent_out = [], [], []

    # 1) Eventos programados: blackout y riesgo de evento
    blackout, risks = [], []
    for e in calendar or []:
        if e["category"] not in W or e.get("date_precision") not in ("exact", "day"):
            continue  # fechas de 'mes' o 'año' no tienen hora: no se puede cronometrar un blackout
        start, end = day_window(e)
        cfg = W[e["category"]]
        w0, w1 = start - timedelta(hours=cfg["before_h"]), end + timedelta(hours=cfg["after_h"])
        if w1 < now or start > now + timedelta(hours=S["lookahead_h"]):
            continue
        mag = magnitude(e, W, priors)
        inside = w0 <= now <= w1
        prox = 1.0 if inside else math.exp(-max(0.0, (w0 - now).total_seconds() / 3600) / 24)
        r = min(1.0, mag) * P_OCCUR.get(e.get("status"), 0.5) * prox
        risks.append(r)
        upcoming.append({"id": e["id"], "utc": e["utc"], "title_es": e["title_es"], "category": e["category"],
                         "status": e.get("status"), "magnitud": round(mag, 3), "riesgo": round(r, 3),
                         "ventana": [iso(w0), iso(w1)], "en_ventana": inside})
        if inside and e.get("status") in ("confirmed", "happened") and mag >= priors["blackout_min_excess"]:
            blackout.append(e)
    event_risk = 1 - math.prod(1 - r for r in risks) if risks else 0.0
    if market.get("vol_regime") == "EXTREME":
        event_risk = min(1.0, event_risk * priors["moderators"]["vol_extreme_risk_mult"])
    upcoming.sort(key=lambda x: -x["riesgo"])

    # 2) Eventos recientes ponderados → sesgo direccional. La misma noticia contada por 5 medios es UN evento:
    #    se agrupa por (categoría, día, postura) y cuenta solo el aporte más fuerte del grupo.
    groups = {}
    for e in recent or []:
        if e["category"] not in W or e["category"] == "DERIVATIVES_EXPIRY" or not sign(e):
            continue
        t = day_window(e)[0]  # sin hora: cuenta desde el inicio del día (no espera al mediodía)
        age_d = (now - t).total_seconds() / 86400
        dec = W[e["category"]]["decay_days"]
        if age_d < 0 or age_d > 3 * dec:
            continue
        conf = max(0.0, min(1.0, float(e.get("confidence", 1.0))))
        c = sign(e) * direction(e, W, priors) * math.exp(-age_d / dec) * conf * _moderator(e, market, priors, weights)
        k = (e["category"], e["utc"][:10], e.get("crypto_stance"))
        if k not in groups or abs(c) > abs(groups[k][0]):
            groups[k] = (c, e)
    # Rendimientos decrecientes por (categoría, postura): el 2º evento del mismo tipo pesa la mitad, el 3º un cuarto…
    # y lo que viene de NOTICIAS (no curado) tiene tope: solo puede llevar a CAUTION, nunca a un veto por sí solo.
    per = {}
    for (cat, _day, st), (c, e) in groups.items():
        news = str(e.get("origin", "")).startswith(("gemini/", "palabras-clave/")) or str(e.get("id", "")).startswith("news-")
        per.setdefault((cat, st, news), []).append((c, e))
    cur_total = news_total = 0.0
    for (cat, st, news), lst in per.items():
        lst.sort(key=lambda x: -abs(x[0]))
        for i, (c, e) in enumerate(lst):
            ci = c * 0.5 ** i
            if news:
                news_total += ci
            else:
                cur_total += ci
            recent_out.append({"id": e["id"], "date": e["utc"][:10], "title_es": e["title_es"], "category": e["category"],
                               "stance": e.get("crypto_stance"), "aporte": round(ci, 3), "fuente": "noticia" if news else "curado"})
    cap = S.get("news_cap", 0.6)
    news_total = cap * math.tanh(news_total / cap)
    total = cur_total + news_total
    bias = math.tanh(total / S["bias_scale"])
    recent_out.sort(key=lambda x: -abs(x["aporte"]))

    # 3) Mercado (independientes cuantitativas)
    mc, adj = priors["market_context"], 0.0
    fr = macro.get("fred") or {}
    sc = macro.get("stablecoins") or {}
    if fr.get("vix") is not None and fr["vix"] >= mc["vix_caution"]:
        adj -= mc["bias_step"]; reasons.append(f"VIX {fr['vix']} ≥ {mc['vix_caution']}")
    if fr.get("dxy_20d_pct") is not None and fr["dxy_20d_pct"] >= mc["dxy_20d_pct_bear"]:
        adj -= mc["bias_step"]; reasons.append(f"Dólar +{fr['dxy_20d_pct']}% en 20 días")
    if fr.get("nasdaq_20d_pct") is not None and fr["nasdaq_20d_pct"] <= mc["nasdaq_20d_pct_bear"]:
        adj -= mc["bias_step"]; reasons.append(f"Nasdaq {fr['nasdaq_20d_pct']}% en 20 días")
    if sc.get("chg_30d_pct") is not None:
        if sc["chg_30d_pct"] >= mc["stablecoin_30d_pct_bull"]:
            adj += mc["bias_step"]; reasons.append(f"Stablecoins +{sc['chg_30d_pct']}% en 30 días (liquidez entrando)")
        elif sc["chg_30d_pct"] <= mc["stablecoin_30d_pct_bear"]:
            adj -= mc["bias_step"]; reasons.append(f"Stablecoins {sc['chg_30d_pct']}% en 30 días (liquidez saliendo)")
    bias = max(-1.0, min(1.0, bias + adj))

    # 4) Alertas on-chain
    active, exit_ids = [], []
    for a in alerts or []:
        try:  # la ventana corre desde que se DETECTÓ (la hora del bloque puede ir 2 h adelantada o el vigía atrasarse)
            t = _dt(a.get("detected_utc") or a.get("block_time_utc") or a.get("ts"))
        except Exception:
            continue
        hrs = S["alert_hours"].get(a.get("severity"), 0)
        if now - timedelta(hours=hrs) <= t <= now + timedelta(hours=2):
            active.append(a)
            if a.get("severity") == "critica":
                exit_ids.append(a["id"])

    # 5) Estado
    stale = inputs_age_h is not None and inputs_age_h > S["stale_hours"]
    dead = inputs_age_h is not None and inputs_age_h > S.get("stale_veto_hours", 72)
    sev = {a.get("severity") for a in active}
    cause = "none"
    if dead and not exit_ids:
        state, cause = "RISK_OFF", "stale"
        reasons.insert(0, f"Contexto sin actualizar hace {inputs_age_h:.0f} h (> {S.get('stale_veto_hours', 72)} h): "
                          "sin vigía no se compra")
    elif exit_ids or "alta" in sev:
        state, cause = "RISK_OFF", "onchain"
        reasons.insert(0, f"Alerta on-chain {'CRÍTICA (era Satoshi)' if exit_ids else 'alta'}: "
                          f"{active[0].get('detail_es', '')[:120]}")
    elif blackout:
        state, cause = "BLACKOUT", "blackout"
        reasons.insert(0, "Blackout por evento programado: " + "; ".join(f"{e['title_es']} ({e['utc']})" for e in blackout[:3]))
    elif bias <= S["risk_off_bias"]:
        state, cause = "RISK_OFF", "bias"
        reasons.insert(0, f"Sesgo de eventos muy negativo ({bias:+.2f})")
    elif bias <= S["caution_bias"] or event_risk >= S["caution_event_risk"] or "media" in sev or stale:
        state = "CAUTION"
        cause = "onchain" if "media" in sev else "stale" if stale else "bias" if bias <= S["caution_bias"] else "event_risk"
        why = []
        if bias <= S["caution_bias"]:
            why.append(f"sesgo {bias:+.2f}")
        if event_risk >= S["caution_event_risk"]:
            why.append(f"riesgo de evento {event_risk:.2f} en {S['lookahead_h']} h")
        if "media" in sev:
            why.append("alerta on-chain media")
        if stale:
            why.append(f"datos de contexto viejos ({inputs_age_h:.0f} h)")
        reasons.insert(0, "Precaución: " + ", ".join(why))
    elif bias >= S["risk_on_bias"] and event_risk < 0.3:
        state, cause = "RISK_ON", "bias"
        reasons.insert(0, f"Contexto favorable: sesgo {bias:+.2f}, riesgo de evento {event_risk:.2f}")
    else:
        state = "NEUTRAL"
        reasons.insert(0, f"Contexto neutral: sesgo {bias:+.2f}, riesgo de evento {event_risk:.2f}")
    size = STATE_SIZE[state]
    if state == "NEUTRAL":
        size = round(max(0.5, 1 - 0.5 * event_risk), 3)
    return {"generated_utc": iso(now), "state": state, "veto_entries": state in ("BLACKOUT", "RISK_OFF"),
            "exit_all": bool(exit_ids), "exit_alert_ids": exit_ids, "size_mult": size,
            "bias": round(bias, 3), "event_risk": round(event_risk, 3),
            "extra_confluence": S["extra_confluence_on_caution"] if state == "CAUTION" else 0,
            "vote": "LONG" if state == "RISK_ON" else "FLAT",  # informativo: el comité NO lo cuenta como voto a favor
            "confidence": int(50 + 40 * abs(bias)),
            "reasons": reasons[:8], "upcoming": upcoming[:8], "recent": recent_out[:8], "alerts": active[:5],
            "cause": cause, "mode": "completo", "stale": stale, "weights_source": "weights.json (estudio de eventos)" if weights else "priors.json (a priori)",
            "inputs": {"market": {k: market.get(k) for k in ("btc_regime", "vol_regime", "fear_greed")},
                       "fred": fr.get("status"), "stablecoins_30d_pct": sc.get("chg_30d_pct")}}


MODES = ("completo", "riesgo", "monitor")


def apply_mode(sig: dict, mode: str) -> dict:
    """CONTEXT_MODE: cuánto manda el contexto en las compras (la salida por alerta CRÍTICA aplica en todos).
      completo → todo (blackout, alertas, sesgo de noticias, riesgo de evento, datos viejos)
      riesgo   → solo lo duro: alertas on-chain, blackout de eventos programados y datos viejos; el sesgo de noticias
                 y el riesgo de evento solo se registran
      monitor  → se calcula y se registra, pero no cambia ninguna compra (para medir en papel sin afectar)"""
    mode = mode if mode in MODES else "completo"
    sig = dict(sig, mode=mode)
    if mode == "completo":
        return sig
    if mode == "riesgo" and sig.get("cause") in ("onchain", "blackout", "stale"):
        return sig
    if sig.get("exit_all"):
        return sig
    sig.update(state_raw=sig["state"], state="NEUTRAL", veto_entries=False, size_mult=1.0, extra_confluence=0,
               reasons=[f"Modo {mode}: {sig['state']} solo se registra"] + sig["reasons"][:6])
    return sig


def explain_md(sig: dict) -> str:
    L = [f"**Estado: {sig['state']}** · sesgo {sig['bias']:+.2f} · riesgo de evento {sig['event_risk']:.2f} · "
         f"tamaño ×{sig['size_mult']} · {'VETO a compras' if sig['veto_entries'] else 'compras permitidas'}"
         f"{' · SALIDA A USDT' if sig['exit_all'] else ''}", ""]
    L += [f"- {r}" for r in sig["reasons"]]
    if sig["upcoming"]:
        L += ["", "| Próximo evento | UTC | Categoría | Magnitud | Riesgo |", "|---|---|---|---|---|"]
        L += [f"| {u['title_es'][:80]} | {u['utc']} | {label(u['category'])} | {u['magnitud']} | {u['riesgo']} |"
              for u in sig["upcoming"]]
    if sig["recent"]:
        L += ["", "| Evento reciente | Fecha | Postura | Aporte al sesgo |", "|---|---|---|---|"]
        L += [f"| {r['title_es'][:80]} | {r['date']} | {r['stance']} | {r['aporte']:+.3f} |" for r in sig["recent"]]
    return "\n".join(L)
