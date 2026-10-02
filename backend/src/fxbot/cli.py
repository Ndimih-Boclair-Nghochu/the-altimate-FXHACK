"""Command-line entry point.

``fxbot`` (or ``fxbot serve``, ``python -m fxbot``) serves the API with uvicorn;
``fxbot data …`` runs the market-data tools. Configuration comes from ``FXBOT_*`` environment
variables and an optional ``.env`` file; secrets are never accepted as arguments (SR-1).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

import uvicorn
from pydantic import ValidationError

from fxbot import __version__
from fxbot.api.app import create_app
from fxbot.brokers.factory import checked_mode
from fxbot.config import Settings, get_settings
from fxbot.data import commands
from fxbot.domain.enums import Mode
from fxbot.domain.errors import FxbotError
from fxbot.logging import configure_logging, get_logger


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fxbot",
        description="Altimate FX. Configuration comes from FXBOT_* environment variables "
        "and an optional .env file.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="run the API server (default)")
    commands.add_data_commands(subparsers)
    return parser


def _serve(settings: Settings) -> int:
    mode = checked_mode(settings)  # second interlock check (the first ran in Settings)
    log = get_logger(__name__)
    if mode is Mode.LIVE:
        log.warning("live trading mode enabled: orders will be placed with real money")
    log.info(
        "starting api",
        version=__version__,
        mode=mode.value,
        host=settings.api_host,
        port=settings.api_port,
    )
    uvicorn.run(
        create_app(settings),
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
        server_header=False,
    )
    return 0


def _run(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "data":
        if args.data_command == "fetch":
            return asyncio.run(commands.run_fetch(args, settings))
        return asyncio.run(commands.run_fetch_validation(args, settings))
    return _serve(settings)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        settings = get_settings()
    except ValidationError as exc:
        sys.stderr.write(f"fxbot: invalid configuration\n{exc}\n")
        raise SystemExit(2) from None

    configure_logging(settings.log_level, json=settings.log_json)
    try:
        code = _run(args, settings)
    except FxbotError as exc:
        sys.stderr.write(f"fxbot: {exc}\n")
        raise SystemExit(1) from None
    if code:
        raise SystemExit(code)
