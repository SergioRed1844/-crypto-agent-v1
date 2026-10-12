"""Camino LIVE contra un exchange falso que SÍ respeta saldos, comisiones y estados de órdenes.
Corre: python -m tests.test_execution"""
import os
import tempfile

db = os.path.join(tempfile.mkdtemp(), "exec.db")
os.environ.update(DATA_MODE="mock", LLM_PROVIDER="mock", TRADING_MODE="live", DATABASE_URL=f"sqlite:///{db}",
                  BINANCE_API_KEY="x", BINANCE_SECRET="y", WEBHOOK_SECRET="w", ADMIN_SECRET="a")

import ccxt  # noqa: E402

from app import execution, store  # noqa: E402


class FakeEx:
    """Saldo real: comprar acredita base − comisión; OCO bloquea; vender sin saldo → InsufficientFunds."""
    markets = {"BTC/USDT": {"limits": {"cost": {"min": 5.0}}}, "ETH/USDT": {"limits": {"cost": {"min": 5.0}}},
               "SOL/USDT": {"limits": {"cost": {"min": 5.0}}}}

    def __init__(self, fill_px=100.5, last=100.0, oco_fails=False, buy_timeout=False, sell_fails=False):
        self.fill_px, self.last, self.oco_fails, self.buy_timeout, self.sell_fails = fill_px, last, oco_fails, buy_timeout, sell_fails
        self.free = {"USDT": 10_000.0, "BTC": 0.5, "ETH": 0.0, "SOL": 0.0}  # 0.5 BTC son DEL USUARIO
        self.orders, self.oco_calls, self.sells, self.cancels, self.legs, self.lists = {}, [], [], [], {}, {}
        self.cancel_fails = False
        self.n = 0

    def amount_to_precision(self, s, a):
        q = float(f"{float(a) - 5e-7:.6f}")  # trunca como ccxt
        if q <= 0:
            raise ccxt.InvalidOrder("amount must be greater than minimum amount precision")
        return q
    def price_to_precision(self, s, p): return f"{p:.2f}"
    def fetch_ticker(self, s): return {"last": self.last}
    def _locked(self):
        if not self.legs or not any(l["status"] == "open" for l in self.legs.values()):
            return {}
        return {self.oco_base: self.oco_qty - sum(l["filled"] for l in self.legs.values())}

    def fetch_balance(self):  # como Binance: lo bloqueado en el OCO cuenta en total, no en free
        lk = self._locked()
        return {"total": {k: v + lk.get(k, 0) for k, v in self.free.items()}, "free": dict(self.free)}

    def create_order(self, sym, typ, side, amount, params=None):
        base = sym.split("/")[0]
        self.n += 1
        if side == "sell":
            if self.sell_fails == "hard":
                raise ccxt.NetworkError("caído")
            if amount > self.free[base] + 1e-12:
                raise ccxt.InsufficientFunds(f"tengo {self.free[base]} quieres {amount}")
            self.free[base] -= amount
            self.sells.append(amount)
            o = {"id": f"s{self.n}", "clientOrderId": (params or {}).get("newClientOrderId"), "average": self.last,
                 "filled": amount, "status": "closed"}
            self.orders[o["id"]] = o
            if self.sell_fails:  # se EJECUTA pero la respuesta se pierde
                raise ccxt.RequestTimeout("timeout")
            return o
        fee = amount * 0.001
        o = {"id": f"b{self.n}", "clientOrderId": (params or {}).get("newClientOrderId"), "filled": amount,
             "average": self.fill_px, "status": "closed", "fees": [{"currency": base, "cost": fee}]}
        self.free[base] += amount - fee
        self.orders[o["id"]] = o
        if self.buy_timeout:
            raise ccxt.RequestTimeout("timeout")
        return o

    def fetch_order(self, oid, sym, params=None):
        if params and params.get("origClientOrderId"):
            o = next((x for x in self.orders.values() if x.get("clientOrderId") == params["origClientOrderId"]), None)
            if not o:
                raise ccxt.OrderNotFound("no existe")
            return {**o, "fees": []}  # como Binance: sin comisiones en fetch_order
        return self.legs.get(oid) or {**self.orders[oid], "fees": []}

    def fetch_my_trades(self, sym, params=None):
        o = self.orders[params["orderId"]]
        return [{"fee": {"currency": sym.split("/")[0], "cost": o["filled"] * 0.001}}]

    def private_post_orderlist_oco(self, p):
        self.oco_calls.append(p)
        if self.oco_fails:
            raise ccxt.InvalidOrder("Filter failure: PERCENT_PRICE")
        base = p["symbol"].replace("USDT", "")
        q = float(p["quantity"])
        if q > self.free[base] + 1e-12:
            raise ccxt.InsufficientFunds("OCO sin saldo")
        self.free[base] -= q  # bloqueado por el OCO
        self.legs = {"11": {"id": "11", "status": "open", "filled": 0, "amount": q, "info": {"type": "LIMIT_MAKER"}},
                     "12": {"id": "12", "status": "open", "filled": 0, "amount": q, "info": {"type": "STOP_LOSS"}}}
        self.oco_qty, self.oco_base = q, base
        self.lists[p["listClientOrderId"]] = {"orderListId": 7, "orders": [{"orderId": 11}, {"orderId": 12}]}
        return self.lists[p["listClientOrderId"]]

    def private_get_orderlist(self, q):
        lst = self.lists.get(q.get("origClientOrderId"))
        if not lst:
            raise ccxt.ExchangeError('binance {"code":-2011,"msg":"Order list does not exist."}')
        done = not any(l["status"] == "open" for l in self.legs.values())
        return {**lst, "listOrderStatus": "ALL_DONE" if done else "EXECUTING"}

    def cancel_order(self, oid, sym):
        if self.cancel_fails:
            raise ccxt.RequestTimeout("timeout al cancelar")
        self.cancels.append(oid)
        if any(l["status"] == "open" for l in self.legs.values()):
            self.free[self.oco_base] += self.oco_qty - sum(l["filled"] for l in self.legs.values())
            for l in self.legs.values():
                l["status"] = "canceled" if l["status"] == "open" else l["status"]


