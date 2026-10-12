"""Persistencia (SQLite local / Postgres en producción vía DATABASE_URL).

- La señal se guarda como PENDING antes de responder 200 (cola durable); un worker la consume.
- La posición se registra como PENDING antes de comprar (write-ahead) para recuperar compras huérfanas.
- Todo se filtra por TRADING_MODE: posiciones de paper/testnet nunca se mezclan con live.
- Índice único (mode, pair) sobre posiciones vivas: candado a nivel base de datos.
- Lock de líder (Postgres advisory lock): en un deploy de Render conviven 2 instancias unos segundos;
  solo el líder procesa señales y reconcilia.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import (Column, DateTime, Float, Index, MetaData, String, Table, Text, create_engine, func,
                        insert, select, text, update)
from sqlalchemy.exc import IntegrityError

from . import config

_url = config.DATABASE_URL
if _url.startswith("postgres://"):
    _url = _url.replace("postgres://", "postgresql+psycopg://", 1)
elif _url.startswith("postgresql://"):
    _url = _url.replace("postgresql://", "postgresql+psycopg://", 1)
IS_SQLITE = _url.startswith("sqlite")
engine = create_engine(_url, pool_pre_ping=True, future=True)
md = MetaData()
MODE = config.TRADING_MODE

decisions = Table("decisions", md,
    Column("id", String, primary_key=True), Column("ts", DateTime(timezone=True)),
    Column("pair", String), Column("signal_id", String, unique=True), Column("action", String),
    Column("reason", Text), Column("payload", Text))

positions = Table("positions", md,
    Column("id", String, primary_key=True), Column("decision_id", String), Column("pair", String),
    Column("mode", String), Column("status", String),  # PENDING | OPEN | UNPROTECTED | CLOSED | FAILED
    Column("qty", Float), Column("entry", Float), Column("stop", Float), Column("tp", Float),
    Column("risk_usdt", Float), Column("client_order_id", String), Column("entry_order_id", String),
    Column("oco_id", String), Column("opened_at", DateTime(timezone=True)), Column("closed_at", DateTime(timezone=True)),
    Column("exit_price", Float), Column("pnl_usdt", Float), Column("r_multiple", Float),
    Column("exit_reason", String))

kv = Table("kv", md, Column("k", String, primary_key=True), Column("v", Text))

LIVE_STATUSES = ("OPEN", "PENDING", "UNPROTECTED")
_live = (positions.c.status.in_(list(LIVE_STATUSES))) & (positions.c.mode != "shadow")
_uidx = Index("one_live_position_per_mode_pair", positions.c.mode, positions.c.pair, unique=True,
              sqlite_where=_live, postgresql_where=_live)

md.create_all(engine)
_uidx.create(engine, checkfirst=True)  # create_all no agrega índices a tablas que ya existían


def now():
    return datetime.now(timezone.utc)


def as_utc(dt):
    """SQLite devuelve datetimes sin zona; Postgres con zona. Normaliza a UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


# ── Líder ─────────────────────────────────────────────────────
_leader_conn = None


_LEADER_KEY = int(hashlib.sha1(b"cryptoagent-leader").hexdigest()[:15], 16)
POOLED_URL = any(x in _url for x in ("-pooler", ":6543", "pgbouncer"))


def try_become_leader() -> bool:
    """Postgres: advisory lock de sesión en una conexión dedicada que vive todo el proceso.
    Requiere URL DIRECTA (sin pooler): con PgBouncer en modo transacción el lock no es confiable.
    SQLite (local): siempre líder."""
    global _leader_conn
    if IS_SQLITE:
        return True
    if _leader_conn is not None:
        return still_leader()
    conn = engine.connect()
    try:
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LEADER_KEY}).scalar()
        conn.commit()
    except Exception:
        conn.close()
        raise
    if got:
        _leader_conn = conn
        return True
    conn.close()
    return False


def still_leader() -> bool:
    """Verifica en CADA vuelta que el lock siga siendo nuestro (si la conexión cayó, el lock se perdió)."""
    global _leader_conn
    if IS_SQLITE:
        return True
    if _leader_conn is None:
        return False
    try:
        n = _leader_conn.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND granted AND pid=pg_backend_pid() "
            "AND ((classid::bigint << 32) | objid::bigint) = :k"), {"k": _LEADER_KEY}).scalar()
        _leader_conn.commit()
        if n:
            return True
    except Exception:
        pass
    try:
        _leader_conn.close()
    except Exception:
        pass
    _leader_conn = None
    return False


