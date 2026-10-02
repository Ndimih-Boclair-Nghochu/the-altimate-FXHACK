"""OANDA hosts, pinned by environment. This is the only module that names them.

There is deliberately no setting for a broker URL: the mode decides the host, so a
configuration mistake cannot send orders (or the token) anywhere else. Tests swap the httpx
transport instead of the URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fxbot.domain.enums import Mode


class OandaEnvironment(StrEnum):
    PRACTICE = "practice"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class OandaHosts:
    rest: str
    stream: str


_HOSTS: Final = {
    OandaEnvironment.PRACTICE: OandaHosts(
        rest="https://api-fxpractice.oanda.com",
        stream="https://stream-fxpractice.oanda.com",
    ),
    OandaEnvironment.LIVE: OandaHosts(
        rest="https://api-fxtrade.oanda.com",
        stream="https://stream-fxtrade.oanda.com",
    ),
}


def hosts_for(environment: OandaEnvironment) -> OandaHosts:
    return _HOSTS[OandaEnvironment(environment)]


def environment_for_mode(mode: Mode) -> OandaEnvironment:
    """Paper (OANDA data feed only) and practice use the practice host; only live uses live."""
    return OandaEnvironment.LIVE if Mode(mode) is Mode.LIVE else OandaEnvironment.PRACTICE
