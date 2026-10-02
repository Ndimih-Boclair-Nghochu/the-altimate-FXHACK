from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from fxbot.domain.instruments import DEFAULT_INSTRUMENTS
from fxbot.domain.models import Financing
from fxbot.persistence.db import Database
from fxbot.persistence.models import DecimalText, UtcDateTime
from fxbot.persistence.repositories import DatasetRepository, InstrumentRepository
from tests.data.conftest import dataset

NOW = datetime(2024, 3, 4, tzinfo=UTC)


async def test_sqlite_file_and_pragmas(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "fx.db"
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    await database.create_all()

    async with database.session() as session:
        mode = await session.scalar(text("PRAGMA journal_mode"))
        timeout = await session.scalar(text("PRAGMA busy_timeout"))
        foreign_keys = await session.scalar(text("PRAGMA foreign_keys"))

    assert path.exists()
    assert (mode, timeout, foreign_keys) == ("wal", 5000, 1)
    assert repr(database) == "Database(dialect='sqlite')"
    await database.dispose()


async def test_instruments_round_trip(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'i.db').as_posix()}")
    await database.create_all()
    repo = InstrumentRepository(database)
    eur_usd = DEFAULT_INSTRUMENTS["EUR_USD"].model_copy(
        update={"financing": Financing(long_rate=Decimal("-0.0153"), short_rate=Decimal("0.001"))}
    )

    await repo.upsert([eur_usd, DEFAULT_INSTRUMENTS["USD_JPY"]], now=NOW)
    await repo.upsert([eur_usd], now=NOW)
    await repo.upsert([], now=NOW)

    assert await repo.get("EUR_USD") == eur_usd
    assert [i.name for i in await repo.list(enabled_only=True)] == ["EUR_USD", "USD_JPY"]
    assert await repo.get("GBP_USD") is None
    datasets = DatasetRepository(database)
    first = await datasets.upsert(dataset(), now=NOW)
    assert await datasets.upsert(dataset(smoothed=True), now=NOW) == first
    assert (await datasets.get("test:eurusd")) == dataset(smoothed=True)
    assert await datasets.get("missing") is None
    await database.dispose()


def test_column_types_refuse_unsafe_values() -> None:
    with pytest.raises(ValueError, match="naive"):
        UtcDateTime().process_bind_param(datetime(2024, 1, 1), None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        DecimalText().process_bind_param(Decimal("NaN"), None)  # type: ignore[arg-type]
    assert DecimalText().process_bind_param(Decimal("1E-5"), None) == "0.00001"  # type: ignore[arg-type]
    assert DecimalText().process_result_value(None, None) is None  # type: ignore[arg-type]
    assert UtcDateTime().process_result_value(None, None) is None  # type: ignore[arg-type]