ORDER = {"pair": "BTCUSDT", "qty": 1.0, "entry_ref": 100.0, "stop": 96.0, "tp": 110.0, "risk_usdt": 4.0}
res = []
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or res.append(bool(c))
live = lambda: store.open_positions()

# 1) Compra + OCO re-anclado, stop a mercado, cantidad = comprado − comisión
fx = FakeEx(); execution._ex = fx
r = execution.buy_with_oco(ORDER, "d1", "sig1")
p = fx.oco_calls[-1]
ok(r["ok"] and abs(r["stop"] - 96.5) < 1e-9 and abs(r["tp"] - 110.5) < 1e-9, f"OCO re-anclado al llenado: {r.get('stop')}/{r.get('tp')}")
ok(abs(float(p["quantity"]) - 0.999) < 1e-9, f"protege comprado − comisión: {p['quantity']}")
ok(p["belowType"] == "STOP_LOSS" and "belowPrice" not in p, "stop a MERCADO")
ok(abs(fx.free["BTC"] - 0.5) < 1e-9, f"los 0.5 BTC del usuario quedan intactos: {fx.free['BTC']}")

# 2) Parcial del TP (0.4) y el stop expira → vende SOLO el resto del bot (0.599), no los BTC del usuario
fx.legs["11"].update(filled=0.4, average=110.5)
fx.legs["12"]["status"] = "expired"
# (el resto sigue bloqueado en la pata TP; el bot debe cancelarla para liberarlo)
execution.reconcile()
ok(not live(), "parcial: posición cerrada")
ok(abs(fx.sells[-1] - 0.599) < 1e-9 and abs(fx.free["BTC"] - 0.5) < 1e-9,
   f"vendió {fx.sells[-1] if fx.sells else 0}, usuario conserva {fx.free['BTC']:.3f} BTC")

# 3) Timeout en la compra que SÍ se llenó → la encuentra por clientOrderId; comisión vía fetch_my_trades
fx = FakeEx(buy_timeout=True); execution._ex = fx
r = execution.buy_with_oco({**ORDER, "pair": "ETHUSDT"}, "d3", "sig3")
ok(r["ok"] and abs(float(fx.oco_calls[-1]["quantity"]) - 0.999) < 1e-9, f"timeout de compra recuperado: {r.get('qty')}")
execution.emergency_flatten()
ok(not live() and abs(fx.free["ETH"]) < 1e-9, "flatten vende lo del bot y libera el par")

# 4) Reinicio entre compra y OCO → recover_pending protege la cantidad real
fx = FakeEx(); execution._ex = fx
store.intent_position(id="P-d4", decision_id="d4", pair="SOLUSDT", mode="live", qty=1.0, entry=100.0, stop=96.0,
                      tp=110.0, risk_usdt=4.0, client_order_id="ca4sig4")
fx.create_order("SOL/USDT", "market", "buy", 1.0, params={"newClientOrderId": "ca4sig4"})
execution.recover_pending(min_age_sec=0)
ok(fx.oco_calls and abs(float(fx.oco_calls[-1]["quantity"]) - 0.999) < 1e-9 and live()[0]["status"] == "OPEN",
   f"compra huérfana protegida: {fx.oco_calls[-1]['quantity'] if fx.oco_calls else None}")
