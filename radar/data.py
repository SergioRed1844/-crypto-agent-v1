"""Datos del Radar: precios diarios, miedo cripto, VIX, peso, atención (Wikipedia) y contexto v4.2.

Reglas:
- Solo fuentes públicas sin llaves (Binance data-api, Yahoo chart, Stooq, FRED csv, alternative.me, Wikimedia).
- Cada serie se guarda en caché (CSV). Si una fuente falla, se usa la caché y se reporta en `HEALTH`.
- Nunca se registra una URL con llave (aquí no hay llaves, pero el logger de httpx queda en WARNING igual).
- Las barras incompletas (día en curso) se marcan y NO se usan para disparar setups.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import numpy as np

from . import config as C

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("radar.data")

UA = {"User-Agent": "Mozilla/5.0 (RadarEB; +https://github.com/SergioRed1844/-crypto-agent-v1)"}
WIKI_UA = {"User-Agent": "RadarEB/1.0 (https://github.com/SergioRed1844/-crypto-agent-v1; research bot)"}
HEALTH: dict[str, dict] = {}    # fuente → {"ok": bool, "last": fecha, "nota": str}


@dataclass
class Series:
    sym: str
    dates: list[str] = field(default_factory=list)        # 'YYYY-MM-DD' (fecha local del mercado)
    open: np.ndarray = field(default_factory=lambda: np.array([]))
    high: np.ndarray = field(default_factory=lambda: np.array([]))
    low: np.ndarray = field(default_factory=lambda: np.array([]))
    close: np.ndarray = field(default_factory=lambda: np.array([]))
    volume: np.ndarray = field(default_factory=lambda: np.array([]))
    source: str = ""
    partial_last: bool = False                              # la última barra es del día en curso

    def __len__(self):
        return len(self.dates)

    @property
    def last_date(self) -> str | None:
        return self.dates[-1] if self.dates else None

    def complete(self) -> "Series":
        """Copia sin la barra en curso (para disparar setups solo con velas cerradas)."""
        if not self.partial_last or len(self) == 0:
            return self
        return Series(self.sym, self.dates[:-1], self.open[:-1], self.high[:-1], self.low[:-1], self.close[:-1],
                      self.volume[:-1], self.source, False)


def from_rows(sym: str, rows: list[tuple], source: str = "", partial_last: bool = False) -> Series:
    """rows: (fecha, o, h, l, c, v) ordenables; se deduplica por fecha (gana la última) y se limpian NaN."""
    by = {}
    for r in rows:
        d, o, h, l, c, v = r
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(c) or c <= 0:
            continue
        def f(x, dflt):
            try:
                x = float(x)
                return x if np.isfinite(x) and x > 0 else dflt
            except (TypeError, ValueError):
                return dflt
        by[str(d)[:10]] = (f(o, c), f(h, c), f(l, c), c, f(v, 0.0) if v not in (None, "") else 0.0)
    ds = sorted(by)
    arr = np.array([by[d] for d in ds], dtype=float).reshape(-1, 5)
    return Series(sym, ds, arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], source, partial_last)


# ── caché ───────────────────────────────────────────────────────────────────────────────────────────────
def _safe(sym: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in sym)


def cache_path(sym: str) -> str:
    return os.path.join(C.CACHE_DIR, f"{_safe(sym)}.csv")


def save_cache(s: Series) -> None:
    """CSV con una primera línea de metadatos JSON (fuente, barra parcial, hora de actualización)."""
    os.makedirs(C.CACHE_DIR, exist_ok=True)
    tmp = cache_path(s.sym) + ".tmp"
    meta = {"source": s.source, "partial_last": bool(s.partial_last),
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with open(tmp, "w", newline="") as fh:
        fh.write("#" + json.dumps(meta) + "\n")
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for i, d in enumerate(s.dates):
            w.writerow([d, f"{s.open[i]:.10g}", f"{s.high[i]:.10g}", f"{s.low[i]:.10g}", f"{s.close[i]:.10g}",
                        f"{s.volume[i]:.6g}"])
    os.replace(tmp, cache_path(s.sym))


def load_cache(sym: str) -> tuple[Series | None, float]:
    """Devuelve (serie, antigüedad de la caché en horas)."""
    p = cache_path(sym)
    if not os.path.exists(p):
        return None, 1e9
    with open(p) as fh:
        first = fh.readline()
        try:
            meta = json.loads(first[1:]) if first.startswith("#") else {}
        except ValueError:
            meta = {}
        rows = [tuple(r[:6]) for r in csv.reader(fh) if r and r[0] != "date"]
    if not rows:
        return None, 1e9
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(meta["updated"])).total_seconds() / 3600
    except (KeyError, ValueError):
        age = 1e9
    return from_rows(sym, rows, meta.get("source", "cache"), bool(meta.get("partial_last"))), age


def merge(old: Series | None, new: Series | None) -> Series | None:
    if new is None or len(new) == 0:
        return old
    if old is None or len(old) == 0:
        return new
    cut = new.dates[0]
    rows = [(d, old.open[i], old.high[i], old.low[i], old.close[i], old.volume[i])
            for i, d in enumerate(old.dates) if d < cut]
    rows += [(d, new.open[i], new.high[i], new.low[i], new.close[i], new.volume[i]) for i, d in enumerate(new.dates)]
    return from_rows(new.sym, rows, new.source, new.partial_last)


# ── HTTP ────────────────────────────────────────────────────────────────────────────────────────────────
def _client():
    import httpx
    return httpx.Client(timeout=25, follow_redirects=True, headers=UA)


def _get(client, url, params=None, headers=None, tries=3):
    last = None
    for k in range(tries):
        try:
            r = client.get(url, params=params, headers=headers)
            if r.status_code == 429:
                time.sleep(3 * (k + 1))
                last = RuntimeError("429")
                continue
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 — se reporta tipo, nunca la URL completa
            last = e
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"{type(last).__name__}: {str(last)[:120]}")


# ── fuentes de precios ──────────────────────────────────────────────────────────────────────────────────
def fetch_binance(client, sym: str, since: str = "2017-08-01") -> Series:
    url = "https://data-api.binance.vision/api/v3/klines"
    start = int(datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp() * 1000)
    rows, now_ms = [], int(time.time() * 1000)
    partial = False
    while True:
        js = _get(client, url, {"symbol": f"{sym}USDT", "interval": "1d", "startTime": start, "limit": 1000}).json()
        if not js:
            break
        for k in js:
            d = datetime.fromtimestamp(k[0] / 1000, timezone.utc).strftime("%Y-%m-%d")
            if k[6] > now_ms:
                partial = True
            rows.append((d, k[1], k[2], k[3], k[4], k[7]))   # volumen en USDT (quote)
        if len(js) < 1000:
            break
        start = js[-1][0] + 86_400_000
    s = from_rows(sym, rows, "binance", partial)
    return s


def _yahoo_complete(local_date: str, sym: str) -> bool:
    """¿La vela de ese día ya cerró? US y BMV cierran ≈21:00 UTC; damos margen a 21:30."""
    now = datetime.now(timezone.utc)
    d = date.fromisoformat(local_date)
    return now >= datetime(d.year, d.month, d.day, 21, 30, tzinfo=timezone.utc)


def fetch_yahoo(client, sym: str, rng: str = "max") -> Series:
    """Diario de Yahoo. OJO: con range=max Yahoo baja la granularidad (barras mensuales/trimestrales) en historias
    largas; por eso se pide con period1/period2 explícitos y se verifica que la serie sea diaria."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym, safe='')}"
    now = int(time.time()) + 86_400
    p1 = int(datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()) if rng == "max" else now - 40 * 86_400
    js = _get(client, url, {"period1": p1, "period2": now, "interval": "1d", "includeAdjustedClose": "true",
                            "events": "div,splits"}).json()
    res = (js.get("chart") or {}).get("result") or []
    if not res:
        raise RuntimeError(f"yahoo sin datos para {sym}")
    r = res[0]
    ts = r.get("timestamp") or []
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    adj = ((r.get("indicators", {}).get("adjclose") or [{}])[0]).get("adjclose")
    off = int((r.get("meta") or {}).get("gmtoffset") or 0)
    rows = []
    for i, t in enumerate(ts):
        c = q.get("close", [None] * len(ts))[i]
        if c is None:
            continue
        f = 1.0
        if adj and adj[i] is not None and c:
            f = adj[i] / c                                   # ajuste por dividendos/splits a toda la vela
        d = datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d")
        def g(k):
            v = q.get(k, [None] * len(ts))[i]
            return None if v is None else v * f
        rows.append((d, g("open"), g("high"), g("low"), c * f, q.get("volume", [0] * len(ts))[i] or 0))
    rows = [r for r in rows if date.fromisoformat(r[0]).weekday() < 5]      # bolsa y FX: sin fines de semana
    s = from_rows(sym, rows, "yahoo")
    check_daily(s)
    if len(s) and not _yahoo_complete(s.last_date, sym):
        s.partial_last = True
    return s


