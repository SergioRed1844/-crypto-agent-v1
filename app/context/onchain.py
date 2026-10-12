"""Vigía on-chain: detecta cuándo se GASTAN monedas de la era Satoshi o de ballenas dormidas (Bitcoin mainnet).

Fuente: API REST compatible con Esplora (mempool.space; respaldo blockstream.info). Solo cuentan los gastos
(inputs): recibir monedas en direcciones viejas no significa nada (al génesis le mandan polvo a diario).
Uso: python -m app.context.onchain --state data/context/onchain_state.json --out data/context/alerts_onchain.json
"""
import argparse
import hashlib
import json
import logging
import os
import re
import struct
import sys
import time
from datetime import datetime, timezone

import httpx

log = logging.getLogger("onchain")

BASES = ("https://mempool.space/api", "https://blockstream.info/api")
UA = "cryptoagent-onchain-watch"
SAT = 100_000_000
YEAR_S = 31_557_600  # año juliano
NULL_TXID = "00" * 32
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

DEFAULTS = {
    "bootstrap_blocks": 3,        # sin estado: arranca en punta - 3
    "max_blocks": 12,             # bloques por corrida
    "satoshi_max_height": 60000,  # P2PK de aquí para abajo = era Satoshi (incluye Patoshi)
    "early_max_height": 210000,   # primera era de recompensa (50 BTC)
    "early_min_btc": 50,
    "max_p2pk_lookups": 40,       # inputs P2PK examinados por bloque
    "whale_min_btc": 100,         # salida total mínima para examinar una tx
    "input_min_btc": 5,           # inputs más chicos no se fechan
    "max_whale_txs": 15,          # txs grandes examinadas por bloque (las de mayor salida)
    "max_input_lookups": 25,      # inputs fechados por tx (los más grandes primero)
    "alta_10y_btc": 500, "alta_5y_btc": 5000, "media_5y_btc": 1000,
    "keep_alerts": 200,
}
# Peor caso por bloque: 2 + 40*2 + 15*(1+25) = 472 llamadas < max_calls → un bloque siempre cabe en una corrida
MAX_CALLS = 500
ACTION = {"critica": "RISK_OFF_EXIT", "alta": "RISK_OFF_BLOCK", "media": "CAUTION"}


# ───────────────────────── parser de bloques ─────────────────────────
def sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def _take(buf: bytes, off: int, n: int):
    end = off + n
    if n < 0 or end > len(buf):
        raise ValueError(f"datos truncados: offset {off} + {n} > {len(buf)}")
    return buf[off:end], end


def read_varint(buf: bytes, off: int):
    """CompactSize: <0xfd 1 byte; 0xfd +2; 0xfe +4; 0xff +8 (little-endian). Devuelve (valor, offset)."""
    if off >= len(buf):
        raise ValueError(f"varint fuera de rango en offset {off}")
    b = buf[off]
    if b < 0xFD:
        return b, off + 1
    raw, end = _take(buf, off + 1, {0xFD: 2, 0xFE: 4, 0xFF: 8}[b])
    return int.from_bytes(raw, "little"), end