execution.emergency_flatten()

# 5) OCO rechazado + venta de emergencia caída → UNPROTECTED (cuenta como exposición) y se reintenta
fx = FakeEx(oco_fails=True, sell_fails="hard"); execution._ex = fx
r = execution.buy_with_oco({**ORDER, "pair": "ETHUSDT"}, "d5", "sig5")
ok(not r["ok"] and live() and live()[0]["status"] == "UNPROTECTED", f"queda UNPROTECTED: {r['error'][:30]}")
fx.sell_fails = False
execution.reconcile()
ok(not live() and abs(fx.free["ETH"]) < 1e-9, "reconcile reintenta y vende lo desprotegido")

# 6) Kill switch activo → no compra aunque el grafo lo pida
store.put("kill_switch", True)
r = execution.buy_with_oco(ORDER, "d6", "sig6")
ok(not r["ok"] and "kill" in r["error"], "kill switch bloquea en el último paso")
store.put("kill_switch", False)

# 7) Índice único: segunda compra en el mismo par se bloquea ANTES de enviarla a Binance
fx = FakeEx(); execution._ex = fx
execution.buy_with_oco(ORDER, "d7", "sig7")
r = execution.buy_with_oco(ORDER, "d8", "sig8")
ok(not r["ok"] and len(fx.orders) == 1, f"2a compra bloqueada: {r['error'][:30]}")

# 8) Riesgo registrado incluye comisiones (misma fórmula que backtest)
p = live()[0]
expect = ((p["entry"] - p["stop"]) + (p["entry"] + p["stop"]) * 0.001) * p["qty"]
ok(abs(p["risk_usdt"] - expect) < 1e-9, f"risk_usdt con comisiones: {p['risk_usdt']:.4f}")

# 9) Stop llenado por completo → cierra como SL con R ≈ -1
fx.legs["12"].update(status="closed", filled=fx.oco_qty, average=96.5)
execution.reconcile()
st = store.stats()
ok(not live() and st["closed_trades"] >= 1, f"SL registrado: {st}")

execution.emergency_flatten()

# 10) Error de BD justo después de un OCO aceptado → NO vende; reintenta la escritura
fx = FakeEx(); execution._ex = fx
fx.free["BTC"] = 2.0
calls = {"n": 0}
orig = store.activate_position
def flaky(*a, **k):
    calls["n"] += 1
    if calls["n"] == 1:
        raise RuntimeError("conexión a BD perdida")
    return orig(*a, **k)
store.activate_position = flaky
execution.time_sleep = None
r = execution.buy_with_oco(ORDER, "d10", "sig10")
store.activate_position = orig
ok(r["ok"] and not fx.sells and live()[0]["status"] == "OPEN", f"BD falló tras OCO: no vendió, reintentó y quedó OPEN ({calls['n']} intentos)")
execution.emergency_flatten()
ok(abs(fx.free["BTC"] - 2.0) < 1e-9, f"tras flatten el usuario conserva sus 2.0 BTC: {fx.free['BTC']:.4f}")

# 11) Venta de emergencia que SÍ se ejecutó pero dio timeout → el reintento la encuentra y no vende tus monedas
fx = FakeEx(oco_fails=True, sell_fails=True); execution._ex = fx
fx.free["BTC"] = 0.5
r = execution.buy_with_oco(ORDER, "d11", "sig11")
fx.sell_fails = False
execution.reconcile()
ok(not live() and abs(fx.free["BTC"] - 0.5) < 1e-9 and len(fx.sells) == 1,
   f"una sola venta; usuario conserva 0.5 BTC: {fx.free['BTC']:.4f}, ventas={fx.sells}")

# 12) El stop se llena ENTRE la consulta y la cancelación → re-consulta y no vende tus monedas
fx = FakeEx(); execution._ex = fx
fx.free["BTC"] = 0.5
execution.buy_with_oco(ORDER, "d12", "sig12")
real_cancel = fx.cancel_order
def cancel_after_fill(oid, sym):
    if fx.legs["12"]["status"] == "open":  # el stop se dispara justo ahora
        fx.legs["12"].update(status="closed", filled=fx.oco_qty, average=96.0)
        fx.legs["11"]["status"] = "expired"
    fx.cancels.append(oid)
