"""Validación fuera de muestra del Radar (C11-009 B: declarar cuántas especificaciones se probaron).

Se ajusta el modelo SOLO con disparos anteriores a SPLIT_DATE y se evalúa en los posteriores:
- Brier del EB vs (a) tasa base del activo, (b) tasa cruda del activo, (c) tasa cruda del setup sin encoger.
- Calibración por tramos.
- Regla de alerta "Selectivo": cuántas habría mandado, cuántas ganaron, rendimiento neto, peor caída.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from . import config as C
from . import eb
from .model import Model, base_rates, clusters, collect, decide
from .setups import SETUPS, risk_flags


def evaluate(panels, split: str | None = None) -> dict:
    split = split or C.SPLIT_DATE
    train = Model().fit(panels, "0000", split)
    test_inst = collect(panels, split, "9999")
    by_sym = {p.sym: p for p in panels}
    rows = []
    for it in test_inst:
        p = by_sym[it.sym]
        flags = risk_flags(p, it.i)
        for h in C.HORIZONS:
            if (h, 1) not in it.out:
                continue
            pred = train.predict(it.sid, it.cls, h, it.sym, it.i)
            if pred is None:
                continue
            y, net, mae = it.out[(h, 1)]
            raw_asset = eb.jeffreys(pred["k"], pred["n"]) if pred["n"] else pred["raw_setup"]
            level, _ = decide(pred, flags, None, it.cls)
            rows.append(dict(sid=it.sid, cls=it.cls, h=h, sym=it.sym, date=it.date, y=int(y), net=net, mae=mae,
                             p_eb=pred["p"], q10=pred["q10"], p_base=pred["base"], p_raw=raw_asset,
                             p_pool=pred["raw_setup"], ret_pred=pred["ret"], level=level, inst=it))
    # tasa base en prueba (comprar un día cualquiera después del corte)
    test_base = defaultdict(list)
    test_base_sym = {}
    for p in panels:
        for h in C.HORIZONS:
            b = base_rates(p, h, split, "9999")
            if b["n"]:
                test_base[(p.cls, h)].append((b["b"], b["m"]))
                test_base_sym[(p.sym, h)] = (b["b"], b["m"])
    out = {"split": split, "n_specs": train.n_specs, "n_test_rows": len(rows), "by": [], "calib": [],
           "alerts": [], "setups": [], "train_tau_logit": float(np.sqrt(train.tau2_all)),
           "dow_train": train.dow, "lag": []}
    for (cls, h) in sorted({(r["cls"], r["h"]) for r in rows}):
        rr = [r for r in rows if r["cls"] == cls and r["h"] == h]
        y = np.array([r["y"] for r in rr])
        res = {"cls": cls, "h": h, "n": len(rr), "n_clusters": len(clusters([r["inst"] for r in rr])),
               "hit": float(y.mean())}
        for k in ("p_eb", "p_base", "p_raw", "p_pool"):
            res["brier_" + k[2:]] = eb.brier(np.array([r[k] for r in rr]), y)
        res["bss_vs_base"] = 1 - res["brier_eb"] / res["brier_base"] if res["brier_base"] > 0 else float("nan")
        tb = test_base.get((cls, h), [])
        res["test_base_hit"] = float(np.mean([b for b, _ in tb])) if tb else float("nan")
        res["test_base_ret"] = float(np.mean([m for _, m in tb])) if tb else float("nan")
        out["by"].append(res)
    # calibración global
    edges = [0, 0.4, 0.5, 0.6, 0.7, 1.01]
    for a, b in zip(edges[:-1], edges[1:]):
        rr = [r for r in rows if a <= r["p_eb"] < b]
        if rr:
            out["calib"].append({"tramo": f"{a:.0%}–{min(b, 1):.0%}", "n": len(rr),
                                 "pred": float(np.mean([r["p_eb"] for r in rr])),
                                 "real": float(np.mean([r["y"] for r in rr]))})
    # por setup (todas las clases y horizontes): ¿el setup superó a un día cualquiera fuera de muestra?
    for sid in SETUPS:
        for h in C.HORIZONS:
            rr = [r for r in rows if r["sid"] == sid and r["h"] == h]
            if not rr:
                continue
            out["setups"].append({"sid": sid, "h": h, "n": len(rr),
                                  "n_clusters": len(clusters([r["inst"] for r in rr])),
                                  "hit": float(np.mean([r["y"] for r in rr])),
                                  "base": float(np.mean([r["p_base"] for r in rr])),
                                  "pred": float(np.mean([r["p_eb"] for r in rr])),
                                  "net": float(np.mean([r["net"] for r in rr])),
                                  "hit_base_test": float(np.nanmean([test_base_sym.get((r["sym"], h), (np.nan,))[0]
                                                                     for r in rr])),
                                  "net_base": float(np.nanmean([test_base_sym.get((r["sym"], h), (np.nan, np.nan))[1]
                                                                for r in rr]))})
    # regla de alerta Selectivo (sin tope semanal ni contexto v4.2, que no existe en la historia)
    al = [r for r in rows if r["level"] == "ALERTA"]
    seen, uniq = set(), []
    for r in sorted(al, key=lambda r: (r["sym"], r["sid"], r["date"], -r["p_eb"])):
        key = (r["sym"], r["sid"], r["date"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    out["alerts_summary"] = {
        "n": len(uniq), "n_clusters": len(clusters([r["inst"] for r in uniq])) if uniq else 0,
        "hit": float(np.mean([r["y"] for r in uniq])) if uniq else float("nan"),
        "pred": float(np.mean([r["p_eb"] for r in uniq])) if uniq else float("nan"),
        "net_mean": float(np.mean([r["net"] for r in uniq])) if uniq else float("nan"),
        "net_median": float(np.median([r["net"] for r in uniq])) if uniq else float("nan"),
        "worst_mae": float(np.min([r["mae"] for r in uniq])) if uniq else float("nan"),
        "per_year": (len(uniq) / max(0.5, _years_since(split))) if uniq else 0.0,
    }
    out["alerts"] = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "inst"}
                     for r in sorted(uniq, key=lambda r: r["date"])][-60:]
    # ventana de entrada: ¿la mejor ventana en entrenamiento también lo fue en prueba?
    for (sid, cls, h), g in sorted(train.groups.items()):
        t = g.get("lag_table")
        if not t or g["n_eff"] < 8:
            continue
        rr = [r for r in rows if r["sid"] == sid and r["cls"] == cls and r["h"] == h]
        if len(rr) < 8:
            continue
        test_lag = []
        for lag in C.ENTRY_LAGS:
            ys = [r["inst"].out[(h, lag)][0] for r in rr if (h, lag) in r["inst"].out]
            test_lag.append(float(np.mean(ys)) if ys else float("nan"))
        out["lag"].append({"sid": sid, "cls": cls, "h": h, "train_post": t["post"], "train_p_best": t["p_best"],
                           "test_raw": test_lag})
    # día de la semana en prueba (tasa cruda) para contrastar con el encogido de entrenamiento
    test_model = Model()
    by_cls = defaultdict(list)
    for p in panels:
        by_cls[p.cls].append(p)
    out["dow_test"] = {cls: test_model._dow_table(ps, 7, split, "9999") for cls, ps in by_cls.items()}
    return out


def _years_since(d: str) -> float:
    from datetime import date
    return (date.today() - date.fromisoformat(d)).days / 365.25


def _pct(x, d=1):
    return "—" if x is None or not np.isfinite(x) else f"{x * 100:.{d}f}%"


def render_md(ev: dict, full_summary: dict | None = None, health: dict | None = None) -> str:
    L = ["# Radar EB — validación fuera de muestra", "",
         f"Entrenamiento: disparos **antes de {ev['split']}** · Prueba: **desde {ev['split']}**. "
         f"Especificaciones probadas (setup × clase × horizonte): **{ev['n_specs']}** — con tantas pruebas, "
         "algún resultado bueno puede ser azar (C11-009 B). Umbrales fijados el 18-oct-2026 antes de ver datos.", "",
         f"τ entre setups (logit, entrenamiento): {ev['train_tau_logit']:.3f}", "",
         "## 1. ¿El encogimiento EB predice mejor? (Brier, menor es mejor)", "",
         "| Clase | Horizonte | Filas | Episodios | Acierto real | Brier EB | Brier tasa base | Brier crudo activo | "
         "Brier crudo setup | Skill vs base | Día cualquiera (prueba) |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in ev["by"]:
        L.append(f"| {r['cls']} | {r['h']} d | {r['n']} | {r['n_clusters']} | {_pct(r['hit'])} | {r['brier_eb']:.4f} | "
                 f"{r['brier_base']:.4f} | {r['brier_raw']:.4f} | {r['brier_pool']:.4f} | "
                 f"{r['bss_vs_base'] * 100:+.1f}% | {_pct(r['test_base_hit'])} |")
    L += ["", "Skill > 0: el modelo le gana a 'la tasa base del activo' fuera de muestra. Si EB < crudo, el "
          "encogimiento sirvió (la promesa de James-Stein).", "",
          "## 2. Calibración (todas las filas de prueba)", "", "| Tramo predicho | n | Predicho | Real |",
          "|---|---|---|---|"]
    for c in ev["calib"]:
        L.append(f"| {c['tramo']} | {c['n']} | {_pct(c['pred'])} | {_pct(c['real'])} |")
    L += ["", "## 3. Setups fuera de muestra vs comprar un día cualquiera", "",
          "| Setup | Horizonte | Disparos | Episodios | Acierto | Base local (predicción) | Día cualquiera real (prueba) | "
          "Predicho EB | Neto medio | Neto día cualquiera (prueba) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for s in ev["setups"]:
        L.append(f"| {s['sid']} | {s['h']} d | {s['n']} | {s['n_clusters']} | {_pct(s['hit'])} | {_pct(s['base'])} | "
                 f"{_pct(s['hit_base_test'])} | {_pct(s['pred'])} | {_pct(s['net'])} | {_pct(s['net_base'])} |")
    a = ev["alerts_summary"]
    L += ["", "## 4. Regla de alerta Selectivo en el periodo de prueba", "",
          f"Alertas: **{a['n']}** ({a['n_clusters']} episodios; ~{a['per_year']:.1f}/año sin tope semanal) · "
          f"acierto real **{_pct(a['hit'])}** vs predicho {_pct(a['pred'])} · neto medio {_pct(a['net_mean'])} · "
          f"mediana {_pct(a['net_median'])} · peor caída durante la tenencia {_pct(a['worst_mae'])}.", "",
          "Sin contexto v4.2 ni verificación de noticias (no existen hacia atrás): en vivo hay más filtros, no menos.", ""]
    if ev["alerts"]:
        L += ["| Fecha | Activo | Setup | Horizonte | P | Ganó | Neto | Peor caída |", "|---|---|---|---|---|---|---|---|"]
        for r in ev["alerts"][-25:]:
            L.append(f"| {r['date']} | {r['sym']} | {r['sid']} | {r['h']} d | {_pct(r['p_eb'], 0)} | "
                     f"{'sí' if r['y'] else 'no'} | {_pct(r['net'])} | {_pct(r['mae'])} |")
    L += ["", "## 5. Mejor día de compra", "", "### Ventana de entrada después del disparador",
          "| Setup | Clase | Horizonte | Encogido entrenamiento (t+1,2,3,5,8) | P(mejor) | Crudo prueba |",
          "|---|---|---|---|---|---|"]
    for g in ev["lag"]:
        L.append(f"| {g['sid']} | {g['cls']} | {g['h']} d | {' · '.join(_pct(x, 0) for x in g['train_post'])} | "
                 f"{' · '.join(f'{x:.0%}' for x in g['train_p_best'])} | "
                 f"{' · '.join(_pct(x, 0) for x in g['test_raw'])} |")
    L += ["", "### Día de la semana (comprar un día cualquiera, 7 días)", "",
          "| Clase | Días | Encogido entrenamiento | P(mejor) | Crudo prueba |", "|---|---|---|---|---|"]
    for cls, t in ev["dow_train"].items():
        tt = ev["dow_test"].get(cls) or {}
        L.append(f"| {cls} | {' · '.join(t.get('dias', []))} | {' · '.join(_pct(x, 1) for x in t.get('post', []))} | "
                 f"{' · '.join(f'{x:.0%}' for x in t.get('p_best', []))} | "
                 f"{' · '.join(_pct(x, 1) for x in tt.get('raw', []))} |")
    L += ["", "Escepticismo de calendario: peso de evidencia "
          f"{ev['dow_train'][next(iter(ev['dow_train']))].get('w', 0) if ev['dow_train'] else 0} (E5 × 0.4 por "
          "publicación antigua, C08-008/C11-006) → concentración mínima del prior 2000·(1−w)."]
    if health:
        L += ["", "## Fuentes", "", "| Serie | OK | Último dato | Nota |", "|---|---|---|---|"]
        for k, v in sorted(health.items()):
            L.append(f"| {k} | {'sí' if v.get('ok') else 'NO'} | {v.get('last') or '—'} | {v.get('nota', '')} |")
    return "\n".join(L) + "\n"
