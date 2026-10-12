"""Vigía on-chain sin red: parser (génesis, legacy, segwit, bloque sintético), P2PK, cliente Esplora (respaldo,
reintentos, caché, presupuesto) y escaneo con estado. Corre: python -m tests.test_onchain"""
import hashlib
import json
import os
import tempfile
import traceback

import httpx

from app.context import onchain as oc

res = []
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or res.append(bool(c))

GENESIS = (
    "0100000000000000000000000000000000000000000000000000000000000000000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a29ab5f49ffff001d1dac2b7c0101000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4d04ffff001d0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e206272696e6b206f66207365636f6e64206261696c6f757420666f722062616e6b73ffffffff0100f2052a01000000434104678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5fac00000000"
)
GENESIS_TXID = "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
GENESIS_HASH = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
GENESIS_SPK = bytes.fromhex("4104678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5fac")

BTC = 100_000_000
NULL = "00" * 32
SIG72 = b"\x30\x45" + bytes(range(1, 70)) + b"\x01"   # forma de firma DER + sighash, 72 bytes
PK33 = b"\x02" + b"\x11" * 32
P2PKH = bytes.fromhex("76a914") + b"\x22" * 20 + bytes.fromhex("88ac")
P2WPKH = bytes.fromhex("0014") + b"\x33" * 20


# ── serializadores independientes del módulo ──
def sha256d(b):
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def vi(n):
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def push(b):
    assert len(b) <= 75
    return bytes([len(b)]) + b


def inp(prev, vout=0, ss=b"", wit=(), seq=0xFFFFFFFF):
    return {"prev": prev, "vout": vout, "ss": ss, "wit": list(wit), "seq": seq}


def ser_tx(vins, vouts, segwit=False, version=2, locktime=0):
    """Devuelve (serialización completa, serialización sin testigos)."""
    ver, lt = version.to_bytes(4, "little"), locktime.to_bytes(4, "little")
    body = vi(len(vins)) + b"".join(bytes.fromhex(i["prev"])[::-1] + i["vout"].to_bytes(4, "little") + vi(len(i["ss"]))
                                   + i["ss"] + i["seq"].to_bytes(4, "little") for i in vins)
    body += vi(len(vouts)) + b"".join(v.to_bytes(8, "little") + vi(len(s)) + s for v, s in vouts)
    nonwit = ver + body + lt
    if not segwit:
        return nonwit, nonwit
    wit = b"".join(vi(len(i["wit"])) + b"".join(vi(len(x)) + x for x in i["wit"]) for i in vins)
    return ver + b"\x00\x01" + body + wit + lt, nonwit


def txid_of(nonwit):
    return sha256d(nonwit)[::-1].hex()


def merkle(txids):
    lv = [bytes.fromhex(t)[::-1] for t in txids]
    while len(lv) > 1:
        lv = lv + [lv[-1]] if len(lv) % 2 else lv
        lv = [sha256d(lv[i] + lv[i + 1]) for i in range(0, len(lv), 2)]
    return lv[0][::-1].hex()


def ser_block(txs, prev=NULL, t=1_790_000_000, bits=0x207FFFFF, nonce=7, version=0x20000000):
    """txs = [(full, nonwit)]. Devuelve (bloque crudo, hash display)."""
    mr = merkle([txid_of(nw) for _, nw in txs])
    hdr = (version.to_bytes(4, "little") + bytes.fromhex(prev)[::-1] + bytes.fromhex(mr)[::-1]
           + t.to_bytes(4, "little") + bits.to_bytes(4, "little") + nonce.to_bytes(4, "little"))
    return hdr + vi(len(txs)) + b"".join(f for f, _ in txs), sha256d(hdr)[::-1].hex()


def coinbase(height, ss=None):
    return ser_tx([inp(NULL, 0xFFFFFFFF, ss or push(height.to_bytes(3, "little")) + push(b"cryptoagent"))],
                  [(312_500_000, P2WPKH)])


