"""Validation datasets: pinned downloads, SHA-256 checks and untrusted-row validation."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from fxbot.data import validation
from fxbot.data.candle_store import CandleStore
from fxbot.data.validation import DATASETS, RemoteFile, ValidationDataset
from fxbot.domain.enums import AskSource, Granularity
from fxbot.domain.errors import DataIntegrityError

LEAN_ROWS = [
    "20070101 21:00,1.31955,1.32000,1.31900,1.31960,0,1.31975,1.32020,1.31920,1.31980,0",
    "20070101 22:00,1.31960,1.32010,1.31950,1.31990,0,1.31980,1.32030,1.31970,1.32010,0",
]


def lean_zip(rows: list[str], members: int = 1) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for i in range(members):
            archive.writestr(f"eurusd{i}.csv", "\n".join(rows) + "\n")
    return buffer.getvalue()


def ejtrader_csv(rows: list[str]) -> bytes:
    return ("Date,open,high,low,close,tick_volume\n" + "\n".join(rows) + "\n").encode()


def install(
    monkeypatch: pytest.MonkeyPatch,
    data_dir: Path,
    template: str,
    payload: bytes,
    *,
    write: bool = True,
) -> ValidationDataset:
    """Register a dataset whose pinned checksum matches ``payload`` (and optionally place it)."""
    base = DATASETS[template]
    remote = replace(
        base.files[0],
        filename=f"test-{template}{Path(base.files[0].filename).suffix}",
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )
    spec = replace(base, name=f"test-{template}", files=(remote,))
    monkeypatch.setitem(DATASETS, spec.name, spec)
    if write:
        folder = validation.validation_dir(data_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / remote.filename).write_bytes(payload)
    return spec


def test_registry_is_pinned_and_safe() -> None:
    names = set()
    for name, spec in DATASETS.items():
        for remote in spec.files:
            assert re.match(
                r"^https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/", remote.url
            )
            assert re.fullmatch(r"[0-9a-f]{64}", remote.sha256) and remote.size > 0
            assert remote.filename not in names
            names.add(remote.filename)
        assert spec.dataset.name == f"validation:{name}"
    assert {"lean-oanda-eurusd-h1", "ejtrader-usdjpy-h1"} <= set(DATASETS)


@pytest.mark.parametrize(
    ("url", "filename", "sha"),
    [
        ("http://example.com/x.csv", "x.csv", "0" * 64),
        ("https://raw.githubusercontent.com/a/b/c/x.csv", "../x.csv", "0" * 64),
        ("https://raw.githubusercontent.com/a/b/c/x.csv", "x.csv", "XYZ"),
    ],
)
def test_remote_files_are_validated(url: str, filename: str, sha: str) -> None:
    with pytest.raises(ValueError):
        RemoteFile(url, filename, sha, 1)


def test_lean_sample_parses_bid_and_ask(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install(monkeypatch, tmp_path, "lean-oanda-eurusd-h1", lean_zip(LEAN_ROWS))

    result = validation.load("test-lean-oanda-eurusd-h1", tmp_path)

    first, second = result.candles
    assert first.time == datetime(2007, 1, 1, 21, tzinfo=UTC)
    assert (first.bid.open, first.ask.close) == (Decimal("1.31955"), Decimal("1.31980"))
    assert first.ask_source is AskSource.QUOTED and second.granularity is Granularity.H1
    assert result.bad_rows == 0 and result.dataset.dataset.smoothed


def test_ejtrader_sample_scales_prices_and_converts_server_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = [
        "2013-01-07 00:00:00,127801.00000000001,127835.00000000001,127777.0,127810.0,869",
        "2013-07-08 00:00:00,130000.0,130100.0,129900.0,130050.0,10",
    ]
    install(monkeypatch, tmp_path, "ejtrader-eurusd-h1", ejtrader_csv(rows))

    winter, summer = validation.load("test-ejtrader-eurusd-h1", tmp_path).candles

    # Server midnight is 17:00 New York: 22:00 UTC in winter, 21:00 UTC in summer.
    assert winter.time == datetime(2013, 1, 6, 22, tzinfo=UTC)
    assert summer.time == datetime(2013, 7, 7, 21, tzinfo=UTC)
    assert winter.bid.open == Decimal("1.27801") and winter.volume == 869
    # Sunday 17:00 New York is inside the rollover window: 4 x 1.3 pips.
    assert winter.spread_open == Decimal("0.00052")
    assert winter.ask_source is AskSource.MODEL_SPREAD


def _ejtrader_rows(count: int) -> list[str]:
    start = datetime(2013, 4, 1)  # away from DST changes
    return [
        f"{(start + timedelta(hours=i)):%Y-%m-%d %H:%M:%S},130000.0,130100.0,129900.0,130050.0,1"
        for i in range(count)
    ]


def test_a_few_bad_rows_are_dropped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rows = _ejtrader_rows(2000)
    rows[10] = rows[10].replace("129900.0", "131000.0")  # low above high
    rows[20] = rows[19]  # duplicate timestamp
    install(monkeypatch, tmp_path, "ejtrader-eurusd-h1", ejtrader_csv(rows))

    result = validation.load("test-ejtrader-eurusd-h1", tmp_path)

    assert result.bad_rows == 2 and len(result.candles) == 1998


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda rows: [r.replace("130100.0", "nan") for r in rows[:10]] + rows[10:],
            "failed validation",
        ),
        (lambda rows: rows[5:] + rows[:5], "not increasing"),
        (lambda rows: ["x" + rows[0][1:]], "failed validation"),
    ],
    ids=["many-bad-rows", "out-of-order", "garbage"],
)
def test_untrusted_files_are_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutate: object, message: str
) -> None:
    rows = mutate(_ejtrader_rows(100))  # type: ignore[operator]
    install(monkeypatch, tmp_path, "ejtrader-eurusd-h1", ejtrader_csv(rows))

    with pytest.raises(DataIntegrityError, match=message):
        validation.load("test-ejtrader-eurusd-h1", tmp_path)


def test_bad_header_and_archive_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install(monkeypatch, tmp_path, "ejtrader-eurusd-h1", b"when,o,h,l,c,v\n")
    with pytest.raises(DataIntegrityError, match="header"):
        validation.load("test-ejtrader-eurusd-h1", tmp_path)

    install(monkeypatch, tmp_path, "lean-oanda-eurusd-h1", lean_zip(LEAN_ROWS, members=2))
    with pytest.raises(DataIntegrityError, match="exactly one CSV"):
        validation.load("test-lean-oanda-eurusd-h1", tmp_path)


def test_tampered_or_missing_files_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = install(monkeypatch, tmp_path, "lean-oanda-eurusd-h1", lean_zip(LEAN_ROWS))
    path = validation.validation_dir(tmp_path) / spec.files[0].filename
    path.write_bytes(lean_zip(LEAN_ROWS[:1]))

    with pytest.raises(DataIntegrityError, match="SHA-256 mismatch"):
        validation.load(spec.name, tmp_path)
    path.unlink()
    with pytest.raises(FileNotFoundError, match="fetch-validation"):
        validation.load(spec.name, tmp_path)


async def test_fetch_downloads_verifies_and_skips_present_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = lean_zip(LEAN_ROWS)
    spec = install(monkeypatch, tmp_path, "lean-oanda-eurusd-h1", payload, write=False)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=payload)

    transport = httpx.MockTransport(handler)
    first = await validation.fetch([spec.name], tmp_path, transport=transport)
    second = await validation.fetch([spec.name], tmp_path, transport=transport)

    assert [r.status for r in first] == ["downloaded"]
    assert [r.status for r in second] == ["present"]
    assert len(seen) == 1 and str(seen[0].url) == spec.files[0].url
    target = validation.validation_dir(tmp_path) / spec.files[0].filename
    assert target.read_bytes() == payload
    assert not list(target.parent.glob("*.part"))


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, content=b"tampered"), httpx.Response(404, content=b"")],
    ids=["checksum", "http-error"],
)
async def test_fetch_refuses_bad_downloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, response: httpx.Response
) -> None:
    spec = install(monkeypatch, tmp_path, "lean-oanda-eurusd-h1", lean_zip(LEAN_ROWS), write=False)
    transport = httpx.MockTransport(lambda request: response)

    with pytest.raises(DataIntegrityError):
        await validation.fetch([spec.name], tmp_path, transport=transport)

    assert not (validation.validation_dir(tmp_path) / spec.files[0].filename).exists()
    with pytest.raises(KeyError, match="unknown"):
        await validation.fetch(["nope"], tmp_path, transport=transport)


async def test_load_into_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: CandleStore
) -> None:
    spec = install(monkeypatch, tmp_path, "lean-oanda-eurusd-h1", lean_zip(LEAN_ROWS))

    result = await validation.load_into_store(spec.name, tmp_path, store)

    stored = await store.get_candles("EUR_USD", Granularity.H1)
    assert stored == list(result.candles)
    (provenance,) = await store.datasets("EUR_USD", Granularity.H1)
    assert provenance.sha256 == DATASETS["lean-oanda-eurusd-h1"].dataset.sha256
