"""Criptos chicas (tamaño parecido a DODO) en Binance spot: cuáles muestran hoy el patrón que tuvo DODO antes de su
subida y qué pasó históricamente después de ese patrón en todo el universo. También: por qué pares se mueve DODO,
profundidad de libro, régimen de BTC (RSI semanal, Mayer) y si se tocaron las órdenes de Bitso del 16-nov.

Señal "despertar" (día t, vela diaria cerrada):
  - cierre en máximo de 90 días (rompe la base),
  - volumen 7 días ≥ 2× el promedio de los 60 días previos,
  - subida de 30 días entre +10% y +60% (todavía no explotó),
  - precio ≤ 20% de su máximo de datos (moneda vieja muy caída, como DODO −99%).
Datos: Binance (data-api.binance.vision), CoinGecko (capitalización, máximo histórico), Bitso (libros y velas).
Uso: python -m core.screener_cripto OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from core.memes import CG, get as cg_get
from core.velas_cripto import BV, get, klines, rsi

BAPI = "https://data-api.binance.vision/api/v3"
ESTABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "AEUR", "USDE", "PYUSD", "XUSD", "BFUSD", "RLUSD", "USD1",
            "EURI", "PAXG", "WBTC", "WBETH", "BUSD", "USDS", "UST", "USTC", "SUSD", "GUSD", "FRAX", "XAUT"}
CAP_MIN, CAP_MAX = 10e6, 200e6


def senales(d: pd.DataFrame) -> pd.DataFrame:
    """Columnas diarias para la señal. d: o,h,l,c,qv con índice diario."""
    c, qv = d.c, d.qv
    x = pd.DataFrame(index=d.index)
    x["c"] = c
    x["max90_prev"] = c.shift(1).rolling(90, min_periods=90).max()
    x["rompe90"] = c > x.max90_prev
    x["dist90"] = c / x.max90_prev - 1
    x["vol_ratio"] = qv.rolling(7).mean() / qv.shift(7).rolling(60, min_periods=60).mean()
    x["ret7"] = c / c.shift(7) - 1
    x["ret30"] = c / c.shift(30) - 1
    x["vs_max"] = c / c.cummax() - 1
    x["rsi"] = rsi(c)
    x["dias_datos"] = np.arange(1, len(c) + 1)
    x["despertar"] = (x.rompe90 & (x.vol_ratio >= 2) & x.ret30.between(.10, .60) & (x.vs_max <= -.80)
                      & (x.dias_datos >= 180))
    return x


def adelante(d: pd.DataFrame, i: int, n: int = 30, gana: float = .5, pierde: float = .2) -> dict | None:
    """Qué pasó en los n días siguientes al cierre del día i."""
    if i + n >= len(d):
        return None
    c0 = float(d.c.iloc[i])
    h, lo, c = d.h.iloc[i + 1:i + n + 1], d.l.iloc[i + 1:i + n + 1], d.c.iloc[i + 1:i + n + 1]
    primero = "ninguno"
    for hh, ll in zip(h, lo):
        if ll <= c0 * (1 - pierde):  # si ambos el mismo día, cuenta como pérdida (conservador)
            primero = "pierde"
            break
        if hh >= c0 * (1 + gana):
            primero = "gana"
            break
    return {"max_30d": float(h.max() / c0 - 1), "min_30d": float(lo.min() / c0 - 1),
            "ret_7d": float(c.iloc[6] / c0 - 1), "ret_30d": float(c.iloc[-1] / c0 - 1), "primero": primero}


def resumen(filas: list[dict]) -> dict:
    if not filas:
        return {"n": 0}
    x = pd.DataFrame(filas)
    r = {"n": int(len(x)), "monedas": int(x.sym.nunique()) if "sym" in x else None}
    for k in ("max_30d", "min_30d", "ret_7d", "ret_30d"):
        r[k] = {"mediana": round(float(x[k].median()), 3), "p25": round(float(x[k].quantile(.25)), 3),
                "p75": round(float(x[k].quantile(.75)), 3)}
    for u in (.3, .5, .8, 1.0, 3.0):
        r[f"P_max_+{int(u * 100)}"] = round(float((x.max_30d >= u).mean()), 3)
    r["P_min_-30"] = round(float((x.min_30d <= -.3).mean()), 3)
    r["P_ret30_pos"] = round(float((x.ret_30d > 0).mean()), 3)
    r["P_+50_antes_-20"] = round(float((x.primero == "gana").mean()), 3)
    r["P_-20_antes_+50"] = round(float((x.primero == "pierde").mean()), 3)
    return r


def eventos(sym: str, d: pd.DataFrame, x: pd.DataFrame, sep: int = 30) -> list[dict]:
    out, ult = [], -10_000
    for i in np.flatnonzero(x.despertar.values):
        if i - ult < sep:
            continue
        f = adelante(d, int(i))
        if f is None:
            continue
        ult = int(i)
        out.append({"sym": sym, "fecha": str(d.index[i].date()), "ret30_previo": round(float(x.ret30.iloc[i]), 3),
                    "vol_ratio": round(float(x.vol_ratio.iloc[i]), 2), **{k: (round(v, 3) if isinstance(v, float) else v)
                                                                         for k, v in f.items()}})
    return out


def base_dias(sym: str, d: pd.DataFrame, x: pd.DataFrame, paso: int = 5) -> list[dict]:
    """Tasa base: cualquier día (cada `paso` días) de una moneda ya −80% de su máximo, con ≥180 días de datos."""
    out = []
    ok = np.flatnonzero(((x.vs_max <= -.80) & (x.dias_datos >= 180)).values)
    for i in ok[::paso]:
        f = adelante(d, int(i))
        if f is not None:
            out.append({"sym": sym, **f})
    return out


def profundidad(sym: str, banda: float = .02) -> dict | None:
    js = get(f"{BAPI}/depth", {"symbol": sym, "limit": 1000})
    if not js or not js.get("bids"):
        return None
    b = np.array(js["bids"], dtype=float)
    a = np.array(js["asks"], dtype=float)
    mid = (b[0, 0] + a[0, 0]) / 2
    bid = float((b[b[:, 0] >= mid * (1 - banda)][:, 0] * b[b[:, 0] >= mid * (1 - banda)][:, 1]).sum())
    ask = float((a[a[:, 0] <= mid * (1 + banda)][:, 0] * a[a[:, 0] <= mid * (1 + banda)][:, 1]).sum())
    return {"mid": mid, "spread": float(a[0, 0] / b[0, 0] - 1), "compras_2pct_usd": round(bid), "ventas_2pct_usd": round(ask)}


def mercado_cg() -> dict:
    por_sym: dict[str, dict] = {}
    for p in range(1, 7):
        js = cg_get(f"{CG}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={p}"
                    "&price_change_percentage=7d,30d")
        if not js:
            continue
        for m in js:
            s = (m.get("symbol") or "").upper()
            if s and (s not in por_sym or (m.get("market_cap") or 0) > (por_sym[s].get("market_cap") or 0)):
                por_sym[s] = m
        time.sleep(3)
    return por_sym


def btc_y_ordenes() -> dict:
    r = {}
    w = klines("BTCUSDT", "1w", 400)
    if not w.empty:
        cerradas = w[w.index + pd.Timedelta(days=7) <= pd.Timestamp.now('UTC').tz_localize(None)]
        rw = rsi(cerradas.c)
        r["btc_semanal"] = {"ultima_semana_inicio": str(cerradas.index[-1].date()), "cierre": float(cerradas.c.iloc[-1]),
                            "rsi14_semanal": round(float(rw.iloc[-1]), 1),
                            "rsi_previas": [round(float(v), 1) for v in rw.iloc[-6:-1]],
                            "sma200_semanas": float(cerradas.c.rolling(200).mean().iloc[-1]),
                            "min_semana": float(cerradas.l.iloc[-1]), "semana_en_curso": {
                                "inicio": str(w.index[-1].date()), "precio": float(w.c.iloc[-1])}}
    dd = klines("BTCUSDT", "1d", 400)
    if not dd.empty:
        r["btc_diario"] = {"precio": float(dd.c.iloc[-1]), "mayer": round(float(dd.c.iloc[-1] / dd.c.rolling(200).mean().iloc[-1]), 3),
                           "sma200": float(dd.c.rolling(200).mean().iloc[-1]), "sma50": float(dd.c.rolling(50).mean().iloc[-1]),
                           "max_hist_400d": float(dd.h.max()), "ult_7": {str(t.date()): [round(float(v.l)), round(float(v.c))]
                                                                         for t, v in dd.iloc[-7:].iterrows()}}
    # mínimos desde que se programaron las órdenes (16-nov 18:00 UTC)
    desde = int(pd.Timestamp("2026-11-16T18:00:00Z").value // 1_000_000)
    for s in ("BTCUSDT", "ETHUSDT", "DOGEUSDT"):
        hh = klines(s, "1h", 1000, desde)
        if not hh.empty:
            r[f"min_{s}"] = {"min": float(hh.l.min()), "cuando": str(hh.l.idxmin()), "ultimo": float(hh.c.iloc[-1])}
    # Bitso: velas por hora (si el endpoint responde) y ticker
    for libro in ("eth_mxn", "doge_usd", "usd_mxn"):
        t = get(f"https://api.bitso.com/v3/ticker/", {"book": libro})
        if t and t.get("payload"):
            r[f"bitso_{libro}"] = {k: t["payload"].get(k) for k in ("last", "high", "low", "created_at")}
        o = get("https://bitso.com/api/v3/ohlc", {"book": libro, "time_bucket": 3600,
                                                   "start": desde, "end": int(time.time() * 1000)}, tries=2)
        if o and o.get("payload"):
            pl = o["payload"]
            r[f"bitso_{libro}"] = {**r.get(f"bitso_{libro}", {}), "ohlc_muestra": pl[:2] if isinstance(pl, list) else str(pl)[:300]}
            try:
                lows = [(float(v.get("min_rate") or v.get("low")), v.get("bucket_start_time")) for v in pl if isinstance(v, dict)]
                if lows:
                    m = min(lows)
                    r[f"bitso_{libro}"].update({"min_desde_16nov": m[0], "cuando_ms": m[1]})
            except (TypeError, ValueError) as e:
                r[f"bitso_{libro}"]["ohlc_error"] = f"{type(e).__name__}: {e}"
    return r


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res: dict = {"generado": pd.Timestamp.now('UTC').isoformat(), "rango_cap": [CAP_MIN, CAP_MAX]}
    info = get(f"{BAPI}/exchangeInfo", {"permissions": "SPOT"}) or {}
    pares = {s["symbol"]: s["baseAsset"] for s in info.get("symbols", [])
             if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"}
    tick = {t["symbol"]: t for t in (get(f"{BAPI}/ticker/24hr") or [])}
    cg = mercado_cg()
    bitso = get("https://api.bitso.com/v3/available_books/") or {}
    en_bitso = {b["book"].split("_")[0].upper() for b in bitso.get("payload", [])}
    res["bitso_bases"] = sorted(en_bitso)

    # Por qué pares se mueve DODO
    tryusd = float(tick.get("USDTTRY", {}).get("lastPrice") or "nan")
    dodo_pares = {}
    for s, t in tick.items():
        if s.startswith("DODO") and float(t.get("quoteVolume") or 0) > 0:
            q = s[4:]
            usd = float(t["quoteVolume"]) / tryusd if q == "TRY" else float(t["quoteVolume"]) if q in ("USDT", "USDC", "FDUSD") else None
            dodo_pares[s] = {"vol_quote": float(t["quoteVolume"]), "vol_usd": usd, "cambio_24h": float(t["priceChangePercent"]),
                             "ultimo": float(t["lastPrice"])}
    res["dodo_pares_24h"] = dodo_pares

    universo = []
    for sym, base in pares.items():
        if base in ESTABLES or base.startswith("BNB") or base.endswith(("UP", "DOWN", "BULL", "BEAR")):
            continue
        m = cg.get(base)
        if not m or not m.get("market_cap"):
            continue
        if CAP_MIN <= m["market_cap"] <= CAP_MAX or base == "DODO":
            universo.append((sym, base, m))
    res["universo_n"] = len(universo)

    ev, base_rows, hoy, dodo_hist = [], [], [], None
    for sym, base, m in universo:
        d = klines(sym, "1d", 1000)
        time.sleep(.15)
        if d.empty or len(d) < 200:
            continue
        d = d.iloc[:-1]  # quita la vela del día en curso (UTC)
        x = senales(d)
        ev += eventos(sym, d, x)
        base_rows += base_dias(sym, d, x)
        u = x.iloc[-1]
        t = tick.get(sym, {})
        fila = {"sym": sym, "base": base, "nombre": m.get("name"), "cap_m": round(m["market_cap"] / 1e6, 1),
                "fdv_cap": round((m.get("fully_diluted_valuation") or m["market_cap"]) / m["market_cap"], 2),
                "rank": m.get("market_cap_rank"), "vs_ath_cg": m.get("ath_change_percentage"),
                "cierre": float(u.c), "precio_vivo": float(t.get("lastPrice") or "nan"),
                "vol24_binance_m": round(float(t.get("quoteVolume") or 0) / 1e6, 2),
                "ret7": round(float(u.ret7), 3), "ret30": round(float(u.ret30), 3), "dist90": round(float(u.dist90), 3),
                "vol_ratio": round(float(u.vol_ratio), 2), "rsi": round(float(u.rsi), 1), "vs_max_datos": round(float(u.vs_max), 3),
                "despertar_hoy": bool(u.despertar), "despertar_5d": bool(x.despertar.iloc[-5:].any()),
                "ult_despertar": (str(x.index[x.despertar.values][-1].date()) if x.despertar.any() else None),
                "en_bitso": base in en_bitso}
        hoy.append(fila)
        if base == "DODO":
            dodo_hist = {"senal_dias": [str(t.date()) for t in x.index[x.despertar.values]][-10:],
                         "eventos": eventos(sym, d, x),
                         "ult_20": {str(t.date()): {"c": round(float(v.c), 5), "rompe90": bool(v.rompe90), "vol_ratio": round(float(v.vol_ratio), 2),
                                                     "ret30": round(float(v.ret30), 3), "vs_max": round(float(v.vs_max), 3)}
                                    for t, v in x.iloc[-20:].iterrows()}}
    res["dodo_senal"] = dodo_hist

    evd = pd.DataFrame(ev)
    res["estudio"] = {"despertar": resumen(ev), "tasa_base_moneda_caida": resumen(base_rows)}
    if not evd.empty:
        evd["anio"] = evd.fecha.str[:4]
        res["estudio"]["por_anio"] = {a: resumen(g.to_dict("records")) for a, g in evd.groupby("anio")}
        res["estudio"]["ultimos_eventos"] = evd.sort_values("fecha").tail(25).to_dict("records")

    h = pd.DataFrame(hoy)
    res["hoy_n"] = int(len(h))
    if not h.empty:
        res["ya_explotaron"] = h[h.ret30 >= .5].sort_values("ret30", ascending=False).head(15).to_dict("records")
        res["despertar_ultimos_5d"] = h[h.despertar_5d].sort_values("vol_ratio", ascending=False).to_dict("records")
        casi = h[(~h.despertar_5d) & (h.dist90 >= -.07) & (h.vol_ratio >= 1.5) & h.ret30.between(0, .6) & (h.vs_max_datos <= -.8)]
        res["casi"] = casi.sort_values("vol_ratio", ascending=False).head(15).to_dict("records")
        res["fuerza_relativa_7d"] = h.sort_values("ret7", ascending=False).head(15).to_dict("records")
        vig = h[(~h.despertar_5d) & (h.dist90 >= -.15) & (h.vol_ratio >= 1.5) & (h.ret30 >= -.10) & (h.ret30 < .5)
                & (h.vs_max_datos <= -.8)]
        res["vigilar"] = vig.sort_values("dist90", ascending=False).head(20).to_dict("records")
        res["tabla_hoy"] = h.to_dict("records")
        cortos = {r["sym"] for k in ("despertar_ultimos_5d", "casi", "vigilar", "ya_explotaron") for r in res[k]} | {"DODOUSDT"}
        res["libro"] = {s: profundidad(s) for s in sorted(cortos)}
    (out / "screener.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    try:
        res["btc"] = btc_y_ordenes()
    except Exception as e:  # noqa: BLE001
        res["btc"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    (out / "screener.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("universo_n", "hoy_n")}), json.dumps(res["estudio"].get("despertar"))[:800])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/screener")