class FakeClient(oc.EsploraClient):
    """EsploraClient real sobre un transporte falso respaldado por un dict {ruta: respuesta}; registra las rutas."""

    def __init__(self, routes, **kw):
        self.routes, self.log = routes, []
        super().__init__(["https://fake.test/api"], sleep=0, backoff=0, transport=httpx.MockTransport(self._h), **kw)

    def _h(self, req):
        p = req.url.path.removeprefix("/api")
        self.log.append(p)
        v = self.routes.get(p)
        if v is None:
            return httpx.Response(404, text="not found")
        if isinstance(v, bytes):
            return httpx.Response(200, content=v)
        if isinstance(v, str):
            return httpx.Response(200, text=v)
        return httpx.Response(200, json=v)


# ── 1. génesis ──
def t_genesis():
    b = oc.parse_block(bytes.fromhex(GENESIS))
    tx = b["txs"][0]
    ok(len(b["txs"]) == 1 and tx["txid"] == GENESIS_TXID, f"génesis: txid coinbase {tx['txid']}")
    ok(tx["is_coinbase"] and len(tx["vout"]) == 1 and tx["vout"][0]["value_sat"] == 5_000_000_000,
       "génesis: coinbase con 1 salida de 5000000000 sats")
    ok(b["header"]["merkle_root"] == GENESIS_TXID and oc.merkle_root([tx["txid"]]) == GENESIS_TXID,
       "génesis: raíz Merkle = txid")
    ok(b["header"]["hash"] == GENESIS_HASH, f"génesis: hash {b['header']['hash']}")
    ok(b["header"]["time"] == 1231006505 and b["header"]["nonce"] == 2083236893 and b["header"]["bits"] == 0x1D00FFFF,
       "génesis: time/nonce/bits")
    ok(not oc.is_p2pk_spend(tx["vin"][0]), "génesis: input coinbase no es gasto P2PK")


# ── 2. varints ──
def t_varints():
    cases = [(bytes([0xFC]), 0xFC), (b"\xfd\xfd\x00", 0xFD), (b"\xfd\xff\xff", 0xFFFF),
             (b"\xfe\x00\x00\x01\x00", 0x10000), (b"\xff" + (2 ** 40 + 5).to_bytes(8, "little"), 2 ** 40 + 5)]
    ok(all(oc.read_varint(b, 0) == (v, len(b)) for b, v in cases), "varint 1/3/5/9 bytes")
    big = bytes(300)  # script de 300 bytes (longitud 0xfd) y 260 salidas (conteo 0xfd)
    full, nw = ser_tx([inp("ab" * 32, 1, push(SIG72) + push(PK33))], [(i, P2WPKH) for i in range(259)] + [(9, big)])
    tx, end = oc.parse_tx(full, 0)
    ok(end == len(full) and len(tx["vout"]) == 260 and tx["vout"][-1]["script_pubkey"] == big
       and tx["vout"][100]["value_sat"] == 100 and tx["txid"] == txid_of(nw), "tx con 260 salidas y script de 300 bytes")
    try:
        oc.parse_tx(full[:-3], 0)
        ok(False, "tx truncada debería fallar")
    except ValueError:
        ok(True, "tx truncada → ValueError")


