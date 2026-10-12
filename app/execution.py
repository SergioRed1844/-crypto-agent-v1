"""Ejecución en Binance Spot vía ccxt (síncrono: se llama desde hilos).

Invariantes (cada una tiene prueba en tests/test_execution.py):
 1) Write-ahead: la posición se registra PENDING antes de comprar. Un timeout en la compra NO se da por
    fallido: se busca la orden por clientOrderId; recover_pending() corre en cada ciclo de reconciliación.
 2) OCO en el exchange (TP LIMIT_MAKER + stop STOP_LOSS a mercado) re-anclado al llenado real.
 3) Cantidad a proteger/vender = min(lo comprado − comisión real, saldo libre). Nunca vende monedas tuyas.
 4) Si el OCO y la venta de emergencia fallan → UNPROTECTED: se reintenta cada ciclo y cuenta como exposición.
 5) Llenados parciales y patas canceladas: lo que quede sin stop se vende a mercado.
 6) BNB nunca se toca. El kill switch se revisa justo antes de enviar la compra.
"""
import json
import logging
import os

from . import config, data, store

log = logging.getLogger("exec")
_ex = None
DUST = 1e-9


def ex():
    global _ex
    if _ex is None:
        import ccxt
        _ex = ccxt.binance({"apiKey": config.BINANCE_API_KEY, "secret": config.BINANCE_SECRET,
                            "enableRateLimit": True, "timeout": 15000,
                            "options": {"defaultType": "spot", "adjustForTimeDifference": True}})
        if config.TRADING_MODE == "testnet":
            _ex.set_sandbox_mode(True)
        _ex.load_markets()
    return _ex


def _is_rejection(err) -> bool:
    """True = Binance rechazó con certeza (no se ejecutó). False = no sabemos (timeout, red)."""
    try:
        import ccxt
        if isinstance(err, (ccxt.InvalidOrder, ccxt.InsufficientFunds, ccxt.AuthenticationError,
                            ccxt.PermissionDenied, ccxt.BadSymbol)):
            return True
        if isinstance(err, ccxt.NetworkError):
            return False
        return isinstance(err, ccxt.BadRequest)
    except ImportError:
        return False


def exec_price(pair: str) -> float:
    """Precio del venue donde se ejecuta (en testnet difiere del mercado real)."""
    if config.TRADING_MODE == "paper":
        return data.last_price(pair)
    return float(ex().fetch_ticker(data.ccxt_symbol(pair))["last"])


def _cap(eq: float) -> float:
    return min(eq, config.MAX_BOT_CAPITAL) if config.MAX_BOT_CAPITAL > 0 else eq


def equity() -> tuple[float, float]:
    """(equity del bot en USDT a precio de entrada, USDT libre utilizable)."""
    opens = store.open_positions()
    locked = sum((p["qty"] or 0) * (p["entry"] or 0) for p in opens)
    if config.TRADING_MODE == "paper":
        eq = store.get("paper_equity", float(os.environ.get("PAPER_EQUITY", "1000")))
        return eq, max(eq - locked, 0)
    bal = ex().fetch_balance()
    usdt_total = float(bal["total"].get("USDT", 0))
    usdt_free = float(bal["free"].get("USDT", 0))
    eq = _cap(usdt_total + locked)
    return eq, max(min(usdt_free, eq - locked), 0)


def unrealized_pnl() -> float:
    total = 0.0
    for p in store.open_positions():
        if p["status"] not in ("OPEN", "UNPROTECTED"):
            continue
        try:
            total += (exec_price(p["pair"]) - p["entry"]) * p["qty"]
        except Exception as e:
            log.warning(f"precio {p['pair']}: {e}")
    return total


# ── helpers de exchange ───────────────────────────────────────
def _base(pair):
    return pair.replace("USDT", "")


def _bal(e, base) -> tuple[float, float]:
    b = e.fetch_balance()
    return float(b["free"].get(base, 0) or 0), float(b["total"].get(base, 0) or 0)


def _bot_cap(e, p_or_pid, base) -> float:
    """Lo máximo que el bot puede vender de `base`: libre, y nunca por debajo de lo que el usuario
    tenía justo antes de que el bot comprara (línea base por posición). Protege tus monedas aunque el
    estado del bot esté desfasado. Si operas esa misma moneda a mano mientras hay posición, no aplica."""
    pid = p_or_pid if isinstance(p_or_pid, str) else p_or_pid["id"]
    free, total = _bal(e, base)
    baseline = float(store.get(f"baseline:{pid}", 0.0))
    return max(min(free, total - baseline), 0.0)


