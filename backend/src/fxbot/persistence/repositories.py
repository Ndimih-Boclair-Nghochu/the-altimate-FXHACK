"""Repositories: the only code that builds SQL (SQLAlchemy Core/ORM, bound parameters)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite

from fxbot.domain.enums import AskSource, Granularity
from fxbot.domain.models import OHLC, Candle, Dataset, Financing, Instrument
from fxbot.persistence.db import Database
from fxbot.persistence.models import CandleRow, DatasetRow, InstrumentRow

_CANDLE_BATCH: Final = 10_000
_CANDLE_VALUE_COLUMNS: Final = (
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
    "volume",
    "ask_source",
)
_CANDLE_KEY: Final = ("dataset_id", "instrument", "granularity", "time")


def _insert(database: Database, table: Any) -> Any:
    if database.dialect == "sqlite":
        return sqlite.insert(table)
    if database.dialect == "postgresql":
        return postgresql.insert(table)
    raise NotImplementedError(f"upserts are not implemented for {database.dialect}")


class InstrumentRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def upsert(self, instruments: Sequence[Instrument], *, now: datetime) -> None:
        if not instruments:
            return
        rows = [
            {
                "name": i.name,
                "base": i.base,
                "quote": i.quote,
                "pip_location": i.pip_location,
                "display_precision": i.display_precision,
                "units_step": i.units_step,
                "min_units": i.min_units,
                "max_units": i.max_units,
                "contract_size": i.contract_size,
                "min_stop_distance": i.min_stop_distance,
                "margin_rate": i.margin_rate,
                "financing": i.financing.model_dump(mode="json") if i.financing else None,
                "updated_at": now,
            }
            for i in instruments
        ]
        statement = _insert(self._db, InstrumentRow).values(rows)
        updates = {key: statement.excluded[key] for key in rows[0] if key != "name"}
        async with self._db.session() as session:
            await session.execute(
                statement.on_conflict_do_update(index_elements=["name"], set_=updates)
            )

    async def list(self, *, enabled_only: bool = False) -> list[Instrument]:
        query = select(InstrumentRow).order_by(InstrumentRow.name)
        if enabled_only:
            query = query.where(InstrumentRow.enabled.is_(True))
        async with self._db.session() as session:
            rows = (await session.scalars(query)).all()
        return [_instrument(row) for row in rows]

    async def get(self, name: str) -> Instrument | None:
        async with self._db.session() as session:
            row = await session.get(InstrumentRow, name)
        return _instrument(row) if row else None


def _instrument(row: InstrumentRow) -> Instrument:
    return Instrument(
        name=row.name,
        pip_location=row.pip_location,
        display_precision=row.display_precision,
        units_step=row.units_step,
        min_units=row.min_units,
        max_units=row.max_units,
        contract_size=row.contract_size,
        min_stop_distance=row.min_stop_distance,
        margin_rate=row.margin_rate,
        financing=Financing.model_validate(row.financing) if row.financing else None,
    )


class DatasetRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def upsert(self, dataset: Dataset, *, now: datetime) -> int:
        """Register or update a dataset by name; returns its id."""
        values = dataset.model_dump(mode="json") | {"fetched_at": now}
        statement = _insert(self._db, DatasetRow).values(values)
        updates = {key: statement.excluded[key] for key in values if key != "name"}
        async with self._db.session() as session:
            await session.execute(
                statement.on_conflict_do_update(index_elements=["name"], set_=updates)
            )
            dataset_id = await session.scalar(
                select(DatasetRow.id).where(DatasetRow.name == dataset.name)
            )
        if dataset_id is None:  # pragma: no cover - the row was just written
            raise RuntimeError("dataset upsert did not persist")
        return dataset_id

    async def get(self, name: str) -> Dataset | None:
        async with self._db.session() as session:
            row = await session.scalar(select(DatasetRow).where(DatasetRow.name == name))
        return _dataset(row) if row else None

    async def id_of(self, name: str) -> int | None:
        async with self._db.session() as session:
            return await session.scalar(select(DatasetRow.id).where(DatasetRow.name == name))

    async def get_by_id(self, dataset_id: int) -> Dataset | None:
        async with self._db.session() as session:
            row = await session.get(DatasetRow, dataset_id)
        return _dataset(row) if row else None


def _dataset(row: DatasetRow) -> Dataset:
    return Dataset(
        name=row.name,
        source=row.source,
        price_side=row.price_side,  # type: ignore[arg-type]  # validated by the model
        ask_source=AskSource(row.ask_source),
        smoothed=row.smoothed,
        tz_origin=row.tz_origin,
        sha256=row.sha256,
        licence_note=row.licence_note,
    )


class CandleRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def upsert(self, candles: Sequence[Candle], *, dataset_id: int) -> int:
        """Insert or replace candles keyed by (instrument, granularity, time)."""
        if not candles:
            return 0
        rows = [_candle_row(candle, dataset_id) for candle in candles]
        statement = _insert(self._db, CandleRow)
        statement = statement.on_conflict_do_update(
            index_elements=list(_CANDLE_KEY),
            set_={key: statement.excluded[key] for key in _CANDLE_VALUE_COLUMNS},
        )
        async with self._db.session() as session:
            for offset in range(0, len(rows), _CANDLE_BATCH):
                # executemany: SQLAlchemy batches the rows into multi-row INSERTs itself.
                await session.execute(statement, rows[offset : offset + _CANDLE_BATCH])
        return len(rows)

    async def range(
        self,
        dataset_id: int,
        instrument: str,
        granularity: Granularity,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        limit: int | None = None,
    ) -> list[Candle]:
        table = CandleRow.__table__
        query = (
            select(table)
            .where(
                table.c.dataset_id == dataset_id,
                table.c.instrument == instrument,
                table.c.granularity == granularity.value,
            )
            .order_by(table.c.time)
        )
        if start is not None:
            query = query.where(table.c.time >= start)
        if end is not None:
            query = query.where(table.c.time < end)
        if limit is not None:
            query = query.limit(limit)
        async with self._db.session() as session:
            rows = (await session.execute(query)).mappings().all()
        return [_candle(row) for row in rows]

    async def times(
        self,
        dataset_id: int,
        instrument: str,
        granularity: Granularity,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[datetime]:
        query = (
            select(CandleRow.time)
            .where(
                CandleRow.dataset_id == dataset_id,
                CandleRow.instrument == instrument,
                CandleRow.granularity == granularity.value,
            )
            .order_by(CandleRow.time)
        )
        if start is not None:
            query = query.where(CandleRow.time >= start)
        if end is not None:
            query = query.where(CandleRow.time < end)
        async with self._db.session() as session:
            return list((await session.scalars(query)).all())

    async def latest_time(
        self, dataset_id: int, instrument: str, granularity: Granularity
    ) -> datetime | None:
        query = select(func.max(CandleRow.time)).where(
            CandleRow.dataset_id == dataset_id,
            CandleRow.instrument == instrument,
            CandleRow.granularity == granularity.value,
        )
        async with self._db.session() as session:
            value = await session.scalar(query)
        # Aggregates bypass the column type on some backends; normalise to aware UTC.
        return _as_utc(value)

    async def dataset_ids(self, instrument: str, granularity: Granularity) -> list[int]:
        query = (
            select(CandleRow.dataset_id)
            .where(CandleRow.instrument == instrument, CandleRow.granularity == granularity.value)
            .distinct()
            .order_by(CandleRow.dataset_id)
        )
        async with self._db.session() as session:
            return list((await session.scalars(query)).all())


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise TypeError("expected a datetime from the database")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _candle_row(candle: Candle, dataset_id: int) -> dict[str, Any]:
    return {
        "instrument": candle.instrument,
        "granularity": candle.granularity.value,
        "time": candle.time,
        "bid_open": candle.bid.open,
        "bid_high": candle.bid.high,
        "bid_low": candle.bid.low,
        "bid_close": candle.bid.close,
        "ask_open": candle.ask.open,
        "ask_high": candle.ask.high,
        "ask_low": candle.ask.low,
        "ask_close": candle.ask.close,
        "volume": candle.volume,
        "ask_source": candle.ask_source.value,
        "dataset_id": dataset_id,
    }


def _ohlc(open_: Decimal, high: Decimal, low: Decimal, close: Decimal) -> OHLC:
    # Stored rows were validated on the way in; skip re-validation on the hot read path.
    return OHLC.model_construct(open=open_, high=high, low=low, close=close)


def _candle(row: Any) -> Candle:
    return Candle.model_construct(
        instrument=row["instrument"],
        granularity=Granularity(row["granularity"]),
        time=row["time"],
        bid=_ohlc(row["bid_open"], row["bid_high"], row["bid_low"], row["bid_close"]),
        ask=_ohlc(row["ask_open"], row["ask_high"], row["ask_low"], row["ask_close"]),
        volume=row["volume"],
        complete=True,
        ask_source=AskSource(row["ask_source"]),
    )