def check_daily(s: Series) -> None:
    """Rechaza series que no son diarias (mediana de separación > 4 días): mezclarlas arruina los horizontes."""
    if len(s) < 30:
        return
    d = np.array([date.fromisoformat(x).toordinal() for x in s.dates[-400:]])
    gap = float(np.median(np.diff(d)))
    if gap > 4:
        raise RuntimeError(f"serie no diaria (separación mediana {gap:.0f} días)")


def fetch_stooq(client, sym: str) -> Series:
    """Respaldo para EUA (Stooq: OHLC ajustado). No cubre BMV."""
    code = sym.lower().replace("^vix", "^vix") + ("" if sym.startswith("^") else ".us")
    txt = _get(client, "https://stooq.com/q/d/l/", {"s": code, "i": "d"}).text
    rows = []
    for r in csv.DictReader(io.StringIO(txt)):
        rows.append((r.get("Date"), r.get("Open"), r.get("High"), r.get("Low"), r.get("Close"), r.get("Volume")))
    rows = [r for r in rows if r[0] and date.fromisoformat(r[0]).weekday() < 5]
    s = from_rows(sym, rows, "stooq")
    check_daily(s)
    if not len(s):
        raise RuntimeError(f"stooq sin datos para {sym}")
    if not _yahoo_complete(s.last_date, sym):
        s.partial_last = True
    return s