def _find_order(e, sym, cid):
    """('FOUND', orden) | ('NOT_FOUND', None) | ('ERROR', None). Solo NOT_FOUND autoriza a darla por inexistente."""
    try:
        return "FOUND", e.fetch_order("", sym, params={"origClientOrderId": cid})
    except Exception as err:
        if _not_exists(err):
            return "NOT_FOUND", None
        log.warning(f"fetch_order cid={cid}: {err}")
        return "ERROR", None


def _fee_in_base(e, sym, buy, base) -> float:
    """Comisión cobrada en la moneda comprada. fetch_order/fetch_orders traen fees=[]: se piden los trades."""
    fees = buy.get("fees") or ([buy["fee"]] if buy.get("fee") else [])
    if not fees:
        try:
            fees = [t.get("fee") or {} for t in e.fetch_my_trades(sym, params={"orderId": buy["id"]})]
        except Exception as err:
            log.warning(f"fetch_my_trades {buy.get('id')}: {err}")
    return sum(float(f.get("cost") or 0) for f in fees if f and f.get("currency") == base)


def _tradable(e, sym, qty, px) -> float:
    """Cantidad redondeada que Binance aceptaría; 0 si es polvo (redondea a 0 o queda bajo el mínimo)."""
    try:
        q = float(e.amount_to_precision(sym, qty))
    except Exception:
        return 0.0
    mkt = (getattr(e, "markets", None) or {}).get(sym, {})
    min_cost = float(((mkt.get("limits") or {}).get("cost") or {}).get("min") or 0)
    return q if q > 0 and q * px >= min_cost else 0.0


def _sell_market(e, sym, qty, cid):
    """Venta a mercado IDEMPOTENTE: antes de enviar busca una venta previa con el mismo clientOrderId
    (un timeout pudo haberla ejecutado). Devuelve (cantidad, precio) o (0, 0) si es polvo."""
    st, prev = _find_order(e, sym, cid)
    if st == "FOUND" and float(prev.get("filled") or 0) > 0:
        return float(prev["filled"]), float(prev.get("average") or prev.get("price") or e.fetch_ticker(sym)["last"])
    if st == "ERROR":
        raise RuntimeError(f"no puedo verificar la venta previa {cid}; reintento después")
    px_ref = float(e.fetch_ticker(sym)["last"])
    q = _tradable(e, sym, qty, px_ref)
    if q <= 0:
        return 0.0, 0.0
    o = e.create_order(sym, "market", "sell", q, params={"newClientOrderId": cid})
    px = o.get("average") or o.get("price")
    if not px:
        try:
            px = e.fetch_order(o["id"], sym).get("average")
        except Exception:
            px = None
    return float(o.get("filled") or q), float(px or px_ref)


def _place_oco(e, sym, qty, sl, tp, cid):
    """Pata baja = STOP_LOSS (dispara orden a MERCADO): un STOP_LOSS_LIMIT puede quedarse sin llenar en una
    caída rápida; el de mercado siempre sale (con slippage). Pata alta = LIMIT_MAKER en el TP."""
    list_cid = f"oco{cid}"[:36]
    params = {"symbol": sym.replace("/", ""), "side": "SELL", "quantity": e.amount_to_precision(sym, qty),
              "aboveType": "LIMIT_MAKER", "abovePrice": e.price_to_precision(sym, tp),
              "belowType": "STOP_LOSS", "belowStopPrice": e.price_to_precision(sym, sl),
              "listClientOrderId": list_cid}
    try:
        return e.private_post_orderlist_oco(params)
    except Exception as err:
        try:  # un timeout no significa que Binance lo rechazó
            found = e.private_get_orderlist({"origClientOrderId": list_cid})
            if found and found.get("orders"):
                log.warning(f"OCO {list_cid} sí existía pese al error ({err})")
                return found
        except Exception:
            pass
        raise


def _cancel_oco(e, sym, p):
    """Cancela el OCO del bot (por ids guardados o por su listClientOrderId) antes de cualquier venta."""
    legs = json.loads(p.get("oco_id") or "{}").get("legs", [])
    for leg in legs:
        try:
            e.cancel_order(leg, sym)
        except Exception:
            pass
    if not legs and p.get("client_order_id"):
        try:
            e.private_delete_orderlist({"symbol": sym.replace("/", ""),
                                        "listClientOrderId": f"oco{p['client_order_id']}"[:36]})
        except Exception:
            pass


