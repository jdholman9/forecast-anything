from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
from scipy import stats
from scipy.stats import gaussian_kde

DISTRIBUTION_REGISTRY: dict[str, type[Distribution]] = {}


def register_distribution(name: str):
    def decorator(cls: type[Distribution]):
        cls.dist_name = name
        DISTRIBUTION_REGISTRY[name] = cls
        return cls
    return decorator


def distribution_from_dict(data: dict) -> Distribution:
    dist_type = data["type"]
    if dist_type not in DISTRIBUTION_REGISTRY:
        raise ValueError(f"Unknown distribution type: {dist_type!r}. Available: {list(DISTRIBUTION_REGISTRY)}")
    return DISTRIBUTION_REGISTRY[dist_type].from_dict(data)


class Distribution(ABC):
    dist_name: str = ""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        ...

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> Distribution:
        ...

    @abstractmethod
    def pdf(self, x: float | np.ndarray) -> float | np.ndarray:
        ...

    @abstractmethod
    def cdf(self, x: float | np.ndarray) -> float | np.ndarray:
        ...

    @abstractmethod
    def quantile(self, p: float | np.ndarray) -> float | np.ndarray:
        ...

    @property
    @abstractmethod
    def mean(self) -> float:
        ...

    @property
    @abstractmethod
    def std(self) -> float:
        ...

    def __repr__(self) -> str:
        params = {k: v for k, v in self.to_dict().items() if k != "type"}
        return f"{self.__class__.__name__}({params})"


# ---------------------------------------------------------------------------
# Parametric distributions backed by scipy.stats
# ---------------------------------------------------------------------------


@register_distribution("normal")
class NormalDistribution(Distribution):
    def __init__(self, mean: float, std: float):
        if std <= 0:
            raise ValueError("std must be positive")
        self._mean = float(mean)
        self._std = float(std)
        self._rv = stats.norm(loc=self._mean, scale=self._std)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "normal", "mean": self._mean, "std": self._std}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NormalDistribution:
        return cls(mean=data["mean"], std=data["std"])

    def pdf(self, x):
        return self._rv.pdf(x)

    def cdf(self, x):
        return self._rv.cdf(x)

    def quantile(self, p):
        return self._rv.ppf(p)

    @property
    def mean(self) -> float:
        return self._mean

    @property
    def std(self) -> float:
        return self._std


@register_distribution("lognormal")
class LogNormalDistribution(Distribution):
    def __init__(self, mu: float, sigma: float):
        if sigma <= 0:
            raise ValueError("sigma must be positive")
        self._mu = float(mu)
        self._sigma = float(sigma)
        self._rv = stats.lognorm(s=self._sigma, scale=np.exp(self._mu))

    def to_dict(self) -> dict[str, Any]:
        return {"type": "lognormal", "mu": self._mu, "sigma": self._sigma}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LogNormalDistribution:
        return cls(mu=data["mu"], sigma=data["sigma"])

    def pdf(self, x):
        return self._rv.pdf(x)

    def cdf(self, x):
        return self._rv.cdf(x)

    def quantile(self, p):
        return self._rv.ppf(p)

    @property
    def mean(self) -> float:
        return float(self._rv.mean())

    @property
    def std(self) -> float:
        return float(self._rv.std())


@register_distribution("uniform")
class UniformDistribution(Distribution):
    def __init__(self, low: float, high: float):
        if high <= low:
            raise ValueError("high must be greater than low")
        self._low = float(low)
        self._high = float(high)
        self._rv = stats.uniform(loc=self._low, scale=self._high - self._low)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "uniform", "low": self._low, "high": self._high}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UniformDistribution:
        return cls(low=data["low"], high=data["high"])

    def pdf(self, x):
        return self._rv.pdf(x)

    def cdf(self, x):
        return self._rv.cdf(x)

    def quantile(self, p):
        return self._rv.ppf(p)

    @property
    def mean(self) -> float:
        return float(self._rv.mean())

    @property
    def std(self) -> float:
        return float(self._rv.std())


@register_distribution("beta")
class BetaDistribution(Distribution):
    def __init__(self, alpha: float, beta: float):
        if alpha <= 0 or beta <= 0:
            raise ValueError("alpha and beta must be positive")
        self._alpha = float(alpha)
        self._beta = float(beta)
        self._rv = stats.beta(self._alpha, self._beta)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "beta", "alpha": self._alpha, "beta": self._beta}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BetaDistribution:
        return cls(alpha=data["alpha"], beta=data["beta"])

    def pdf(self, x):
        return self._rv.pdf(x)

    def cdf(self, x):
        return self._rv.cdf(x)

    def quantile(self, p):
        return self._rv.ppf(p)

    @property
    def mean(self) -> float:
        return float(self._rv.mean())

    @property
    def std(self) -> float:
        return float(self._rv.std())


@register_distribution("gamma")
class GammaDistribution(Distribution):
    def __init__(self, shape: float, scale: float):
        if shape <= 0 or scale <= 0:
            raise ValueError("shape and scale must be positive")
        self._shape = float(shape)
        self._scale = float(scale)
        self._rv = stats.gamma(self._shape, scale=self._scale)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "gamma", "shape": self._shape, "scale": self._scale}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GammaDistribution:
        return cls(shape=data["shape"], scale=data["scale"])

    def pdf(self, x):
        return self._rv.pdf(x)

    def cdf(self, x):
        return self._rv.cdf(x)

    def quantile(self, p):
        return self._rv.ppf(p)

    @property
    def mean(self) -> float:
        return float(self._rv.mean())

    @property
    def std(self) -> float:
        return float(self._rv.std())


