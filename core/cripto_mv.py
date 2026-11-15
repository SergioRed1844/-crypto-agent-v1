"""Modelo multivariable de cripto: ¿cuánto más puede caer BTC, ETH y DOGE en 30/90/180 días?

Variables por día: múltiplo de Mayer, caída desde el máximo histórico, precio contra promedio de 200 semanas,
RSI semanal, volatilidad de 30 días, retorno de 30 días, Fear & Greed (alternative.me), dólar (DXY), bono a 10 años,
Nasdaq (QQQ), VIX y oferta de stablecoins (DefiLlama). Para ETH y DOGE se agregan las variables de BTC.

Tres lecturas:
1. Análogos (vecinos más cercanos): días del pasado con variables parecidas a hoy → caída adicional y retorno.
2. Modelos con validación año contra año (entrenan con años anteriores, prueban el año siguiente):
   logística P(caer ≥20% más en 90 días) y regresión por cuantiles de la caída adicional y del retorno.
3. Betas a BTC y escenarios: a qué precio quedan ETH y DOGE si BTC cae a ciertos niveles.

Corre en GitHub Actions. Uso: python -m core.cripto_mv OUT_DIR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

MONEDAS = ["BTC-USD", "ETH-USD", "DOGE-USD"]
MACRO = ["DX-Y.NYB", "^TNX", "QQQ", "^VIX", "GC=F"]
HS = (30, 90, 180)
UA = {"User-Agent": "Mozilla/5.0 (rebotes-bot; research)"}


# ---------------------------------------------------------------- datos
def history(tks: list[str]) -> pd.DataFrame:
    import yfinance as yf
    for i in range(4):
        try:
            df = yf.download(tks, start="2014-09-01", auto_adjust=True, progress=False, threads=True)["Close"]
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001
            print("reintento", i, type(e).__name__, str(e)[:120])
        time.sleep(10 * (i + 1))
    return pd.DataFrame()


def fear_greed() -> pd.Series:
    import requests
    try:
        js = requests.get("https://api.alternative.me/fng/?limit=0&format=json", headers=UA, timeout=30).json()
        d = {pd.Timestamp(int(x["timestamp"]), unit="s").normalize(): float(x["value"]) for x in js["data"]}
        return pd.Series(d).sort_index()
    except Exception as e:  # noqa: BLE001
        print("fng", type(e).__name__, str(e)[:120])
        return pd.Series(dtype=float)


def stablecoins() -> pd.Series:
    import requests
    try:
        js = requests.get("https://stablecoins.llama.fi/stablecoincharts/all", headers=UA, timeout=60).json()
        d = {}
        for x in js:
            v = (x.get("totalCirculatingUSD") or {}).get("peggedUSD")
            if v:
                d[pd.Timestamp(int(x["date"]), unit="s").normalize()] = float(v)
        return pd.Series(d).sort_index()
    except Exception as e:  # noqa: BLE001
        print("stables", type(e).__name__, str(e)[:120])
        return pd.Series(dtype=float)


def dvol() -> pd.Series:
    """Volatilidad implícita de BTC a 30 días (índice DVOL de Deribit)."""
    import requests
    out = {}
    try:
        end = int(time.time() * 1000)
        start = end - 1000 * 86400 * 1000
        url = ("https://www.deribit.com/api/v2/public/get_volatility_index_data"
               f"?currency=BTC&start_timestamp={start}&end_timestamp={end}&resolution=1D")
        js = requests.get(url, headers=UA, timeout=30).json()
        for ts, _o, _h, _l, c in js["result"]["data"]:
            out[pd.Timestamp(int(ts), unit="ms").normalize()] = float(c)
    except Exception as e:  # noqa: BLE001
        print("dvol", type(e).__name__, str(e)[:120])
    return pd.Series(out).sort_index()


# ---------------------------------------------------------------- variables
def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def variables_moneda(p: pd.Series, pref: str) -> pd.DataFrame:
    p = p.dropna()
    p = p[p > 0]
    f = pd.DataFrame(index=p.index)
    f[f"{pref}mayer"] = p / p.rolling(200, min_periods=200).mean()
    f[f"{pref}dd_ath"] = p / p.cummax() - 1
    f[f"{pref}vs200s"] = p / p.rolling(1400, min_periods=1400).mean()
    w = p.resample("W-SUN").last()
    f[f"{pref}rsi_sem"] = rsi(w).reindex(f.index, method="ffill")
    lr = np.log(p).diff()
    f[f"{pref}vol30"] = lr.rolling(30).std() * np.sqrt(365)
    f[f"{pref}r30"] = p / p.shift(30) - 1
    return f


def objetivos(p: pd.Series) -> pd.DataFrame:
    """Para cada día: caída adicional máxima (mínimo futuro / hoy − 1) y retorno a h días."""
    p = p.dropna()
    v = p.values
    out = {}
    for h in HS:
        mn = np.full(len(v), np.nan)
        rt = np.full(len(v), np.nan)
        for i in range(len(v) - h):
            mn[i] = v[i + 1:i + h + 1].min() / v[i] - 1
            rt[i] = v[i + h] / v[i] - 1
        out[f"min{h}"] = mn
        out[f"ret{h}"] = rt
    return pd.DataFrame(out, index=p.index)


def tabla(px: pd.DataFrame, fg: pd.Series, st: pd.Series, moneda: str) -> pd.DataFrame:
    idx = px[moneda].dropna().index
    f = variables_moneda(px[moneda], "")
    if moneda != "BTC-USD":
        f = f.join(variables_moneda(px["BTC-USD"], "btc_"), how="left")
    mac = px[MACRO].reindex(idx).ffill(limit=5)
    f["dxy_20d"] = mac["DX-Y.NYB"] / mac["DX-Y.NYB"].shift(28) - 1
    f["tnx_20d"] = mac["^TNX"] - mac["^TNX"].shift(28)
    f["qqq_20d"] = mac["QQQ"] / mac["QQQ"].shift(28) - 1
    f["vix"] = mac["^VIX"]
    if len(fg):
        g = fg.reindex(idx).ffill(limit=3)
        f["fg"] = g
        f["fg_7d"] = g.rolling(7).mean()
    if len(st):
        s = st.reindex(idx).ffill(limit=3)
        f["stables_30d"] = s / s.shift(30) - 1
    return f.join(objetivos(px[moneda]), how="left")


# ---------------------------------------------------------------- modelos
def analogos(df: pd.DataFrame, feats: list[str], k: int = 120, excluir_ult: int = 180) -> dict:
    """Vecinos más cercanos (distancia en variables estandarizadas) entre días con datos completos y objetivos
    conocidos; se excluyen los últimos `excluir_ult` días para no mirar hacia adelante."""
    hoy = df[feats].iloc[-1]
    if hoy.isna().any():
        feats = [c for c in feats if pd.notna(hoy[c])]
        hoy = df[feats].iloc[-1]
    base = df.iloc[:-excluir_ult].dropna(subset=feats + [f"min{HS[-1]}"])
    if len(base) < k:
        return {"n": int(len(base))}
    mu, sd = base[feats].mean(), base[feats].std().replace(0, 1)
    z = (base[feats] - mu) / sd
    zh = (hoy - mu) / sd
    dist = np.sqrt(((z - zh) ** 2).sum(axis=1))
    vec = base.loc[dist.nsmallest(k).index]
    fechas = vec.index.sort_values()
    episodios = int(1 + (np.diff(fechas.values).astype("timedelta64[D]").astype(int) > 45).sum())
    out = {"k": k, "variables": feats, "episodios": episodios,
           "fechas": [str(d.date()) for d in fechas[:: max(1, len(fechas) // 12)]]}
    for h in HS:
        m, r = vec[f"min{h}"].dropna(), vec[f"ret{h}"].dropna()
        out[f"h{h}"] = {"caida_adicional_mediana": float(m.median()), "caida_adicional_p10": float(m.quantile(0.10)),
                        "caida_adicional_p25": float(m.quantile(0.25)),
                        "p_caer_10": float((m <= -0.10).mean()), "p_caer_20": float((m <= -0.20).mean()),
                        "p_caer_30": float((m <= -0.30).mean()), "p_caer_40": float((m <= -0.40).mean()),
                        "ret_mediana": float(r.median()), "ret_p10": float(r.quantile(0.10)),
                        "ret_p90": float(r.quantile(0.90)), "p_ret_pos": float((r > 0).mean())}
    return out


def validado(df: pd.DataFrame, feats: list[str], h: int = 90, umbral: float = -0.20) -> dict:
    """Logística P(caída adicional ≥20% en h días) y cuantiles de caída/retorno, validados año contra año."""
    from sklearn.linear_model import LogisticRegression, QuantileRegressor
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    d = df.dropna(subset=feats + [f"min{h}", f"ret{h}"]).copy()
    d["y"] = (d[f"min{h}"] <= umbral).astype(int)
    anios = sorted(set(d.index.year))
    preds, ys, base_preds = [], [], []
    for a in anios[3:]:
        tr = d[d.index < pd.Timestamp(f"{a}-01-01") - pd.Timedelta(days=h)]
        te = d[d.index.year == a]
        if len(tr) < 400 or tr.y.nunique() < 2 or len(te) < 30:
            continue
        m = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000)).fit(tr[feats], tr.y)
        preds += list(m.predict_proba(te[feats])[:, 1])
        ys += list(te.y)
        base_preds += [tr.y.mean()] * len(te)
    out = {"h": h, "umbral": umbral, "variables": feats, "n_prueba": len(ys)}
    if len(set(ys)) == 2:
        out.update({"auc": float(roc_auc_score(ys, preds)), "brier": float(brier_score_loss(ys, preds)),
                    "brier_base": float(brier_score_loss(ys, base_preds)), "tasa_base": float(np.mean(ys))})
    # Modelo final con todos los datos → probabilidad para hoy
    hoy = df[feats].iloc[-1:]
    if not hoy.isna().any(axis=None):
        m = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000)).fit(d[feats], d.y)
        out["p_hoy"] = float(m.predict_proba(hoy)[:, 1][0])
        coef = m[-1].coef_[0]
        out["coeficientes"] = {f: float(c) for f, c in sorted(zip(feats, coef), key=lambda x: -abs(x[1]))}
        sub = d.iloc[::3]   # submuestra para la regresión por cuantiles (rápido)
        sc = StandardScaler().fit(sub[feats])
        X, Xh = sc.transform(sub[feats]), sc.transform(hoy)
        for nombre, col in (("caida", f"min{h}"), ("ret", f"ret{h}")):
            for q in (0.1, 0.5, 0.9):
                try:
                    qr = QuantileRegressor(quantile=q, alpha=0.001, solver="highs").fit(X, sub[col])
                    out[f"{nombre}_q{int(q * 100)}"] = float(qr.predict(Xh)[0])
                except Exception as e:  # noqa: BLE001
                    out[f"{nombre}_q{int(q * 100)}_error"] = str(e)[:100]
    return out


def betas(px: pd.DataFrame) -> dict:
    """Beta diaria y beta de 30 días de ETH y DOGE contra BTC (1 y 2 años), y beta en días de caída de BTC."""
    out = {}
    lr = np.log(px[MONEDAS]).diff()
    r30 = px[MONEDAS] / px[MONEDAS].shift(30) - 1
    hoy = px.index[-1]
    for m in ("ETH-USD", "DOGE-USD"):
        f = {}
        for anios in (1, 2):
            x = lr.loc[hoy - pd.Timedelta(days=365 * anios):, ["BTC-USD", m]].dropna()
            b = np.cov(x["BTC-USD"], x[m])[0, 1] / x["BTC-USD"].var()
            dn = x[x["BTC-USD"] < 0]
            bd = np.cov(dn["BTC-USD"], dn[m])[0, 1] / dn["BTC-USD"].var()
            y = r30.loc[hoy - pd.Timedelta(days=365 * anios):, ["BTC-USD", m]].dropna().iloc[::5]
            b30 = np.polyfit(y["BTC-USD"], y[m], 1)
            f[f"{anios}a"] = {"beta_diaria": float(b), "beta_dias_baja": float(bd), "corr": float(x.corr().iloc[0, 1]),
                              "beta_30d": float(b30[0]), "alfa_30d": float(b30[1])}
        out[m] = f
    return out


def escenarios(px: pd.DataFrame, bt: dict, ath_btc: float) -> list[dict]:
    """Precios de ETH y DOGE si BTC llega a ciertos niveles (beta de 30 días de 2 años, sin alfa)."""
    p = px[MONEDAS].dropna().iloc[-1]
    filas = []
    for nombre, nivel in [("Piso de junio 2026", 58_559.0), ("−55% desde el máximo", ath_btc * 0.45),
                          ("−60% desde el máximo", ath_btc * 0.40), ("−70% desde el máximo", ath_btc * 0.30),
                          ("−77% (como 2022)", ath_btc * 0.23)]:
            mv = nivel / p["BTC-USD"] - 1
            fila = {"escenario": nombre, "btc": float(nivel), "btc_mov": float(mv)}
            for m in ("ETH-USD", "DOGE-USD"):
                b = bt[m]["2a"]["beta_30d"]
                mov = max(-0.95, b * mv)
                fila[m] = float(p[m] * (1 + mov))
                fila[f"{m}_mov"] = float(mov)
            filas.append(fila)
    return filas


def episodios_miedo(df: pd.DataFrame) -> dict:
    """Rachas de Fear & Greed ≤ 20 desde 2018: qué pasó después (inicio de cada racha)."""
    if "fg" not in df:
        return {}
    m = df["fg"] <= 20
    ini = df.index[m & ~m.shift(1, fill_value=False)]
    filas = []
    for d in ini:
        r = df.loc[d]
        filas.append({"inicio": str(d.date()), "fg": float(r.fg), "dd_ath": float(r.dd_ath),
                      **{k: (None if pd.isna(r[k]) else float(r[k])) for k in ("min90", "ret90", "ret180")}})
    x = pd.DataFrame(filas).dropna()
    res = {"rachas": len(filas), "ultimas": filas[-8:]}
    if len(x):
        res.update({"ret90_mediana": float(x.ret90.median()), "ret90_pos": float((x.ret90 > 0).mean()),
                    "caida_adicional_90_mediana": float(x.min90.median()), "caida_adicional_90_peor": float(x.min90.min())})
    racha_actual = 0
    for v in df["fg"].iloc[::-1]:
        if pd.notna(v) and v <= 25:
            racha_actual += 1
        else:
            break
    res["dias_seguidos_fg_le_25"] = racha_actual
    return res


def main(out: str) -> int:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    px = history(MONEDAS + MACRO)
    fg, st, dv = fear_greed(), stablecoins(), dvol()
    print("historia", px.shape, "fng", len(fg), "stables", len(st), "dvol", len(dv))
    res = {"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ultimo_dia": str(px["BTC-USD"].dropna().index[-1].date())}
    feats_base = ["mayer", "dd_ath", "rsi_sem", "vol30", "r30", "dxy_20d", "tnx_20d", "qqq_20d", "vix"]
    for m in MONEDAS:
        df = tabla(px, fg, st, m)
        extra = [c for c in ("fg", "stables_30d") if c in df]
        feats_btc = ["btc_mayer", "btc_dd_ath", "btc_r30"] if m != "BTC-USD" else []
        f_an = feats_base + extra + feats_btc + (["vs200s"] if m == "BTC-USD" else [])
        hoy = df.iloc[-1]
        res[m] = {"precio": float(px[m].dropna().iloc[-1]), "ath": float(px[m].dropna().max()),
                  "hoy": {c: (None if pd.isna(hoy[c]) else float(hoy[c])) for c in f_an + ["vs200s"] if c in df},
                  "analogos": analogos(df, f_an),
                  "analogos_sin_miedo": analogos(df, [c for c in f_an if c not in ("fg", "stables_30d")]),
                  "validado_90": validado(df, [c for c in f_an if c not in ("fg", "stables_30d")]),
                  "validado_90_con_miedo": validado(df, f_an) if extra else {}}
        if m == "BTC-USD":
            res["miedo"] = episodios_miedo(df)
        print(m, json.dumps(res[m]["analogos"].get("h90", {}))[:300])
    bt = betas(px)
    res["betas"] = bt
    res["escenarios"] = escenarios(px, bt, res["BTC-USD"]["ath"])
    if len(st):
        res["stablecoins"] = {"total": float(st.iloc[-1]), "fecha": str(st.index[-1].date()),
                              "cambio_30d": float(st.iloc[-1] / st.iloc[-31] - 1), "cambio_90d": float(st.iloc[-1] / st.iloc[-91] - 1),
                              "max": float(st.max()), "fecha_max": str(st.idxmax().date())}
    if len(fg):
        res["fear_greed"] = {"hoy": float(fg.iloc[-1]), "fecha": str(fg.index[-1].date()),
                             "prom_7d": float(fg.iloc[-7:].mean()), "min_30d": float(fg.iloc[-30:].min())}
    if len(dv):
        v = float(dv.iloc[-1])
        p = res["BTC-USD"]["precio"]
        res["dvol"] = {"hoy": v, "fecha": str(dv.index[-1].date()), "media_1a": float(dv.iloc[-365:].mean()),
                       "rango_30d_1sigma": [p * np.exp(-v / 100 * np.sqrt(30 / 365)), p * np.exp(v / 100 * np.sqrt(30 / 365))],
                       "rango_30d_2sigma": [p * np.exp(-2 * v / 100 * np.sqrt(30 / 365)), p * np.exp(2 * v / 100 * np.sqrt(30 / 365))]}
    json.dump(res, open(o / "cripto_mv.json", "w"), indent=1, default=str)
    print(json.dumps({k: res.get(k) for k in ("fear_greed", "stablecoins", "dvol")}, default=str)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