fx.cancel_order = cancel_after_fill
fx.last = 90.0  # precio bajo el stop → camino SL_GAP
execution.reconcile()
ok(not live() and not fx.sells and abs(fx.free["BTC"] - 0.5) < 1e-9, f"re-consulta tras cancelar: ventas={fx.sells}, BTC usuario={fx.free['BTC']:.4f}")

# 13) Resto en polvo (TP llenó casi todo) → se cierra como DUST, no se queda trabado para siempre
fx = FakeEx(); execution._ex = fx
fx.free["BTC"] = 0.0
execution.buy_with_oco(ORDER, "d13", "sig13")
fx.legs["11"].update(filled=fx.oco_qty - 0.00001, average=110.5)
fx.legs["12"]["status"] = "expired"
execution.reconcile()
ok(not live(), "resto de polvo cerrado (no bloquea el par)")

# 14) Cancelación del OCO con timeout → NO vende (tus monedas libres no se tocan); reintenta después
fx = FakeEx(); execution._ex = fx
fx.free["BTC"] = 0.5
execution.buy_with_oco(ORDER, "d14", "sig14")
fx.cancel_fails = True
fx.last = 90.0
execution.reconcile()
ok(not fx.sells and live() and abs(fx.free["BTC"] - 0.5) < 1e-9, f"cancelación fallida: no vendió nada ({fx.sells})")
fx.cancel_fails = False
execution.reconcile()
ok(not live() and abs(fx.free["BTC"] - 0.5) < 1e-9 and abs(sum(fx.sells) - 0.999) < 1e-9,
   f"siguiente ciclo: vendió solo lo del bot ({fx.sells}); usuario conserva {fx.free['BTC']:.4f}")

# 15) Muere después de crear el OCO y antes de registrarlo → la recuperación ADOPTA el OCO (no crea otro, no DUST)
import time as _t
fx = FakeEx(); execution._ex = fx
fx.free["BTC"] = 0.5
orig_act, orig_sleep = store.activate_position, _t.sleep
store.activate_position = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("BD caída"))
_t.sleep = lambda s: None
try:
    execution.buy_with_oco(ORDER, "d15", "sig15")
except Exception:
    pass
store.activate_position, _t.sleep = orig_act, orig_sleep
ok(live() and live()[0]["status"] == "PENDING" and len(fx.oco_calls) == 1, "OCO creado y posición quedó PENDING")
execution.recover_pending(min_age_sec=0)
p = live()[0] if live() else {}
ok(p.get("status") == "OPEN" and len(fx.oco_calls) == 1 and abs(p.get("qty", 0) - 0.999) < 1e-9,
   f"recuperación adoptó el OCO existente: status={p.get('status')} qty={p.get('qty')} OCOs={len(fx.oco_calls)}")
execution.emergency_flatten()
ok(abs(fx.free["BTC"] - 0.5) < 1e-9, f"usuario conserva 0.5 BTC tras todo: {fx.free['BTC']:.4f}")

# 16) OCO creado pero su respuesta Y la consulta dan timeout → NO vende en caliente; reconcile cancela y vende solo lo del bot
fx = FakeEx(); execution._ex = fx
fx.free["BTC"] = 0.5
real_oco, real_get = fx.private_post_orderlist_oco, fx.private_get_orderlist
def oco_timeout(p):
    real_oco(p)
    raise ccxt.RequestTimeout("timeout tras crear el OCO")
fx.private_post_orderlist_oco = oco_timeout
fx.private_get_orderlist = lambda q: (_ for _ in ()).throw(ccxt.RequestTimeout("timeout consulta"))
r = execution.buy_with_oco(ORDER, "d16", "sig16")
ok(not fx.sells and live()[0]["status"] == "UNPROTECTED" and abs(fx.free["BTC"] - 0.5) < 1e-9,
   f"OCO en duda: no vendió en caliente ({fx.sells}), usuario conserva {fx.free['BTC']:.4f}")
execution.reconcile()  # la consulta sigue fallando → no puede verificar → no vende
ok(not fx.sells and abs(fx.free["BTC"] - 0.5) < 1e-9, "sin poder verificar el OCO, sigue sin vender")
fx.private_get_orderlist = real_get
fx.private_delete_orderlist = lambda q: fx.cancel_order("11", "BTC/USDT")
execution.reconcile()  # ahora sí: cancela el OCO por listClientOrderId, verifica y vende solo lo del bot
ok(not live() and abs(sum(fx.sells) - 0.999) < 1e-9 and abs(fx.free["BTC"] - 0.5) < 1e-9,
   f"resuelto: vendió {fx.sells}, usuario conserva {fx.free['BTC']:.4f}")

print(f"\n{sum(res)}/{len(res)} pruebas pasaron")
raise SystemExit(0 if all(res) else 1)
