# forecast_anything

## What this is

A Python package for storing, managing, and scoring forecasts of any type. Inspired by Philip Tetlock's *Superforecasting* — Brier scores for binary events, CRPS for distributional numeric forecasts. The package is the core engine (like git); a web frontend (like GitHub) may come later but the package must work fully standalone.

## Architecture

Single entry point: `ForecastStore(db_path)`. SQLite via SQLAlchemy. No web framework, no HTTP, no UI coupling. All business logic lives in the package.

### Key files

- `store.py` — `ForecastStore` class: CRUD for events/forecasts/actuals, scoring methods
- `models.py` — SQLAlchemy ORM: `Event`, `Forecast`, `Actual` tables
- `distributions.py` — `Distribution` ABC with registry pattern, 10 built-in distributions (normal, lognormal, uniform, beta, gamma, exponential, poisson, student_t, triangular, empirical)
- `scoring.py` — CRPS (standard + generalized) and Brier score
- `schemas.py` — Pydantic input validation
- `database.py` — Engine/session setup, FK enforcement

### Data model

- **Event** defines what's being forecasted (numeric/categorical/binary)
- **Forecast** stores a prediction (point, distribution, probability). Multiple forecasts per event allowed (timestamped). Model name goes in `notes` field.
- **Actual** stores the outcome (one per event). Can carry uncertainty via `margin_of_error`/`confidence_level` or full `distribution_type`/`distribution_params`.

### Distribution registry

Distributions self-register via `@register_distribution("name")`. Adding a new one requires implementing `to_dict`, `from_dict`, `pdf`, `cdf`, `quantile`, `mean`, `std`. Backed by scipy.stats for parametric, numpy + KDE for empirical.

### Scoring

- Binary: Brier score `(p - o)^2`
- Numeric: CRPS `∫(F(x) - G(x))² dx`
  - Point actual: closed-form for normal, exact formula for empirical
  - Distributional actual: numerical integration with smart splitting at empirical CDF jump points
  - Normal-vs-normal: direct numerical integration over finite range

## Current state

- Phase 1 complete: framework for storing events, forecasts (any type), and actuals (with uncertainty)
- Scoring implemented: CRPS (standard and generalized) and Brier score
- Tested with real MF permits data: 32 monthly events, 6 models, 192 forecasts loaded from `mf-permits-forecast` project
- Phase 2 (not started): charts, accuracy dashboards, trend visualization

## Related project

`C:\Users\jdhol\Documents\mf-permits-forecast` — multifamily permit forecasting project. Has a loading script at `scripts/load_into_forecast_anything.py` that creates 32 monthly events (May 2026–Dec 2028) with forecasts from SeasonalNaive, HoltWinters, SARIMA, SARIMAX, Ensemble, and XGBoost. Database at `mf_permits_forecasts.db`.

## Commands

```bash
pip install -e .          # install in editable mode
python -c "from forecast_anything import ForecastStore; ..."  # use from REPL
```

## Dependencies

sqlalchemy>=2.0, pydantic>=2.0, scipy>=1.11, numpy>=1.24

## Design principles

- Package is the product; any web app is just a frontend
- Actuals can be distributions (census MOE, measurement uncertainty)
- Multiple forecasts per event from different models — track via `notes` field
- Proper scoring rules only (CRPS, Brier) — no ad hoc metrics
- Distribution registry is open for extension without modifying core code