# ── 3. legacy y segwit ──
def t_tx_roundtrip():
    lf, lnw = ser_tx([inp("cd" * 32, 3, push(SIG72) + push(PK33), seq=0xFFFFFFFE)], [(12_345, P2PKH), (6_789, P2WPKH)],
                     version=1, locktime=800_000)
    lt, end = oc.parse_tx(b"\x99" * 7 + lf, 7)  # con offset
    v = lt["vin"][0]
    ok(end == 7 + len(lf) and lt["txid"] == txid_of(lnw) and not lt["is_coinbase"], "legacy: txid y offset")
    ok(v["prev_txid"] == "cd" * 32 and v["prev_vout"] == 3 and v["script_sig"] == push(SIG72) + push(PK33)
       and v["witness"] == [] and v["sequence"] == 0xFFFFFFFE, "legacy: campos del input")
    ok([o["value_sat"] for o in lt["vout"]] == [12_345, 6_789] and lt["vout"][0]["script_pubkey"] == P2PKH,
       "legacy: salidas")
    sf, snw = ser_tx([inp("ef" * 32, 0, wit=[SIG72, PK33]), inp("12" * 32, 5, push(SIG72) + push(PK33))],
                     [(50_000, P2WPKH)], segwit=True)
    st, end = oc.parse_tx(sf, 0)
    ok(end == len(sf) and st["txid"] == txid_of(snw) and st["txid"] != txid_of(sf),
       "segwit: txid excluye los testigos")
    ok(st["vin"][0]["witness"] == [SIG72, PK33] and st["vin"][0]["script_sig"] == b""
       and st["vin"][1]["witness"] == [] and st["vin"][1]["prev_vout"] == 5, "segwit: pilas de testigos por input")


# ── 4. bloque sintético ──
def t_block():
    txs = [coinbase(123)] + [ser_tx([inp(f"{i:02x}" * 32, i, wit=[SIG72, PK33])], [(i * 1000, P2WPKH)], segwit=i % 2 == 0)
                             for i in range(1, 5)]
    raw, h = ser_block(txs, prev="aa" * 32, t=1_790_000_123, nonce=42)
    b = oc.parse_block(raw)
    hd = b["header"]
    ok(hd["hash"] == h and hd["prev_hash"] == "aa" * 32 and hd["time"] == 1_790_000_123 and hd["nonce"] == 42
       and hd["bits"] == 0x207FFFFF and hd["version"] == 0x20000000, "bloque: encabezado")
    ok([t["txid"] for t in b["txs"]] == [txid_of(nw) for _, nw in txs], "bloque: 5 txid (mezcla legacy/segwit)")
    ok(hd["merkle_root"] == oc.merkle_root([t["txid"] for t in b["txs"]]), "bloque: Merkle impar (duplica el último)")
    ok(b["txs"][0]["is_coinbase"] and not any(t["is_coinbase"] for t in b["txs"][1:]), "bloque: solo la 1a es coinbase")
    try:
        oc.parse_block(raw + b"\x00")
        ok(False, "bytes sobrantes deberían fallar")
    except ValueError:
        ok(True, "bloque con bytes sobrantes → ValueError")


# ── 5. P2PK ──
def t_p2pk():
    base = {"prev_txid": "11" * 32, "prev_vout": 0, "witness": [], "sequence": 0xFFFFFFFF}
    ok(oc.is_p2pk_spend({**base, "script_sig": push(SIG72)}), "P2PK: un push de 72 bytes con 0x30")
    ok(oc.is_p2pk_spend({**base, "script_sig": b"\x4c\x47" + SIG72[:71]}), "P2PK: OP_PUSHDATA1 de 71 bytes")
    ok(not oc.is_p2pk_spend({**base, "script_sig": push(SIG72) + push(PK33)}), "P2PKH (firma + pubkey) no cuenta")
    ok(not oc.is_p2pk_spend({**base, "script_sig": b"", "witness": [SIG72, PK33]}), "gasto con testigo no cuenta")
    ok(not oc.is_p2pk_spend({**base, "script_sig": push(SIG72), "witness": [SIG72]}), "push P2PK + testigo no cuenta")
    ok(not oc.is_p2pk_spend({**base, "prev_txid": NULL, "prev_vout": 0xFFFFFFFF, "script_sig": push(SIG72)}),
       "coinbase con scriptSig parecido no cuenta")
    ok(not oc.is_p2pk_spend({**base, "script_sig": push(SIG72[:69])}), "push de 69 bytes no cuenta")
    ok(not oc.is_p2pk_spend({**base, "script_sig": push(b"\x31" + SIG72[1:])}), "payload sin 0x30 no cuenta")
    ok(not oc.is_p2pk_spend({**base, "script_sig": push(SIG72)[:-1]}), "push incompleto no cuenta")


