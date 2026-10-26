"""Pruebas sin red de la alerta de rebotes (lunes/miércoles). Uso: python -m tests.test_rebotes_alerta"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from rebotes import alerta as A, config as C, signals as S

FAILS: list[str] = []
# sha256 de la dirección del usuario: la prueba la busca en el repo sin escribirla (el repo es público)
USER_ADDR_SHA = "0364ccd2ad26585d44e40efa36c5ec1d62e12d1c12b8c4453360ff1eaacb3db4"


def check(name: str, cond: bool) -> None:
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def giro_panel(T: int, fire_at: dict[int, int], N: int = 4, seed: int = 3) -> dict:
    """Acciones que caen 60% y rompen su máximo de 20 días en la vela indicada (CAIDA_GIRO)."""
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2017-01-02", periods=T)
    c = (100 * np.exp(np.cumsum(rng.normal(0, 0.003, (T, N)), axis=0))).astype(np.float32)
    for j, t in fire_at.items():
        a, b = t - 120, t - 20
        c[a:b, j] = np.linspace(c[a - 1, j], c[a - 1, j] * 0.4, b - a)
        c[b:t, j] = c[b - 1, j]
        c[t:, j] = c[b - 1, j] * 1.2
    P = {"Open": c.copy(), "High": c * 1.01, "Low": c * 0.99, "Close": c.copy(),
         "Volume": np.full((T, N), 1e7, dtype=np.float32), "dates": d,
         "tickers": [f"T{k}" for k in range(N - 1)] + ["SPY"]}
    return P


def vol_panel(T=400, N=6, seed=8, vol=0.05) -> dict:
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2018-01-01", periods=T)
    c = 50 * np.exp(np.cumsum(rng.normal(0, vol, (T, N)), axis=0))
    o = c * np.exp(rng.normal(0, vol / 2, (T, N)))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, vol / 2, (T, N))))
    lo = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, vol / 2, (T, N))))
    P = {"Open": o.astype(np.float32), "High": h.astype(np.float32), "Low": lo.astype(np.float32),
         "Close": c.astype(np.float32), "Volume": np.full((T, N), 1e7, dtype=np.float32), "dates": d,
         "tickers": [f"V{k}" for k in range(N)]}
    m = rng.random((T, N))
    for f in ("Open", "High", "Low", "Close"):
        P[f][(m > 0.97) & (np.arange(T)[:, None] > 2)] = np.nan       # huecos
    P["Open"][m < 0.005] = 0.0                                          # precios en cero
    return P


def test_new_signals():
    T = 421
    P = giro_panel(T, {0: T - 1, 1: 380})
    new = A.new_signals(P)
    check("señal nueva solo en la última vela", list(new.ticker) == ["T0"] and set(new.setup) == {"CAIDA_GIRO"})
    allev = S.cooldown(S.raw_setup("CAIDA_GIRO", S.features(P)), 60)
    check("la otra señal existe pero no es nueva", (380, 1) in allev)
    ent, sal = A.approx_dates(new.fecha_senal.iloc[0])
    check("fechas aprox. de entrada y salida", pd.Timestamp(ent) > pd.Timestamp(new.fecha_senal.iloc[0])
          and len(pd.bdate_range(ent, sal)) == C.HOLD)


def test_track_equals_outcomes():
    P = vol_panel()
    T = len(P["dates"])
    ev = [(i, j) for i in range(5, T - C.HOLD - 1, 3) for j in range(len(P["tickers"]))]
    ref = S.outcomes(P, ev).set_index(["i", "j"])
    bad = 0
    kinds = set()
    skipped = 0
    for i, j in ev:
        st = A.track(P, i, j)
        if (i, j) not in ref.index:
            skipped += st["estado"] != "sin_entrada"
            continue
        r = ref.loc[(i, j)]
        kinds.add(r.reason)
        same = (st["estado"] == r.reason and abs(st["neto"] - r.net) < 1e-9
                and st["fecha_salida"] == str(P["dates"][int(r.exit_i)].date()))
        bad += not same
    check(f"bitácora = regla del estudio en {len(ref)} operaciones", bad == 0 and kinds == {"toma", "stop", "tiempo"})
    check("sin open de entrada → sin_entrada (el estudio la omite)", skipped == 0)
    st = A.track(P, T - 6, 0)
    check("con menos de 21 velas queda abierta o ya cerró por toma/stop",
          st["estado"] in ("abierta", "toma", "stop") and st.get("velas") == 5)
    check("la última vela no tiene entrada aún", A.track(P, T - 1, 0)["estado"] == "pendiente")


def test_ledger_flow():
    T = 421
    full = giro_panel(T + 30, {0: T - 1})
    short = {k: (v[:T] if isinstance(v, np.ndarray) else v) for k, v in full.items()}
    short["dates"] = full["dates"][:T]
    new = A.new_signals(short)
    led, closed = A.update_ledger(short, pd.DataFrame(), new, "2026-10-26 06:47")
    check("primera corrida: señal pendiente en bitácora", len(led) == 1 and led.estado.iloc[0] == "pendiente" and not closed)
    with tempfile.TemporaryDirectory() as d:
        led.to_csv(Path(d) / "l.csv", index=False)
        led0 = pd.read_csv(Path(d) / "l.csv", dtype=str)
    led2, closed2 = A.update_ledger(full, led0, A.new_signals(full), "2026-11-25 06:47")
    r = led2.iloc[0]
    exp = S.outcomes(full, [(T - 1, 0)]).iloc[0]
    check("corrida posterior: entra al open siguiente y cierra con la regla",
          r.estado == exp.reason and abs(float(r.neto) - exp.net) < 1e-9 and closed2 == [r.id]
          and abs(float(r.entrada) - exp.entry) < 1e-6)
    led3, closed3 = A.update_ledger(full, led2, pd.DataFrame(columns=new.columns), "2026-11-26 06:47")
    check("una cerrada no se vuelve a tocar", not closed3 and len(led3) == 1)
    ps = A.paper_stats(led2)
    check("estadística de papel", ps["cerradas"] == 1 and ps["neto_medio"] is not None)


def test_email():
    T = 421
    P = giro_panel(T, {0: T - 1})
    new = A.new_signals(P)
    led, closed = A.update_ledger(P, pd.DataFrame(), new, "2026-10-26 06:47")
    st = {"base": {"net_mean": 0.001}, "pasan": 0, "total": 3,
          "setups": {k: {"n": 100, "p_hit30": 0.2, "p_dd20": 0.3, "net_mean": -0.01, "pasa": False} for k in C.SETUPS}}
    subj, text, body = A.render("2026-10-26 06:47", str(P["dates"][-1].date()), new, led, closed, st)
    both = (subj + text + body).lower()
    check("asunto y cuerpo dicen que no es recomendación", "no recomendación de compra" in subj.lower()
          and "no recomendación de compra" in text.lower())
    check("nunca 'recomendado' ni 'recomendación' fuera del aviso",
          "recomendad" not in both and both.count("recomendaci") == both.count("no recomendación de compra"))
    check("trae niveles de referencia y dictamen", "T0" in text and "Sin ventaja demostrada" in text
          and "open × 0.85" in text and "<table" in body)
    st["setups"]["CAIDA_GIRO"]["pasa"] = True
    check("dictamen cambia si el setup pasa", A.dictamen("CAIDA_GIRO", st).startswith("Pasó la compuerta"))
    pl = A.sheet_payload("2026-10-26 06:47", A.signal_rows(new, st), led, {"x": 1})
    check("payload de la hoja con 3 pestañas", set(pl["tabs"]) == {"Señales", "Bitácora", "Resumen"}
          and pl["tabs"]["Señales"]["mode"] == "append" and len(pl["tabs"]["Señales"]["rows"]) == 1)


def test_recipient():
    keys = ("REB_EMAIL_TO", "RADAR_EMAIL_TO", "RADAR_SMTP_USER")
    saved = {k: os.environ.pop(k, None) for k in keys}
    try:
        os.environ["RADAR_SMTP_USER"] = "c@x.test"
        a = A.recipient()
        os.environ["RADAR_EMAIL_TO"] = "b@x.test"
        b = A.recipient()
        os.environ["REB_EMAIL_TO"] = "a@x.test"
        c = A.recipient()
        check("destinatario: REB_EMAIL_TO → RADAR_EMAIL_TO → RADAR_SMTP_USER", (a, b, c) == ("c@x.test", "b@x.test", "a@x.test"))
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def test_no_address_in_repo():
    root = Path(__file__).resolve().parent.parent
    try:
        files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout.split()
    except Exception:  # noqa: BLE001 — sin git (p. ej. un tarball): se revisa el árbol
        files = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]
    rx = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    found = False
    for f in files + ["sheets/rebotes_sheet.gs", "rebotes/alerta.py", "tests/test_rebotes_alerta.py"]:
        p = root / f
        if not p.is_file() or p.stat().st_size > 3_000_000:
            continue
        try:
            txt = p.read_text(errors="ignore")
        except OSError:
            continue
        if any(hashlib.sha256(m.lower().encode()).hexdigest() == USER_ADDR_SHA for m in rx.findall(txt)):
            found = True
            print("     dirección del usuario en", f)
    check("la dirección del usuario no está escrita en el repo", not found)


def main():
    for f in (test_new_signals, test_track_equals_outcomes, test_ledger_flow, test_email, test_recipient,
              test_no_address_in_repo):
        f()
    print(("OK" if not FAILS else f"FALLAS: {len(FAILS)}") + " rebotes_alerta")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
