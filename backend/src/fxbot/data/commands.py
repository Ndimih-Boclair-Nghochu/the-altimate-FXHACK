"""``fxbot data …`` commands: OANDA history download and validation datasets."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime

from fxbot.brokers.factory import build_oanda_client
from fxbot.brokers.oanda.feed import OandaFeed
from fxbot.config import Settings
from fxbot.data import validation
from fxbot.data.candle_store import CandleStore
from fxbot.data.downloader import HistoricalDownloader, oanda_dataset
from fxbot.data.resample import DERIVED_GRANULARITIES
from fxbot.domain.clock import SystemClock
from fxbot.domain.enums import Granularity
from fxbot.persistence.db import Database

_INSTRUMENT = re.compile(r"^[A-Z]{3}_[A-Z]{3}$")


def instrument_arg(value: str) -> str:
    if not _INSTRUMENT.fullmatch(value):
        raise argparse.ArgumentTypeError("expected an instrument like EUR_USD")
    return value


def utc_arg(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected an ISO date or datetime") from None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def add_data_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    data = subparsers.add_parser("data", help="market data tools")
    commands = data.add_subparsers(dest="data_command", required=True)

    fetch = commands.add_parser("fetch", help="download broker candles into the candle store")
    fetch.add_argument("--source", choices=["oanda"], default="oanda")
    fetch.add_argument("--instrument", type=instrument_arg, required=True)
    fetch.add_argument(
        "--granularity",
        type=Granularity,
        choices=[g for g in Granularity if g not in DERIVED_GRANULARITIES],
        default=Granularity.H1,
        help="H1 or finer; coarser bars are built from H1",
    )
    fetch.add_argument("--from", dest="start", type=utc_arg, required=True, help="UTC start")
    fetch.add_argument("--to", dest="end", type=utc_arg, default=None, help="UTC end (exclusive)")
    fetch.add_argument("--price", choices=["BA"], default="BA", help="price sides (bid+ask)")

    validation_parser = commands.add_parser(
        "fetch-validation", help="download the pinned validation datasets (SHA-256 checked)"
    )
    validation_parser.add_argument(
        "--dataset",
        action="append",
        choices=sorted(validation.DATASETS),
        help="dataset to fetch (repeatable; default: all)",
    )
    validation_parser.add_argument(
        "--load", action="store_true", help="also load the data into the candle store"
    )
    validation_parser.add_argument("--list", action="store_true", help="list datasets and exit")


async def _store(settings: Settings) -> tuple[Database, CandleStore]:
    database = Database(settings.resolved_database_url)
    await database.create_all()
    return database, CandleStore(database)


async def run_fetch(args: argparse.Namespace, settings: Settings) -> int:
    client = build_oanda_client(settings)
    feed = OandaFeed(client, clock=SystemClock(), owns_client=True)
    database, store = await _store(settings)
    try:
        report = await HistoricalDownloader(feed, store).download(
            args.instrument,
            args.granularity,
            args.start,
            args.end,
            dataset=oanda_dataset(client.environment.value, args.instrument, args.granularity),
        )
    finally:
        await feed.aclose()
        await database.dispose()
    resumed = (
        f" (resumed after {report.resumed_from:%Y-%m-%d %H:%M})" if report.resumed_from else ""
    )
    sys.stdout.write(
        f"stored {report.stored} {args.instrument} {args.granularity} candles{resumed}\n"
    )
    return 0


async def run_fetch_validation(args: argparse.Namespace, settings: Settings) -> int:
    if args.list:
        for name, spec in sorted(validation.DATASETS.items()):
            sys.stdout.write(
                f"{name}\t{spec.instrument}\t{spec.granularity}\t{spec.dataset.source}\n"
            )
        return 0
    names = args.dataset or sorted(validation.DATASETS)
    for result in await validation.fetch(names, settings.data_dir):
        sys.stdout.write(f"{result.status:<10} {result.filename}  sha256 {result.sha256}\n")
    if args.load:
        database, store = await _store(settings)
        try:
            for name in names:
                loaded = await validation.load_into_store(name, settings.data_dir, store)
                sys.stdout.write(
                    f"loaded     {name}: {len(loaded.candles)} candles, "
                    f"{loaded.bad_rows} rows rejected\n"
                )
        finally:
            await database.dispose()
    return 0