# ── 6. cliente Esplora (MockTransport, sin red) ──
def t_client():
    seen = []

    def h_fallback(req):
        seen.append((req.url.host, req.url.path, req.headers.get("user-agent")))
        if req.url.host == "a.test":
            return httpx.Response(429)
        return httpx.Response(200, text={"/api/blocks/tip/height": "900003\n",
                                         "/api/block-height/900001": ("ab" * 32) + "\n"}.get(req.url.path, ""))

    c = oc.EsploraClient(["http://a.test/api/", "http://b.test/api"], sleep=0, backoff=0,
                         transport=httpx.MockTransport(h_fallback))
    tip, bh = c.tip_height(), c.block_hash(900001)
    ok(tip == 900003 and bh == "ab" * 32, "cliente: 429 en la principal → responde la de respaldo")
    ok([s[0] for s in seen] == ["a.test", "b.test", "b.test"] and c.calls == 2 and c.requests == 3,
       f"cliente: se queda en la base que respondió {[s[0] for s in seen]}")
    ok(all(s[2] == "cryptoagent-onchain-watch" for s in seen), "cliente: User-Agent propio")

    n = {"k": 0}

    def h_retry(req):
        n["k"] += 1
        return httpx.Response(503) if n["k"] <= 2 else httpx.Response(200, text="5")

    c = oc.EsploraClient(["http://a.test/api", "http://b.test/api"], sleep=0, backoff=0, transport=httpx.MockTransport(h_retry))
    ok(c.tip_height() == 5 and c.requests == 3 and c.calls == 1, "cliente: 503 en ambas → backoff y reintento")

    def h_404(req):
        return httpx.Response(404)

    c = oc.EsploraClient(["http://a.test/api", "http://b.test/api"], sleep=0, backoff=0, transport=httpx.MockTransport(h_404))
    try:
        c.tx("ab" * 32)
        ok(False, "404 debería lanzar EsploraError")
    except oc.EsploraError:
        ok(c.requests == 2, f"cliente: 404 en ambas → EsploraError sin rondas extra ({c.requests} peticiones)")

    def h_net(req):
        if req.url.host == "a.test":
            raise httpx.ConnectError("caída", request=req)
        return httpx.Response(200, json={"timestamp": 1_790_000_000})

    c = oc.EsploraClient(["http://a.test/api", "http://b.test/api"], sleep=0, backoff=0, transport=httpx.MockTransport(h_net))
    ok(c.block_meta("cd" * 32)["timestamp"] == 1_790_000_000, "cliente: error de red → respaldo")

    t1, t2 = "e1" * 32, "e2" * 32
    fc = FakeClient({f"/tx/{t1}": {"txid": t1, "vout": [], "status": {"confirmed": True, "block_height": 9}},
                     f"/block/{'cd' * 32}/raw": b"\x00\x01\xff", "/block-height/1": "no-es-hash",
                     f"/tx/{t2}/status": {"confirmed": True}}, max_calls=3)
    fc.tx(t1), fc.tx(t1)
    st = fc.tx_status(t1)
    ok(fc.calls == 1 and st["block_height"] == 9, "cliente: caché de tx y status (tx trae su status)")
    ok(fc.raw_block("cd" * 32) == b"\x00\x01\xff" and fc.calls == 2, "cliente: bloque crudo en bytes")
    try:
        fc.block_hash(1)
        ok(False, "hash inválido debería fallar")
    except oc.EsploraError:
        ok(True, "cliente: texto que no es hash → EsploraError")
    try:
        fc.tx_status(t2)
        ok(False, "presupuesto agotado debería lanzar")
    except oc.BudgetExhausted:
        ok(fc.calls == 3 and fc.log.count(f"/tx/{t2}/status") == 0, "cliente: presupuesto agotado → BudgetExhausted")