@register_distribution("exponential")
class ExponentialDistribution(Distribution):
    def __init__(self, rate: float):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._rate = float(rate)
        self._rv = stats.expon(scale=1.0 / self._rate)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "exponential", "rate": self._rate}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExponentialDistribution:
        return cls(rate=data["rate"])

    def pdf(self, x):
        return self._rv.pdf(x)

    def cdf(self, x):
        return self._rv.cdf(x)

    def quantile(self, p):
        return self._rv.ppf(p)

    @property
    def mean(self) -> float:
        return float(self._rv.mean())

    @property
    def std(self) -> float:
        return float(self._rv.std())


@register_distribution("poisson")
class PoissonDistribution(Distribution):
    def __init__(self, mu: float):
        if mu <= 0:
            raise ValueError("mu must be positive")
        self._mu = float(mu)
        self._rv = stats.poisson(self._mu)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "poisson", "mu": self._mu}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PoissonDistribution:
        return cls(mu=data["mu"])

    def pdf(self, x):
        return self._rv.pmf(x)

    def cdf(self, x):
        return self._rv.cdf(x)

    def quantile(self, p):
        return self._rv.ppf(p)

    @property
    def mean(self) -> float:
        return self._mu

    @property
    def std(self) -> float:
        return float(np.sqrt(self._mu))


@register_distribution("student_t")
class StudentTDistribution(Distribution):
    def __init__(self, df: float, loc: float = 0.0, scale: float = 1.0):
        if df <= 0:
            raise ValueError("df must be positive")
        if scale <= 0:
            raise ValueError("scale must be positive")
        self._df = float(df)
        self._loc = float(loc)
        self._scale = float(scale)
        self._rv = stats.t(df=self._df, loc=self._loc, scale=self._scale)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "student_t", "df": self._df, "loc": self._loc, "scale": self._scale}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StudentTDistribution:
        return cls(df=data["df"], loc=data.get("loc", 0.0), scale=data.get("scale", 1.0))

    def pdf(self, x):
        return self._rv.pdf(x)

    def cdf(self, x):
        return self._rv.cdf(x)

    def quantile(self, p):
        return self._rv.ppf(p)

    @property
    def mean(self) -> float:
        if self._df > 1:
            return self._loc
        return float("nan")

    @property
    def std(self) -> float:
        if self._df > 2:
            return float(self._rv.std())
        return float("nan")


@register_distribution("triangular")
class TriangularDistribution(Distribution):
    def __init__(self, low: float, mode: float, high: float):
        if not (low <= mode <= high):
            raise ValueError("must have low <= mode <= high")
        if low == high:
            raise ValueError("low and high must differ")
        self._low = float(low)
        self._mode = float(mode)
        self._high = float(high)
        c = (self._mode - self._low) / (self._high - self._low)
        self._rv = stats.triang(c, loc=self._low, scale=self._high - self._low)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "triangular", "low": self._low, "mode": self._mode, "high": self._high}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriangularDistribution:
        return cls(low=data["low"], mode=data["mode"], high=data["high"])

    def pdf(self, x):
        return self._rv.pdf(x)

    def cdf(self, x):
        return self._rv.cdf(x)

    def quantile(self, p):
        return self._rv.ppf(p)

    @property
    def mean(self) -> float:
        return float(self._rv.mean())

    @property
    def std(self) -> float:
        return float(self._rv.std())


# ---------------------------------------------------------------------------
# Non-parametric
# ---------------------------------------------------------------------------


@register_distribution("empirical")
class EmpiricalDistribution(Distribution):
    def __init__(self, samples: list[float] | np.ndarray):
        arr = np.asarray(samples, dtype=float)
        if arr.ndim != 1 or len(arr) < 2:
            raise ValueError("samples must be a 1-D array with at least 2 elements")
        self._samples = np.sort(arr)
        self._kde = gaussian_kde(self._samples)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "empirical", "samples": self._samples.tolist()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmpiricalDistribution:
        return cls(samples=data["samples"])

    def pdf(self, x):
        return self._kde.evaluate(np.atleast_1d(x)).squeeze()

    def cdf(self, x):
        x_arr = np.atleast_1d(x)
        result = np.searchsorted(self._samples, x_arr, side="right") / len(self._samples)
        return result.squeeze() if np.ndim(x) == 0 else result

    def quantile(self, p):
        p_arr = np.atleast_1d(p)
        indices = np.clip(np.ceil(p_arr * len(self._samples)).astype(int) - 1, 0, len(self._samples) - 1)
        result = self._samples[indices]
        return result.item() if np.ndim(p) == 0 else result

    @property
    def mean(self) -> float:
        return float(np.mean(self._samples))

    @property
    def std(self) -> float:
        return float(np.std(self._samples, ddof=1))

    @property
    def samples(self) -> np.ndarray:
        return self._samples.copy()