def parse_tx(buf: bytes, offset: int = 0):
    """Una tx desde buf[offset:] (legacy o segwit BIP144). Devuelve (tx, offset_siguiente).
    txid = doble SHA-256 de la serialización SIN testigos, en orden de bytes invertido (display)."""
    start = offset
    ver, off = _take(buf, offset, 4)
    segwit = off + 1 < len(buf) and buf[off] == 0x00 and buf[off + 1] == 0x01
    if segwit:
        off += 2
    body = off
    n_in, off = read_varint(buf, off)
    vin = []
    for _ in range(n_in):
        prev, off = _take(buf, off, 32)
        idx, off = _take(buf, off, 4)
        n, off = read_varint(buf, off)
        ss, off = _take(buf, off, n)
        seq, off = _take(buf, off, 4)
        vin.append({"prev_txid": prev[::-1].hex(), "prev_vout": int.from_bytes(idx, "little"),
                    "script_sig": ss, "witness": [], "sequence": int.from_bytes(seq, "little")})
    n_out, off = read_varint(buf, off)
    vout = []
    for _ in range(n_out):
        val, off = _take(buf, off, 8)
        n, off = read_varint(buf, off)
        spk, off = _take(buf, off, n)
        vout.append({"value_sat": int.from_bytes(val, "little"), "script_pubkey": spk})
    body_end = off
    if segwit:
        for v in vin:
            items, off = read_varint(buf, off)
            for _ in range(items):
                n, off = read_varint(buf, off)
                item, off = _take(buf, off, n)
                v["witness"].append(item)
    lock, off = _take(buf, off, 4)
    nonwit = ver + buf[body:body_end] + lock if segwit else buf[start:off]
    is_cb = len(vin) == 1 and vin[0]["prev_txid"] == NULL_TXID and vin[0]["prev_vout"] == 0xFFFFFFFF
    return {"txid": sha256d(nonwit)[::-1].hex(), "is_coinbase": is_cb, "vin": vin, "vout": vout}, off


def parse_block(raw: bytes) -> dict:
    """Bloque crudo → {"header": {...}, "txs": [...]}. Hashes en display hex."""
    raw = bytes(raw)
    hdr, off = _take(raw, 0, 80)
    version, = struct.unpack_from("<i", hdr, 0)
    t, bits, nonce = struct.unpack_from("<III", hdr, 68)
    header = {"version": version, "prev_hash": hdr[4:36][::-1].hex(), "merkle_root": hdr[36:68][::-1].hex(),
              "time": t, "bits": bits, "nonce": nonce, "hash": sha256d(hdr)[::-1].hex()}
    n, off = read_varint(raw, off)
    txs = []
    for _ in range(n):
        tx, off = parse_tx(raw, off)
        txs.append(tx)
    if off != len(raw):
        raise ValueError(f"bloque con {len(raw) - off} bytes sobrantes")
    return {"header": header, "txs": txs}


def merkle_root(txids: list) -> str:
    """Raíz Merkle (display hex) desde txids en display hex; duplica el último en niveles impares."""
    if not txids:
        raise ValueError("bloque sin transacciones")
    level = [bytes.fromhex(t)[::-1] for t in txids]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0][::-1].hex()


def is_p2pk_spend(vin: dict) -> bool:
    """Gasto de salida P2PK (así están las monedas 2009-2010): sin testigo y scriptSig = UN solo push de
    70-74 bytes que empieza con 0x30 (firma DER + byte sighash). Coinbase nunca cuenta."""
    if vin.get("is_coinbase") or (vin.get("prev_txid") == NULL_TXID and vin.get("prev_vout") == 0xFFFFFFFF):
        return False
    if vin.get("witness"):
        return False
    s = vin.get("script_sig") or b""
    if len(s) >= 2 and 70 <= s[0] <= 74:   # push directo (opcode = longitud)
        n, p = s[0], 1
    elif len(s) >= 3 and s[0] == 0x4C:     # OP_PUSHDATA1 (no mínimo, pero válido)
        n, p = s[1], 2
    else:
        return False
    return 70 <= n <= 74 and len(s) == p + n and s[p] == 0x30


# ───────────────────────── cliente Esplora ─────────────────────────
class BudgetExhausted(RuntimeError):
    """Se acabó el presupuesto de llamadas de la corrida."""


class EsploraError(RuntimeError):
    """La API no respondió bien tras reintentos y respaldo."""


