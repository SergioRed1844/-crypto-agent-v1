"""Bayes empírico (skill adjunta, Vidakovic): las funciones puras del modelo.

- Beta-Binomial PEB por método de momentos (ejemplo de contaminación de agua, §4.2): tablas de ventana de entrada
  y de día de la semana.
- Normal-Normal / James-Stein en escala logit (§3.4 y §4.4): ventaja del setup sobre "comprar un día cualquiera",
  con prior escéptico centrado en CERO (sin ventaja, McLean-Pontiff C02-011) cuya varianza se estima con TODOS los
  setups (EB) y se reparte según el peso de evidencia del corpus.
- Poisson-Gamma PEB (§4.2): frecuencia con que aparece un setup en cada activo.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.special import expit, logit
from scipy.stats import beta as beta_dist

Z10 = 1.2815515655446004   # cuantil 90% de la normal (IC80 = q10..q90)


def jeffreys(k: float, n: float) -> float:
    return (k + 0.5) / (n + 1.0)


def logit_lift(k: float, n: float, base: float) -> tuple[float, float]:
    """Ventaja observada en logit y su varianza de muestreo (aprox. delta, con corrección de Jeffreys)."""
    p = jeffreys(k, n)
    b = min(max(base, 1e-4), 1 - 1e-4)
    return float(logit(p) - logit(b)), float(1.0 / ((n + 1.0) * p * (1 - p)))


# ── prior escéptico estimado con todos los setups (James-Stein centrado en 0) ───────────────────────────
def tau2_across(effects: list[float], variances: list[float], floor: float, cap: float) -> float:
    """MoM para δ_k ~ N(0, τ² + v_k):  τ² = mean(δ_k² − v_k), recortado a [floor, cap]."""
    if len(effects) < 3:
        return floor
    est = float(np.mean(np.square(effects) - np.asarray(variances)))
    return float(min(max(est, floor), cap))


def prior_var(tau2_all: float, w: float, floor: float) -> float:
    """El corpus reparte la variación real entre setups: w alto → prior más ancho (le cree antes a los datos)."""
    return max(floor, tau2_all * 2.0 * max(0.0, min(1.0, w)))


def normal_posterior(y: float, v: float, prior_mean: float, prior_v: float) -> tuple[float, float, float]:
    """Normal-Normal: devuelve (media, varianza, B) con B = fracción encogida hacia el prior."""
    if not np.isfinite(y) or v <= 0:
        return prior_mean, prior_v, 1.0
    B = v / (v + prior_v)
    return prior_mean + (1 - B) * (y - prior_mean), prior_v * v / (prior_v + v), B


def tau2_between(ys: list[float], vs: list[float], cap: float, min_groups: int = 5) -> float:
    """Varianza real entre activos por DerSimonian-Laird (momentos ponderados por precisión), con tope `cap`.

    Con pocos activos el estimador es muy ruidoso (bajo la nula sale > 0 la mitad de las veces), así que se exige
    ≥ min_groups y se acota: un activo no puede desviarse del setup más de lo que los setups varían entre sí."""
    if len(ys) < min_groups:
        return 0.0
    y, v = np.asarray(ys, float), np.asarray(vs, float)
    w = 1.0 / v
    ybar = float(np.sum(w * y) / np.sum(w))
    Q = float(np.sum(w * (y - ybar) ** 2))
    denom = float(np.sum(w) - np.sum(w * w) / np.sum(w))
    if denom <= 0:
        return 0.0
    return float(min(max(0.0, (Q - (len(y) - 1)) / denom), cap))


def shrink_member(y: float, v: float, center: float, center_var: float, tau2: float) -> tuple[float, float, float]:
    """Encoge el efecto de un miembro (activo) hacia el centro del grupo, propagando la incertidumbre del centro."""
    if tau2 <= 0 or not np.isfinite(y):
        return center, center_var + max(tau2, 0.0), 1.0
    B = v / (v + tau2)
    mean = center + (1 - B) * (y - center)
    var = tau2 * v / (tau2 + v) + B * B * center_var
    return mean, var, B


def prob_from_logit(base: float, delta: float, var: float) -> dict:
    b = min(max(base, 1e-4), 1 - 1e-4)
    m = logit(b) + delta
    sd = math.sqrt(max(var, 0.0))
    return {"p": float(expit(m)), "q10": float(expit(m - Z10 * sd)), "q90": float(expit(m + Z10 * sd)),
            "lift": float(expit(m) - b)}


# ── Beta-Binomial por momentos (tablas por categoría) ───────────────────────────────────────────────────
def beta_binomial_mom(k: np.ndarray, n: np.ndarray, c_min: float = 2.0, c_max: float = 1e5) -> tuple[float, float]:
    """Hiperparámetros (μ, c=α+β) de θ_j ~ Beta(μc, (1−μ)c) con k_j ~ Bin(n_j, θ_j), por momentos.

    E[s²] ≈ μ(1−μ)[ρ + (1−ρ)/n̄], ρ = 1/(c+1). Si la varianza entre grupos no supera la binomial → c = c_max."""
    k, n = np.asarray(k, float), np.asarray(n, float)
    ok = n > 0
    k, n = k[ok], n[ok]
    if len(n) == 0:
        return 0.5, c_min
    mu = float(k.sum() / n.sum())
    if len(n) < 2 or mu <= 0 or mu >= 1:
        return min(max(mu, 1e-3), 1 - 1e-3), c_max
    p = k / n
    s2 = float(np.average((p - mu) ** 2, weights=n))
    nbar = float(n.mean())
    rho = (s2 / (mu * (1 - mu)) - 1 / nbar) / (1 - 1 / nbar) if nbar > 1 else 0.0
    if rho <= 1.0 / (c_max + 1):
        return mu, c_max
    c = 1.0 / rho - 1.0
    return mu, float(min(max(c, c_min), c_max))


def beta_table(k: np.ndarray, n: np.ndarray, c_floor: float = 0.0, draws: int = 4000, seed: int = 7) -> dict:
    """Posteriores Beta encogidas por categoría + P(cada categoría es la mejor) por Monte Carlo.

    c_floor es el escepticismo del corpus: concentración mínima del prior (más alta → más encogimiento)."""
    mu, c = beta_binomial_mom(k, n)
    c = max(c, c_floor)
    a = np.asarray(k, float) + mu * c
    b = np.asarray(n, float) - np.asarray(k, float) + (1 - mu) * c
    post = a / (a + b)
    rng = np.random.default_rng(seed)
    sims = np.stack([rng.beta(ai, bi, draws) for ai, bi in zip(a, b)])
    p_best = np.bincount(np.argmax(sims, axis=0), minlength=len(a)) / draws
    q10 = beta_dist.ppf(0.10, a, b)
    q90 = beta_dist.ppf(0.90, a, b)
    return {"mu": mu, "c": c, "post": post.tolist(), "q10": q10.tolist(), "q90": q90.tolist(),
            "p_best": p_best.tolist(), "raw": (np.asarray(k, float) / np.maximum(np.asarray(n, float), 1)).tolist(),
            "n": np.asarray(n, float).tolist()}


# ── Poisson-Gamma: frecuencia de aparición ──────────────────────────────────────────────────────────────
def poisson_gamma(x: np.ndarray, e: np.ndarray) -> dict:
    """λ_a ~ Gamma(α, β) por momentos; posterior (x_a + α)/(e_a + β). x = conteos, e = años de exposición."""
    x, e = np.asarray(x, float), np.asarray(e, float)
    ok = e > 0
    if ok.sum() == 0:
        return {"alpha": 0.0, "beta": 0.0, "post": [0.0] * len(x), "pooled": 0.0}
    m = float(x[ok].sum() / e[ok].sum())
    r = x[ok] / e[ok]
    var_lam = float(np.var(r, ddof=1) - m * np.mean(1 / e[ok])) if ok.sum() > 1 else 0.0
    if var_lam <= 1e-9 or m <= 0:
        post = [m] * len(x)
        return {"alpha": float("inf"), "beta": float("inf"), "post": post, "pooled": m}
    a, b = m * m / var_lam, m / var_lam
    post = [float((xi + a) / (ei + b)) if ei > 0 else m for xi, ei in zip(x, e)]
    return {"alpha": a, "beta": b, "post": post, "pooled": m}


def brier(p: np.ndarray, y: np.ndarray) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2)) if len(p) else float("nan")
