"""Ejecución: adaptador OANDA v20 (practice/live) y simulador local (paper) con la misma interfaz async.

OANDA v20 (developer.oanda.com/rest-live-v20): REST en api-fx{practice,trade}.oanda.com, streams en
stream-fx{practice,trade}.oanda.com; límites 120 req/s por IP, 20 streams y 2 conexiones nuevas/s por cuenta.
Para latencia: un solo cliente HTTP con keep-alive (sin abrir conexiones por orden), órdenes MARKET FOK con
``priceBound`` (si el precio se movió más del tope, OANDA cancela en lugar de llenar mal) y ``stopLossOnFill`` (el
stop vive en el servidor del broker desde el primer instante: si el VPS se cae, el stop sigue). El stop nunca se
mueve después (R2: stops inmutables).

El token y el número de cuenta salen solo del entorno (OANDA_TOKEN, OANDA_ACCOUNT_ID) y nunca se registran.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config as C

OANDA_TO_SYM = {p.oanda: s for s, p in C.PAIRS.items()}


@dataclass
class Quote:
    sym: str
    bid: float
    ask: float
    t_provider: float      # hora del precio según el broker (epoch s)
    t_recv: float          # hora de llegada a este proceso (epoch s)
    tradeable: bool = True

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class Fill:
    trade_id: str
    sym: str
    units: float
    price: float
    t_fill: float
    t_sent: float
    t_ack: float
    stop: float
    client_id: str
    raw: dict = field(default_factory=dict)


class OrderRejected(Exception):
    pass


def rfc3339(s: str) -> float:
    """'2026-10-19T12:30:00.123456789Z' → epoch con microsegundos (OANDA manda nanosegundos)."""
    if not s:
        return 0.0
    s = s.rstrip("Z")
    if "." in s:
        a, frac = s.split(".", 1)
        s = f"{a}.{frac[:6].ljust(6, '0')}"
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
    else:
        fmt = "%Y-%m-%dT%H:%M:%S"
    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()


def decimals(sym: str) -> int:
    return 3 if sym.endswith("JPY") else 5


def fmt_price(sym: str, x: float) -> str:
    return f"{x:.{decimals(sym)}f}"


def _redact(text: str) -> str:
    tok = os.environ.get("OANDA_TOKEN", "")
    acc = os.environ.get("OANDA_ACCOUNT_ID", "")
    for s in (tok, acc):
        if s and len(s) > 4:
            text = text.replace(s, "***")
    return text


class OandaBroker:
    name = "oanda"

    def __init__(self, mode: str, token: str | None = None, account: str | None = None, transport=None,
                 stream_transport=None):
        import httpx
        if mode not in ("practice", "live"):
            raise ValueError("OandaBroker solo opera en practice o live")
        if mode == "live" and C.mode() != "live":   # C.mode() exige FX_LIVE_CONFIRM con FX_MODE=live
            raise RuntimeError("OANDA live requiere FX_MODE=live y la confirmación humana en el entorno")
        self.mode = mode
        self.api, self.stream = C.OANDA_HOSTS[mode]
        self._token = token or os.environ.get("OANDA_TOKEN", "")
        self.account = account or os.environ.get("OANDA_ACCOUNT_ID", "")
        if not self._token or not self.account:
            raise RuntimeError("Faltan OANDA_TOKEN / OANDA_ACCOUNT_ID en el entorno")
        h = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
             "Accept-Datetime-Format": "RFC3339"}
        limits = httpx.Limits(max_keepalive_connections=4, max_connections=8, keepalive_expiry=120)
        self.http = httpx.AsyncClient(base_url=self.api, headers=h, timeout=httpx.Timeout(5.0, connect=3.0),
                                      limits=limits, transport=transport)
        self.http_stream = httpx.AsyncClient(base_url=self.stream, headers=h,
                                             timeout=httpx.Timeout(None, connect=5.0), transport=stream_transport)

    async def aclose(self):
        await self.http.aclose()
        await self.http_stream.aclose()

    async def _req(self, method: str, path: str, **kw) -> dict:
        r = await self.http.request(method, path, **kw)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:300]}
        if r.status_code >= 400:
            raise OrderRejected(_redact(f"HTTP {r.status_code}: {body.get('errorMessage') or body}"))
        return body

    # ── cuenta ─────────────────────────────────────────────────────────────────────────────────────────────────
    async def summary(self) -> dict:
        a = (await self._req("GET", f"/v3/accounts/{self.account}/summary"))["account"]
        return {"currency": a.get("currency"), "balance": float(a["balance"]), "nav": float(a["NAV"]),
                "unrealized": float(a.get("unrealizedPL", 0)), "margin_used": float(a.get("marginUsed", 0)),
                "open_trades": int(a.get("openTradeCount", 0))}

    async def open_trades(self) -> list[dict]:
        d = await self._req("GET", f"/v3/accounts/{self.account}/openTrades")
        out = []
        for t in d.get("trades", []):
            out.append({"id": t["id"], "sym": OANDA_TO_SYM.get(t["instrument"], t["instrument"]),
                        "units": float(t["currentUnits"]), "price": float(t["price"]),
                        "client_id": (t.get("clientExtensions") or {}).get("id", ""),
                        "stop": float(t["stopLossOrder"]["price"]) if t.get("stopLossOrder") else None,
                        "unrealized": float(t.get("unrealizedPL", 0)), "open_time": rfc3339(t.get("openTime", ""))})
        return out

    async def pricing(self, syms) -> dict[str, Quote]:
        inst = ",".join(C.PAIRS[s].oanda for s in syms)
        d = await self._req("GET", f"/v3/accounts/{self.account}/pricing", params={"instruments": inst})
        now = time.time()
        return {q.sym: q for q in (self._quote(p, now) for p in d.get("prices", [])) if q}

    @staticmethod
    def _quote(p: dict, now: float) -> Quote | None:
        sym = OANDA_TO_SYM.get(p.get("instrument", ""))
        if not sym or not p.get("bids") or not p.get("asks"):
            return None
        return Quote(sym, float(p["bids"][0]["price"]), float(p["asks"][0]["price"]), rfc3339(p.get("time", "")),
                     now, bool(p.get("tradeable", True)))

    # ── órdenes ────────────────────────────────────────────────────────────────────────────────────────────────
    async def market(self, sym: str, units: float, stop: float, price_bound: float, client_id: str,
                     comment: str = "") -> Fill:
        body = {"order": {
            "type": "MARKET", "instrument": C.PAIRS[sym].oanda, "units": str(int(units)), "timeInForce": "FOK",
            "positionFill": "OPEN_ONLY", "priceBound": fmt_price(sym, price_bound),
            "stopLossOnFill": {"price": fmt_price(sym, stop), "timeInForce": "GTC"},
            "clientExtensions": {"id": client_id, "tag": "fx-agente", "comment": comment[:120]},
            "tradeClientExtensions": {"id": client_id, "tag": "fx-agente", "comment": comment[:120]}}}
        t_sent = time.time()
        d = await self._req("POST", f"/v3/accounts/{self.account}/orders", content=json.dumps(body))
        t_ack = time.time()
        f = d.get("orderFillTransaction")
        if not f or not f.get("tradeOpened"):
            c = d.get("orderCancelTransaction") or d.get("orderRejectTransaction") or {}
            raise OrderRejected(f"orden no llenada: {c.get('reason') or c.get('rejectReason') or 'sin fill'}")
        return Fill(f["tradeOpened"]["tradeID"], sym, float(f["tradeOpened"]["units"]),
                    float(f.get("fullVWAP") or f.get("price")), rfc3339(f.get("time", "")), t_sent, t_ack, stop,
                    client_id, {"id": f.get("id"), "halfSpreadCost": f.get("halfSpreadCost"),
                                "financing": f.get("financing")})

    async def trade(self, trade_id: str) -> dict:
        """Estado de un trade (abierto o cerrado). ``trade_id`` puede ser '@<client id>'."""
        t = (await self._req("GET", f"/v3/accounts/{self.account}/trades/{trade_id}"))["trade"]
        return {"id": t["id"], "state": t.get("state"), "sym": OANDA_TO_SYM.get(t["instrument"], t["instrument"]),
                "units": float(t.get("currentUnits") or t.get("initialUnits") or 0),
                "price": float(t.get("averageClosePrice") or t.get("price") or 0),
                "pl": float(t.get("realizedPL", 0)) + float(t.get("financing", 0) or 0),
                "stop": float(t["stopLossOrder"]["price"]) if t.get("stopLossOrder") else None,
                "client_id": (t.get("clientExtensions") or {}).get("id", ""),
                "open_time": rfc3339(t.get("openTime", ""))}

    async def close(self, trade_id: str) -> dict:
        t_sent = time.time()
        d = await self._req("PUT", f"/v3/accounts/{self.account}/trades/{trade_id}/close",
                            content=json.dumps({"units": "ALL"}))
        f = d.get("orderFillTransaction")
        if not f:
            c = d.get("orderCancelTransaction") or {}
            raise OrderRejected(f"cierre no llenado: {c.get('reason') or 'sin fill'}")
        return {"price": float(f.get("fullVWAP") or f.get("price") or 0), "pl": float(f.get("pl", 0)),
                "financing": float(f.get("financing", 0)), "t_fill": rfc3339(f.get("time", "")),
                "t_sent": t_sent, "t_ack": time.time()}

    async def close_all(self) -> list[dict]:
        out = []
        for t in await self.open_trades():
            if (t["client_id"] or "").startswith("fx-"):
                try:
                    out.append({"id": t["id"], **(await self.close(t["id"]))})
                except OrderRejected as e:
                    out.append({"id": t["id"], "error": str(e)})
        return out

    # ── streams ────────────────────────────────────────────────────────────────────────────────────────────────
    async def stream_prices(self, syms, on_quote, stop: asyncio.Event, on_status=None):
        """Stream de precios con reconexión exponencial y vigilancia de heartbeat (OANDA manda uno cada 5 s)."""
        inst = ",".join(C.PAIRS[s].oanda for s in syms)
        path = f"/v3/accounts/{self.account}/pricing/stream"
        await self._stream(path, {"instruments": inst, "snapshot": "true"}, stop, on_status,
                           lambda d, now: on_quote(q) if d.get("type") == "PRICE" and (q := self._quote(d, now))
                           else None)

    async def stream_transactions(self, on_tx, stop: asyncio.Event, on_status=None):
        path = f"/v3/accounts/{self.account}/transactions/stream"
        await self._stream(path, {}, stop, on_status,
                           lambda d, now: on_tx(d) if d.get("type") not in ("HEARTBEAT", None) else None)

    async def _stream(self, path, params, stop, on_status, handle):
        delay = 1.0
        while not stop.is_set():
            try:
                async with self.http_stream.stream("GET", path, params=params) as r:
                    if r.status_code != 200:
                        raise OrderRejected(f"stream HTTP {r.status_code}")
                    delay = 1.0
                    if on_status:
                        on_status("conectado")
                    it = r.aiter_lines().__aiter__()
                    while not stop.is_set():
                        line = await asyncio.wait_for(it.__anext__(), timeout=15)
                        if not line:
                            continue
                        handle(json.loads(line), time.time())
            except (asyncio.TimeoutError, StopAsyncIteration):
                msg = "stream sin heartbeat 15 s: reconecto"
            except Exception as e:  # red: reconectar sin tirar el proceso
                msg = _redact(f"stream caído: {type(e).__name__}: {e}")[:200]
            else:
                msg = "stream cerrado"
            if on_status:
                on_status(msg)
            if stop.is_set():
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)   # respeta el límite de 2 conexiones nuevas por segundo


class PaperBroker:
    """Simulador: llena al bid/ask vigente + deslizamiento, stops revisados con cada precio. Saldo en USD."""
    name = "paper"

    def __init__(self, equity: float = 2000.0, quotes: dict | None = None):
        self.balance = float(equity)
        self.quotes: dict[str, Quote] = quotes if quotes is not None else {}
        self.trades: dict[str, dict] = {}
        self.closed: list[dict] = []
        self._n = 0
        self.on_tx = None

    def feed(self, q: Quote):
        self.quotes[q.sym] = q
        for tid, t in list(self.trades.items()):
            if t["sym"] != q.sym:
                continue
            hit = (q.bid <= t["stop"]) if t["units"] > 0 else (q.ask >= t["stop"])
            if hit:
                px = min(t["stop"], q.bid) if t["units"] > 0 else max(t["stop"], q.ask)
                res = self._settle(tid, px, q.t_provider or time.time())
                if self.on_tx:
                    self.on_tx({"type": "ORDER_FILL", "reason": "STOP_LOSS_ORDER", "tradesClosed": [
                        {"tradeID": tid, "realizedPL": str(res["pl"]), "price": str(px)}], "time": ""})

    def _slip(self, sym):
        p = C.PAIRS[sym]
        return p.slip_pips * p.pip

    def _settle(self, tid, px, t):
        tr = self.trades.pop(tid)
        q2u = 1.0 if tr["sym"].endswith("USD") else 1.0 / px
        pl = (px - tr["price"]) * tr["units"] * q2u
        self.balance += pl
        rec = {**tr, "id": tid, "exit": px, "pl": pl, "t_exit": t}
        self.closed.append(rec)
        return {"price": px, "pl": pl, "financing": 0.0, "t_fill": t, "t_sent": t, "t_ack": time.time()}

    async def summary(self) -> dict:
        unreal = 0.0
        for t in self.trades.values():
            q = self.quotes.get(t["sym"])
            if q:
                px = q.bid if t["units"] > 0 else q.ask
                unreal += (px - t["price"]) * t["units"] * (1.0 if t["sym"].endswith("USD") else 1.0 / px)
        return {"currency": "USD", "balance": self.balance, "nav": self.balance + unreal, "unrealized": unreal,
                "margin_used": 0.0, "open_trades": len(self.trades)}

    async def open_trades(self) -> list[dict]:
        return [{"id": k, "sym": t["sym"], "units": t["units"], "price": t["price"], "client_id": t["client_id"],
                 "stop": t["stop"], "unrealized": 0.0, "open_time": t["t"]} for k, t in self.trades.items()]

    async def market(self, sym, units, stop, price_bound, client_id, comment="") -> Fill:
        q = self.quotes.get(sym)
        if q is None or not q.tradeable:
            raise OrderRejected("sin precio")
        t_sent = time.time()
        px = q.ask + self._slip(sym) if units > 0 else q.bid - self._slip(sym)
        if (units > 0 and px > price_bound) or (units < 0 and px < price_bound):
            raise OrderRejected("orden no llenada: BOUNDS_VIOLATION")
        self._n += 1
        tid = f"P{self._n}"
        self.trades[tid] = {"sym": sym, "units": float(units), "price": px, "stop": stop, "client_id": client_id,
                            "t": q.t_provider or t_sent}
        return Fill(tid, sym, float(units), px, q.t_provider or t_sent, t_sent, time.time(), stop, client_id)

    async def trade(self, trade_id: str) -> dict:
        if trade_id.startswith("@"):
            cid = trade_id[1:]
            hit = [k for k, t in self.trades.items() if t["client_id"] == cid]
            hit_c = [c for c in self.closed if c["client_id"] == cid]
            if hit:
                trade_id = hit[0]
            elif hit_c:
                c = hit_c[-1]
                return {"id": c["id"], "state": "CLOSED", "pl": c["pl"], "price": c["exit"], "units": c["units"]}
            else:
                raise OrderRejected("trade inexistente")
        if trade_id in self.trades:
            t = self.trades[trade_id]
            return {"id": trade_id, "state": "OPEN", "sym": t["sym"], "units": t["units"], "price": t["price"],
                    "stop": t["stop"], "client_id": t["client_id"], "open_time": t["t"], "pl": 0.0}
        for c in reversed(self.closed):
            if c["id"] == trade_id:
                return {"id": trade_id, "state": "CLOSED", "pl": c["pl"], "price": c["exit"], "units": c["units"]}
        raise OrderRejected("trade inexistente")

    def dump(self) -> dict:
        return {"balance": self.balance, "trades": self.trades, "n": self._n, "closed": self.closed[-50:]}

    def load(self, st: dict):
        self.balance = float(st.get("balance", self.balance))
        self.trades = dict(st.get("trades", {}))
        self._n = int(st.get("n", 0))
        self.closed = list(st.get("closed", []))

    async def close(self, trade_id: str) -> dict:
        t = self.trades.get(trade_id)
        if not t:
            raise OrderRejected("trade inexistente")
        q = self.quotes[t["sym"]]
        px = q.bid - self._slip(t["sym"]) if t["units"] > 0 else q.ask + self._slip(t["sym"])
        return self._settle(trade_id, px, q.t_provider or time.time())

    async def close_all(self) -> list[dict]:
        return [{"id": k, **(await self.close(k))} for k in list(self.trades)]

    async def aclose(self):
        return None