def foreign_live_positions() -> list:
    """Posiciones vivas de OTRO modo (p.ej. testnet al arrancar en live): el bot no debe arrancar así."""
    with engine.begin() as c:
        return [dict(r) for r in c.execute(select(positions.c.id, positions.c.mode, positions.c.pair).where(
            positions.c.status.in_(list(LIVE_STATUSES)), positions.c.mode != "shadow",
            positions.c.mode != MODE)).mappings()]


# ── Decisiones (cola de señales) ──────────────────────────────
def claim_signal(signal_id: str, pair: str, signal: dict | None = None) -> bool:
    """Persiste la señal como PENDING ANTES de responder 200. False si ya existía (duplicado)."""
    try:
        with engine.begin() as c:
            c.execute(insert(decisions).values(id=f"D-{signal_id}", ts=now(), pair=pair, signal_id=signal_id,
                                               action="PENDING", reason="",
                                               payload=json.dumps({"signal": signal or {}}, default=str)))
        return True
    except IntegrityError:
        return False


def next_pending_signal(max_age_min: int = 20):
    """Toma la señal PENDING más vieja y la marca PROCESSING (solo el líder llama esto).
    Las que pasaron de max_age_min se marcan EXPIRED: el precio ya se movió."""
    with engine.begin() as c:
        c.execute(update(decisions).where(decisions.c.action == "PENDING",
                                          decisions.c.ts < now() - timedelta(minutes=max_age_min)).values(
            action="EXPIRED", reason="no se procesó a tiempo"))
        q = select(decisions).where(decisions.c.action == "PENDING").order_by(decisions.c.ts).limit(1)
        if not IS_SQLITE:
            q = q.with_for_update(skip_locked=True)  # dos líderes momentáneos nunca toman la misma señal
        r = c.execute(q).mappings().first()
        if not r:
            return None
        c.execute(update(decisions).where(decisions.c.id == r["id"]).values(action="PROCESSING"))
        return json.loads(r["payload"] or "{}").get("signal")


def expire_stale_processing(minutes: int = 10):
    """PROCESSING viejas = el proceso murió a la mitad. NO se re-ejecutan (podría duplicar la compra);
    si alcanzaron a comprar, recover_pending() se encarga de la posición."""
    with engine.begin() as c:
        c.execute(update(decisions).where(decisions.c.action == "PROCESSING",
                                          decisions.c.ts < now() - timedelta(minutes=minutes)).values(
            action="EXPIRED", reason="proceso interrumpido"))


def finish_decision(signal_id, action, reason, payload):
    with engine.begin() as c:
        c.execute(update(decisions).where(decisions.c.signal_id == signal_id).values(
            ts=now(), action=action, reason=reason, payload=json.dumps(payload, default=str)))


def signal_seen(signal_id: str) -> bool:
    with engine.begin() as c:
        return c.execute(select(decisions.c.id).where(decisions.c.signal_id == signal_id)).first() is not None


# ── Posiciones ────────────────────────────────────────────────
def intent_position(**kw):
    """Write-ahead: se escribe ANTES de mandar la compra. Falla (IntegrityError) si ya hay una viva en el par."""
    with engine.begin() as c:
        c.execute(insert(positions).values(status="PENDING", opened_at=now(), **kw))


def set_status(pid, status, **kw):
    with engine.begin() as c:
        c.execute(update(positions).where(positions.c.id == pid).values(status=status, **kw))


def activate_position(pid, **kw):
    set_status(pid, "OPEN", **kw)


def fail_position(pid, reason):
    set_status(pid, "FAILED", exit_reason=reason[:200], closed_at=now())


def open_position(**kw):  # paper / shadow
    with engine.begin() as c:
        c.execute(insert(positions).values(status="OPEN", opened_at=now(), **kw))


