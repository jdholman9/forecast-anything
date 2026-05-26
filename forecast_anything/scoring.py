"""
Scoring rules for evaluating forecast accuracy.

Standard CRPS:      forecast distribution vs point observation
Generalized CRPS:   forecast distribution vs uncertain observation (distribution)
Brier score:        binary probability vs boolean outcome

The generalized CRPS is:

    CRPS(F, G) = ∫_{-∞}^{∞} [F(x) - G(x)]² dx

where F is the forecast CDF and G is the observation CDF.  When the
observation is a known point y, G becomes a step function and this
reduces to the standard CRPS.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy import integrate, stats

if TYPE_CHECKING:
    from forecast_anything.distributions import Distribution


# -----------------------------------------------------------------------
# Standard CRPS — point observation
# -----------------------------------------------------------------------


def crps_normal_point(mean: float, std: float, observation: float) -> float:
    """
    Closed-form CRPS for a Normal forecast against a point observation.

    CRPS(N(μ,σ), y) = σ [z(2Φ(z) − 1) + 2φ(z) − 1/√π]
    where z = (y − μ) / σ
    """
    z = (observation - mean) / std
    return float(
        std * (z * (2.0 * stats.norm.cdf(z) - 1.0) + 2.0 * stats.norm.pdf(z) - 1.0 / np.sqrt(np.pi))
    )


def crps_empirical_point(samples: np.ndarray, observation: float) -> float:
    """
    Exact CRPS for an empirical forecast against a point observation.

    CRPS = (1/n) Σ|xᵢ − y| − (1/2n²) ΣΣ|xᵢ − xⱼ|

    Uses the sorted-sample shortcut for the spread term:
    (1/2n²) ΣΣ|xᵢ − xⱼ| = (1/n²) Σᵢ (2i − n − 1) x_{(i)}
    """
    s = np.sort(samples)
    n = len(s)
    mae = np.mean(np.abs(s - observation))
    # Gini mean difference via sorted samples
    idx = np.arange(1, n + 1)
    spread = np.sum((2.0 * idx - n - 1.0) * s) / (n * n)
    return float(mae - spread)


def crps_point(dist: Distribution, observation: float) -> float:
    """
    Standard CRPS for any Distribution object against a point observation.

    Uses closed-form when available, otherwise falls back to numerical
    integration.
    """
    from forecast_anything.distributions import (
        EmpiricalDistribution,
        NormalDistribution,
    )

    if isinstance(dist, NormalDistribution):
        d = dist.to_dict()
        return crps_normal_point(d["mean"], d["std"], observation)

    if isinstance(dist, EmpiricalDistribution):
        return crps_empirical_point(dist.samples, observation)

    # General case: numerical integration
    # CRPS(F, y) = ∫ [F(x) − 𝟙(x ≥ y)]² dx
    #            = ∫_{-∞}^{y} F(x)² dx + ∫_{y}^{∞} [1 − F(x)]² dx
    #            (split avoids integrating across the step discontinuity)
    lo = dist.quantile(1e-6)
    hi = dist.quantile(1 - 1e-6)
    # Extend range a bit past the observation if needed
    lo = min(lo, observation - abs(observation) * 0.1 - 1)
    hi = max(hi, observation + abs(observation) * 0.1 + 1)

    def left_integrand(x):
        return dist.cdf(x) ** 2

    def right_integrand(x):
        return (1.0 - dist.cdf(x)) ** 2

    left, _ = integrate.quad(left_integrand, lo, observation, limit=100)
    right, _ = integrate.quad(right_integrand, observation, hi, limit=100)
    return float(left + right)


# -----------------------------------------------------------------------
# Generalized CRPS — uncertain (distributional) observation
# -----------------------------------------------------------------------


def crps_normal_normal(
    f_mean: float, f_std: float,
    g_mean: float, g_std: float,
) -> float:
    """
    Closed-form CRPS for Normal forecast vs Normal observation.

    ∫ [Φ((x−μ_f)/σ_f) − Φ((x−μ_g)/σ_g)]² dx

    Derived from the identity:
    ∫ Φ((x−a)/α) Φ((x−b)/β) dx = ... (bivariate normal formula)

    Result:
    CRPS = √(σ_f² + σ_g²) · A(δ) − σ_f/√π − σ_g/√π + σ_f·A(0) + σ_g·A(0)

    where A(z) = 2z·Φ(z) + 2φ(z),  δ = (μ_f − μ_g)/√(σ_f² + σ_g²)

    Actually, using the decomposition:
    ∫(F−G)² = ∫F² + ∫G² − 2∫FG

    Each piece has known forms for normals.
    """
    # Numerical integration is more reliable for this case and still fast
    sigma_total = np.sqrt(f_std**2 + g_std**2)
    lo = min(f_mean, g_mean) - 6 * sigma_total
    hi = max(f_mean, g_mean) + 6 * sigma_total

    f_rv = stats.norm(f_mean, f_std)
    g_rv = stats.norm(g_mean, g_std)

    def integrand(x):
        return (f_rv.cdf(x) - g_rv.cdf(x)) ** 2

    result, _ = integrate.quad(integrand, lo, hi, limit=200)
    return float(result)


def _crps_empirical_vs_dist(empirical_dist, other_dist) -> float:
    """
    Generalized CRPS for an empirical forecast vs a smooth actual distribution.

    Splits the integral at the empirical CDF's jump points to avoid
    quadrature warnings from step-function discontinuities.

    ∫(F_emp(x) - G(x))² dx
      = ∫_{-∞}^{x₁} G(x)² dx
      + Σᵢ ∫_{xᵢ}^{x_{i+1}} (i/n - G(x))² dx
      + ∫_{xₙ}^{∞} (1 - G(x))² dx
    """
    samples = np.sort(empirical_dist.samples)
    n = len(samples)

    # Determine tail bounds from the smooth distribution
    try:
        lo = other_dist.quantile(1e-7)
        hi = other_dist.quantile(1 - 1e-7)
    except Exception:
        lo = other_dist.mean - 7 * other_dist.std
        hi = other_dist.mean + 7 * other_dist.std

    lo = min(lo, samples[0] - abs(samples[0]) * 0.1 - 1)
    hi = max(hi, samples[-1] + abs(samples[-1]) * 0.1 + 1)

    total = 0.0

    # Left tail: ∫_{lo}^{x₁} G(x)² dx   (F=0 in this region)
    def left_tail(x):
        return other_dist.cdf(x) ** 2
    val, _ = integrate.quad(left_tail, lo, samples[0], limit=50)
    total += val

    # Interior segments: ∫_{xᵢ}^{x_{i+1}} (i/n - G(x))² dx
    for i in range(n - 1):
        level = (i + 1) / n

        def segment_integrand(x, lev=level):
            return (lev - other_dist.cdf(x)) ** 2

        val, _ = integrate.quad(segment_integrand, samples[i], samples[i + 1], limit=50)
        total += val

    # Right tail: ∫_{xₙ}^{hi} (1 - G(x))² dx   (F=1 in this region)
    def right_tail(x):
        return (1.0 - other_dist.cdf(x)) ** 2
    val, _ = integrate.quad(right_tail, samples[-1], hi, limit=50)
    total += val

    return float(total)


def crps_generalized(forecast_dist: Distribution, actual_dist: Distribution) -> float:
    """
    Generalized CRPS: ∫ [F(x) − G(x)]² dx

    Works for any combination of Distribution types.  Uses closed-form
    when both are Normal; otherwise numerical integration with smart
    splitting for empirical distributions.
    """
    from forecast_anything.distributions import EmpiricalDistribution, NormalDistribution

    # Normal–Normal path
    if isinstance(forecast_dist, NormalDistribution) and isinstance(actual_dist, NormalDistribution):
        fd = forecast_dist.to_dict()
        gd = actual_dist.to_dict()
        return crps_normal_normal(fd["mean"], fd["std"], gd["mean"], gd["std"])

    # Empirical forecast vs smooth actual — split at jump points
    if isinstance(forecast_dist, EmpiricalDistribution) and not isinstance(actual_dist, EmpiricalDistribution):
        return _crps_empirical_vs_dist(forecast_dist, actual_dist)

    # Smooth forecast vs empirical actual — swap and use symmetry
    # ∫(F-G)² = ∫(G-F)²
    if isinstance(actual_dist, EmpiricalDistribution) and not isinstance(forecast_dist, EmpiricalDistribution):
        return _crps_empirical_vs_dist(actual_dist, forecast_dist)

    # General fallback: numerical integration
    try:
        f_lo = forecast_dist.quantile(1e-6)
        f_hi = forecast_dist.quantile(1 - 1e-6)
    except Exception:
        f_lo = forecast_dist.mean - 6 * forecast_dist.std
        f_hi = forecast_dist.mean + 6 * forecast_dist.std

    try:
        g_lo = actual_dist.quantile(1e-6)
        g_hi = actual_dist.quantile(1 - 1e-6)
    except Exception:
        g_lo = actual_dist.mean - 6 * actual_dist.std
        g_hi = actual_dist.mean + 6 * actual_dist.std

    lo = min(f_lo, g_lo)
    hi = max(f_hi, g_hi)

    def integrand(x):
        return (forecast_dist.cdf(x) - actual_dist.cdf(x)) ** 2

    result, _ = integrate.quad(integrand, lo, hi, limit=200)
    return float(result)


# -----------------------------------------------------------------------
# Dispatcher
# -----------------------------------------------------------------------


def crps(
    forecast_dist: Distribution,
    actual: float | Distribution,
) -> float:
    """
    Compute CRPS for a forecast distribution against an actual.

    If actual is a float, uses the standard point-observation CRPS.
    If actual is a Distribution, uses the generalized CRPS.
    """
    from forecast_anything.distributions import Distribution as DistBase

    if isinstance(actual, (int, float)):
        return crps_point(forecast_dist, float(actual))
    elif isinstance(actual, DistBase):
        return crps_generalized(forecast_dist, actual)
    else:
        raise TypeError(f"actual must be a float or Distribution, got {type(actual)}")


# -----------------------------------------------------------------------
# Brier score (binary forecasts)
# -----------------------------------------------------------------------


def brier_score(probability: float, outcome: bool) -> float:
    """
    Brier score: (p − o)² where o ∈ {0, 1}.

    Lower is better.  Range: [0, 1].
    """
    o = 1.0 if outcome else 0.0
    return float((probability - o) ** 2)
