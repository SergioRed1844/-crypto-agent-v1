"""Setups de compra (derivados del corpus de microcomportamientos) y vetos de riesgo.

Cada setup es una regla determinista evaluada al CIERRE de la barra t con información ≤ t. El modelo EB
(radar/eb.py) estima después qué tan seguido "funcionó" en la historia, encogido hacia "sin ventaja".

Peso de evidencia w = peso_base(E) × decaimiento post-publicación × aplicabilidad a la clase (C11-004, C11-006,
C11-007). w NO es una probabilidad: solo decide qué tan escéptico es el prior (w bajo → hace falta más historia
para creerle al setup). Umbrales fijados el 18-oct-2026 ANTES de ver resultados; todo cambio posterior se declara
en docs/RADAR_EB.md (regla anti data-mining, C11-009 B).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import config as C
from . import features as F

E_WEIGHT = {"E1": 0.7, "E2": 0.9, "E3": 0.85, "E4": 0.6, "E5": 0.4, "E6": 0.35, "E7": 0.15}   # C11-004


@dataclass
class Setup:
    id: str
    nombre: str
    classes: tuple                       # clases donde aplica
    horizons: tuple                      # horizontes que reporta (el modelo los estima todos)
    cooldown: int                        # barras sin re-disparar en el mismo activo (episodios independientes)
    evidence: str                        # nivel E del mejor respaldo aplicable
    decay: float                         # C11-006
    applic: dict                         # aplicabilidad por clase (C11-007)
    refs: list = field(default_factory=list)   # chunks del corpus ("ID:clase" = solo para esa clase)
    mecanismo: str = ""
    no_inferir: str = ""
    verificar: str = ""
    in_corpus: bool = True

    def weight(self, cls: str) -> float:
        return round(E_WEIGHT[self.evidence] * self.decay * self.applic.get(cls, 0.0), 3)


SETUPS: dict[str, Setup] = {s.id: s for s in [
    Setup("PANICO_SIN_DANO", "Pánico sin daño real", ("crypto", "us", "bmv"), (7, 30), 5, "E3", 0.6,
          {"us": 1.0, "crypto": 0.7, "bmv": 0.7}, ["C08-006", "C12-013", "C12-017", "C12-008"],
          "Choque de ánimo amplio sin daño económico equivalente: el mercado sobrerreacciona y revierte en días "
          "(Kaplanski y Levy, 2010) [E3]; la atención rápida tiene vida media de ~1.5–2 días (Igarashi et al., 2022) [E4].",
          "Que el precio 'ya tocó piso'. Si hay daño fundamental (quiebra, hackeo, fraude) la reversión es parcial.",
          "Confirmar que la caída no viene de una noticia propia del activo (resultados, hackeo, demanda)."),
    Setup("CAPITULACION", "Capitulación con miedo extremo", ("crypto", "us", "bmv"), (90, 30), 30, "E4", 0.4,
          {"us": 1.0, "crypto": 0.7, "bmv": 0.8}, ["C12-013", "C09-018", "C13-014:crypto", "C12-007"],
          "Sobrerreacción a narrativas: perdedores extremos tienden a revertir a meses/años (De Bondt y Thaler, 1985) "
          "[E4]; el IPC cayó −24% a −27% en 1995, 2008 y 2020 y se recuperó en 6–12 meses [E5].",
          "Que la caída terminó: los pisos de choques sistémicos (Lehman) tardan años; el modelo no fecha el piso.",
          "Revisar si es choque financiero sistémico (solvencia) o de sentimiento; liquidez y deuda del emisor."),
    Setup("CHOQUE_POLITICO", "Reversión tras choque político/comercial", ("crypto", "us", "bmv"), (30, 7), 10,
          "E4", 0.6, {"us": 1.0, "crypto": 0.7, "bmv": 0.8}, ["C13-016", "C12-007", "C13-014:crypto", "C12-006"],
          "En choques no financieros la mediana de recuperación del índice va de días a ~2 meses; el mercado "
          "sobrerreacciona y revierte salvo cambio estructural (síntesis de 10 hitos, C13-016) [E4]; aranceles "
          "detonaron las mayores liquidaciones cripto (C13-014) [E7].",
          "Que el choque es transitorio si cambia flujos de caja permanentes (aranceles sostenidos, guerra larga).",
          "Clasificar el choque (C12-017 paso 1) y listar confusores ±5 días (bancos centrales, datos macro)."),
    Setup("MIEDO_HOGARES", "Miedo de hogares (FEARS) alto", ("us", "bmv"), (7, 30), 10, "E5", 0.6,
          {"us": 0.7, "bmv": 0.5}, ["C08-012", "C12-013", "C02-008"],
          "Búsquedas de ansiedad económica predicen reversiones de corto plazo y alzas temporales de volatilidad "
          "(Da, Engelberg y Gao, 2015) [E5]. Aquí con Wikipedia como proxy de Google: hipótesis, no regla.",
          "Que el miedo predice el piso exacto; es un termómetro de sentimiento, no de fundamentales.",
          "Ver si el miedo viene de un dato real (desempleo, quiebra bancaria) o de titulares."),
    Setup("CHOQUE_PESO", "Choque del peso con BMV castigada", ("bmv",), (30, 90), 15, "E5", 0.8, {"bmv": 1.0},
          ["C13-016", "C09-018", "C11-007", "C09-012"],
          "En los hitos globales el canal dominante hacia México fue el tipo de cambio, no el consumo (C13-016) "
          "[E4]; caídas del IPC de −24% a −27% se recuperaron en 6–12 meses (C09-018) [E5].",
          "Que el peso va a regresar: en la BMV la señal micro se lee en tipo de cambio, crédito y consumo, no en el "
          "IPC (C11-007).",
          "Revisar Banxico, calificación soberana y si el choque es local (fiscal) o global (aversión al riesgo)."),
    Setup("ATENCION_MOMENTUM", "Atención + momentum semanal (cripto)", ("crypto",), (7,), 7, "E4", 0.8,
          {"crypto": 0.8}, ["C13-013", "C16-006", "C12-013"],
          "Momentum y atención son los mejores predictores semanales de cripto: +1 DE de retorno semanal → +3.16% "
          "la semana siguiente en BTC; +1 DE de búsquedas → +1.84% (Liu y Tsyvinski, 2021) [E4]. Revierte después.",
          "Adopción: los flujos récord no son nuevos tenedores (SHED 10% vs 12%). La atención revierte en semanas.",
          "Semáforo de fase C16-006: si ya hay memecoins de celebridades o liquidaciones récord, es techo."),
    Setup("PULLBACK_TENDENCIA", "Retroceso dentro de tendencia alcista", ("crypto", "us", "bmv"), (30, 7), 15,
          "E4", 0.6, {"crypto": 0.8, "us": 0.8, "bmv": 0.8}, [],
          "Fuera del corpus: momentum de serie de tiempo (Moskowitz, Ooi y Pedersen, 2012, JFE) — comprar un "
          "retroceso cuando la tendencia de 200 días sigue arriba. Señal clásica de trading profesional.",
          "Que la tendencia sigue: un retroceso puede ser el inicio de un cambio de régimen.",
          "Ver volumen del retroceso y si el soporte (media de 50) aguantó al cierre.", in_corpus=False),
]}

W_BAR = round(float(np.mean([s.weight(c) for s in SETUPS.values() for c in s.classes])), 4)   # w promedio
CAL_EVIDENCE = ("E5", 0.4)    # efectos de calendario: correlacionales y erosionados (C08-008, C11-006)
CAL_WEIGHT = round(E_WEIGHT[CAL_EVIDENCE[0]] * CAL_EVIDENCE[1], 3)

DAMAGE_CATS = {"crypto": {"FINANCIAL_CRISIS", "HACK_SECURITY"}, "us": {"FINANCIAL_CRISIS"},
               "bmv": {"FINANCIAL_CRISIS"}}
POLITICAL_CATS = {"TRADE", "GEOPOLITICAL", "ELECTION", "GOV_TRANSITION", "FISCAL"}


# ── panel de variables por activo ───────────────────────────────────────────────────────────────────────
@dataclass
class Panel:
    sym: str
    cls: str
    dates: list
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    f: dict                       # variables (arrays alineados a dates)


def build_panel(s, cls: str, bench, aux: dict) -> Panel:
    """aux: {'vix': Series|None, 'mxn': Series|None, 'fg': dict, 'fears_en': dict, 'fears_es': dict,
             'attn': dict (vistas), 'events': list[dict]}"""
    c = s.close
    year = 365 if cls == "crypto" else 252
    wk = 7 if cls == "crypto" else 5
    f = {}
    f["r1"] = F.log_ret(c)
    f["sig60"] = F.roll_std(f["r1"], 60, shift=1)
    f["dd1y"] = c / F.roll_max(c, year) - 1
    f["ret2y"] = F.pct_change(c, 2 * year)
    f["ret5"] = F.pct_change(c, wk)
    f["sma50"] = F.roll_mean(c, 50)
    f["sma200"] = F.roll_mean(c, 200)
    f["max20"] = F.roll_max(c, 20)
    f["rsi14"] = F.rsi(c, 14)
    r7 = F.pct_change(c, wk)
    f["r7z"] = F.zscore_prev(r7, year)
    # mercado de la clase
    if bench is not None and len(bench):
        br1 = F.log_ret(bench.close)
        f["b_r1"] = F.align_series(s.dates, bench.dates, br1, 0)
        f["b_sig60"] = F.align_series(s.dates, bench.dates, F.roll_std(br1, 60, shift=1), 0)
        f["b_ret5"] = F.align_series(s.dates, bench.dates, F.pct_change(bench.close, wk), 0)
        f["b_ret2y"] = F.align_series(s.dates, bench.dates, F.pct_change(bench.close, 2 * year), 0)
        f["b_dd1y"] = F.align_series(s.dates, bench.dates, bench.close / F.roll_max(bench.close, year) - 1, 0)
    else:
        for k in ("b_r1", "b_sig60", "b_ret5", "b_ret2y", "b_dd1y"):
            f[k] = np.full(len(s), np.nan)
    vix = aux.get("vix")
    if vix is not None and len(vix):
        f["vix"] = F.align_series(s.dates, vix.dates, vix.close, 4)
        f["vix_m20"] = F.align_series(s.dates, vix.dates, F.roll_mean(vix.close, 20, shift=1), 4)
    else:
        f["vix"] = f["vix_m20"] = np.full(len(s), np.nan)
    mxn = aux.get("mxn")
    if mxn is not None and len(mxn):
        mr = F.log_ret(mxn.close)
        f["mxn_r1"] = F.align_series(s.dates, mxn.dates, mr, 0)
        f["mxn_sig60"] = F.align_series(s.dates, mxn.dates, F.roll_std(mr, 60, shift=1), 0)
        f["mxn_ret5"] = F.align_series(s.dates, mxn.dates, F.pct_change(mxn.close, 5), 0)
    else:
        f["mxn_r1"] = f["mxn_sig60"] = f["mxn_ret5"] = np.full(len(s), np.nan)
    fg = F.align(s.dates, aux.get("fg") or {}, 1)
    f["fg"] = fg
    fg3 = np.full(len(fg), np.nan)
    fg3[3:] = fg[3:] - fg[:-3]
    f["fg_chg3"] = fg3
    # FEARS y atención con rezago de 1 día (las vistas del día t se publican después del cierre)
    lang = "es" if cls == "bmv" else "en"
    fears = _lagged(s.dates, aux.get(f"fears_{lang}") or {})
    f["fears_z"] = F.zscore_prev(fears, 90)
    attn = aux.get("attn") or {}
    if attn:
        lv = _lagged(s.dates, {k: float(np.log1p(v)) for k, v in attn.items()})
        a7 = F.roll_mean(lv, 7)
        f["attn_z"] = F.zscore_prev(a7, 365)
    else:
        f["attn_z"] = np.full(len(s), np.nan)
    # eventos históricos curados (v4.2): días con daño fundamental o choque político en [t-3, t]
    f["damage"], f["political"] = _event_flags(s.dates, aux.get("events") or [], cls)
    return Panel(s.sym, cls, s.dates, s.open, s.high, s.low, s.close, f)


def _lagged(dates, mapping):
    from datetime import date, timedelta
    shifted = {}
    for d, v in mapping.items():
        try:
            shifted[(date.fromisoformat(d) + timedelta(days=1)).isoformat()] = v
        except ValueError:
            continue
    return F.align(dates, shifted, 3)


def _event_flags(dates, events, cls):
    from datetime import date, timedelta
    dmg, pol = set(), set()
    for e in events:
        if e.get("status") not in (None, "happened", "confirmed"):
            continue
        try:
            d0 = date.fromisoformat(str(e["date"])[:10])
        except (KeyError, ValueError):
            continue
        cat = e.get("category")
        win = [(d0 + timedelta(days=k)).isoformat() for k in range(0, 4)]   # el evento cuenta de t a t+3
        if cat in DAMAGE_CATS[cls]:
            dmg.update(win)
        if cat in POLITICAL_CATS:
            pol.update(win[:3])
    return (np.array([d in dmg for d in dates]), np.array([d in pol for d in dates]))


# ── reglas de disparo ───────────────────────────────────────────────────────────────────────────────────
def _nz(x):
    return np.nan_to_num(x, nan=np.nan)


def _lt(a, b):
    with np.errstate(invalid="ignore"):
        return np.asarray(a < b) & ~np.isnan(a) & ~np.isnan(np.broadcast_to(b, np.shape(a)))


def _gt(a, b):
    with np.errstate(invalid="ignore"):
        return np.asarray(a > b) & ~np.isnan(a) & ~np.isnan(np.broadcast_to(b, np.shape(a)))


def raw_triggers(setup_id: str, p: Panel) -> np.ndarray:
    f, cls, n = p.f, p.cls, len(p.dates)
    broad = p.sym in C.BROAD
    has_fg = ~np.isnan(f["fg"])
    if setup_id == "PANICO_SIN_DANO":
        shock = _lt(f["r1"], -2.5 * f["sig60"])
        market = _lt(f["b_r1"], -2.0 * f["b_sig60"])
        if cls == "crypto":
            fear = np.where(has_fg, _lt(f["fg"], 35.0001) | _lt(f["fg_chg3"], -15), _lt(f["r1"], -3.0 * f["sig60"]))
        else:
            fear = _gt(f["vix"], 1.25 * f["vix_m20"])
        return shock & market & fear & ~f["damage"]
    if setup_id == "CAPITULACION":
        lim = {"crypto": -0.50, "us": -0.20 if broad else -0.35, "bmv": -0.20 if broad else -0.30}[cls]
        deep = _lt(f["dd1y"], lim) & _lt(f["rsi14"], 30)
        if cls == "crypto":
            fear = np.where(has_fg, _lt(f["fg"], 20.0001), True)
        else:
            fear = _gt(f["vix"], 25) | _lt(f["b_dd1y"], -0.15)
        return deep & fear
    if setup_id == "CHOQUE_POLITICO":
        return f["political"] & _lt(f["b_r1"], -1.5 * f["b_sig60"]) & _lt(f["r1"], -1.5 * f["sig60"])
    if setup_id == "MIEDO_HOGARES":
        if not broad:
            return np.zeros(n, bool)
        return _gt(f["fears_z"], 2.0) & _lt(f["b_ret5"], -0.03)
    if setup_id == "CHOQUE_PESO":
        if cls != "bmv":
            return np.zeros(n, bool)
        fx = _gt(f["mxn_r1"], 2.5 * f["mxn_sig60"]) | _gt(f["mxn_ret5"], 0.04)
        return fx & _lt(f["ret5"], -0.03)
    if setup_id == "ATENCION_MOMENTUM":
        if cls != "crypto":
            return np.zeros(n, bool)
        calm = np.where(has_fg, _lt(f["fg"], 75), True)
        return _gt(f["r7z"], 1.0) & _gt(f["attn_z"], 1.0) & calm
    if setup_id == "PULLBACK_TENDENCIA":
        pb = {"crypto": 0.15, "us": 0.05 if broad else 0.08, "bmv": 0.06}[cls]
        trend = _gt(p.close, f["sma200"]) & _gt(f["sma50"], f["sma200"])
        dip = _lt(p.close, (1 - pb) * f["max20"]) & _gt(p.close, 0.97 * f["sma50"])
        return trend & dip
    raise KeyError(setup_id)


def apply_cooldown(trig: np.ndarray, cooldown: int) -> np.ndarray:
    out = np.zeros_like(trig)
    last = -10**9
    for i in np.flatnonzero(trig):
        if i - last > cooldown:
            out[i] = True
            last = i
    return out


def triggers(setup_id: str, p: Panel) -> np.ndarray:
    s = SETUPS[setup_id]
    if p.cls not in s.classes:
        return np.zeros(len(p.dates), bool)
    return apply_cooldown(raw_triggers(setup_id, p), s.cooldown)


# ── vetos y avisos de riesgo (solo RESTAN) ──────────────────────────────────────────────────────────────
def risk_flags(p: Panel, i: int) -> dict:
    """Avisos al cierre de la barra i. GSY (C15-011): run-up neto de mercado en 2 años."""
    f = p.f
    run = f["ret2y"][i]
    if p.sym != C.BENCH.get(p.cls) and np.isfinite(f["b_ret2y"][i]):
        run = run - f["b_ret2y"][i]
    out = {"gsy_runup_2y": None if not np.isfinite(run) else round(float(run), 3)}
    out["gsy"] = "rojo" if (np.isfinite(run) and run >= 1.5) else ("amarillo" if (np.isfinite(run) and run >= 1.0)
                                                                    else "ok")
    fg = f["fg"][i]
    out["fear_greed"] = None if not np.isfinite(fg) else int(fg)
    out["euforia"] = bool(p.cls == "crypto" and np.isfinite(fg) and fg >= 80)       # C16-006 rojo / DERIV_STRICT
    out["vix"] = None if not np.isfinite(f["vix"][i]) else round(float(f["vix"][i]), 1)
    out["damage_event"] = bool(f["damage"][i])
    return out


def vetoed(flags: dict, horizon: int) -> list[str]:
    v = []
    if flags.get("euforia"):
        v.append("euforia cripto (Fear&Greed ≥ 80; C16-006)")
    if flags.get("gsy") == "rojo" and horizon >= 90:
        v.append("run-up ≥150% en 2 años: riesgo de crash ≥40% ~81% (industrias EUA, GSY 2019; C15-011)")
    if flags.get("damage_event"):
        v.append("evento con daño fundamental reciente (quiebra/hackeo)")
    return v
