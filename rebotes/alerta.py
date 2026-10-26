"""Alerta de lunes y miércoles: señales del estudio de rebotes en el último cierre + bitácora en papel.

    python -m rebotes.alerta STORE OUT [--results results.json] [--ledger ledger.csv]

STORE trae panel.npz (si falta, se baja: universo + 2 años de velas, ver data.py y REB_START). Las señales se calculan
exactamente como en el estudio (signals.features + cooldown(raw_setup)); son NUEVAS solo las del último cierre del
panel. La bitácora sigue cada señal con la misma regla que signals._outcomes (entrada al open siguiente, stop −15%
primero si el mismo día toca ambos, toma +30%, huecos se llenan al open, salida al cierre de la vela 21, costos por
lado). Esto NO es una recomendación de compra: el estudio no encontró ventaja (docs/REBOTES.md); es papel.

Salidas en OUT/alertas/: ledger.csv (bitácora completa), ultima.md (el correo), ultima.json (resumen de la corrida).
Canales: correo por Gmail SMTP (RADAR_SMTP_USER/RADAR_SMTP_PASS; destinatario REB_EMAIL_TO → RADAR_EMAIL_TO →
RADAR_SMTP_USER) o, sin SMTP, un issue de GitHub; hoja de Google por REB_SHEET_URL (+ REB_SHEET_TOKEN), ver
sheets/rebotes_sheet.gs. Ningún secreto ni dirección de correo se imprime ni se guarda.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from . import signals as S

CAP = 25
DISCLAIMER = "Señales del estudio, no recomendación de compra. Solo papel."
LEDGER_COLS = ["id", "setup", "ticker", "fecha_senal", "cierre_senal", "caida_252d", "corrida", "fecha_entrada",
               "entrada", "stop", "toma", "velas", "ultimo_cierre", "fecha_salida", "salida", "estado", "neto"]
CLOSED = ("toma", "stop", "tiempo")
TERMINAL = CLOSED + ("sin_entrada",)          # sin_entrada: el open siguiente no existe (suspensión); el estudio la omite
LOG: list[str] = []


def _log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


# ─────────────────────────── señales ───────────────────────────

def new_signals(P: dict, F: dict | None = None) -> pd.DataFrame:
    """Disparos (con la pausa por acción del estudio) en la ÚLTIMA vela del panel."""
    F = F or S.features(P)
    T = len(P["dates"])
    rows = []
    for name, s in C.SETUPS.items():
        for i, j in S.cooldown(S.raw_setup(name, F), s["cooldown"]):
            if i != T - 1:
                continue
            raw = float(P["RawClose"][i, j]) if "RawClose" in P else float(P["Close"][i, j])
            rows.append({"setup": name, "ticker": P["tickers"][j], "fecha_senal": str(P["dates"][i].date()),
                         "cierre_senal": raw, "cierre_aj": float(P["Close"][i, j]),
                         "caida_252d": float(F["dd"].iat[i, j])})
    df = pd.DataFrame(rows, columns=["setup", "ticker", "fecha_senal", "cierre_senal", "cierre_aj", "caida_252d"])
    return df.sort_values(["setup", "caida_252d"]).reset_index(drop=True)


def approx_dates(fecha: str) -> tuple[str, str]:
    """Entrada = siguiente día hábil; salida por tiempo = cierre de la vela 21 (aprox.: sin feriados de EUA)."""
    d = pd.Timestamp(fecha)
    b = pd.bdate_range(d + pd.Timedelta(days=1), periods=C.HOLD)
    return str(b[0].date()), str(b[-1].date())


# ─────────────────────────── bitácora ───────────────────────────

def track(P: dict, i: int, j: int) -> dict:
    """Estado de la señal (i, j) con las velas disponibles; idéntico a signals._outcomes cuando hay 21 velas."""
    T = len(P["dates"])
    K = min(C.HOLD, T - 1 - i)
    if K < 1:
        return {"estado": "pendiente"}
    entry = float(P["Open"][i + 1, j])
    if not (np.isfinite(entry) and entry > 0):
        return {"estado": "sin_entrada"}
    rows = np.arange(i + 1, i + 1 + K)
    o, h, lo, cl, _, _ = S._clean_window(*(P[f][rows, j].astype(float)[None, :] for f in ("Open", "High", "Low", "Close")),
                                         np.array([entry]))
    o, h, lo, cl = o[0], h[0], lo[0], cl[0]
    tp, sl = entry * (1 + C.TP), entry * (1 + C.SL)
    hit_tp, hit_sl = np.flatnonzero(h >= tp), np.flatnonzero(lo <= sl)
    f_tp = int(hit_tp[0]) if len(hit_tp) else None
    f_sl = int(hit_sl[0]) if len(hit_sl) else None
    out = {"fecha_entrada": str(P["dates"][i + 1].date()), "entrada": entry, "stop": sl, "toma": tp, "velas": int(K),
           "ultimo_cierre": float(cl[-1])}
    if f_sl is not None and (f_tp is None or f_sl <= f_tp):        # empate en el mismo día → stop
        px, k, est = min(sl, o[f_sl]), f_sl, "stop"
    elif f_tp is not None:
        px, k, est = max(tp, o[f_tp]), f_tp, "toma"
    elif K == C.HOLD:
        px, k, est = float(cl[-1]), C.HOLD - 1, "tiempo"
    else:
        gross = cl[-1] / entry - 1
        return out | {"estado": "abierta", "neto": (1 + gross) * (1 - C.COST_SIDE) / (1 + C.COST_SIDE) - 1}
    gross = px / entry - 1
    return out | {"estado": est, "fecha_salida": str(P["dates"][i + 1 + k].date()), "salida": float(px),
                  "neto": (1 + gross) * (1 - C.COST_SIDE) / (1 + C.COST_SIDE) - 1}


def update_ledger(P: dict, ledger: pd.DataFrame, new: pd.DataFrame, run_date: str) -> tuple[pd.DataFrame, list[str]]:
    """Agrega las señales nuevas y actualiza las no cerradas. Devuelve (bitácora, ids cerrados en esta corrida)."""
    led = ledger.copy() if not ledger.empty else pd.DataFrame(columns=LEDGER_COLS)
    for c in LEDGER_COLS:
        if c not in led.columns:
            led[c] = np.nan
    led = led[LEDGER_COLS].astype(object)
    if not new.empty:
        add = new.assign(id=new.setup + "|" + new.ticker + "|" + new.fecha_senal, corrida=run_date, estado="pendiente")
        add = add[~add.id.isin(set(led.id))]
        led = pd.concat([led, add.reindex(columns=LEDGER_COLS).astype(object)], ignore_index=True)
    pos = {d: k for k, d in enumerate(P["dates"].strftime("%Y-%m-%d"))}
    col = {t: k for k, t in enumerate(P["tickers"])}
    closed_now = []
    for r in led.index:
        if led.at[r, "estado"] in TERMINAL:
            continue
        i, j = pos.get(str(led.at[r, "fecha_senal"])), col.get(str(led.at[r, "ticker"]))
        if i is None or j is None:
            continue                                   # fuera de la ventana de datos o sin precio hoy: se deja igual
        st = track(P, i, j)
        for k, v in st.items():
            led.at[r, k] = v
        if st["estado"] in CLOSED:
            closed_now.append(led.at[r, "id"])
    return led, closed_now


def paper_stats(led: pd.DataFrame) -> dict:
    c = led[led.estado.isin(CLOSED)]
    net = pd.to_numeric(c.neto, errors="coerce").dropna()
    return {"cerradas": int(len(net)), "abiertas": int((led.estado == "abierta").sum()),
            "pendientes": int((led.estado == "pendiente").sum()),
            "gana": float((net > 0).mean()) if len(net) else None, "neto_medio": float(net.mean()) if len(net) else None}


# ─────────────────────────── estudio ───────────────────────────

def study_stats(path: str | None) -> dict:
    if not path or not Path(path).exists():
        return {}
    r = json.load(open(path))
    out = {"base": r.get("base", {}).get("test", {}), "setups": {}}
    for k, v in r.get("setups", {}).items():
        t = v.get("test", {})
        out["setups"][k] = {"n": t.get("n"), "p_hit30": t.get("p_hit30"), "p_dd20": t.get("p_dd20"),
                            "net_mean": t.get("net_mean"), "pasa": bool(v.get("gate", {}).get("pasa", False))}
    out["pasan"] = sum(s["pasa"] for s in out["setups"].values())
    out["total"] = len(out["setups"])
    return out


def dictamen(setup: str, st: dict) -> str:
    if st.get("setups", {}).get(setup, {}).get("pasa"):
        return "Pasó la compuerta del estudio (papel)"
    return "Sin ventaja demostrada en el estudio — solo papel"


# ─────────────────────────── correo ───────────────────────────

def pc(x, d=1) -> str:
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x * 100:.{d}f}%"


def px(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return "—" if not np.isfinite(v) else f"{v:,.2f}"


def signal_rows(new: pd.DataFrame, st: dict) -> list[dict]:
    rows = []
    for r in new.itertuples():
        ent, sal = approx_dates(r.fecha_senal)
        s = st.get("setups", {}).get(r.setup, {})
        rows.append({"setup": r.setup, "ticker": r.ticker, "fecha_senal": r.fecha_senal, "cierre": r.cierre_senal,
                     "caida_252d": r.caida_252d, "entrada": f"al abrir la siguiente sesión (~{ent})",
                     "stop_ref": r.cierre_senal * (1 + C.SL), "toma_ref": r.cierre_senal * (1 + C.TP),
                     "salida_tiempo": f"cierre ~{sal} (aprox.)", "p_hit30": s.get("p_hit30"), "p_dd20": s.get("p_dd20"),
                     "neto_hist": s.get("net_mean"), "dictamen": dictamen(r.setup, st)})
    return rows


def render(run_date: str, last_bar: str, new: pd.DataFrame, led: pd.DataFrame, closed_now: list[str], st: dict
           ) -> tuple[str, str, str]:
    """(asunto, texto, html)."""
    rows = signal_rows(new, st)
    ps = paper_stats(led)
    base = st.get("base", {})
    subj = f"Rebotes — {len(rows)} señales del estudio al cierre del {last_bar} (papel, no recomendación de compra)"
    verdict = (f"Estudio: {st.get('pasan', 0)}/{st.get('total', 3)} setups pasan la compuerta (2019→2026, costos GBM)."
               if st else "Estudio: sin results.json en esta corrida.")
    lines = [f"# Rebotes — corrida {run_date}", "", DISCLAIMER, "",
             f"- {verdict}",
             f"- Señales nuevas al cierre del {last_bar}: {len(rows)}" + (f" (se muestran {CAP})" if len(rows) > CAP else ""),
             f"- Bitácora en papel: {ps['cerradas']} cerradas, {ps['abiertas']} abiertas, {ps['pendientes']} por entrar; "
             f"gana {pc(ps['gana'], 0)}, neto medio {pc(ps['neto_medio'])} "
             f"(base del estudio: neto medio {pc(base.get('net_mean'))})", "",
             "Niveles: los reales salen del open de mañana (stop = open × 0.85, toma = open × 1.30); los de abajo son "
             "referencia desde el cierre de la señal. Salida por tiempo al cierre de la vela 21.", ""]
    if rows:
        lines += ["## Señales nuevas", "",
                  "| setup | ticker | cierre | caída 252d | stop ref. | toma ref. | salida por tiempo | P(+30%) hist. | "
                  "P(−20%) hist. | neto hist. | dictamen |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows[:CAP]:
            lines.append(f"| {r['setup']} | {r['ticker']} | {px(r['cierre'])} | {pc(r['caida_252d'])} | {px(r['stop_ref'])} | "
                         f"{px(r['toma_ref'])} | {r['salida_tiempo']} | {pc(r['p_hit30'])} | {pc(r['p_dd20'])} | "
                         f"{pc(r['neto_hist'])} | {r['dictamen']} |")
        lines.append("")
    op = led[led.estado == "abierta"]
    if len(op):
        lines += ["## Abiertas (papel)", "", "| setup | ticker | entrada | stop | toma | último cierre | velas | neto si sale hoy |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in op.itertuples():
            lines.append(f"| {r.setup} | {r.ticker} | {r.fecha_entrada} @ {px(r.entrada)} | {px(r.stop)} | {px(r.toma)} | "
                         f"{px(r.ultimo_cierre)} | {r.velas}/{C.HOLD} | {pc(_f(r.neto))} |")
        lines.append("")
    cl = led[led.id.isin(closed_now)]
    if len(cl):
        lines += ["## Cerradas desde la corrida anterior", "", "| setup | ticker | entrada | salida | motivo | neto |",
                  "|---|---|---|---|---|---|"]
        for r in cl.itertuples():
            lines.append(f"| {r.setup} | {r.ticker} | {r.fecha_entrada} @ {px(r.entrada)} | {r.fecha_salida} @ {px(r.salida)} | "
                         f"{r.estado} | {pc(_f(r.neto))} |")
        lines.append("")
    lines += ["Método y compuerta: docs/REBOTES.md (rama rebotes). Bitácora completa: alertas/ledger.csv (rama rebotes-data)."]
    text = "\n".join(lines) + "\n"
    return subj, text, md_to_html(text)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def md_to_html(md: str) -> str:
    out, table = [], []

    def flush():
        if not table:
            return
        rows = [r for r in table if not set(r.replace("|", "").strip()) <= set("-: ")]
        cells = [[html.escape(c.strip()) for c in r.strip().strip("|").split("|")] for r in rows]
        h = "".join(f"<th style='text-align:left;padding:4px 8px;border-bottom:1px solid #ccc'>{c}</th>" for c in cells[0])
        b = "".join("<tr>" + "".join(f"<td style='padding:4px 8px;border-bottom:1px solid #eee'>{c}</td>" for c in r)
                    + "</tr>" for r in cells[1:])
        out.append(f"<table style='border-collapse:collapse;font-size:13px'><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>")
        table.clear()

    for line in md.splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush()
        e = html.escape(line)
        if line.startswith("## "):
            out.append(f"<h3>{html.escape(line[3:])}</h3>")
        elif line.startswith("# "):
            out.append(f"<h2>{html.escape(line[2:])}</h2>")
        elif line.startswith("- "):
            out.append(f"<div>• {html.escape(line[2:])}</div>")
        elif line.strip():
            out.append(f"<p>{e}</p>")
    flush()
    return "<div style='font-family:Arial,sans-serif;font-size:14px'>" + "\n".join(out) + "</div>"


def recipient() -> str:
    return os.getenv("REB_EMAIL_TO") or os.getenv("RADAR_EMAIL_TO") or os.getenv("RADAR_SMTP_USER") or ""


def email_send(subject: str, text: str, body_html: str) -> bool:
    user, pwd, to = os.getenv("RADAR_SMTP_USER", ""), os.getenv("RADAR_SMTP_PASS", ""), recipient()
    if not (user and pwd and to):
        _log("correo: sin credenciales SMTP")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL(os.getenv("RADAR_SMTP_HOST", "smtp.gmail.com"), int(os.getenv("RADAR_SMTP_PORT", "465")),
                              context=ssl.create_default_context(), timeout=30) as s:
            s.login(user, pwd)
            s.sendmail(user, [to], msg.as_string())
        _log("correo enviado")
        return True
    except Exception as e:  # noqa: BLE001 — nunca se registran credenciales ni destinatario
        _log(f"correo falló: {type(e).__name__}")
        return False


def issue_send(subject: str, text: str) -> bool:
    tok, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not (tok and repo):
        _log("issue: sin GITHUB_TOKEN/GITHUB_REPOSITORY")
        return False
    import httpx
    hd = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    for body in ({"title": subject[:240], "body": text[:65000], "labels": ["rebotes"]},
                 {"title": subject[:240], "body": text[:65000]}):
        try:
            r = httpx.post(f"https://api.github.com/repos/{repo}/issues", json=body, headers=hd, timeout=30)
            if r.status_code < 300:
                _log(f"issue #{r.json()['number']} creado (sin SMTP: el correo llega por la notificación de GitHub)")
                return True
            _log(f"issue: HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            _log(f"issue falló: {type(e).__name__}")
    return False


def sheet_payload(run_date: str, rows: list[dict], led: pd.DataFrame, summary: dict) -> dict:
    sh = ["corrida", "setup", "ticker", "fecha_senal", "cierre", "caida_252d", "entrada", "stop_ref", "toma_ref",
          "salida_tiempo", "p_hit30", "p_dd20", "neto_hist", "dictamen"]
    clean = lambda v: None if v is None or (isinstance(v, float) and not np.isfinite(v)) else v
    sig = [[run_date] + [clean(r[k]) for k in sh[1:]] for r in rows]
    bit = [[clean(_f(v)) if k in ("cierre_senal", "caida_252d", "entrada", "stop", "toma", "ultimo_cierre", "salida", "neto")
            else (None if pd.isna(v) else v) for k, v in zip(LEDGER_COLS, r)] for r in led[LEDGER_COLS].itertuples(index=False)]
    res = [[k, clean(v) if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)] for k, v in summary.items()]
    return {"token": os.getenv("REB_SHEET_TOKEN", ""), "corrida": run_date,
            "tabs": {"Señales": {"mode": "append", "header": sh, "rows": sig},
                     "Bitácora": {"mode": "replace", "header": LEDGER_COLS, "rows": bit},
                     "Resumen": {"mode": "replace", "header": ["campo", "valor"], "rows": res}}}


def sheet_send(payload: dict) -> bool:
    url = os.getenv("REB_SHEET_URL")
    if not url:
        _log("hoja: sin REB_SHEET_URL")
        return False
    import httpx
    try:
        r = httpx.post(url, content=json.dumps(payload, ensure_ascii=False, default=str).encode(),
                       headers={"Content-Type": "application/json"}, timeout=60, follow_redirects=True)
        ok = r.status_code == 200 and '"ok":true' in r.text.replace(" ", "")
        _log("hoja actualizada" if ok else f"hoja respondió HTTP {r.status_code}: {r.text[:120]}")
        return ok
    except Exception as e:  # noqa: BLE001 — la URL no se registra
        _log(f"hoja falló: {type(e).__name__}")
        return False


# ─────────────────────────── corrida ───────────────────────────

def run(store: str, out: str, results: str | None = None, ledger_path: str | None = None, send: bool = True) -> dict:
    from .data import load_panel, prices, universe
    st_dir = Path(store)
    if not (st_dir / "panel.npz").exists():
        st_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("REB_START", str((pd.Timestamp.now("UTC") - pd.DateOffset(years=2)).date()))
        universe(store)
        prices(store)
    P = load_panel(str(st_dir / "panel.npz"))
    run_date = str(pd.Timestamp.now(tz="America/Monterrey").strftime("%Y-%m-%d %H:%M"))
    last_bar = str(P["dates"][-1].date())
    st = study_stats(results)
    new = new_signals(P)
    led0 = pd.read_csv(ledger_path, dtype=str) if ledger_path and Path(ledger_path).exists() else pd.DataFrame()
    led, closed_now = update_ledger(P, led0, new, run_date)
    subj, text, body = render(run_date, last_bar, new, led, closed_now, st)
    o = Path(out) / "alertas"
    o.mkdir(parents=True, exist_ok=True)
    num = ["cierre_senal", "caida_252d", "entrada", "stop", "toma", "ultimo_cierre", "salida", "neto"]
    led.assign(**{c: pd.to_numeric(led[c], errors="coerce") for c in num}).to_csv(o / "ledger.csv", index=False,
                                                                                  float_format="%.4f")
    (o / "ultima.md").write_text(text)
    ps = paper_stats(led)
    summary = {"corrida": run_date, "ultimo_cierre": last_bar, "senales_nuevas": int(len(new)),
               "por_setup": new.setup.value_counts().to_dict() if len(new) else {}, "cerradas_hoy": len(closed_now),
               "estudio_pasan": st.get("pasan"), "estudio_total": st.get("total"), **{f"papel_{k}": v for k, v in ps.items()}}
    sent = {}
    if send:
        sent["correo"] = email_send(subj, text, body)
        if not sent["correo"]:
            sent["issue"] = issue_send(subj, text)
        sent["hoja"] = sheet_send(sheet_payload(run_date, signal_rows(new, st), led, summary))
    summary["canales"] = sent
    summary["log"] = LOG
    json.dump(summary, open(o / "ultima.json", "w"), indent=1, ensure_ascii=False, default=str)
    _log(f"señales nuevas {len(new)}; bitácora {len(led)} filas; cerradas hoy {len(closed_now)}")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("store")
    ap.add_argument("out")
    ap.add_argument("--results")
    ap.add_argument("--ledger")
    ap.add_argument("--no-send", action="store_true")
    a = ap.parse_args(argv)
    s = run(a.store, a.out, a.results, a.ledger, send=not a.no_send)
    ch = s.get("canales", {})
    if not a.no_send and not (ch.get("correo") or ch.get("issue")):
        _log("ningún canal de aviso funcionó")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