FRED_IDS = {"^VIX": "VIXCLS", "MXN=X": "DEXMXUS"}


def fetch_fred_csv(client, sym: str) -> Series:
    sid = FRED_IDS[sym]
    txt = _get(client, "https://fred.stlouisfed.org/graph/fredgraph.csv", {"id": sid}).text
    rows = []
    for r in csv.reader(io.StringIO(txt)):
        if len(r) < 2 or r[0] in ("DATE", "observation_date") or r[1] in (".", ""):
            continue
        rows.append((r[0], r[1], r[1], r[1], r[1], 0))
    return from_rows(sym, rows, "fred")


def price(sym: str, client=None, full_after_h: float = 20.0) -> Series | None:
    """Serie diaria con caché. Refresco completo si la caché tiene > full_after_h horas; si no, incremental."""
    cached, age = load_cache(sym)
    if cached is not None and C.asset_class(sym) != "crypto":
        try:
            check_daily(cached)
        except RuntimeError:
            cached, age = None, 1e9                     # caché vieja con barras no diarias: se descarta
    cls = C.asset_class(sym)
    if age < 0.75 and cached is not None:            # ya se actualizó en los últimos 45 min
        HEALTH[sym] = {"ok": True, "last": cached.last_date, "nota": f"caché {cached.source}"}
        return cached
    own = client is None
    client = client or _client()
    new, err = None, None
    try:
        if cls == "crypto" and sym in C.CRYPTO:
            since = "2017-08-01"
            if cached is not None and age < full_after_h and len(cached) > 30:
                since = cached.dates[-5]
            new = fetch_binance(client, sym, since)
        else:
            rng = "max" if (cached is None or age >= full_after_h) else "1mo"
            try:
                new = fetch_yahoo(client, sym, rng)
            except Exception as e:  # noqa: BLE001
                err = e
                if sym in FRED_IDS:
                    new = fetch_fred_csv(client, sym)
                elif cls == "us" or sym == "^VIX":
                    new = fetch_stooq(client, sym)
                else:
                    raise
    except Exception as e:  # noqa: BLE001
        err = e
    finally:
        if own:
            client.close()
    if new is not None and len(new):
        full = new if (cached is None or new.dates[0] <= (cached.dates[0] if cached else "9999")) else merge(cached, new)
        save_cache(full)
        HEALTH[sym] = {"ok": True, "last": full.last_date, "nota": new.source + (f" (respaldo; {err})" if err else "")}
        return full
    HEALTH[sym] = {"ok": False, "last": cached.last_date if cached else None,
                   "nota": f"falló: {err}" + (" — uso caché" if cached else " — sin datos")}
    return cached


