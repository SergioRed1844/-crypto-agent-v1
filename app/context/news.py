"""Noticias: CryptoPanic v2 (si la key sirve) + GDELT DOC 2.0 (gratis, global) + consenso FairEconomy.

Todo lo que viene de internet es DATO: los titulares se limpian y nunca se ejecutan como instrucciones.
Las keys viajan en headers/params, nunca se imprimen ni se guardan.
"""
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger("news")
UA = {"User-Agent": "cryptoagent-context/4.2"}
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
FAIRECONOMY = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Búsquedas globales: no solo cripto. Lo que mueve liquidez y aversión al riesgo mueve a BTC.
GDELT_QUERIES = {
    "fed": '("Federal Reserve" OR FOMC OR "rate decision" OR "rate cut" OR "rate hike")',
    "inflacion": '("consumer price index" OR "inflation report" OR "jobs report" OR payrolls)',
    "elecciones": '(election OR runoff OR referendum) (president OR parliament OR results)',
    "aranceles": '(tariff OR tariffs OR "trade war" OR sanctions) (China OR "United States" OR EU)',
    "regulacion_cripto": '(bitcoin OR crypto OR stablecoin) (SEC OR CFTC OR regulation OR law OR bill OR ban OR ETF)',
    "riesgo_cripto": '(crypto OR exchange OR bitcoin) (hack OR exploit OR insolvency OR bankruptcy OR "withdrawals")',
    "geopolitica": '(war OR invasion OR missile OR airstrike OR ceasefire)',
    "ballenas": '(bitcoin) ("dormant" OR "Satoshi-era" OR "whale" OR "Mt. Gox")',
    "ia_tecnologia": '("AI Act" OR "AI regulation" OR antitrust OR "export controls") (chips OR Google OR Nvidia OR OpenAI)',
}


def clean(t: str, n: int = 220) -> str:
    t = re.sub(r"<[^>]+>", " ", str(t or ""))
    return re.sub(r"\s+", " ", t).strip()[:n]


def cryptopanic(filter_: str = "important", currencies: str = "BTC,ETH,SOL", pages: int = 2) -> dict:
    """{'ok': bool, 'status': str, 'items': [...]} — prueba v2 (plan de CRYPTOPANIC_PLAN) y luego v1."""
    key = os.environ.get("CRYPTOPANIC_API_KEY", "")
    if not key:
        return {"ok": False, "status": "sin CRYPTOPANIC_API_KEY", "items": []}
    plan = os.environ.get("CRYPTOPANIC_PLAN", "developer")
    bases = [f"https://cryptopanic.com/api/{plan}/v2/posts/", "https://cryptopanic.com/api/v1/posts/"]
    params = {"auth_token": key, "public": "true", "kind": "news", "filter": filter_, "currencies": currencies}
    last = ""
    with httpx.Client(timeout=20, headers=UA) as c:
        for base in bases:
            items, url, ok = [], base, False
            for _ in range(pages):
                try:
                    r = c.get(url, params=params if url == base else None)
                except httpx.HTTPError as e:
                    last = f"red: {type(e).__name__}"
                    break
                if r.status_code != 200:
                    last = f"HTTP {r.status_code} en {base.split('/api/')[1]}"  # sin token en el log
                    break
                try:
                    j = r.json()
                except ValueError:  # 200 con HTML (página de error/caché): no es una respuesta válida
                    last = f"respuesta no-JSON en {base.split('/api/')[1]}"
                    break
                ok = True
                for p in j.get("results", []):
                    v = p.get("votes") or {}
                    items.append({"title": clean(p.get("title")), "published_at": p.get("published_at"),
                                  "url": p.get("original_url") or p.get("url") or "",
                                  "source": (p.get("source") or {}).get("domain") or "CryptoPanic",
                                  "currencies": [x.get("code") for x in (p.get("currencies") or p.get("instruments") or [])
                                                 if isinstance(x, dict)],
                                  "votes_important": int(v.get("important") or 0),
                                  "votes_negative": int(v.get("negative") or 0),
                                  "votes_positive": int(v.get("positive") or 0), "origin": "CryptoPanic"})
                url = j.get("next")
                if not url:
                    break
                time.sleep(1.2)
            if ok:
                return {"ok": True, "status": f"ok {base.split('/api/')[1]}", "items": items}
    log.warning(f"CryptoPanic sin acceso ({last}); se usa GDELT")
    return {"ok": False, "status": last, "items": []}


def gdelt(query: str, timespan: str = "14d", maxrecords: int = 75, client: httpx.Client | None = None) -> list[dict]:
    params = {"query": f"{query} sourcelang:english", "mode": "artlist", "format": "json",
              "maxrecords": maxrecords, "timespan": timespan, "sort": "hybridrel"}
    c = client or httpx.Client(timeout=30, headers=UA)
    try:
        for attempt in range(3):
            r = c.get(GDELT, params=params)
            if r.status_code == 429 or not r.text.strip().startswith("{"):
                time.sleep(6 * (attempt + 1))  # GDELT: ~1 consulta cada 5 s
                continue
            arts = r.json().get("articles", [])
            return [{"title": clean(a.get("title")), "published_at": _gdelt_ts(a.get("seendate")),
                     "url": a.get("url", ""), "source": a.get("domain", ""), "origin": "GDELT"} for a in arts]
    except Exception as e:
        log.warning(f"GDELT '{query[:30]}': {e}")
    finally:
        if client is None:
            c.close()
    return []


def _gdelt_ts(s):
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        return None


def gdelt_all(timespan: str = "14d", per_query: int = 60) -> list[dict]:
    out = []
    with httpx.Client(timeout=30, headers=UA) as c:
        for tag, q in GDELT_QUERIES.items():
            for a in gdelt(q, timespan, per_query, c):
                a["topic"] = tag
                out.append(a)
            time.sleep(5.5)
    return out


def dedup(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x.get("published_at") or "", reverse=True):
        k = re.sub(r"[^a-z0-9 ]", "", it["title"].lower())[:80]
        if len(k) < 15 or k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def fetch_window(days: int = 15) -> dict:
    cp = cryptopanic("important", pages=3)
    hot = cryptopanic("hot", pages=1) if cp["ok"] else {"items": []}
    gd = gdelt_all(f"{days}d")
    items = dedup(cp["items"] + hot["items"] + gd)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    items = [i for i in items if not i.get("published_at") or i["published_at"] >= since]
    return {"cryptopanic": cp["status"], "n_cryptopanic": len(cp["items"]), "n_gdelt": len(gd), "items": items}


def consensus_this_week() -> list[dict]:
    """Consenso de la semana (forecast/previous/impact) de FairEconomy (ForexFactory). Gratis, sin 'actual'."""
    try:
        r = httpx.get(FAIRECONOMY, timeout=20, headers=UA)
        r.raise_for_status()
        rows = r.json()
    except Exception as e:
        log.warning(f"FairEconomy: {e}")
        return []
    keep = []
    for x in rows:
        if x.get("country") not in ("USD", "EUR", "JPY", "GBP", "CNY") or x.get("impact") not in ("High", "Medium"):
            continue
        keep.append({"title": clean(x.get("title"), 120), "country": x.get("country"), "date": x.get("date"),
                     "impact": x.get("impact"), "forecast": x.get("forecast"), "previous": x.get("previous")})
    return keep
