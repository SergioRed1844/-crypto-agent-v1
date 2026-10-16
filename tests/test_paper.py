"""Prueba en papel v4.2 (runner hacia adelante) con datos sintéticos. Corre: python -m tests.test_paper"""
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path

os.environ.update(DATA_MODE="mock", LLM_PROVIDER="mock", TRADING_MODE="paper",
                  DATABASE_URL=f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'p.db')}")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app import paper_forward as pf  # noqa: E402
from app.context.live import mock_signal  # noqa: E402

res = []
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or res.append(bool(c))


def synth(seed, p0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-06-01", "2026-10-10", freq="1h", tz="UTC")
    r = rng.normal(0.00018, 0.006, len(idx))
    c = p0 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0015, len(idx))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0015, len(idx))))
    df = pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": rng.uniform(100, 300, len(idx))}, index=idx)
    df.index.name = "ts"
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return {"1h": df, "4h": df.resample("4h").agg(agg).dropna(), "1d": df.resample("1D").agg(agg).dropna()}


dfs = {p: synth(i, p0) for i, (p, p0) in enumerate((("BTCUSDT", 60000), ("ETHUSDT", 3000), ("SOLUSDT", 150)))}
end = pd.Timestamp("2026-10-10 00:00", tz="UTC")
cut = lambda d, t: {k: v[v.index < t] for k, v in d.items()}
live_at = lambda t: {"dfs": {p: cut(d, t) for p, d in dfs.items()}, "funding": {p: (0.0001, "test") for p in dfs}, "fg": 50}
neutral = lambda now, mk: mock_signal("NEUTRAL")
blackout = lambda now, mk: mock_signal("BLACKOUT")

# 1) historia como si cada vela se procesara en vivo (sin tope de atraso), hasta un punto intermedio
pf.MAX_LAG = pd.Timedelta(days=9999)
st = pf.new_state(pd.Timestamp("2026-06-01", tz="UTC").to_pydatetime())
mid = pd.Timestamp("2026-08-01", tz="UTC")
dec = pf.process_bars(st, live_at(mid), mid.to_pydatetime(), neutral)
nA = sum(d["A"] == "entra" for d in dec)
nB = sum(d["B"] == "entra" for d in dec)
ok(len(dec) > 0 and nA >= 1, f"señales técnicas procesadas: {len(dec)}, entradas A {nA}, B {nB}")
ok(all("A" in d and "B" in d for d in dec), "cada señal registra qué hizo A y qué hizo B")
ok(len(st["portfolios"]["A"]["positions"]) <= 2 and len(st["portfolios"]["B"]["positions"]) <= 2, "máx 2 posiciones")
again = pf.process_bars(st, live_at(mid), mid.to_pydatetime(), neutral)
ok(not again, "re-correr con los mismos datos no duplica decisiones")

# 2) salidas con velas de 1H
ex = pf.manage_exits(st, live_at(end)["dfs"], end.to_pydatetime(), mock_signal("NEUTRAL"))
Rs = [t["R"] for _, t in ex]
ok(ex and all((-1.25 < r < -0.95) or (1.4 < r < 2.6) for r in Rs), f"salidas por stop/objetivo con R coherente: {Rs}")
ok(all(t["why"] in ("SL", "SL_GAP", "TP") for _, t in ex), "motivos de salida válidos")

# 3) contexto en BLACKOUT: B no entra, A sí puede
st2 = pf.new_state(pd.Timestamp("2026-06-01", tz="UTC").to_pydatetime())
d2 = pf.process_bars(st2, live_at(mid), mid.to_pydatetime(), blackout)
ok(all(d["B"].startswith("contexto BLACKOUT") for d in d2 if d["A"] == "entra" or d["B"] != "ya hay posición en el par")
   and not st2["portfolios"]["B"]["positions"], "BLACKOUT: el portafolio B no abre nada")

# 4) señal vieja (corrida atrasada > 2 h) no se opera
pf.MAX_LAG = pd.Timedelta(hours=2)
st3 = pf.new_state(pd.Timestamp("2026-07-01", tz="UTC").to_pydatetime())
d3 = pf.process_bars(st3, live_at(mid), mid.to_pydatetime(), neutral)
old = [d for d in d3 if mid - pd.Timestamp(d["t"]) > pd.Timedelta(hours=2)]
fresh_pairs = {d["pair"] for d in d3 if mid - pd.Timestamp(d["t"]) <= pd.Timedelta(hours=2) and d["A"] == "entra"}
ok(old and all(d["A"].startswith("señal vieja") and d["B"].startswith("señal vieja") for d in old)
   and set(st3["portfolios"]["A"]["positions"]) == fresh_pairs,
   f"{len(old)} señales con más de 2 h de atraso se registran pero no se operan")

# 5) corrida completa: estado, README, aviso en el primer trade
tmp = Path(tempfile.mkdtemp()) / "state.json"
pf.MAX_LAG = pd.Timedelta(days=9999)
st4 = pf.new_state(pd.Timestamp("2026-06-01", tz="UTC").to_pydatetime())
tmp.write_text(json.dumps(st4))
pf.run(tmp, mid.to_pydatetime(), live_at(mid), neutral)
out = pf.run(tmp, end.to_pydatetime(), live_at(end), neutral)
s = json.loads(tmp.read_text())
readme = (tmp.parent / "README.md").read_text()
ok(s["runs"] == 2 and "Gate de papel" in readme and "A · reglas v4.1" in readme, f"corrida completa: {out}")
ok(any(n.startswith("trades_1") for n in s["notified"]) if s["portfolios"]["B"]["trades"] else True,
   "aviso (issue) al primer trade cerrado de B")
g = pf.gate(s, (end + timedelta(days=1)).to_pydatetime())
ok(set(g["checks"]) == {"≥30 trades", "≥14 días", "ganadas >50%", "R:R promedio ≥2.0", "drawdown <10%"}, "gate de papel completo")

print(("PASS" if all(res) else "FAIL") + f" {sum(res)}/{len(res)} pruebas de papel v4.2")
raise SystemExit(0 if all(res) else 1)