# ── miedo cripto y atención ─────────────────────────────────────────────────────────────────────────────
def fear_greed(client=None) -> dict[str, float]:
    """Fear & Greed cripto (alternative.me), fecha → valor. Desde 2018-02."""
    p = os.path.join(C.CACHE_DIR, "fear_greed.json")
    old = {}
    if os.path.exists(p):
        try:
            old = json.load(open(p))
        except ValueError:
            old = {}
    own = client is None
    client = client or _client()
    try:
        d = _get(client, "https://api.alternative.me/fng/", {"limit": 0, "format": "json"}).json()["data"]
        out = {datetime.fromtimestamp(int(x["timestamp"]), timezone.utc).strftime("%Y-%m-%d"): float(x["value"])
               for x in d}
        old.update(out)
        os.makedirs(C.CACHE_DIR, exist_ok=True)
        json.dump(old, open(p, "w"))
        HEALTH["fear_greed"] = {"ok": True, "last": max(old) if old else None, "nota": "alternative.me"}
    except Exception as e:  # noqa: BLE001
        HEALTH["fear_greed"] = {"ok": False, "last": max(old) if old else None, "nota": f"falló: {e}"}
    finally:
        if own:
            client.close()
    return old


def wiki_views(lang: str, article: str, client=None, start: str = "2015-07-01") -> dict[str, float]:
    """Vistas diarias de un artículo de Wikipedia (usuarios, todos los accesos). Caché incremental."""
    key = f"wiki_{lang}_{_safe(article)}"
    p = os.path.join(C.CACHE_DIR, key + ".json")
    old = {}
    if os.path.exists(p):
        try:
            old = json.load(open(p))
        except ValueError:
            old = {}
    if old:
        start = (date.fromisoformat(max(old)) - timedelta(days=3)).isoformat()
    end = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    if start > end:
        return old
    own = client is None
    client = client or _client()
    try:
        url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia/all-access/user/"
               f"{quote(article, safe='')}/daily/{start.replace('-', '')}00/{end.replace('-', '')}00")
        items = _get(client, url, headers=WIKI_UA).json().get("items", [])
        for it in items:
            old[f"{it['timestamp'][:4]}-{it['timestamp'][4:6]}-{it['timestamp'][6:8]}"] = float(it["views"])
        os.makedirs(C.CACHE_DIR, exist_ok=True)
        json.dump(old, open(p, "w"))
        HEALTH[key] = {"ok": True, "last": max(old) if old else None, "nota": "wikimedia"}
    except Exception as e:  # noqa: BLE001
        HEALTH[key] = {"ok": False, "last": max(old) if old else None, "nota": f"falló: {e}"}
    finally:
        if own:
            client.close()
    return old


def fears_index(lang: str, client=None) -> dict[str, float]:
    """Índice tipo FEARS (Da-Engelberg-Gao 2015) con Wikipedia: suma de log-vistas de términos de ansiedad.
    Es un PROXY (Wikipedia ≠ Google; C08-012 lo marca como hipótesis para México)."""
    series = [wiki_views(lang, t, client) for t in C.FEARS_TERMS[lang]]
    days = sorted(set().union(*[set(s) for s in series])) if series else []
    out = {}
    for d in days:
        vals = [s[d] for s in series if d in s]
        if len(vals) >= max(2, len(series) - 1):
            out[d] = float(np.mean(np.log1p(vals)))
    return out


# ── contexto v4.2 ───────────────────────────────────────────────────────────────────────────────────────
def context_signal(client=None) -> dict:
    """Lee el context_signal.json vivo de la rama v4.2 (raw de GitHub). Si falla: estado desconocido."""
    own = client is None
    client = client or _client()
    try:
        js = _get(client, C.CONTEXT_RAW).json()
        HEALTH["contexto_v42"] = {"ok": True, "last": js.get("generated_utc"), "nota": js.get("state")}
        return js
    except Exception as e:  # noqa: BLE001
        HEALTH["contexto_v42"] = {"ok": False, "last": None, "nota": f"falló: {e}"}
        return {"state": "DESCONOCIDO", "stale": True, "reasons": ["no se pudo leer el contexto v4.2"]}
    finally:
        if own:
            client.close()


def history_events(path: str = "data/context/sources/history_events.json") -> list[dict]:
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return []
