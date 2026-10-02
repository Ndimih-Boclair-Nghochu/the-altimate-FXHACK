"""Built-in instrument specifications for the paper broker, synthetic data and tests.

Values mirror OANDA's v20 instrument fields. Margin rates follow EU retail caps (30:1 for
majors, 20:1 otherwise). Live and practice sessions use the broker's own specifications.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from fxbot.domain.models import Instrument

_MAJOR_MARGIN: Final = Decimal("0.0333")
_MINOR_MARGIN: Final = Decimal("0.05")


def _spec(name: str, margin_rate: Decimal) -> Instrument:
    jpy = name.endswith("_JPY")
    return Instrument(
        name=name,
        pip_location=-2 if jpy else -4,
        display_precision=3 if jpy else 5,
        units_step=Decimal(1),
        min_units=Decimal(1),
        max_units=Decimal(100_000_000),
        margin_rate=margin_rate,
    )


DEFAULT_INSTRUMENTS: Final[Mapping[str, Instrument]] = MappingProxyType(
    {
        spec.name: spec
        for spec in (
            _spec("EUR_USD", _MAJOR_MARGIN),
            _spec("GBP_USD", _MAJOR_MARGIN),
            _spec("USD_JPY", _MAJOR_MARGIN),
            _spec("USD_CAD", _MAJOR_MARGIN),
            _spec("USD_CHF", _MAJOR_MARGIN),
            _spec("EUR_GBP", _MAJOR_MARGIN),
            _spec("EUR_JPY", _MAJOR_MARGIN),
            _spec("GBP_JPY", _MAJOR_MARGIN),
            _spec("EUR_CHF", _MAJOR_MARGIN),
            _spec("AUD_USD", _MINOR_MARGIN),
            _spec("NZD_USD", _MINOR_MARGIN),
            _spec("AUD_JPY", _MINOR_MARGIN),
        )
    }
)


def default_instruments(names: Iterable[str] | None = None) -> dict[str, Instrument]:
    """Specs for ``names`` (all built-ins when ``None``). Unknown names raise ``KeyError``."""
    if names is None:
        return dict(DEFAULT_INSTRUMENTS)
    return {name: DEFAULT_INSTRUMENTS[name] for name in names}