def close_position(pid, exit_price, reason):
    with engine.begin() as c:
        p = c.execute(select(positions).where(positions.c.id == pid)).mappings().first()
        if not p or p["status"] not in ("OPEN", "UNPROTECTED"):
            return None
        # comisión estimada de entrada + salida (conservadora: se resta aunque se pague en BNB)
        fee = (p["entry"] + exit_price) * p["qty"] * config.FEE_RATE
        pnl = (exit_price - p["entry"]) * p["qty"] - fee
        r = pnl / p["risk_usdt"] if p["risk_usdt"] else 0
        c.execute(update(positions).where(positions.c.id == pid).values(
            status="CLOSED", closed_at=now(), exit_price=exit_price, pnl_usdt=pnl, r_multiple=r, exit_reason=reason))
        return {"pnl_usdt": pnl, "r": r}


def _query(statuses, mode_filter):
    with engine.begin() as c:
        rows = c.execute(select(positions).where(positions.c.status.in_(list(statuses)), mode_filter)).mappings()
        return [{**dict(r), "opened_at": as_utc(r["opened_at"])} for r in rows]


def open_positions():
    """Del modo actual. PENDING y UNPROTECTED cuentan para límites de exposición."""
    return _query(LIVE_STATUSES, positions.c.mode == MODE)


def pending_positions(min_age_sec: int = 0):
    rows = _query(("PENDING",), positions.c.mode == MODE)
    return [p for p in rows if (now() - p["opened_at"]).total_seconds() >= min_age_sec]


def unprotected_positions():
    return _query(("UNPROTECTED",), positions.c.mode == MODE)


def shadow_positions():
    return _query(("OPEN",), positions.c.mode == "shadow")


def realized_pnl_since(hours: int) -> float:
    with engine.begin() as c:
        v = c.execute(select(func.coalesce(func.sum(positions.c.pnl_usdt), 0.0)).where(
            positions.c.status == "CLOSED", positions.c.mode == MODE,
            positions.c.closed_at >= now() - timedelta(hours=hours))).scalar()
        return float(v or 0)


def consecutive_losses() -> int:
    """Racha actual de operaciones perdedoras (modo actual, sin sombra). Se reinicia a mano con
    POST /admin/reset-streak, que guarda streak_reset_at: lo cerrado antes de esa hora ya no cuenta."""
    reset = get("streak_reset_at")
    reset_dt = as_utc(datetime.fromisoformat(reset)) if reset else None
    with engine.begin() as c:
        rows = c.execute(select(positions.c.r_multiple, positions.c.closed_at).where(
            positions.c.status == "CLOSED", positions.c.mode == MODE).order_by(positions.c.closed_at.desc()).limit(50)).all()
    n = 0
    for r, t in rows:
        if reset_dt and as_utc(t) <= reset_dt:
            break
        if (r or 0) > 0:
            break
        n += 1
    return n


# ── KV ────────────────────────────────────────────────────────
def get(k, default=None):
    with engine.begin() as c:
        r = c.execute(select(kv.c.v).where(kv.c.k == k)).first()
        return json.loads(r[0]) if r else default


def put(k, v):
    with engine.begin() as c:
        if c.execute(select(kv.c.k).where(kv.c.k == k)).first():
            c.execute(update(kv).where(kv.c.k == k).values(v=json.dumps(v)))
        else:
            c.execute(insert(kv).values(k=k, v=json.dumps(v)))


def stats(shadow: bool = False):
    """shadow=False: trades del bot en el modo actual. shadow=True: setups que las REGLAS habrían tomado
    pero el comité (LLMs/vetos) bloqueó. Si las sombra rinden más, los agentes están destruyendo valor."""
    with engine.begin() as c:
        rows = [dict(r) for r in c.execute(select(positions).where(
            positions.c.status == "CLOSED", positions.c.mode == ("shadow" if shadow else MODE))).mappings()]
    n = len(rows)
    if not n:
        return {"closed_trades": 0}
    wins = [r for r in rows if r["r_multiple"] > 0]
    gp = sum(r["pnl_usdt"] for r in wins)
    gl = -sum(r["pnl_usdt"] for r in rows if r["pnl_usdt"] < 0)
    eq, peak, mdd = 0.0, 0.0, 0.0
    for r in sorted(rows, key=lambda x: as_utc(x["closed_at"])):
        eq += r["pnl_usdt"]
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return {"closed_trades": n, "win_rate": round(len(wins) / n, 3),
            "expectancy_R": round(sum(r["r_multiple"] for r in rows) / n, 3),
            "profit_factor": round(gp / gl, 2) if gl else None,
            "pnl_usdt": round(sum(r["pnl_usdt"] for r in rows), 2),
            "max_drawdown_usdt": round(mdd, 2)}