def _not_exists(err) -> bool:
    import ccxt
    msg = str(err).lower()
    return isinstance(err, ccxt.OrderNotFound) or "does not exist" in msg or "-2011" in msg or "-2013" in msg \
        or "unknown order" in msg


def _existing_oco(e, sym, cid):
    """OCO del bot ya creado en Binance para esta compra (por su listClientOrderId), o None.
    Un error distinto a 'no existe' se propaga: no se puede asumir nada."""
    try:
        found = e.private_get_orderlist({"origClientOrderId": f"oco{cid}"[:36]})
        return found if found and found.get("orders") else None
    except Exception as err:
        if _not_exists(err):
            return None
        raise


def _oco_still_open(e, sym, p, legs) -> bool:
    """True si alguna pata del OCO del bot sigue abierta (o no se puede verificar)."""
    if legs:
        return any(o.get("status") == "open" for o in legs)
    if not p.get("client_order_id"):
        return False
    try:
        found = _existing_oco(e, sym, p["client_order_id"])
    except Exception:
        return True  # no se puede verificar → se asume vivo (no vender)
    return bool(found) and str(found.get("listOrderStatus", "")).upper() != "ALL_DONE"


def _db_retry(fn, *a, **kw):
    import time
    for i in range(5):
        try:
            return fn(*a, **kw)
        except Exception as err:
            log.error(f"BD falló ({err}); reintento {i + 1}/5")
            time.sleep(1 + i)
    return fn(*a, **kw)


def _arm(e, sym, pid, pair, buy, order, cid, check_existing=False):
    """Con la compra llena: re-ancla niveles, pone OCO y activa.
    OCO rechazado → venta idempotente; si eso falla → UNPROTECTED. Un error de BD DESPUÉS de un OCO
    aceptado nunca dispara una venta: se reintenta la escritura."""
    base = _base(pair)
    filled = float(buy.get("filled") or 0)
    avg = float(buy.get("average") or buy.get("price") or order["entry_ref"])
    sl = avg - (order["entry_ref"] - order["stop"])  # mismas distancias aprobadas, desde el llenado real
    tp = avg + (order["tp"] - order["entry_ref"])
    # ¿Ya existe el OCO? (el proceso murió después de crearlo y antes de registrarlo) → adoptarlo, no crear otro
    existing = _existing_oco(e, sym, cid) if check_existing else None
    if existing:
        legs = sorted(str(o["orderId"]) for o in existing.get("orders", []))
        leg0 = e.fetch_order(legs[0], sym)
        q = float(leg0.get("amount") or 0)
        risk_usdt = ((avg - sl) + (avg + sl) * config.FEE_RATE) * q
        _db_retry(store.activate_position, pid, qty=q, entry=avg, stop=sl, tp=tp, risk_usdt=risk_usdt,
                  entry_order_id=str(buy["id"]), oco_id=json.dumps({"listId": existing.get("orderListId"), "legs": legs}))
        log.warning(f"{pid}: OCO existente adoptado ({legs})")
        return {"ok": True, "mode": config.TRADING_MODE, "position_id": pid, "avg": avg, "qty": q, "stop": sl,
                "tp": tp, "adopted": True}
    held = filled - _fee_in_base(e, sym, buy, base)
    try:
        held = min(held, _bot_cap(e, pid, base))
    except Exception as err:
        log.warning(f"balance {base}: {err}")
    sell_qty = _tradable(e, sym, max(held, 0), avg)
    if sell_qty <= 0:
        free, total = _bal(e, base)
        if total - float(store.get(f"baseline:{pid}", 0.0)) > 1e-9 and _tradable(e, sym, filled, avg) > 0:
            # hay monedas del bot pero no están libres: bloqueadas en algo que no veo. No es polvo.
            raise RuntimeError(f"{pid}: monedas del bot bloqueadas sin OCO identificado; queda PENDING")
        _db_retry(store.set_status, pid, "CLOSED", qty=0.0, entry=avg, exit_price=avg, pnl_usdt=0.0, r_multiple=0.0,
                  exit_reason="DUST", closed_at=store.now(), entry_order_id=str(buy["id"]))
        return {"ok": False, "error": "cantidad comprada es polvo; nada que proteger"}
    risk_usdt = ((avg - sl) + (avg + sl) * config.FEE_RATE) * sell_qty  # misma fórmula que risk.py/backtest
    fields = dict(qty=sell_qty, entry=avg, stop=sl, tp=tp, risk_usdt=risk_usdt, entry_order_id=str(buy["id"]))
    try:
        oco = _place_oco(e, sym, sell_qty, sl, tp, cid)
    except Exception as err:
        _db_retry(store.set_status, pid, "UNPROTECTED", oco_id=json.dumps({"legs": []}), **fields)
        if not _is_rejection(err):
            # Timeout/red: el OCO PUDO haberse creado. No se vende aquí; reconcile (_exit_rest) primero lo
            # cancela por listClientOrderId y verifica que no siga vivo antes de vender.
            log.critical(f"{pid}: OCO en duda ({err}); reconcile lo resolverá sin tocar tus monedas")
            return {"ok": False, "error": f"OCO en duda, UNPROTECTED: {err}"}
        log.error(f"OCO rechazado ({err}); vendiendo {pair} a mercado")
        try:
            q, px = _sell_market(e, sym, min(sell_qty, _bot_cap(e, pid, base)), f"xs{pid}"[:36])
            store.close_position(pid, px or avg, "OCO_FAILED")
            return {"ok": False, "error": f"OCO falló, posición cerrada a mercado: {err}"}
        except Exception as err2:
            log.critical(f"{pid} SIN STOP: OCO y venta fallaron ({err2}); se reintenta cada ciclo")
            return {"ok": False, "error": f"UNPROTECTED: {err} / {err2}"}
    legs = sorted(str(o["orderId"]) for o in oco.get("orders", []))
    _db_retry(store.activate_position, pid, oco_id=json.dumps({"listId": oco.get("orderListId"), "legs": legs}), **fields)
    return {"ok": True, "mode": config.TRADING_MODE, "position_id": pid, "avg": avg, "qty": sell_qty, "stop": sl, "tp": tp}


