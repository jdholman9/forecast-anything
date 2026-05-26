import json
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    categories_json: Mapped[str | None] = mapped_column("categories", Text, nullable=True)
    resolution_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow, onupdate=_utcnow)

    forecasts: Mapped[list["Forecast"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    actual: Mapped["Actual | None"] = relationship(back_populates="event", uselist=False, cascade="all, delete-orphan")

    @property
    def categories(self) -> list[str] | None:
        if self.categories_json is None:
            return None
        return json.loads(self.categories_json)

    @categories.setter
    def categories(self, value: list[str] | None):
        self.categories_json = json.dumps(value) if value is not None else None

    def __repr__(self) -> str:
        return f"<Event(id={self.id}, title={self.title!r}, type={self.event_type}, status={self.status})>"


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    forecast_type: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    event: Mapped["Event"] = relationship(back_populates="forecasts")

    @property
    def value(self) -> dict:
        return json.loads(self.value_json)

    def __repr__(self) -> str:
        return f"<Forecast(id={self.id}, event_id={self.event_id}, type={self.forecast_type})>"


class Actual(Base):
    __tablename__ = "actuals"
    __table_args__ = (UniqueConstraint("event_id", name="uq_actuals_event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    binary_outcome: Mapped[int | None] = mapped_column(Integer, nullable=True)
    margin_of_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    distribution_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    distribution_params_json: Mapped[str | None] = mapped_column("distribution_params", Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow)

    event: Mapped["Event"] = relationship(back_populates="actual")

    @property
    def distribution_params(self) -> dict | None:
        if self.distribution_params_json is None:
            return None
        return json.loads(self.distribution_params_json)

    @distribution_params.setter
    def distribution_params(self, value: dict | None):
        self.distribution_params_json = json.dumps(value) if value is not None else None

    def __repr__(self) -> str:
        return f"<Actual(id={self.id}, event_id={self.event_id})>"
