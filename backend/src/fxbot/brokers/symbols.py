"""Mapping between canonical instrument names (``EUR_USD``) and broker symbols.

Broker symbol names vary (``EURUSD``, ``EURUSDm``, ``EURUSD.a``). Everything above the adapter
layer uses canonical names; adapters translate at the boundary with a ``SymbolMap``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Final

_CANONICAL: Final = re.compile(r"^[A-Z]{3}_[A-Z]{3}$")


class SymbolMap:
    def __init__(self, mapping: Mapping[str, str]) -> None:
        for canonical in mapping:
            if not _CANONICAL.fullmatch(canonical):
                raise ValueError(f"not a canonical instrument name: {canonical!r}")
        reverse: dict[str, str] = {}
        for canonical, symbol in mapping.items():
            if symbol in reverse:
                raise ValueError(f"broker symbol {symbol!r} is mapped twice")
            reverse[symbol] = canonical
        self._to_broker = dict(mapping)
        self._to_canonical = reverse

    @classmethod
    def identity(cls, instruments: Iterable[str]) -> SymbolMap:
        """Broker uses canonical names (OANDA)."""
        return cls({name: name for name in instruments})

    @classmethod
    def concatenated(
        cls, instruments: Iterable[str], *, prefix: str = "", suffix: str = ""
    ) -> SymbolMap:
        """``EUR_USD`` → ``{prefix}EURUSD{suffix}`` (typical MT5 naming, e.g. suffix ``m``)."""
        return cls({name: f"{prefix}{name.replace('_', '')}{suffix}" for name in instruments})

    def to_broker(self, instrument: str) -> str:
        try:
            return self._to_broker[instrument]
        except KeyError:
            raise KeyError(f"no broker symbol configured for {instrument}") from None

    def to_canonical(self, symbol: str) -> str:
        try:
            return self._to_canonical[symbol]
        except KeyError:
            raise KeyError(f"broker symbol {symbol!r} is not mapped") from None

    def __contains__(self, instrument: object) -> bool:
        return instrument in self._to_broker

    def __repr__(self) -> str:
        return f"SymbolMap({self._to_broker!r})"