# ── compra ────────────────────────────────────────────────────
def buy_with_oco(order: dict, decision_id: str, signal_id: str) -> dict:
    pair = order["pair"]
    if _base(pair) in config.PROTECTED_ASSETS:
        return {"ok": False, "error": "BNB protegido"}
    if store.get("kill_switch", False):
        return {"ok": False, "error": "kill_switch activo"}
    pid = f"P-{decision_id}"
    if config.TRADING_MODE == "paper":
        store.open_position(id=pid, decision_id=decision_id, pair=pair, mode="paper", qty=order["qty"],
                            entry=order["entry_ref"], stop=order["stop"], tp=order["tp"],
                            risk_usdt=order["risk_usdt"], entry_order_id="paper", oco_id="paper")
        return {"ok": True, "mode": "paper", "position_id": pid}

    e, sym = ex(), data.ccxt_symbol(pair)
    cid = f"ca4{signal_id}"[:36]
    qty = _tradable(e, sym, order["qty"], order["entry_ref"])
    if qty <= 0 or qty * order["entry_ref"] < config.RISK["min_notional_usdt"]:
        return {"ok": False, "error": f"nocional {order['qty'] * order['entry_ref']:.2f} USDT bajo el mínimo del par"}
    try:
        store.intent_position(id=pid, decision_id=decision_id, pair=pair, mode=config.TRADING_MODE, qty=qty,
                              entry=order["entry_ref"], stop=order["stop"], tp=order["tp"],
                              risk_usdt=order["risk_usdt"], client_order_id=cid)
    except Exception as err:  # índice único: ya hay una posición viva en el par
        return {"ok": False, "error": f"posición viva en {pair}: {err.__class__.__name__}"}
    try:  # línea base: lo que el USUARIO tiene de esta moneda justo antes de comprar
        store.put(f"baseline:{pid}", _bal(e, _base(pair))[1])
    except Exception as err:
        store.fail_position(pid, f"no pude leer saldo: {err}")
        return {"ok": False, "error": f"no pude leer saldo previo: {err}"}
    try:
        buy = e.create_order(sym, "market", "buy", qty, params={"newClientOrderId": cid})
    except Exception as err:
        if _is_rejection(err):
            store.fail_position(pid, str(err))
            return {"ok": False, "error": str(err)}
        log.error(f"compra {pid} sin respuesta clara ({err}); buscando por clientOrderId")
        st, buy = _find_order(e, sym, cid)
        if st != "FOUND":  # sigue PENDING: recover_pending() lo resolverá
            return {"ok": False, "error": f"estado desconocido, queda PENDING: {err}"}
    if float(buy.get("filled") or 0) <= 0:
        buy = e.fetch_order(buy["id"], sym)
    if float(buy.get("filled") or 0) <= 0:
        store.fail_position(pid, "compra sin llenar")
        return {"ok": False, "error": "compra sin llenar"}
    return _arm(e, sym, pid, pair, buy, order, cid)