class EsploraClient:
    """Cliente síncrono con presupuesto, pausa entre llamadas, reintento con backoff y URL de respaldo.
    `calls` = llamadas lógicas (fallos de caché, lo que limita max_calls); `requests` = peticiones HTTP reales."""

    def __init__(self, bases=None, timeout: float = 15.0, max_calls: int = MAX_CALLS, sleep: float = 0.25,
                 retries: int = 2, backoff: float = 1.0, transport=None):
        self.bases = [b.rstrip("/") for b in (bases or BASES)]
        self.max_calls, self.sleep, self.retries, self.backoff = max_calls, sleep, retries, backoff
        self.calls = self.requests = 0
        self._pref = 0          # base que respondió último (se queda pegada tras un respaldo)
        self._last = 0.0
        self._tx, self._status = {}, {}
        self._http = httpx.Client(timeout=timeout, headers={"User-Agent": UA}, transport=transport,
                                  follow_redirects=True)

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _get(self, path: str, kind: str = "json"):
        if self.calls >= self.max_calls:
            raise BudgetExhausted(f"presupuesto de {self.max_calls} llamadas agotado")
        self.calls += 1
        err = "sin bases"
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(self.backoff * 2 ** (attempt - 1))
            retryable = False
            for k in range(len(self.bases)):
                i = (self._pref + k) % len(self.bases)
                url = self.bases[i] + path
                wait = self.sleep - (time.monotonic() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self.requests += 1
                try:
                    r = self._http.get(url)
                except httpx.HTTPError as e:
                    err, retryable = f"{url}: {type(e).__name__}", True
                    continue
                finally:
                    self._last = time.monotonic()
                if r.status_code != 200:
                    err = f"{url}: HTTP {r.status_code}"
                    retryable = retryable or r.status_code == 429 or r.status_code >= 500
                    continue
                try:
                    out = r.content if kind == "bytes" else r.text.strip() if kind == "text" else r.json()
                except ValueError:
                    err, retryable = f"{url}: respuesta inválida", True
                    continue
                self._pref = i
                return out
            if not retryable:  # 4xx en todas las bases: reintentar no sirve
                break
        raise EsploraError(err)

    def tip_height(self) -> int:
        return int(self._get("/blocks/tip/height", "text"))

    def block_hash(self, height: int) -> str:
        h = self._get(f"/block-height/{int(height)}", "text").lower()
        if not _HEX64.match(h):
            raise EsploraError(f"hash inválido para altura {height}: {h[:80]!r}")
        return h

    def raw_block(self, block_hash: str) -> bytes:
        return self._get(f"/block/{_hex64(block_hash)}/raw", "bytes")

    def block_meta(self, block_hash: str) -> dict:
        return self._get(f"/block/{_hex64(block_hash)}")

    def tx(self, txid: str) -> dict:
        if txid not in self._tx:
            t = self._get(f"/tx/{_hex64(txid)}")
            self._tx[txid] = t
            if isinstance(t.get("status"), dict):  # la tx trae su status: ahorra una llamada
                self._status.setdefault(txid, t["status"])
        return self._tx[txid]

    def tx_status(self, txid: str) -> dict:
        if txid not in self._status:
            self._status[txid] = self._get(f"/tx/{_hex64(txid)}/status")
        return self._status[txid]


def _hex64(h: str) -> str:
    if not isinstance(h, str) or not _HEX64.match(h):
        raise ValueError(f"id inválido: {h!r}")
    return h


# ───────────────────────── reglas ─────────────────────────
def _iso(ts) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alert(typ, sev, txid, height, btime, sats, extra, detail):
    return {"id": f"{typ}-{txid}", "type": typ, "severity": sev, "txid": txid, "block_height": height,
            "block_time_utc": _iso(btime), "btc_moved": round(sats / SAT, 8), **extra, "detail_es": detail,
            "url": f"https://mempool.space/tx/{txid}", "action": ACTION[sev]}


def _p2pk_rule(client, txs, height, btime, c, out):
    """SATOSHI_ERA (crítica) / EARLY_MINER (alta): gastos P2PK de salidas minadas muy temprano."""
    lookups, capped = 0, False
    for tx in txs:
        if tx["is_coinbase"]:
            continue
        hits = {"SATOSHI_ERA": [], "EARLY_MINER": []}
        for v in tx["vin"]:
            if not is_p2pk_spend(v):
                continue
            if lookups >= c["max_p2pk_lookups"]:
                capped = True
                break
            lookups += 1
            st = client.tx_status(v["prev_txid"])
            ph = st.get("block_height")
            if not st.get("confirmed") or ph is None or ph > c["early_max_height"]:
                continue  # P2PK moderno: no se pide la tx
            outs = client.tx(v["prev_txid"]).get("vout") or []
            if v["prev_vout"] >= len(outs):
                continue
            sats = int(outs[v["prev_vout"]]["value"])
            if ph <= c["satoshi_max_height"]:
                hits["SATOSHI_ERA"].append((ph, sats))
            elif sats >= c["early_min_btc"] * SAT:
                hits["EARLY_MINER"].append((ph, sats))
        for typ, hs in hits.items():
            if not hs:
                continue
            sats, oldest = sum(s for _, s in hs), min(h for h, _ in hs)
            btc = f"{sats / SAT:,.2f} BTC P2PK"
            if typ == "SATOSHI_ERA":
                sev, det = "critica", f"Se gastaron {btc} de la era Satoshi (input más viejo: bloque {oldest})."
            else:
                sev, det = "alta", f"Minero temprano gastó {btc} (input más viejo: bloque {oldest})."
            out.append(_alert(typ, sev, tx["txid"], height, btime, sats,
                              {"oldest_input_height": oldest, "n_inputs": len(hs)}, det))
        if capped:
            log.warning("bloque %d: tope de %d consultas P2PK alcanzado", height, c["max_p2pk_lookups"])
            return


def _whale_rule(client, txs, height, btime, c, out):
    """DORMANT_WHALE: txs grandes cuyos inputs llevaban 5-10+ años sin moverse."""
    cands = sorted(((sum(o["value_sat"] for o in t["vout"]), t["txid"]) for t in txs if not t["is_coinbase"]),
                   reverse=True)
    cands = [x for x in cands if x[0] >= c["whale_min_btc"] * SAT]
    if len(cands) > c["max_whale_txs"]:
        log.info("bloque %d: %d txs grandes, se examinan %d", height, len(cands), c["max_whale_txs"])
    for _, txid in cands[:c["max_whale_txs"]]:
        ins = sorted(((int(v["prevout"]["value"]), v["txid"]) for v in client.tx(txid).get("vin") or []
                      if not v.get("is_coinbase") and v.get("prevout")
                      and v["prevout"].get("value", 0) >= c["input_min_btc"] * SAT), reverse=True)
        a5 = a10 = n = 0
        max_age = 0.0
        for sats, ptx in ins[:c["max_input_lookups"]]:
            bt = client.tx_status(ptx).get("block_time")
            if bt is None:
                continue
            age = (btime - bt) / YEAR_S
            max_age = max(max_age, age)
            if age >= 5:
                a5, n = a5 + sats, n + 1
            if age >= 10:
                a10 += sats
        if a10 >= c["alta_10y_btc"] * SAT or a5 >= c["alta_5y_btc"] * SAT:
            sev = "alta"
        elif a5 >= c["media_5y_btc"] * SAT:
            sev = "media"
        else:
            continue
        det = (f"Ballena dormida movió {a5 / SAT:,.0f} BTC con ≥5 años ({a10 / SAT:,.0f} con ≥10); "
               f"el input más viejo tenía {max_age:.1f} años.")
        out.append(_alert("DORMANT_WHALE", sev, txid, height, btime, a5,
                          {"max_age_years": round(max_age, 2), "btc_aged_5y": round(a5 / SAT, 8),
                           "btc_aged_10y": round(a10 / SAT, 8), "n_inputs": n}, det))


def scan_block(client, height: int, cfg: dict = None) -> list:
    """Baja, verifica (hash + Merkle) y analiza un bloque. Si se corta a medias, la excepción lleva `.partial`."""
    c = {**DEFAULTS, **(cfg or {})}
    bh = client.block_hash(height)
    blk = parse_block(client.raw_block(bh))
    hd, txs = blk["header"], blk["txs"]
    if hd["hash"] != bh:
        raise ValueError(f"bloque {height}: hash {hd['hash']} != {bh}")
    if merkle_root([t["txid"] for t in txs]) != hd["merkle_root"]:
        raise ValueError(f"bloque {height}: la raíz Merkle no cuadra")
    alerts = []
    try:
        _p2pk_rule(client, txs, height, hd["time"], c, alerts)
        _whale_rule(client, txs, height, hd["time"], c, alerts)
    except Exception as e:
        e.partial = alerts  # las alertas ya halladas no se pierden (dedup por id al re-escanear)
        raise
    return alerts


# ───────────────────────── corrida con estado ─────────────────────────
_STOP = (BudgetExhausted, EsploraError, ValueError, KeyError, TypeError, IndexError)


def _read_json(path) -> dict:
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)  # atómico: nunca queda un JSON a medias


