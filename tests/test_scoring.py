"""
Lightest-possible safety net for the scoring math.

Covers closed-form-known CRPS values (Normal vs point, empirical vs point,
Normal vs Normal self-pair) and textbook Brier values. The point is to catch
regressions in the integrators or sign errors, not to be a full numerical
analysis suite.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from forecast_anything.distributions import (
    EmpiricalDistribution,
    NormalDistribution,
    UniformDistribution,
)
from forecast_anything.scoring import (
    brier_score,
    crps,
    crps_empirical_point,
    crps_generalized,
    crps_normal_normal,
    crps_normal_point,
)


# ── Brier — textbook values ───────────────────────────────────────────


class TestBrier:
    def test_perfect_yes(self):
        assert brier_score(1.0, True) == pytest.approx(0.0)

    def test_perfect_no(self):
        assert brier_score(0.0, False) == pytest.approx(0.0)

    def test_max_wrong_yes(self):
        assert brier_score(0.0, True) == pytest.approx(1.0)

    def test_max_wrong_no(self):
        assert brier_score(1.0, False) == pytest.approx(1.0)

    def test_coin_flip(self):
        assert brier_score(0.5, True) == pytest.approx(0.25)
        assert brier_score(0.5, False) == pytest.approx(0.25)

    def test_seventy_percent(self):
        assert brier_score(0.7, True) == pytest.approx(0.09, abs=1e-9)
        assert brier_score(0.7, False) == pytest.approx(0.49, abs=1e-9)

    def test_range_bounded(self):
        for p in np.linspace(0.0, 1.0, 11):
            assert 0.0 <= brier_score(p, True) <= 1.0
            assert 0.0 <= brier_score(p, False) <= 1.0


# ── CRPS — Normal forecast vs point observation ───────────────────────


# Closed form: CRPS(N(0,1), 0) = √(2/π) − 1/√π
CRPS_STD_NORMAL_AT_ZERO = math.sqrt(2.0 / math.pi) - 1.0 / math.sqrt(math.pi)


class TestCrpsNormalPoint:
    def test_standard_normal_at_zero(self):
        got = crps_normal_point(mean=0.0, std=1.0, observation=0.0)
        assert got == pytest.approx(CRPS_STD_NORMAL_AT_ZERO, abs=1e-12)

    def test_scaling_with_std(self):
        # CRPS(N(0, σ), 0) = σ · CRPS(N(0, 1), 0)
        for sigma in (0.5, 1.5, 3.0, 10.0):
            got = crps_normal_point(mean=0.0, std=sigma, observation=0.0)
            expected = sigma * CRPS_STD_NORMAL_AT_ZERO
            assert got == pytest.approx(expected, abs=1e-10)

    def test_shift_invariance(self):
        # CRPS(N(μ, σ), μ) should equal CRPS(N(0, σ), 0)
        for mu in (-5.0, -0.3, 0.0, 2.7, 42.0):
            got = crps_normal_point(mean=mu, std=1.0, observation=mu)
            assert got == pytest.approx(CRPS_STD_NORMAL_AT_ZERO, abs=1e-10)

    def test_non_negative(self):
        # CRPS is a proper scoring rule — never negative
        for obs in (-3.0, -0.5, 0.0, 1.7, 5.0):
            assert crps_normal_point(0.0, 1.0, obs) >= 0.0

    def test_increases_with_distance(self):
        # Further-from-mean observation → strictly higher CRPS
        base = crps_normal_point(0.0, 1.0, 0.0)
        for d in (0.5, 1.0, 2.0, 5.0):
            assert crps_normal_point(0.0, 1.0, d) > base


# ── CRPS — empirical forecast vs point observation ────────────────────


class TestCrpsEmpiricalPoint:
    def test_single_sample_at_observation(self):
        # CRPS({x}, x) = 0 (zero distance, zero spread)
        got = crps_empirical_point(np.array([5.0]), observation=5.0)
        assert got == pytest.approx(0.0, abs=1e-12)

    def test_two_samples_known(self):
        # samples {0, 1}, obs = 0.5:
        # MAE = (0.5 + 0.5) / 2 = 0.5
        # spread = (1/4) Σ (2i − n − 1) x_(i)
        #        = (1/4) [(−1)·0 + (1)·1] = 0.25
        # CRPS = 0.5 − 0.25 = 0.25
        got = crps_empirical_point(np.array([0.0, 1.0]), observation=0.5)
        assert got == pytest.approx(0.25, abs=1e-12)

    def test_identical_samples(self):
        # All samples at x, observation at x → CRPS = 0
        got = crps_empirical_point(np.full(20, 3.7), observation=3.7)
        assert got == pytest.approx(0.0, abs=1e-12)

    def test_non_negative_random(self):
        rng = np.random.default_rng(42)
        samples = rng.normal(0.0, 1.0, size=100)
        for obs in (-2.0, 0.0, 2.0):
            assert crps_empirical_point(samples, obs) >= 0.0

    def test_unsorted_input_handled(self):
        # Function must sort internally — order shouldn't matter
        a = crps_empirical_point(np.array([1.0, 0.0]), observation=0.5)
        b = crps_empirical_point(np.array([0.0, 1.0]), observation=0.5)
        assert a == pytest.approx(b, abs=1e-12)


# ── CRPS dispatcher (Distribution objects) ────────────────────────────


class TestCrpsDispatcher:
    def test_normal_point_matches_closed_form(self):
        f = NormalDistribution(mean=0.0, std=1.0)
        got = crps(f, 0.0)
        assert got == pytest.approx(CRPS_STD_NORMAL_AT_ZERO, abs=1e-10)

    def test_empirical_point_matches_direct(self):
        samples = np.array([0.0, 1.0, 2.0, 3.0])
        f = EmpiricalDistribution(samples=samples.tolist())
        direct = crps_empirical_point(samples, observation=1.5)
        via_dispatcher = crps(f, 1.5)
        assert via_dispatcher == pytest.approx(direct, abs=1e-12)

    def test_int_observation_accepted(self):
        f = NormalDistribution(mean=0.0, std=1.0)
        # int should be coerced to float
        assert crps(f, 0) == pytest.approx(crps(f, 0.0), abs=1e-12)

    def test_rejects_unsupported_actual_type(self):
        f = NormalDistribution(mean=0.0, std=1.0)
        with pytest.raises(TypeError):
            crps(f, "not a number")  # type: ignore[arg-type]


# ── Generalized CRPS (distribution vs distribution) ───────────────────


class TestCrpsGeneralized:
    def test_normal_vs_self_is_zero(self):
        # ∫(F − G)² dx = 0 when F == G
        result = crps_normal_normal(0.0, 1.0, 0.0, 1.0)
        assert result == pytest.approx(0.0, abs=1e-8)

    def test_normal_vs_self_dispatcher(self):
        f = NormalDistribution(mean=0.0, std=1.0)
        # Cleaner to compare via dispatcher path
        result = crps_generalized(f, NormalDistribution(mean=0.0, std=1.0))
        assert result == pytest.approx(0.0, abs=1e-8)

    def test_symmetry_normal_vs_normal(self):
        # CRPS(F, G) == CRPS(G, F) — ∫(F-G)² is symmetric
        a = crps_normal_normal(0.0, 1.0, 2.0, 1.5)
        b = crps_normal_normal(2.0, 1.5, 0.0, 1.0)
        assert a == pytest.approx(b, abs=1e-8)

    def test_increases_with_mean_separation(self):
        # Further-apart means → higher CRPS, holding stds fixed
        base = crps_normal_normal(0.0, 1.0, 0.5, 1.0)
        far = crps_normal_normal(0.0, 1.0, 3.0, 1.0)
        assert far > base

    def test_empirical_vs_normal(self):
        # Empirical mass near the mean of a tight normal → small CRPS.
        # Use ≥ 2 samples (EmpiricalDistribution requires it for KDE).
        f = EmpiricalDistribution(samples=[-0.01, 0.0, 0.01])
        g = NormalDistribution(mean=0.0, std=0.01)
        result = crps_generalized(f, g)
        assert result >= 0.0
        assert result < 0.05  # tight normal centered at the empirical mass

    def test_dispatcher_uses_generalized_for_distribution_actual(self):
        f = NormalDistribution(mean=0.0, std=1.0)
        g = NormalDistribution(mean=0.0, std=1.0)
        result = crps(f, g)
        assert result == pytest.approx(0.0, abs=1e-8)

    def test_uniform_vs_uniform_self(self):
        # General numerical-integration path: U(0,1) vs U(0,1) should be ≈ 0
        f = UniformDistribution(low=0.0, high=1.0)
        g = UniformDistribution(low=0.0, high=1.0)
        result = crps_generalized(f, g)
        assert result == pytest.approx(0.0, abs=1e-6)
