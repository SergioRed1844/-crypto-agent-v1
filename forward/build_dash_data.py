"""Convierte forward/results/*.json + baseline_historica.json en los archivos del tablero.
Uso: python build_dash_data.py <dir_rama_forward-test> <dir_salida>"""
import json
import os
import sys
from datetime import datetime, timezone

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
EQ = 1000.0  # cuenta hipotética por escala
NAMES = {"swing": "Swing (1D / 4H / 1H)", "intradia": "Intradía (4H / 1H / 15m)", "scalp": "Scalp (1H / 15m / 5m)"}
iso = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
res = os.path.join(src, "forward", "results")
latest = json.load(open(os.path.join(res, "latest.json")))
pre = json.load(open(os.path.join(src, "forward", "prerregistro.json")))
base = json.load(open(os.path.join(src, "forward", "baseline_historica.json")))
usd = lambda pct: round((pct or 0) / 100 * EQ, 2)


def scale_total(s):
    p = s["portfolio"]
    return usd(p.get("ret_pct")), usd(p.get("open_pct")), round(usd(p.get("ret_pct")) + usd(p.get("open_pct")), 2)


resumen, curva, por_moneda, operaciones = [], [], [], []
for k, s in latest["scales"].items():
    p = s["portfolio"]
    cerrado, flot, total = scale_total(s)
    resumen.append({"escala": k, "escala_nombre": NAMES[k], "trades": p.get("trades", 0),
                    "ganadas_pct": p.get("win_rate"), "expectativa_R": p.get("expectancy_R"),
                    "cerrado_usdt": cerrado, "flotante_usdt": flot, "total_usdt": total, "abiertas": p.get("open", 0),
                    "senales": sum(len(v) for v in s["signals"].values()),
                    "generado_utc": latest["generated_utc"][:19] + "Z", "datos_hasta_utc": iso(latest["data_until"]),
                    "fuente": latest["source"]})
    acc = 0.0
    curva.append({"escala": k, "t_utc": iso(latest["window_start"]), "pnl_usdt": 0.0})
    for t in sorted(s["trades"], key=lambda x: x["out"]):
        acc += t["pct"] / 100 * EQ
        curva.append({"escala": k, "t_utc": iso(t["out"]), "pnl_usdt": round(acc, 2)})
    curva.append({"escala": k, "t_utc": iso(min(latest["data_until"], latest["to"])), "pnl_usdt": round(acc, 2)})
    for c, m in s["per_coin"].items():
        por_moneda.append({"escala": k, "moneda": c.replace("USDT", ""), "trades": m.get("trades", 0),
                           "ganadas_pct": m.get("win_rate"), "total_R": m.get("total_R", 0.0),
                           "pnl_usdt": usd(m.get("ret_pct")), "abiertas": m.get("open", 0),
                           "flotante_R": m.get("open_R", 0.0), "senales": m.get("signals", 0),
                           "buy_hold_pct": m.get("buy_hold_pct")})
    for t in s["trades"]:
        operaciones.append({"id": f"{k}-{t['pair']}-{t['in']}", "escala": k, "moneda": t["pair"].replace("USDT", ""),
                            "estado": "cerrada", "entrada_utc": iso(t["in"]), "salida_utc": iso(t["out"]),
                            "precio_entrada": t["entry"], "precio_salida": t["exit"], "motivo": t["why"],
                            "R": t["R"], "pnl_usdt": round(t["pct"] / 100 * EQ, 2)})
    for t in s["open_positions"]:
        operaciones.append({"id": f"{k}-{t['pair']}-{t['in']}", "escala": k, "moneda": t["pair"].replace("USDT", ""),
                            "estado": "abierta", "entrada_utc": iso(t["in"]), "salida_utc": None,
                            "precio_entrada": t["entry"], "precio_salida": t["mark"], "motivo": "a mercado",
                            "R": t["R"], "pnl_usdt": round(t["pct"] / 100 * EQ, 2)})
operaciones.sort(key=lambda r: r["entrada_utc"], reverse=True)

cortes = []
for name, ts in pre["cortes_utc"].items():
    f = os.path.join(res, f"{name}.json")
    row = {"corte": name, "nombre": {"corte_1": "Corte 1", "corte_2": "Corte 2", "corte_final": "Corte final"}[name],
           "hora_utc": ts, "estado": "pendiente", "swing_usdt": None, "intradia_usdt": None, "scalp_usdt": None,
           "trades": None}
    if os.path.exists(f):
        cj = json.load(open(f))
        row["estado"] = "guardado"
        for k, s in cj["scales"].items():
            row[f"{k}_usdt"] = scale_total(s)[2]
        row["trades"] = sum(s["portfolio"].get("trades", 0) for s in cj["scales"].values())
    cortes.append(row)

linea_base, linea_base_moneda = [], []
K = base["keys"]
days = {"swing": 365, "intradia": 90, "scalp": 30}
for k, h in base["h"].items():
    p = dict(zip(K, h["port"][:len(K)]))
    ic = h["port"][len(K)]
    linea_base.append({"escala": k, "escala_nombre": NAMES[k], "ventana_dias": days[k], "desde_utc": iso(h["from"]),
                       "hasta_utc": pre["inicio_ventana_utc"], "trades": p["trades"], "ganadas_pct": p["win_rate"],
                       "expectativa_R": p["expectancy_R"], "profit_factor": p["profit_factor"],
                       "retorno_pct": p["ret_pct"], "ic95_bajo": ic[0], "ic95_alto": ic[1]})
    for c, v in h["pc"].items():
        m = dict(zip(K, v[:len(K)]))
        linea_base_moneda.append({"escala": k, "moneda": c, "trades": m["trades"], "expectativa_R": m["expectancy_R"],
                                  "total_R": m["total_R"], "buy_hold_pct": m["buy_hold_pct"]})

for name, rows in {"resumen": resumen, "curva": curva, "por_moneda": por_moneda, "operaciones": operaciones,
                   "cortes": cortes, "linea_base": linea_base, "linea_base_moneda": linea_base_moneda}.items():
    json.dump(rows, open(os.path.join(out, f"{name}.json"), "w"), ensure_ascii=False)
    print(f"{name}.json: {len(rows)} filas")
print("datos hasta", iso(latest["data_until"]), "| fuente", latest["source"])
