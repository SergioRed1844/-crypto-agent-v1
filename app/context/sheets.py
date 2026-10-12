"""Espejo del contexto en tu Google Sheet (Apps Script Web App, ver sheets/google_apps_script.js).

Un POST por pestaña con el lote completo (las cuotas de Apps Script castigan muchos requests chicos).
SHEETS_WEBAPP_URL y SHEETS_TOKEN vienen del entorno; si faltan, no hace nada. Nunca se imprimen.
"""
import logging
import os

import httpx

from .event_calendar import _mty
from .schema import label

log = logging.getLogger("sheets")


def _post(sheet: str, mode: str, header: list, rows: list, key: str = "id") -> str:
    url = os.environ.get("SHEETS_WEBAPP_URL", "")
    if not url:
        return "sin SHEETS_WEBAPP_URL"
    body = {"action": "context_sheet", "token": os.environ.get("SHEETS_TOKEN", ""), "sheet": sheet, "mode": mode,
            "key": key, "header": header, "rows": rows}
    try:
        r = httpx.post(url, json=body, timeout=60, follow_redirects=True)
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return "ok" if j.get("ok") else f"error {r.status_code}: {str(j.get('error', ''))[:80]}"
    except Exception as e:
        return f"error {type(e).__name__}"


def mirror(calendar: list, history_recent: list, weights: dict | None, alerts: list, signal: dict) -> dict:
    if not os.environ.get("SHEETS_WEBAPP_URL"):
        return {"status": "sin SHEETS_WEBAPP_URL (opcional)"}
    fut = [e for e in calendar if e["utc"] >= signal["generated_utc"][:10]]
    res = {"Calendario": _post("Calendario", "replace",
                               ["id", "fecha_utc", "fecha_monterrey", "evento", "categoria", "pais", "estado", "importancia",
                                "por_que", "fuente"],
                               [[e["id"], e["utc"], _mty(e), e["title_es"], label(e["category"]), e["country"], e["status"],
                                 e["prior_tier"], e.get("why_es", ""), e.get("source_url", "")] for e in fut])}
    res["Eventos"] = _post("Eventos", "upsert",
                           ["id", "fecha", "evento", "categoria", "pais", "postura", "importancia", "origen", "fuente"],
                           [[e["id"], e["utc"][:10], e["title_es"], label(e["category"]), e["country"],
                             e.get("crypto_stance"), e["prior_tier"], e.get("origin", ""), e.get("source_url", "")]
                            for e in history_recent])
    if weights:
        res["Pesos"] = _post("Pesos", "replace",
                             ["categoria", "n", "abs_z3", "x_azar", "p_magnitud", "efecto_dir", "acierto", "p_dir",
                              "peso_magnitud", "peso_direccion", "evidencia"],
                             [[v["label"], v["n"], v["mean_abs_z3"], v["ratio_vs_random"], v["p_abs"], v["mean_signed_z3"],
                               v["hit_rate"], v["p_dir"], v["w_abs"], v["w_dir"],
                               f"{v['evidence_abs']} / {v['evidence_dir']}"] for v in weights["categories"].values()],
                             key="categoria")
    if alerts:
        res["Alertas"] = _post("Alertas", "upsert", ["id", "tipo", "severidad", "btc", "bloque", "hora_utc", "detalle", "url"],
                               [[a["id"], a["type"], a["severity"], a.get("btc_moved"), a.get("block_height"),
                                 a.get("block_time_utc"), a.get("detail_es", ""), a.get("url", "")] for a in alerts])
    res["Contexto"] = _post("Contexto", "append",
                            ["generado_utc", "estado", "sesgo", "riesgo_evento", "tamano", "veto", "salida", "razones"],
                            [[signal["generated_utc"], signal["state"], signal["bias"], signal["event_risk"],
                              signal["size_mult"], signal["veto_entries"], signal["exit_all"],
                              " | ".join(signal["reasons"])[:900]]], key="generado_utc")
    return res
