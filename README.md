# Forecast Anything

A Python framework for storing and evaluating forecasts of any type — numeric point estimates, categorical predictions, binary yes/no, or full probability distributions.

## Install

```bash
pip install -e .
```

## Quick Start

```python
from forecast_anything import ForecastStore

store = ForecastStore("my_forecasts.db")
```

### Example: Forecasting mortgage rates

```python
# Create a forecasting event
event = store.create_event(
    title="Freddie Mac 30-Year Mortgage Rate",
    event_type="numeric",
    description="Primary Mortgage Market Survey rate for week of 2026-05-28",
    resolution_date="2026-05-28",
)

# Submit a point forecast
store.submit_forecast(event.id, point=6.50)

# Or express uncertainty with a distribution
store.submit_forecast(event.id, normal={"mean": 6.50, "std": 0.15})

# When the actual rate is published
store.record_actual(
    event.id,
    value=6.48,
    source="Freddie Mac PMMS",
    reported_at="2026-05-28",
)
```

## Event Types

| Type | Description | Example |
|------|-------------|---------|
| `numeric` | Outcome is a number | GDP growth, mortgage rates, population |
| `categorical` | Outcome is one of N categories | Election winner, product color |
| `binary` | Outcome is yes or no | "Will inflation exceed 5%?" |

### Categorical events

```python
event = store.create_event(
    title="2028 Election Winner",
    event_type="categorical",
    categories=["Candidate A", "Candidate B", "Candidate C"],
)

store.submit_forecast(event.id, categorical={
    "Candidate A": 0.50,
    "Candidate B": 0.35,
    "Candidate C": 0.15,
})

store.record_actual(event.id, category_value="Candidate A")
```

### Binary events

```python
event = store.create_event(
    title="Will inflation exceed 5% in 2027?",
    event_type="binary",
)

# Submit probability of "yes"
store.submit_forecast(event.id, binary=0.30)

store.record_actual(event.id, binary_outcome=False)
```

## Distribution Forecasts

For numeric events, you can submit forecasts as probability distributions instead of point estimates. Ten distributions are built in:

| Distribution | Parameters | Use case |
|---|---|---|
| `normal` | mean, std | General symmetric uncertainty |
| `lognormal` | mu, sigma | Positive-only, right-skewed (prices, populations) |
| `uniform` | low, high | Simple range |
| `beta` | alpha, beta | Probabilities and proportions |
| `gamma` | shape, scale | Positive, skewed (wait times, costs) |
| `exponential` | rate | Memoryless waiting times |
| `poisson` | mu | Count data |
| `student_t` | df, loc, scale | Heavy-tailed uncertainty |
| `triangular` | low, mode, high | Subjective "best guess + range" |
| `empirical` | samples | Nonparametric, any shape |

```python
# Named parameter style
store.submit_forecast(event.id, normal={"mean": 6.50, "std": 0.15})
store.submit_forecast(event.id, triangular={"low": 6.0, "mode": 6.5, "high": 7.2})
store.submit_forecast(event.id, empirical={"samples": [6.3, 6.4, 6.5, 6.5, 6.6, 6.8]})

# Generic style (useful for dynamic distribution selection)
store.submit_forecast(event.id, distribution="gamma", params={"shape": 2.0, "scale": 3.25})
```

### Working with distribution objects

```python
forecast = store.get_forecasts(event.id)[0]
dist = store.get_forecast_distribution(forecast.id)

dist.mean       # expected value
dist.std        # standard deviation
dist.cdf(6.5)   # P(X <= 6.5)
dist.quantile(0.95)  # 95th percentile
dist.pdf(6.5)   # probability density at 6.5
```

### Adding custom distributions

```python
from forecast_anything import Distribution, register_distribution
from scipy import stats

@register_distribution("weibull")
class WeibullDistribution(Distribution):
    def __init__(self, shape: float, scale: float):
        self._shape = shape
        self._scale = scale
        self._rv = stats.weibull_min(self._shape, scale=self._scale)

    def to_dict(self):
        return {"type": "weibull", "shape": self._shape, "scale": self._scale}

    @classmethod
    def from_dict(cls, data):
        return cls(shape=data["shape"], scale=data["scale"])

    def pdf(self, x):   return self._rv.pdf(x)
    def cdf(self, x):   return self._rv.cdf(x)
    def quantile(self, p): return self._rv.ppf(p)

    @property
    def mean(self): return float(self._rv.mean())
    @property
    def std(self): return float(self._rv.std())
```

## Actuals with Uncertainty

Real-world reported values often come with uncertainty. For example, census figures include a margin of error.

```python
store.record_actual(
    event.id,
    value=334_500_000,
    margin_of_error=500_000,
    confidence_level=0.90,
    source="US Census Bureau",
    reported_at="2031-04-01",
)

# Or specify uncertainty as a full distribution
store.record_actual(
    event.id,
    value=334_500_000,
    distribution_type="normal",
    distribution_params={"mean": 334_500_000, "std": 304_000},
    source="US Census Bureau",
)
```

## Scoring

Accuracy is measured with proper scoring rules:

- **Numeric events** — CRPS (Continuous Ranked Probability Score)
- **Binary events** — Brier score

Lower is better for both. CRPS rewards forecasts that place probability mass near the actual outcome and penalizes overconfidence and miscalibration.

### Scoring against a point actual

```python
store.record_actual(event.id, value=6.48, source="Freddie Mac PMMS")

# Score a single forecast
score = store.score_forecast(forecast.id)

# Score and rank all forecasts for an event
results = store.score_event(event.id)
for r in results:
    print(f"{r['notes']:20s}  CRPS={r['score']:.4f}")
```

### Scoring against an uncertain actual

When the actual value has measurement uncertainty (e.g., census standard errors), the scoring uses generalized CRPS that integrates over the actual's distribution:

```python
store.record_actual(
    event.id,
    value=44.2,
    margin_of_error=1.8,
    confidence_level=0.90,
    source="Census Bureau",
)

# CRPS is computed against N(44.2, SE=1.094) — not a point
results = store.score_event(event.id)
```

The margin of error is converted to a standard error using the confidence level (SE = MOE / z). You can also provide an explicit distribution:

```python
store.record_actual(
    event.id,
    value=44.2,
    distribution_type="normal",
    distribution_params={"mean": 44.2, "std": 1.094},
    source="Census Bureau",
)
```

### Using scoring functions directly

```python
from forecast_anything import crps, NormalDistribution, EmpiricalDistribution

forecast = NormalDistribution(mean=6.50, std=0.15)

# Against a point observation
crps(forecast, 6.48)

# Against an uncertain observation
actual = NormalDistribution(mean=6.48, std=0.05)
crps(forecast, actual)
```

## Querying

```python
store.list_events()                    # all events
store.list_events(status="open")       # only unresolved
store.get_event(1)                     # by ID
store.get_forecasts(event.id)          # all forecasts for an event
store.get_actual(event.id)             # the recorded actual (or None)
```

## Managing Data

```python
store.update_event_status(event.id, "cancelled")
store.delete_forecast(forecast.id)
store.update_actual(event.id, margin_of_error=600_000)
store.delete_actual(event.id)   # reopens the event
store.delete_event(event.id)    # cascades to forecasts and actual
```