def recover_pending(min_age_sec: int = 120) -> list:
    """PENDING con más de min_age_sec = el proceso murió o la compra quedó en duda. Corre cada ciclo.
    Solo una respuesta 'la orden no existe' (OrderNotFound) por 30 min autoriza a darla por fallida;
    cualquier otro error (IP bloqueada, key mal) la deja PENDING y lo registra como crítico."""
    out = []
    for p in store.pending_positions(min_age_sec):
        e, sym = ex(), data.ccxt_symbol(p["pair"])
        try:
            st, buy = _find_order(e, sym, p["client_order_id"])
            if st == "NOT_FOUND":
                if (store.now() - p["opened_at"]).total_seconds() > 1800:
                    store.fail_position(p["id"], "Binance confirma: la compra no existe")
                    out.append({p["id"]: "sin compra"})
                continue
            if st == "ERROR":
                log.critical(f"{p['id']}: no puedo consultar Binance para resolver una compra en duda")
                continue
            if float(buy.get("filled") or 0) <= 0:
                if buy.get("status") in ("canceled", "expired", "rejected"):
                    store.fail_position(p["id"], f"compra {buy.get('status')}")
                continue
            order = {"pair": p["pair"], "entry_ref": p["entry"], "stop": p["stop"], "tp": p["tp"]}
            out.append({p["id"]: _arm(e, sym, p["id"], p["pair"], buy, order, p["client_order_id"], check_existing=True)})
        except Exception as err:
            log.error(f"recover {p['id']}: {err}")
    return out


# ── reconciliación ────────────────────────────────────────────
def _legs(e, sym, p):
    ids = json.loads(p["oco_id"] or "{}").get("legs", [])
    return [e.fetch_order(i, sym) for i in ids]


def _is_stop_leg(o) -> bool:
    t = str((o.get("info") or {}).get("type") or o.get("type") or "").upper()
    return "STOP" in t


def _exit_rest(e, sym, p, reason, tag):
    """Cancela el OCO del bot, RE-CONSULTA las patas (un llenado pudo ocurrir mientras tanto) y vende a mercado
    solo lo que de verdad le queda al bot, con tope en la línea base del usuario. Polvo → se cierra en BD."""
    _cancel_oco(e, sym, p)
    legs = _legs(e, sym, p)
    if not legs and p.get("client_order_id"):  # OCO "en duda": si existía, usar sus patas reales
        found = _existing_oco(e, sym, p["client_order_id"])
        if found:
            legs = [e.fetch_order(str(o["orderId"]), sym) for o in found.get("orders", [])]
    if _oco_still_open(e, sym, p, legs):
        # la cancelación falló o no se pudo verificar: las monedas del bot siguen bloqueadas en el OCO y
        # el saldo libre podría ser TUYO. No se vende; se reintenta el próximo ciclo.
        raise RuntimeError(f"{p['id']}: OCO sigue vivo tras cancelar; no vendo")
    sold_q = sum(float(o.get("filled") or 0) for o in legs)
    sold_v = sum(float(o.get("filled") or 0) * float(o.get("average") or o.get("price") or 0) for o in legs)
    remaining = max(p["qty"] - sold_q, 0)
    if remaining > DUST:
        q, px = _sell_market(e, sym, min(remaining, _bot_cap(e, p, _base(p["pair"]))), f"x{tag}{p['id']}"[:36])
        sold_q, sold_v = sold_q + q, sold_v + q * px
        if q <= 0:
            reason += "+DUST"
    exit_px = sold_v / sold_q if sold_q > DUST else exec_price(p["pair"])
    return store.close_position(p["id"], exit_px, reason)


