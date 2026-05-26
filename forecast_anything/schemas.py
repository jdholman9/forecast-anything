from __future__ import annotations

from pydantic import BaseModel, field_validator, model_validator

from forecast_anything.distributions import DISTRIBUTION_REGISTRY

VALID_EVENT_TYPES = {"numeric", "categorical", "binary"}


class EventCreate(BaseModel):
    title: str
    description: str | None = None
    event_type: str
    categories: list[str] | None = None
    resolution_date: str | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in VALID_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {VALID_EVENT_TYPES}")
        return v

    @model_validator(mode="after")
    def validate_categories(self) -> EventCreate:
        if self.event_type == "categorical":
            if not self.categories or len(self.categories) < 2:
                raise ValueError("categorical events require at least 2 categories")
        return self


class PointForecast(BaseModel):
    value: float


class BinaryForecast(BaseModel):
    probability: float

    @field_validator("probability")
    @classmethod
    def validate_probability(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("probability must be between 0 and 1")
        return v


class CategoricalForecast(BaseModel):
    probs: dict[str, float]

    @field_validator("probs")
    @classmethod
    def validate_probs(cls, v: dict[str, float]) -> dict[str, float]:
        for cat, p in v.items():
            if not 0.0 <= p <= 1.0:
                raise ValueError(f"probability for {cat!r} must be between 0 and 1")
        total = sum(v.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"probabilities must sum to 1.0, got {total:.4f}")
        return v


class DistributionForecast(BaseModel):
    dist_type: str
    params: dict

    @field_validator("dist_type")
    @classmethod
    def validate_dist_type(cls, v: str) -> str:
        if v not in DISTRIBUTION_REGISTRY:
            raise ValueError(f"Unknown distribution type: {v!r}. Available: {list(DISTRIBUTION_REGISTRY)}")
        return v

    def build_distribution(self):
        from forecast_anything.distributions import distribution_from_dict
        return distribution_from_dict({"type": self.dist_type, **self.params})


class ActualCreate(BaseModel):
    value: float | None = None
    category_value: str | None = None
    binary_outcome: bool | None = None
    margin_of_error: float | None = None
    confidence_level: float | None = None
    distribution_type: str | None = None
    distribution_params: dict | None = None
    source: str | None = None
    reported_at: str | None = None

    @field_validator("confidence_level")
    @classmethod
    def validate_confidence(cls, v: float | None) -> float | None:
        if v is not None and not 0.0 < v < 1.0:
            raise ValueError("confidence_level must be between 0 and 1 (exclusive)")
        return v

    @field_validator("margin_of_error")
    @classmethod
    def validate_moe(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("margin_of_error must be non-negative")
        return v

    @field_validator("distribution_type")
    @classmethod
    def validate_dist_type(cls, v: str | None) -> str | None:
        if v is not None and v not in DISTRIBUTION_REGISTRY:
            raise ValueError(f"Unknown distribution type: {v!r}. Available: {list(DISTRIBUTION_REGISTRY)}")
        return v