def _merge(out_path, found, keep) -> list:
    prev = _read_json(out_path).get("alerts") or []
    seen = {a.get("id") for a in prev if isinstance(a, dict)}
    new = []
    for a in found:
        if a["id"] not in seen:
            seen.add(a["id"])
            new.append(a)
    _write_json(out_path, {"updated_utc": _iso(time.time()), "alerts": (prev + new)[-keep:]})
    return new


def scan(client, state_path, out_path, cfg: dict = None, report: dict = None) -> list:
    """Escanea bloques nuevos (máx. max_blocks) hasta la punta; guarda estado y alertas. Devuelve las alertas nuevas.
    last_height solo avanza por bloques analizados completos. `report` (opcional) recibe scanned/new_alerts/calls."""
    c = {**DEFAULTS, **(cfg or {})}
    rep = report if report is not None else {}
    rep.update(scanned=None, new_alerts=0, calls=0, stopped=None)
    found = []
    try:
        tip = client.tip_height()
    except _STOP as e:
        log.warning("no se pudo leer la punta de la cadena: %s", e)
        rep["stopped"] = str(e)
        tip = None
    if tip is not None:
        last = _read_json(state_path).get("last_height")
        if not isinstance(last, int) or isinstance(last, bool):
            last = tip - c["bootstrap_blocks"]
        frm, to, done = last + 1, min(tip, last + c["max_blocks"]), last
        for h in range(frm, to + 1):
            try:
                found += scan_block(client, h, c)
            except _STOP as e:
                found += getattr(e, "partial", [])
                log.warning("bloque %d sin terminar (%s: %s); last_height se queda en %d", h, type(e).__name__, e, done)
                rep["stopped"] = f"{type(e).__name__}: {e}"
                break
            done = h
        _write_json(state_path, {"last_height": done, "updated_utc": _iso(time.time())})
        if done >= frm:
            rep["scanned"] = [frm, done]
    new = _merge(out_path, found, c["keep_alerts"])
    for a in new:
        log.warning("ALERTA %s %s: %.2f BTC en %s", a["severity"], a["type"], a["btc_moved"], a["url"])
    rep.update(new_alerts=len(new), calls=getattr(client, "calls", 0))
    return new


def main(argv=None):
    ap = argparse.ArgumentParser(description="Vigía on-chain: gastos de monedas era Satoshi y ballenas dormidas")
    ap.add_argument("--state", default="data/context/onchain_state.json")
    ap.add_argument("--out", default="data/context/alerts_onchain.json")
    ap.add_argument("--max-blocks", type=int, default=DEFAULTS["max_blocks"])
    ap.add_argument("--max-calls", type=int, default=MAX_CALLS)
    ap.add_argument("--base", help="URL Esplora principal; las públicas quedan de respaldo")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s onchain: %(message)s")
    bases = None
    if a.base:
        b0 = a.base.rstrip("/")
        bases = [b0] + [b for b in BASES if b != b0]
    rep = {}
    with EsploraClient(bases, max_calls=a.max_calls) as cl:
        scan(cl, a.state, a.out, {"max_blocks": a.max_blocks}, rep)
    print(json.dumps({"scanned": rep["scanned"], "new_alerts": rep["new_alerts"], "calls": rep["calls"]}))


if __name__ == "__main__":
    main()