def _reconcile_live(p):
    e, sym = ex(), data.ccxt_symbol(p["pair"])
    if p["status"] == "UNPROTECTED":
        return _exit_rest(e, sym, p, "UNPROTECTED_EXIT", "s")  # misma etiqueta que la venta de emergencia
    legs = _legs(e, sym, p)
    filled = sum(float(o.get("filled") or 0) for o in legs)
    done = [o for o in legs if o.get("status") == "closed"]
    if done and p["qty"] - filled <= p["qty"] * 1e-6 + DUST:
        v = sum(float(o.get("filled") or 0) * float(o.get("average") or o.get("price") or 0) for o in legs)
        px = v / filled
        return store.close_position(p["id"], px, "TP" if px >= p["entry"] else "SL")
    stop_alive = any(_is_stop_leg(o) and o.get("status") == "open" for o in legs)
    if not stop_alive:  # parcial del TP canceló el stop, o patas canceladas/expiradas
        return _exit_rest(e, sym, p, "PARTIAL_OR_CANCELED", "r")
    if config.RISK["stop_gap_market_exit"] and exec_price(p["pair"]) < p["stop"] * 0.995:
        return _exit_rest(e, sym, p, "SL_GAP", "g")
    return None


def _reconcile_sim(p):
    """paper / shadow: recorre velas de 5m desde el último punto revisado (paginado, sin tope de días)."""
    key = f"chk:{p['id']}"
    cursor = max(int(p["opened_at"].timestamp() * 1000), int(store.get(key, 0)))
    while True:
        bars = data.fetch_ohlcv(p["pair"], "5m", 1000, since=cursor)
        bars = [r for r in bars if r[0] >= cursor]
        if not bars:
            return None
        for ts, o, hi, lo, _, _ in bars:
            if lo <= p["stop"]:  # conservador: si SL y TP caen en la misma vela, gana el SL
                return store.close_position(p["id"], min(o, p["stop"]), "SL")
            if hi >= p["tp"]:
                return store.close_position(p["id"], p["tp"], "TP")  # una orden límite en reposo llena a su precio
        cursor = bars[-1][0] + data.TF_MS["5m"]
        store.put(key, cursor)
        if len(bars) < 1000:
            return None


def reconcile() -> list[dict]:
    """Cada 5 min: recupera PENDING, cierra lo ejecutado, protege lo que quedó sin stop."""
    out = []
    if config.TRADING_MODE != "paper":
        out += [{"recovered": r} for r in recover_pending(min_age_sec=120)]
    paper_pnl = 0.0
    for p in store.open_positions() + store.shadow_positions():
        if p["status"] not in ("OPEN", "UNPROTECTED"):
            continue
        try:
            res = _reconcile_sim(p) if p["mode"] in ("paper", "shadow") else _reconcile_live(p)
            if res:
                out.append({p["id"]: res})
                if p["mode"] == "paper":
                    paper_pnl += res["pnl_usdt"]
        except Exception as err:
            log.warning(f"reconcile {p['id']}: {err}")
    if paper_pnl:  # las sombra no mueven el equity
        eq = store.get("paper_equity", float(os.environ.get("PAPER_EQUITY", "1000")))
        store.put("paper_equity", eq + paper_pnl)
    store.put("last_reconcile", store.now().isoformat())
    return out


def emergency_flatten() -> list:
    """Kill switch (lo ejecuta el líder bajo el candado de trading): resuelve PENDING, cancela SOLO el OCO
    del bot y vende SOLO lo que le queda al bot."""
    out = []
    if config.TRADING_MODE != "paper":
        recover_pending(min_age_sec=0)
    for p in store.open_positions():
        try:
            if p["mode"] == "paper":
                out.append(store.close_position(p["id"], data.last_price(p["pair"]), "KILL"))
                continue
            if p["status"] == "PENDING":
                out.append({"id": p["id"], "error": "compra en duda; se reintenta en reconcile"})
                continue
            e, sym = ex(), data.ccxt_symbol(p["pair"])
            out.append(_exit_rest(e, sym, p, "KILL", "k"))
        except Exception as err:
            store.set_status(p["id"], "UNPROTECTED")
            out.append({"id": p["id"], "error": str(err)})
    if config.TRADING_MODE == "paper" and out:
        eq = store.get("paper_equity", float(os.environ.get("PAPER_EQUITY", "1000")))
        store.put("paper_equity", eq + sum(v["pnl_usdt"] for v in out if v and "pnl_usdt" in v))
    return out
