"""SQLAlchemy models. Tables arrive with the stage that first needs them (ROADMAP)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fxbot.domain.calendar import ensure_utc


class UtcDateTime(TypeDecorator[datetime]):
    """Stores naive UTC; always returns tz-aware UTC. Naive input is refused."""

    impl = DateTime(timezone=False)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else ensure_utc(value).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class DecimalText(TypeDecorator[Decimal]):
    """Exact decimal storage on every backend (SQLite has no native decimal type)."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("only finite Decimal values can be stored")
        return format(value, "f")

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(str(value))


class Base(DeclarativeBase):
    pass


class InstrumentRow(Base):
    __tablename__ = "instruments"

    name: Mapped[str] = mapped_column(String(16), primary_key=True)
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    pip_location: Mapped[int] = mapped_column(Integer)
    display_precision: Mapped[int] = mapped_column(Integer)
    units_step: Mapped[Decimal] = mapped_column(DecimalText)
    min_units: Mapped[Decimal] = mapped_column(DecimalText)
    max_units: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    contract_size: Mapped[Decimal] = mapped_column(DecimalText)
    min_stop_distance: Mapped[Decimal] = mapped_column(DecimalText)
    margin_rate: Mapped[Decimal] = mapped_column(DecimalText)
    financing: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class DatasetRow(Base):
    """Provenance of stored candles (research 07 §4)."""

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    source: Mapped[str] = mapped_column(String(64))
    price_side: Mapped[str] = mapped_column(String(2))  # BA, B or M
    ask_source: Mapped[str] = mapped_column(String(16))
    smoothed: Mapped[bool] = mapped_column(Boolean)
    tz_origin: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    licence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime)


class CandleRow(Base):
    """One bar of one dataset. Datasets never overwrite each other's bars."""

    __tablename__ = "candles"

    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), primary_key=True)
    instrument: Mapped[str] = mapped_column(String(16), primary_key=True)
    granularity: Mapped[str] = mapped_column(String(4), primary_key=True)
    time: Mapped[datetime] = mapped_column(UtcDateTime, primary_key=True)
    bid_open: Mapped[Decimal] = mapped_column(DecimalText)
    bid_high: Mapped[Decimal] = mapped_column(DecimalText)
    bid_low: Mapped[Decimal] = mapped_column(DecimalText)
    bid_close: Mapped[Decimal] = mapped_column(DecimalText)
    ask_open: Mapped[Decimal] = mapped_column(DecimalText)
    ask_high: Mapped[Decimal] = mapped_column(DecimalText)
    ask_low: Mapped[Decimal] = mapped_column(DecimalText)
    ask_close: Mapped[Decimal] = mapped_column(DecimalText)
    volume: Mapped[int] = mapped_column(Integer)
    ask_source: Mapped[str] = mapped_column(String(16))
