"""Fichas de alerta (formato C11-025 adaptado a compras) y resumen diario. Markdown para correo/issue y texto corto
para WhatsApp. Toda cifra viene del modelo o de las fuentes; lo que es estimación se marca."""
from __future__ import annotations

import json
import os

import numpy as np

from . import config as C
from .setups import SETUPS

_REFS = None
DISCLAIMER = ("Señal estadística para que TÚ la revises. No es asesoría financiera ni una orden; el Radar no opera "
              "y no tiene llaves de ningún exchange. Probabilidades históricas encogidas, no garantías.")
CLS_ES = {"crypto": "cripto", "us": "EUA", "bmv": "BMV"}


def refs() -> dict:
    global _REFS
    if _REFS is None:
        p = os.path.join(os.path.dirname(__file__), "corpus_refs.json")
        try:
            _REFS = json.load(open(p))["chunks"]
        except (OSError, ValueError, KeyError):
            _REFS = {}
    return _REFS


def pct(x, d=1, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def pp(x):
    return "—" if x is None or not np.isfinite(x) else f"{x * 100:+.1f} pp"


def confidence(c: dict) -> tuple[str, str]:
    """Etiqueta y cálculo visible (C11-025: la confianza muestra la cuenta, no solo la categoría)."""
    pr = c["pred"]
    fam = c.get("families", [])
    w = pr["w"]
    if len(fam) >= 3 and w >= 0.45 and pr["n_eff"] >= 30 and pr["q10"] > pr["base"]:
        lab = "Alta"
    elif w >= 0.25 and pr["n_eff"] >= 15 and pr["q10"] >= pr["base"] - 0.02:
        lab = "Media"
    else:
        lab = "Baja"
    if c.get("ctx_cap") and lab == "Alta":
        lab = "Media"
    s = SETUPS[c["sid"]]
    calc = (f"peso de evidencia w={w:.2f} ({s.evidence} × {s.decay} por publicación × "
            f"{s.applic.get(c['cls'], 0)} aplicabilidad a {CLS_ES[c['cls']]}) · encogimiento hacia 'sin ventaja' "
            f"{pr['B'] * 100:.0f}% · {pr['n_eff']} episodios independientes · familias de señal: "
            f"{', '.join(fam) if fam else 'solo precio'} ({len(fam)}; 'Alta' exige ≥3, C11-008)")
    return lab, calc


def _refs_line(sid: str, cls: str | None = None) -> str:
    s = SETUPS[sid]
    if not s.refs:
        return "fuera del corpus (literatura general de trading)"
    R = refs()
    out = []
    for r in s.refs:
        r, _, only = r.partition(":")
        if only and cls and only != cls:
            continue
        meta = R.get(r, {})
        mark = " ⚠️verificar" if meta.get("verificar") else ""
        out.append(f"{r} «{meta.get('titulo', '?')}» [{meta.get('evidencia_max', '?')}]{mark}")
    return "; ".join(out)


def ficha_md(c: dict) -> str:
    s = SETUPS[c["sid"]]
    pr = c["pred"]
    lab, calc = confidence(c)
    fl = c["flags"]
    head = {"ALERTA": "🟢 ALERTA DE COMPRA", "VIGILANCIA": "🟡 EN VIGILANCIA", "VETADA": "⛔ VETADA"}[c["level"]]
    L = [f"## {head} — {c['sym']} ({CLS_ES[c['cls']]}) · {s.nombre}", "",
         f"**Disparo:** cierre del {c['date']} · precio {c['price']:.6g} · horizonte sugerido **{pr['h']} días**", "",
         f"**LECTURA:** {c['lectura']}", "",
         "| | Este setup en este activo (encogido) | Comprar un día cualquiera (último año) |", "|---|---|---|",
         f"| Probabilidad de ganar ≥ {pct(C.TARGET[pr['h']], 1)} neto en {pr['h']} días | **{pct(pr['p'], 0)}** "
         f"(IC80 {pct(pr['q10'], 0)}–{pct(pr['q90'], 0)}) | {pct(pr['base'], 0)} |",
         f"| Rendimiento neto esperado | **{pct(pr['ret'], 1, True)}** (cota baja {pct(pr['ret_q10'], 1, True)}) | "
         f"{pct(pr['base_ret'], 1, True)} |",
         f"| Ventaja (lo único que el setup agrega) | **{pp(pr['lift'])}** · P(ventaja > 0) "
         f"{pct(pr.get('p_lift_pos'), 0)} | — |",
         f"| Episodios pasados que terminaron con ganancia neta > 0 (crudo, el setup en la clase) | "
         f"{pct(pr.get('pos_p'), 0)} | — |",
         f"| Riesgo de caída ≥ {pct(-C.MAE_LIMIT[c['cls']], 0)} durante la tenencia | {pct(pr['mae_p'], 0)} | — |", "",
         "_La probabilidad es de ganar AL MENOS la meta neta (no solo 'subir'); por eso se ve baja. Lo que importa es la "
         "ventaja contra comprar un día cualquiera y qué tan creíble es._", "",
         f"Historia: {pr['k']}/{pr['n']} aciertos crudos en {c['sym']}; el setup en {CLS_ES[c['cls']]}: "
         f"{pr['n_inst']} disparos = {pr['n_eff']} episodios independientes, crudo {pct(pr['raw_setup'], 0)}. "
         f"Aparece ~{c.get('freq', '—')} veces/año en este activo (Poisson-Gamma).", "",
         "**Otros horizontes:** " + " · ".join(
             f"{h} d: P {pct(p['p'], 0)} vs {pct(p['base'], 0)}, neto {pct(p['ret'], 1, True)}"
             for h, p in sorted(c["preds"].items()) if p), "",
         f"**MEJOR DÍA DE COMPRA:** {c['lag_txt']}. Día de la semana (desempate): {c['dow_txt']}.", "",
         f"**MECANISMO:** {s.mecanismo}", "",
         f"**CONFIANZA: {lab}** — {calc}", "",
         f"**CONTEXTO:** {c['ctx_txt']}", ""]
    if c.get("news"):
        n = c["news"]
        L += [f"**NOTICIAS (Gemini con búsqueda, solo puede RESTAR):** causa probable *{n.get('causa', '?')}* — "
              f"{n.get('resumen', '')}"]
        for f_ in (n.get("fuentes") or [])[:4]:
            L.append(f"- [{f_.get('titulo', 'fuente')[:90]}]({f_.get('url')})")
        L.append("")
    ern = c.get("earnings") or {}
    if ern.get("date"):
        L += [f"**RESULTADOS TRIMESTRALES:** próximo reporte {ern['date']} (en {ern.get('days')} días; Finnhub)", ""]
    L += [f"**RIESGOS REVISADOS:** run-up 2 años (neto de mercado) {pct(fl.get('gsy_runup_2y'), 0)} → GSY "
          f"{fl.get('gsy')} · euforia {'SÍ' if fl.get('euforia') else 'no'} · Fear&Greed {fl.get('fear_greed') or '—'} · "
          f"VIX {fl.get('vix') or '—'}", ""]
    if c.get("why"):
        L += ["**Por qué no es alerta / ajustes:** " + "; ".join(c["why"]), ""]
    L += [f"**QUÉ NO INFERIR:** {s.no_inferir}", "",
          f"**SIGUIENTE VERIFICACIÓN:** {s.verificar}", "",
          f"**CORPUS:** {_refs_line(c['sid'], c['cls'])}", "",
          f"_Costos supuestos ida y vuelta: {pct(C.COST_RT[c['cls']], 2)} (estimación). {DISCLAIMER}_"]
    return "\n".join(L)


def short_txt(c: dict) -> str:
    pr = c["pred"]
    s = SETUPS[c["sid"]]
    return (f"RADAR EB {c['level']}: {c['sym']} — {s.nombre}. P(ganar ≥{pct(C.TARGET[pr['h']], 1)} neto en "
            f"{pr['h']}d) {pct(pr['p'], 0)} vs {pct(pr['base'], 0)} un día cualquiera; neto esperado "
            f"{pct(pr['ret'], 1, True)}. Entrada: {c['lag_txt'].split('(')[0].strip()}. Ficha completa en tu correo. "
            "No es asesoría.")


def digest_md(d: dict) -> str:
    L = [f"# 📡 Radar EB — resumen {d['local_date']}", "",
         f"**Sigo vivo:** {d['runs_24h']} corridas en 24 h · última {d['last_scan_utc']} UTC · "
         f"{d['n_assets']} activos vigilados · modelo ajustado con {d['n_specs']} especificaciones.", ""]
    L += ["## Alertas y candidatos (últimas 24 h)", ""]
    if d["candidates"]:
        L += ["| Nivel | Activo | Setup | Disparo | H | P | Día cualquiera | Neto esp. | Motivo |",
              "|---|---|---|---|---|---|---|---|---|"]
        for c in d["candidates"]:
            pr = c["pred"]
            L.append(f"| {c['level']} | {c['sym']} | {SETUPS[c['sid']].nombre} | {c['date']} | {pr['h']} d | "
                     f"{pct(pr['p'], 0)} | {pct(pr['base'], 0)} | {pct(pr['ret'], 1, True)} | "
                     f"{'; '.join(c.get('why', [])[:2]) or '—'} |")
    else:
        L.append("Ningún setup disparó en las últimas 24 h. Eso también es información: no hay pánico ni capitulación "
                 "medibles.")
    L += ["", "## Clima de mercado", "", d["climate"], ""]
    L += ["## Mejor día de compra (día de la semana, encogido)", ""]
    for cls, txt in d["dow"].items():
        L.append(f"- **{CLS_ES[cls]}:** {txt}")
    L += ["", "## Seguimiento de alertas pasadas (proceso, no resultado)", "", d["tracking"], "",
          "## Salud de fuentes", ""]
    bad = [f"{k}: {v.get('nota')}" for k, v in sorted(d["health"].items()) if not v.get("ok")]
    L.append("Todas las fuentes respondieron." if not bad else "Fallas (se usó caché): " + "; ".join(bad[:12]))
    L += ["", f"_{DISCLAIMER}_"]
    return "\n".join(L)


def md_to_html(md: str) -> str:
    """Conversión mínima para correo (encabezados, negritas, tablas y viñetas)."""
    import html
    import re
    out, in_table = [], False
    for line in md.splitlines():
        esc = html.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
        esc = re.sub(r"(?<![\w*])_(.+?)_(?![\w*])", r"<i>\1</i>", esc)
        esc = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', esc)
        if line.startswith("|"):
            cells = [x.strip() for x in esc.strip("|").split("|")]
            if all(set(x) <= set("-: ") for x in cells):
                continue
            if not in_table:
                out.append('<table style="border-collapse:collapse;font-size:13px">')
                in_table = True
            out.append("<tr>" + "".join(f'<td style="border:1px solid #ccc;padding:3px 6px">{x}</td>' for x in cells)
                       + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("# "):
            out.append(f"<h2>{esc[2:]}</h2>")
        elif line.startswith("## "):
            out.append(f"<h3>{esc[3:]}</h3>")
        elif line.startswith("- "):
            out.append(f"<div>• {esc[2:]}</div>")
        elif not line.strip():
            out.append("<br>")
        else:
            out.append(f"<div>{esc}</div>")
    if in_table:
        out.append("</table>")
    return '<div style="font-family:Arial,sans-serif;font-size:14px">' + "\n".join(out) + "</div>"
