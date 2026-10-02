"""Pinned public validation datasets (research 07 §3): download, verify, load.

Files are fetched from commit-pinned GitHub URLs into the git-ignored ``<data_dir>/validation/``
folder and must match a SHA-256 recorded here; a mismatch is refused. The data is untrusted
input (SR-44): every row is parsed into validated ``Candle`` objects, timestamps are converted
to UTC with an explicit rule, must strictly increase, and a file with more than a handful of
bad rows is rejected as a whole. Licences of the underlying prices are unclear: local use
only, never commit or redistribute these files.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import os
import re
import zipfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import Final, Literal

import httpx
from pydantic import ValidationError

from fxbot.data.candle_store import CandleStore
from fxbot.data.spreads import SpreadProfile, candle_from_bid
from fxbot.domain.enums import AskSource, Granularity
from fxbot.domain.errors import DataIntegrityError
from fxbot.domain.instruments import DEFAULT_INSTRUMENTS
from fxbot.domain.models import OHLC, Candle, Dataset
from fxbot.domain.server_time import (
    FixedOffsetServerTime,
    NewYorkCloseServerTime,
    ServerTimePolicy,
)
from fxbot.logging import get_logger

log = get_logger(__name__)

ALLOWED_PREFIX: Final = "https://raw.githubusercontent.com/"
MAX_DOWNLOAD_BYTES: Final = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES: Final = 256 * 1024 * 1024
MAX_ROWS: Final = 2_000_000
MAX_BAD_ROW_FRACTION: Final = 0.001
DOWNLOAD_TIMEOUT: Final = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
_FILENAME: Final = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,80}$")

_LEAN: Final = "https://raw.githubusercontent.com/QuantConnect/Lean/0ebc2fc44fd4754ff66bdc7ef6cb42c5003f8fc1/Data/forex"
_EJTRADER: Final = "https://raw.githubusercontent.com/ejtraderLabs/historical-data/fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd"

Format = Literal["lean", "ejtrader"]


@dataclass(frozen=True, slots=True)
class RemoteFile:
    url: str
    filename: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        if not self.url.startswith(ALLOWED_PREFIX):
            raise ValueError(f"validation data must come from {ALLOWED_PREFIX}")
        if not _FILENAME.fullmatch(self.filename):
            raise ValueError(f"unsafe file name {self.filename!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("sha256 must be 64 lowercase hex digits")


@dataclass(frozen=True, slots=True)
class ValidationDataset:
    name: str
    instrument: str
    granularity: Granularity
    format: Format
    files: tuple[RemoteFile, ...]
    dataset: Dataset
    server_time: ServerTimePolicy = field(default_factory=lambda: FixedOffsetServerTime(0))
    price_scale: int = 1  # ejtrader stores prices as scaled integers


def _lean(name: str, instrument: str, broker: str, sha: str, size: int) -> ValidationDataset:
    pair = instrument.replace("_", "").lower()
    smoothed_note = "smoothed (open = previous close): no weekend gaps"
    return ValidationDataset(
        name=name,
        instrument=instrument,
        granularity=Granularity.H1,
        format="lean",
        files=(RemoteFile(f"{_LEAN}/{broker}/hour/{pair}.zip", f"{name}.zip", sha, size),),
        dataset=Dataset(
            name=f"validation:{name}",
            source=f"lean-{broker}",
            price_side="BA",
            ask_source=AskSource.QUOTED,
            smoothed=True,
            tz_origin="UTC" if broker == "oanda" else "UTC-05",
            sha256=sha,
            licence_note=(
                f"QuantConnect LEAN sample data ({broker}); {smoothed_note}; local use only"
            ),
        ),
        server_time=FixedOffsetServerTime(0 if broker == "oanda" else -5),
    )


def _ejtrader(
    name: str, instrument: str, granularity: Granularity, suffix: str, sha: str, size: int
) -> ValidationDataset:
    symbol = instrument.replace("_", "")
    return ValidationDataset(
        name=name,
        instrument=instrument,
        granularity=granularity,
        format="ejtrader",
        files=(RemoteFile(f"{_EJTRADER}/{symbol}/{symbol}{suffix}.csv", f"{name}.csv", sha, size),),
        dataset=Dataset(
            name=f"validation:{name}",
            source="ejtrader-mt5",
            price_side="B",
            ask_source=AskSource.MODEL_SPREAD,
            smoothed=False,
            tz_origin="MT5 server time (assumed New York close + 7h)",
            sha256=sha,
            licence_note="ejtraderLabs/historical-data (Apache-2.0 repo, broker unknown); "
            "bid only, ask = bid + typical spread by New York hour of week; local use only",
        ),
        # MT5 server clock with 00:00 = 17:00 New York (research 07 §3.2).
        server_time=NewYorkCloseServerTime(),
        price_scale=1000 if instrument.endswith("_JPY") else 100_000,
    )


# Not included, because they fail the SR-44 checks (ask below bid within a bar): LEAN's FXCM
# EUR/USD H1 file (about 11% of rows) and nautilus_trader's FXCM M1 bid/ask files (1-3% of rows,
# bid and ask bars built separately). research 07 §3.1 and §3.3.
DATASETS: Final[dict[str, ValidationDataset]] = {
    d.name: d
    for d in (
        _lean(
            "lean-oanda-eurusd-h1",
            "EUR_USD",
            "oanda",
            "09f9a548cdb8088e06d40b8af9fca611952d4c88a7ea9e92a7749466951bf92d",
            1_603_996,
        ),
        _lean(
            "lean-oanda-nzdusd-h1",
            "NZD_USD",
            "oanda",
            "1e122113f4ed088cc4683ef6a948da3c258a4961f91c88d7c655f26cb08cce7f",
            1_567_370,
        ),
        _ejtrader(
            "ejtrader-eurusd-h1",
            "EUR_USD",
            Granularity.H1,
            "h1",
            "1b29ca23bdc7b2645ae48a0ccb06108263b69e586bdc7d0ba40e66d1e5966eb9",
            4_246_269,
        ),
        _ejtrader(
            "ejtrader-gbpusd-h1",
            "GBP_USD",
            Granularity.H1,
            "h1",
            "affda7b6e6f4ea505e46f714de37a51bf5d466efb78c3247c5900a0f0a85d3d7",
            3_892_643,
        ),
        _ejtrader(
            "ejtrader-usdjpy-h1",
            "USD_JPY",
            Granularity.H1,
            "h1",
            "4bdca353ee0403727fc0eae621ff8206f5c06d7323b0126923d2a456abc21dbe",
            3_545_887,
        ),
        _ejtrader(
            "ejtrader-eurusd-m15",
            "EUR_USD",
            Granularity.M15,
            "m15",
            "8f9a8d0f7fe483cdede1f19dade91b79928f63678c7a199f990ee555be10faf1",
            16_831_438,
        ),
    )
}


# ---------------------------------------------------------------------------- download


@dataclass(frozen=True, slots=True)
class FetchResult:
    dataset: str
    filename: str
    status: Literal["downloaded", "present"]
    sha256: str


def validation_dir(data_dir: Path) -> Path:
    return data_dir / "validation"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _destination(directory: Path, remote: RemoteFile) -> Path:
    target = (directory / remote.filename).resolve()
    if not target.is_relative_to(directory.resolve()):
        raise DataIntegrityError("validation file path escapes the data directory")
    return target


async def _download(client: httpx.AsyncClient, remote: RemoteFile) -> bytes:
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    received = 0
    async with client.stream("GET", remote.url) as response:
        if response.status_code != 200:
            raise DataIntegrityError(
                f"download of {remote.filename} failed with HTTP {response.status_code}"
            )
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > MAX_DOWNLOAD_BYTES:
                raise DataIntegrityError(f"{remote.filename} exceeds the size limit")
            digest.update(chunk)
            chunks.append(chunk)
    if digest.hexdigest() != remote.sha256 or received != remote.size:
        raise DataIntegrityError(f"SHA-256 mismatch for {remote.filename}; file refused")
    return b"".join(chunks)


def _write_atomically(target: Path, data: bytes) -> None:
    partial = target.with_name(target.name + ".part")
    try:
        partial.write_bytes(data)
        partial.chmod(0o600)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def _is_verified(target: Path, sha256: str) -> bool:
    return target.exists() and _sha256(target) == sha256


async def fetch(
    names: Sequence[str],
    data_dir: Path,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[FetchResult]:
    """Download (or verify already present) files of the named datasets."""
    unknown = [n for n in names if n not in DATASETS]
    if unknown:
        raise KeyError(f"unknown validation datasets: {', '.join(unknown)}")
    directory = validation_dir(data_dir)
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True, mode=0o700)
    results: list[FetchResult] = []
    async with httpx.AsyncClient(
        timeout=DOWNLOAD_TIMEOUT, follow_redirects=False, verify=True, transport=transport
    ) as client:
        for name in names:
            for remote in DATASETS[name].files:
                target = _destination(directory, remote)
                if await asyncio.to_thread(_is_verified, target, remote.sha256):
                    results.append(FetchResult(name, remote.filename, "present", remote.sha256))
                    continue
                data = await _download(client, remote)
                await asyncio.to_thread(_write_atomically, target, data)
                log.info("validation file verified", dataset=name, file=remote.filename)
                results.append(FetchResult(name, remote.filename, "downloaded", remote.sha256))
    return results


# ---------------------------------------------------------------------------- parsing


@dataclass(frozen=True, slots=True)
class LoadResult:
    dataset: ValidationDataset
    candles: tuple[Candle, ...]
    bad_rows: int


def _decimal(text: str) -> Decimal:
    value = Decimal(text.strip())
    if not value.is_finite():
        raise InvalidOperation
    return value


def _validated_rows(
    rows: Iterable[list[str]], build: Callable[[list[str]], Candle], source: str
) -> tuple[list[Candle], int]:
    """Build candles from untrusted rows; drop bad rows, refuse out-of-order data."""
    candles: list[Candle] = []
    bad = 0
    total = 0
    for row in rows:
        total += 1
        if total > MAX_ROWS:
            raise DataIntegrityError(f"{source}: more than {MAX_ROWS} rows")
        try:
            candle = build(row)
        except (ValueError, InvalidOperation, IndexError, ValidationError):
            bad += 1
            continue
        if candles and candle.time <= candles[-1].time:
            if candle.time == candles[-1].time:
                bad += 1  # duplicate timestamp
                continue
            raise DataIntegrityError(f"{source}: timestamps are not increasing")
        candles.append(candle)
    if total and bad / total > MAX_BAD_ROW_FRACTION:
        raise DataIntegrityError(f"{source}: {bad} of {total} rows failed validation")
    return candles, bad


def parse_lean(text_rows: Iterable[list[str]], spec: ValidationDataset) -> tuple[list[Candle], int]:
    """``Time,BidO,BidH,BidL,BidC,BidSize,AskO,AskH,AskL,AskC,AskSize`` (no header)."""

    def build(row: list[str]) -> Candle:
        when = spec.server_time.to_utc(datetime.strptime(row[0].strip(), "%Y%m%d %H:%M"))
        return Candle(
            instrument=spec.instrument,
            granularity=spec.granularity,
            time=when,
            bid=OHLC(
                open=_decimal(row[1]),
                high=_decimal(row[2]),
                low=_decimal(row[3]),
                close=_decimal(row[4]),
            ),
            ask=OHLC(
                open=_decimal(row[6]),
                high=_decimal(row[7]),
                low=_decimal(row[8]),
                close=_decimal(row[9]),
            ),
            ask_source=AskSource.QUOTED,
        )

    return _validated_rows(text_rows, build, spec.name)


def parse_ejtrader(
    text_rows: Iterable[list[str]], spec: ValidationDataset
) -> tuple[list[Candle], int]:
    """Header ``Date,open,high,low,close,tick_volume``; prices are scaled integers (bid)."""
    instrument = DEFAULT_INSTRUMENTS[spec.instrument]
    scale = Decimal(spec.price_scale)
    profile = SpreadProfile.typical([spec.instrument])

    def price(text: str) -> Decimal:
        return instrument.round_price(_decimal(text) / scale, ROUND_HALF_EVEN)

    def build(row: list[str]) -> Candle:
        when = spec.server_time.to_utc(datetime.strptime(row[0].strip(), "%Y-%m-%d %H:%M:%S"))
        bid = OHLC(open=price(row[1]), high=price(row[2]), low=price(row[3]), close=price(row[4]))
        return candle_from_bid(
            instrument=spec.instrument,
            granularity=spec.granularity,
            time=when,
            bid=bid,
            bar_spread=Decimal(0),  # this export has no spread column
            profile=profile,
            volume=int(float(row[5])),
        )

    rows = iter(text_rows)
    header = next(rows, None)
    if header is None or [h.strip().lower() for h in header[:5]] != [
        "date",
        "open",
        "high",
        "low",
        "close",
    ]:
        raise DataIntegrityError(f"{spec.name}: unexpected header")
    return _validated_rows(rows, build, spec.name)


def _open_zip_csv(path: Path) -> Iterator[list[str]]:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) != 1 or not members[0].filename.endswith(".csv"):
            raise DataIntegrityError(f"{path.name}: expected exactly one CSV in the archive")
        if members[0].file_size > MAX_UNCOMPRESSED_BYTES:
            raise DataIntegrityError(f"{path.name}: archive content exceeds the size limit")
        with archive.open(members[0]) as raw:
            yield from csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))


def _open_csv(path: Path) -> Iterator[list[str]]:
    if path.stat().st_size > MAX_UNCOMPRESSED_BYTES:
        raise DataIntegrityError(f"{path.name}: file exceeds the size limit")
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.reader(handle)


def load(name: str, data_dir: Path, *, verify: bool = True) -> LoadResult:
    """Parse a fetched dataset into validated candles (SHA-256 re-checked by default)."""
    spec = DATASETS[name]
    directory = validation_dir(data_dir)
    paths = [_destination(directory, remote) for remote in spec.files]
    for path, remote in zip(paths, spec.files, strict=True):
        if not path.exists():
            raise FileNotFoundError(f"{remote.filename} not fetched; run fetch-validation first")
        if verify and _sha256(path) != remote.sha256:
            raise DataIntegrityError(f"SHA-256 mismatch for {remote.filename}; file refused")
    if spec.format == "lean":
        candles, bad = parse_lean(_open_zip_csv(paths[0]), spec)
    else:
        candles, bad = parse_ejtrader(_open_csv(paths[0]), spec)
    return LoadResult(dataset=spec, candles=tuple(candles), bad_rows=bad)


async def load_into_store(name: str, data_dir: Path, store: CandleStore) -> LoadResult:
    result = load(name, data_dir)
    await store.upsert(result.candles, dataset=result.dataset.dataset)
    log.info(
        "validation dataset loaded",
        dataset=name,
        candles=len(result.candles),
        bad_rows=result.bad_rows,
    )
    return result