# ── 7-8. escenario: 3 bloques con estado ──
T1 = 1_790_000_000
P1, P2a, P2b, P3, P4, P5, P6, P7 = ("a1" * 32, "b1" * 32, "b2" * 32, "c1" * 32, "d1" * 32, "e1" * 32, "f1" * 32,
                                    "a7" * 32)


def st_(h, t):
    return {"confirmed": True, "block_height": h, "block_hash": "99" * 32, "block_time": t}


def build_chain():
    tx_i = ser_tx([inp(P1, 0, push(SIG72))], [(50 * BTC - 10_000, P2WPKH)])                    # (i) P2PK de 2009
    tx_ii = ser_tx([inp(P2a, 0, push(SIG72) + push(PK33)), inp(P2b, 1, push(SIG72) + push(PK33))],
                   [(2000 * BTC, P2PKH), (1000 * BTC - 20_000, P2WPKH)])                         # (ii) 3000 BTC de 12 años
    tx_iii = ser_tx([inp(P3, 0, wit=[SIG72, PK33])], [(200 * BTC, P2WPKH)], segwit=True)        # (iii) 200 BTC frescos
    tx_iv = ser_tx([inp(P4, 2, wit=[SIG72, PK33])], [(546, GENESIS_SPK), (1_000_000, P2WPKH)], segwit=True)  # (iv) polvo AL génesis
    raw1, h1 = ser_block([coinbase(900001), tx_i, tx_ii, tx_iii, tx_iv], prev="77" * 32, t=T1)
    tx_v = ser_tx([inp(P5, 0, push(SIG72))], [(50 * BTC - 10_000, P2WPKH)])                    # P2PK de altura 100000
    tx_vi = ser_tx([inp(P6, 0, push(SIG72))], [(BTC, P2WPKH)])                                  # P2PK moderno (300000)
    tx_vii = ser_tx([inp(P7, 0, push(SIG72) + push(PK33))], [(1500 * BTC - 10_000, P2PKH)])     # 1500 BTC de 6 años
    raw2, h2 = ser_block([coinbase(900002), tx_v, tx_vi, tx_vii], prev=h1, t=T1 + 600)
    raw3, h3 = ser_block([coinbase(900003)], prev=h2, t=T1 + 1200)
    ids = {k: txid_of(v[1]) for k, v in dict(i=tx_i, ii=tx_ii, iii=tx_iii, iv=tx_iv, v=tx_v, vi=tx_vi, vii=tx_vii).items()}

    def ptx(txid, vin, vout_vals, status):
        return {"txid": txid, "vin": vin, "vout": [{"value": x, "scriptpubkey_type": "p2pk"} for x in vout_vals],
                "status": status}

    def pin(prev, vout, sats):
        return {"txid": prev, "vout": vout, "is_coinbase": False, "prevout": {"value": sats, "scriptpubkey_type": "p2pkh"}}

    y12, y6 = T1 - int(12 * oc.YEAR_S), T1 + 600 - int(6 * oc.YEAR_S)
    routes = {
        "/blocks/tip/height": "900003",
        "/block-height/900001": h1, f"/block/{h1}/raw": raw1,
        "/block-height/900002": h2, f"/block/{h2}/raw": raw2,
        "/block-height/900003": h3, f"/block/{h3}/raw": raw3,
        f"/tx/{P1}/status": st_(1500, 1_233_100_000),
        f"/tx/{P1}": ptx(P1, [{"is_coinbase": True, "prevout": None}], [50 * BTC], st_(1500, 1_233_100_000)),
        f"/tx/{ids['ii']}": ptx(ids["ii"], [pin(P2a, 0, 1500 * BTC), pin(P2b, 1, 1500 * BTC)], [], st_(900001, T1)),
        f"/tx/{P2a}/status": st_(330_000, y12), f"/tx/{P2b}/status": st_(330_001, y12),
        f"/tx/{ids['iii']}": ptx(ids["iii"], [pin(P3, 0, 200 * BTC + 5000)], [], st_(900001, T1)),
        f"/tx/{P3}/status": st_(900_000, T1 - 3600),
        f"/tx/{P5}/status": st_(100_000, 1_293_000_000),
        f"/tx/{P5}": ptx(P5, [{"is_coinbase": True, "prevout": None}], [50 * BTC], st_(100_000, 1_293_000_000)),
        f"/tx/{P6}/status": st_(300_000, 1_400_000_000),
        f"/tx/{ids['vii']}": ptx(ids["vii"], [pin(P7, 0, 1500 * BTC)], [], st_(900002, T1 + 600)),
        f"/tx/{P7}/status": st_(500_000, y6),
    }
    return routes, ids, (h1, h2, h3)


