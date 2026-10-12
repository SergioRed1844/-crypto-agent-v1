"""Genera docs/MODELO_CONTEXTO.md desde la plantilla, el registro de variables y los datos actuales."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.context import read_json, variables  # noqa: E402
from app.context.event_calendar import build  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tpl = open(os.path.join(ROOT, "docs", "_modelo_contexto.tpl.md"), encoding="utf-8").read()
cal = build()
apis = read_json("sources/apis.json", [])
rows = ["| Fuente | Área | Estado 2026 | Gratis | ¿Estaba en v4.1? | ¿Conectada en v4.2? | Recomendación |",
        "|---|---|---|---|---|---|---|"]
V42 = ("CryptoPanic", "GDELT DOC", "alternative.me", "FRED API", "FRED Release", "DefiLlama", "Polymarket Gamma",
       "mempool.space", "Blockstream", "Coin Metrics", "ForexFactory", "data.binance.vision", "data-api.binance.vision",
       "Funding Rate History", "Grounding", "Apps Script")
rec = {"adopt_now": "adoptar ya", "adopt_later_paid": "después (pago)", "optional": "opcional", "avoid": "evitar"}
for a in sorted(apis, key=lambda x: (x["kind"], x["recommendation"], x["name"])):
    if a["kind"] != "api":
        continue
    rows.append(f"| {a['name']} | {a['area']} | {str(a['status_2026'])[:90].replace('|', '/')} | "
                f"{str(a['free_tier'])[:40].replace('|', '/')} | {'sí' if a['have_already'] else 'no'} | "
                f"{'sí' if any(k in a['name'] for k in V42) else 'no'} | "
                f"{rec.get(a['recommendation'], a['recommendation'])} |")
gdp = read_json("sources/gdp_shares.json", [])
out = (tpl.replace("{{VARIABLES}}", variables.markdown()).replace("{{APIS}}", "\n".join(rows))
       .replace("{{N_EVENTS}}", str(len(cal))).replace("{{LAST_DATE}}", max(e["utc"] for e in cal)[:10])
       .replace("{{N_COUNTRIES}}", str(sum(1 for g in gdp if g.get("meets_1pct_threshold")))))
open(os.path.join(ROOT, "docs", "MODELO_CONTEXTO.md"), "w", encoding="utf-8").write(out)
print("docs/MODELO_CONTEXTO.md", len(out.splitlines()), "líneas")
