from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from forecast_anything.database import create_tables, get_engine, get_session_factory
from forecast_anything.distributions import DISTRIBUTION_REGISTRY, distribution_from_dict
from forecast_anything.models import Actual, Event, Forecast
from forecast_anything.schemas import (
    ActualCreate,
    BinaryForecast,
    CategoricalForecast,
    DistributionForecast,
    EventCreate,
    PointForecast,
)


class ForecastStore:
    def __init__(self, db_path: str | Path = "forecasts.db"):
        self._engine = get_engine(db_path)
        create_tables(self._engine)
        self._session_factory = get_session_factory(self._engine)

    def _session(self) -> Session:
        return self._session_factory()

    def close(self) -> None:
        self._engine.dispose()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def create_event(
        self,
        title: str,
        event_type: str,
        description: str | None = None,
        categories: list[str] | None = None,
        resolution_date: str | None = None,
    ) -> Event:
        schema = EventCreate(
            title=title,
            event_type=event_type,
            description=description,
            categories=categories,
            resolution_date=resolution_date,
        )
        with self._session() as session:
            event = Event(
                title=schema.title,
                description=schema.description,
                event_type=schema.event_type,
                resolution_date=schema.resolution_date,
                status="open",
            )
            if schema.categories:
                event.categories = schema.categories
            session.add(event)
            session.commit()
            session.refresh(event)
            session.expunge(event)
            return event

    def get_event(self, event_id: int) -> Event:
        with self._session() as session:
            event = session.get(Event, event_id)
            if event is None:
                raise ValueError(f"Event {event_id} not found")
            session.expunge(event)
            return event

    def list_events(self, status: str | None = None) -> list[Event]:
        with self._session() as session:
            query = session.query(Event)
            if status is not None:
                query = query.filter(Event.status == status)
            events = query.order_by(Event.created_at.desc()).all()
            for e in events:
                session.expunge(e)
            return events

    def update_event_status(self, event_id: int, status: str) -> Event:
        valid = {"open", "resolved", "cancelled"}
        if status not in valid:
            raise ValueError(f"status must be one of {valid}")
        with self._session() as session:
            event = session.get(Event, event_id)
            if event is None:
                raise ValueError(f"Event {event_id} not found")
            event.status = status
            session.commit()
            session.refresh(event)
            session.expunge(event)
            return event

    def delete_event(self, event_id: int) -> None:
        with self._session() as session:
            event = session.get(Event, event_id)
            if event is None:
                raise ValueError(f"Event {event_id} not found")
            session.delete(event)
            session.commit()

    # ------------------------------------------------------------------
    # Forecasts
    # ------------------------------------------------------------------

    def submit_forecast(
        self,
        event_id: int,
        *,
        point: float | None = None,
        normal: dict | None = None,
        lognormal: dict | None = None,
        uniform: dict | None = None,
        beta: dict | None = None,
        gamma: dict | None = None,
        exponential: dict | None = None,
        student_t: dict | None = None,
        triangular: dict | None = None,
        poisson: dict | None = None,
        empirical: dict | None = None,
        categorical: dict[str, float] | None = None,
        binary: float | None = None,
        distribution: str | None = None,
        params: dict | None = None,
        notes: str | None = None,
    ) -> Forecast:
        event = self.get_event(event_id)

        forecast_type, value_json = self._resolve_forecast_input(
            event=event,
            point=point,
            normal=normal,
            lognormal=lognormal,
            uniform=uniform,
            beta=beta,
            gamma=gamma,
            exponential=exponential,
            student_t=student_t,
            triangular=triangular,
            poisson=poisson,
            empirical=empirical,
            categorical=categorical,
            binary=binary,
            distribution=distribution,
            params=params,
        )

        with self._session() as session:
            forecast = Forecast(
                event_id=event_id,
                forecast_type=forecast_type,
                value_json=json.dumps(value_json),
                notes=notes,
            )
            session.add(forecast)
            session.commit()
            session.refresh(forecast)
            session.expunge(forecast)
            return forecast

    def _resolve_forecast_input(
        self,
        event: Event,
        **kwargs,
    ) -> tuple[str, dict]:
        point = kwargs.get("point")
        categorical = kwargs.get("categorical")
        binary = kwargs.get("binary")
        distribution = kwargs.get("distribution")
        params = kwargs.get("params")

        named_dists = {
            name: kwargs.get(name)
            for name in DISTRIBUTION_REGISTRY
            if kwargs.get(name) is not None
        }

        provided = []
        if point is not None:
            provided.append("point")
        if categorical is not None:
            provided.append("categorical")
        if binary is not None:
            provided.append("binary")
        if distribution is not None:
            provided.append("distribution")
        provided.extend(named_dists.keys())

        if len(provided) != 1:
            raise ValueError(f"Exactly one forecast type must be provided, got: {provided or 'none'}")

        if point is not None:
            if event.event_type != "numeric":
                raise ValueError(f"point forecasts are only valid for numeric events, not {event.event_type}")
            PointForecast(value=point)
            return "point", {"value": point}

        if binary is not None:
            if event.event_type != "binary":
                raise ValueError(f"binary forecasts are only valid for binary events, not {event.event_type}")
            BinaryForecast(probability=binary)
            return "binary", {"probability": binary}

        if categorical is not None:
            if event.event_type != "categorical":
                raise ValueError(f"categorical forecasts are only valid for categorical events, not {event.event_type}")
            CategoricalForecast(probs=categorical)
            event_cats = set(event.categories or [])
            forecast_cats = set(categorical.keys())
            if forecast_cats != event_cats:
                raise ValueError(f"forecast categories {forecast_cats} don't match event categories {event_cats}")
            return "categorical", {"probs": categorical}

        if distribution is not None:
            if event.event_type != "numeric":
                raise ValueError(f"distribution forecasts are only valid for numeric events, not {event.event_type}")
            if params is None:
                raise ValueError("params required when using distribution=")
            schema = DistributionForecast(dist_type=distribution, params=params)
            schema.build_distribution()
            return distribution, params

        dist_name = list(named_dists.keys())[0]
        dist_params = named_dists[dist_name]
        if event.event_type != "numeric":
            raise ValueError(f"distribution forecasts are only valid for numeric events, not {event.event_type}")
        schema = DistributionForecast(dist_type=dist_name, params=dist_params)
        schema.build_distribution()
        return dist_name, dist_params

    def get_forecasts(self, event_id: int) -> list[Forecast]:
        self.get_event(event_id)
        with self._session() as session:
            forecasts = (
                session.query(Forecast)
                .filter(Forecast.event_id == event_id)
                .order_by(Forecast.created_at.desc())
                .all()
            )
            for f in forecasts:
                session.expunge(f)
            return forecasts

    def get_forecast(self, forecast_id: int) -> Forecast:
        with self._session() as session:
            forecast = session.get(Forecast, forecast_id)
            if forecast is None:
                raise ValueError(f"Forecast {forecast_id} not found")
            session.expunge(forecast)
            return forecast

    def delete_forecast(self, forecast_id: int) -> None:
        with self._session() as session:
            forecast = session.get(Forecast, forecast_id)
            if forecast is None:
                raise ValueError(f"Forecast {forecast_id} not found")
            session.delete(forecast)
            session.commit()

    def get_forecast_distribution(self, forecast_id: int):
        forecast = self.get_forecast(forecast_id)
        if forecast.forecast_type == "point":
            return None
        if forecast.forecast_type in ("binary", "categorical"):
            return None
        return distribution_from_dict({"type": forecast.forecast_type, **forecast.value})

    # ------------------------------------------------------------------
    # Actuals
    # ------------------------------------------------------------------

    def record_actual(
        self,
        event_id: int,
        *,
        value: float | None = None,
        category_value: str | None = None,
        binary_outcome: bool | None = None,
        margin_of_error: float | None = None,
        confidence_level: float | None = None,
        distribution_type: str | None = None,
        distribution_params: dict | None = None,
        source: str | None = None,
        reported_at: str | None = None,
    ) -> Actual:
        event = self.get_event(event_id)

        schema = ActualCreate(
            value=value,
            category_value=category_value,
            binary_outcome=binary_outcome,
            margin_of_error=margin_of_error,
            confidence_level=confidence_level,
            distribution_type=distribution_type,
            distribution_params=distribution_params,
            source=source,
            reported_at=reported_at,
        )

        self._validate_actual_for_event(event, schema)

        if distribution_type and distribution_params:
            distribution_from_dict({"type": distribution_type, **distribution_params})

        with self._session() as session:
            existing = session.query(Actual).filter(Actual.event_id == event_id).first()
            if existing is not None:
                raise ValueError(f"Actual already recorded for event {event_id}. Use update_actual() to modify.")

            actual = Actual(
                event_id=event_id,
                value=schema.value,
                category_value=schema.category_value,
                binary_outcome=int(schema.binary_outcome) if schema.binary_outcome is not None else None,
                margin_of_error=schema.margin_of_error,
                confidence_level=schema.confidence_level,
                distribution_type=schema.distribution_type,
                distribution_params_json=json.dumps(schema.distribution_params) if schema.distribution_params else None,
                source=schema.source,
                reported_at=schema.reported_at,
            )
            session.add(actual)

            e = session.get(Event, event_id)
            e.status = "resolved"

            session.commit()
            session.refresh(actual)
            session.expunge(actual)
            return actual

    def _validate_actual_for_event(self, event: Event, schema: ActualCreate) -> None:
        if event.event_type == "numeric":
            if schema.value is None:
                raise ValueError("numeric events require a value")
        elif event.event_type == "categorical":
            if schema.category_value is None:
                raise ValueError("categorical events require a category_value")
            if event.categories and schema.category_value not in event.categories:
                raise ValueError(
                    f"category_value {schema.category_value!r} not in event categories: {event.categories}"
                )
        elif event.event_type == "binary":
            if schema.binary_outcome is None:
                raise ValueError("binary events require a binary_outcome (True/False)")

    def update_actual(
        self,
        event_id: int,
        **kwargs,
    ) -> Actual:
        with self._session() as session:
            actual = session.query(Actual).filter(Actual.event_id == event_id).first()
            if actual is None:
                raise ValueError(f"No actual found for event {event_id}")

            updatable = {
                "value", "category_value", "binary_outcome", "margin_of_error",
                "confidence_level", "distribution_type", "source", "reported_at",
            }
            for key, val in kwargs.items():
                if key == "distribution_params":
                    actual.distribution_params = val
                elif key in updatable:
                    setattr(actual, key, val)
                else:
                    raise ValueError(f"Cannot update field: {key}")

            session.commit()
            session.refresh(actual)
            session.expunge(actual)
            return actual

    def get_actual(self, event_id: int) -> Actual | None:
        self.get_event(event_id)
        with self._session() as session:
            actual = session.query(Actual).filter(Actual.event_id == event_id).first()
            if actual is not None:
                session.expunge(actual)
            return actual

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _build_actual_distribution(self, actual: Actual):
        """
        Reconstruct the actual's distribution.

        Priority:
        1. Explicit distribution_type + distribution_params
        2. value + margin_of_error + confidence_level → Normal
        3. value alone → point (returned as float, not Distribution)
        """
        if actual.distribution_type and actual.distribution_params:
            return distribution_from_dict(
                {"type": actual.distribution_type, **actual.distribution_params}
            )

        if actual.value is not None and actual.margin_of_error is not None:
            cl = actual.confidence_level or 0.90
            from scipy import stats as sp_stats
            z = sp_stats.norm.ppf(1.0 - (1.0 - cl) / 2.0)
            std = actual.margin_of_error / z
            from forecast_anything.distributions import NormalDistribution
            return NormalDistribution(mean=actual.value, std=std)

        return actual.value

    def score_forecast(self, forecast_id: int) -> float | None:
        """
        Compute the accuracy score for a single forecast.

        Returns CRPS for numeric events, Brier score for binary events,
        or None if the event has no actual recorded.
        """
        from forecast_anything.scoring import brier_score, crps

        forecast = self.get_forecast(forecast_id)
        event = self.get_event(forecast.event_id)
        actual = self.get_actual(event.id)

        if actual is None:
            return None

        if event.event_type == "binary":
            prob = forecast.value.get("probability")
            outcome = bool(actual.binary_outcome)
            return brier_score(prob, outcome)

        if event.event_type == "numeric":
            dist = self.get_forecast_distribution(forecast_id)
            if dist is None:
                # Point forecast — wrap in a tight normal for scoring
                from forecast_anything.distributions import NormalDistribution
                pt = forecast.value["value"]
                dist = NormalDistribution(mean=pt, std=0.01)

            actual_val = self._build_actual_distribution(actual)
            return crps(dist, actual_val)

        return None

    def score_event(self, event_id: int) -> list[dict] | None:
        """
        Score all forecasts for an event.

        Returns a list of {forecast_id, notes, forecast_type, score, metric}
        sorted best-to-worst, or None if no actual is recorded.
        """
        actual = self.get_actual(event_id)
        if actual is None:
            return None

        forecasts = self.get_forecasts(event_id)
        event = self.get_event(event_id)
        metric = "brier" if event.event_type == "binary" else "crps"

        results = []
        for f in forecasts:
            score = self.score_forecast(f.id)
            results.append({
                "forecast_id": f.id,
                "notes": f.notes,
                "forecast_type": f.forecast_type,
                "score": score,
                "metric": metric,
            })

        results.sort(key=lambda r: r["score"] if r["score"] is not None else float("inf"))
        return results

    def delete_actual(self, event_id: int) -> None:
        with self._session() as session:
            actual = session.query(Actual).filter(Actual.event_id == event_id).first()
            if actual is None:
                raise ValueError(f"No actual found for event {event_id}")
            event = session.get(Event, event_id)
            event.status = "open"
            session.delete(actual)
            session.commit()