KEYS = {"id", "type", "severity", "txid", "block_height", "block_time_utc", "btc_moved", "detail_es", "url", "action"}


def t_scan_block():
    routes, ids, _ = build_chain()
    fc = FakeClient(routes)
    al = oc.scan_block(fc, 900001, {})
    by = {a["type"]: a for a in al}
    ok(len(al) == 2 and set(by) == {"SATOSHI_ERA", "DORMANT_WHALE"}, f"bloque 1: 2 alertas {[a['id'][:20] for a in al]}")
    s = by.get("SATOSHI_ERA", {})
    ok(s.get("txid") == ids["i"] and s.get("severity") == "critica" and s.get("action") == "RISK_OFF_EXIT"
       and s.get("btc_moved") == 50.0 and s.get("oldest_input_height") == 1500 and s.get("id") == f"SATOSHI_ERA-{ids['i']}",
       f"(i) SATOSHI_ERA crítica: {s.get('btc_moved')} BTC del bloque {s.get('oldest_input_height')}")
    w = by.get("DORMANT_WHALE", {})
    ok(w.get("txid") == ids["ii"] and w.get("severity") == "alta" and w.get("action") == "RISK_OFF_BLOCK"
       and w.get("btc_moved") == 3000.0 and abs(w.get("max_age_years", 0) - 12) < 0.01,
       f"(ii) DORMANT_WHALE alta: {w.get('btc_moved')} BTC, {w.get('max_age_years')} años")
    ok(all(KEYS <= set(a) for a in al) and s.get("block_time_utc") == "2026-09-21T14:13:20Z"
       and s.get("url") == f"https://mempool.space/tx/{ids['i']}" and s.get("block_height") == 900001,
       "alertas: campos completos (hora ISO Z, url, altura)")
    ok(f"/tx/{ids['iii']}" in fc.log and not any(a["txid"] == ids["iii"] for a in al),
       "(iii) 200 BTC con inputs frescos: examinada, sin alerta")
    ok(not any(P4 in p or ids["iv"] in p for p in fc.log) and not any(a["txid"] == ids["iv"] for a in al),
       "(iv) polvo enviado AL génesis: ni se consulta ni alerta")
    ok(fc.calls == 9, f"bloque 1 en {fc.calls} llamadas")

    fc = FakeClient(routes)
    al = oc.scan_block(fc, 900001, {"max_whale_txs": 1, "max_p2pk_lookups": 0})
    ok([a["type"] for a in al] == ["DORMANT_WHALE"] and f"/tx/{ids['iii']}" not in fc.log
       and f"/tx/{P1}/status" not in fc.log, "topes por bloque: max_whale_txs=1 y max_p2pk_lookups=0")

    fc = FakeClient(routes)
    al = oc.scan_block(fc, 900002, {})
    by = {a["type"]: a for a in al}
    ok(set(by) == {"EARLY_MINER", "DORMANT_WHALE"} and by["EARLY_MINER"]["severity"] == "alta"
       and by["EARLY_MINER"]["txid"] == ids["v"] and by["DORMANT_WHALE"]["severity"] == "media"
       and by["DORMANT_WHALE"]["action"] == "CAUTION" and by["DORMANT_WHALE"]["txid"] == ids["vii"],
       f"bloque 2: EARLY_MINER alta + ballena media {sorted(by)}")
    ok(f"/tx/{P6}" not in fc.log, "P2PK moderno (altura 300000): solo status, sin alerta")

    bad = dict(routes)
    bad[f"/block/{routes['/block-height/900003']}/raw"] = routes[f"/block/{routes['/block-height/900002']}/raw"]
    try:
        oc.scan_block(FakeClient(bad), 900003, {})
        ok(False, "bloque con hash distinto debería fallar")
    except ValueError:
        ok(True, "bloque crudo que no corresponde al hash → ValueError")


