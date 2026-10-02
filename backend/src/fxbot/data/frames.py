"""Conversion of candles to pandas frames for vectorized indicator code (float64)."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from fxbot.domain.models import Candle

COLUMNS = (
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
)


def candles_to_frame(candles: Sequence[Candle]) -> pd.DataFrame:
    """One row per candle, indexed by UTC open time, with bid, ask and mid columns."""
    records = [
        {
            "time": c.time,
            "bid_open": float(c.bid.open),
            "bid_high": float(c.bid.high),
            "bid_low": float(c.bid.low),
            "bid_close": float(c.bid.close),
            "ask_open": float(c.ask.open),
            "ask_high": float(c.ask.high),
            "ask_low": float(c.ask.low),
            "ask_close": float(c.ask.close),
            "volume": c.volume,
        }
        for c in candles
    ]
    frame = pd.DataFrame.from_records(records, columns=["time", *COLUMNS, "volume"])
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.set_index("time")
    for part in ("open", "high", "low", "close"):
        frame[f"mid_{part}"] = (frame[f"bid_{part}"] + frame[f"ask_{part}"]) / 2
    return frame