def t_scan_state():
    routes, ids, _ = build_chain()
    d = tempfile.mkdtemp()
    sp, op = os.path.join(d, "ctx", "onchain_state.json"), os.path.join(d, "ctx", "alerts_onchain.json")
    load = lambda p: json.load(open(p))

    # presupuesto se agota a mitad del bloque 2 (ya halló EARLY_MINER): last_height se queda en 900001
    rep = {}
    new = oc.scan(FakeClient(routes, max_calls=14), sp, op, {}, rep)
    ok(load(sp)["last_height"] == 900001 and rep["scanned"] == [900001, 900001] and "Budget" in (rep["stopped"] or ""),
       f"sin estado arranca en punta-3; presupuesto agotado no avanza: {load(sp)['last_height']} {rep}")
    ok(sorted(a["type"] for a in new) == ["DORMANT_WHALE", "EARLY_MINER", "SATOSHI_ERA"],
       "alertas del bloque a medias se conservan")

    rep = {}
    new = oc.scan(FakeClient(routes), sp, op, {}, rep)
    out = load(op)
    ok(load(sp)["last_height"] == 900003 and rep["scanned"] == [900002, 900003] and rep["calls"] == 10,
       f"siguiente corrida retoma en 900002 y llega a la punta {rep}")
    ok([a["id"] for a in new] == [f"DORMANT_WHALE-{ids['vii']}"] and len(out["alerts"]) == 4
       and len({a["id"] for a in out["alerts"]}) == 4 and out["updated_utc"].endswith("Z"),
       f"dedup: EARLY_MINER no se repite; archivo con {len(out['alerts'])} alertas")

    rep = {}
    new = oc.scan(FakeClient(routes), sp, op, {}, rep)
    ok(new == [] and rep["scanned"] is None and rep["calls"] == 1 and load(sp)["last_height"] == 900003,
       "en la punta: nada que escanear (1 llamada)")

    json.dump({"last_height": 900000}, open(sp, "w"))
    rep = {}
    new = oc.scan(FakeClient(routes), sp, op, {}, rep)
    ok(new == [] and len(load(op)["alerts"]) == 4 and load(sp)["last_height"] == 900003 and rep["calls"] == 19,
       f"re-escaneo completo: 0 nuevas, sigue en 4 alertas ({rep['calls']} llamadas)")

    json.dump({"last_height": 900000}, open(sp, "w"))
    op2 = os.path.join(d, "ctx", "alerts2.json")
    rep = {}
    new = oc.scan(FakeClient(routes, max_calls=3), sp, op2, {}, rep)
    ok(load(sp)["last_height"] == 900000 and rep["scanned"] is None and new == [] and load(op2)["alerts"] == [],
       "presupuesto agotado dentro del primer bloque: last_height no se mueve")

    rep = {}
    new = oc.scan(FakeClient(routes), sp, op2, {"max_blocks": 1}, rep)
    ok(rep["scanned"] == [900001, 900001] and load(sp)["last_height"] == 900001 and len(new) == 2, "max_blocks=1")


for fn in (t_genesis, t_varints, t_tx_roundtrip, t_block, t_p2pk, t_client, t_scan_block, t_scan_state):
    try:
        fn()
    except Exception as e:  # una excepción es un FAIL, no un traceback suelto
        traceback.print_exc()
        ok(False, f"{fn.__name__} lanzó {type(e).__name__}: {e}")

print(f"\n{'PASS' if all(res) else 'FAIL'} {sum(res)}/{len(res)} pruebas on-chain")
raise SystemExit(0 if all(res) else 1)
