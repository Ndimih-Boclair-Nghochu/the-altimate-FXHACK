"""Command-line entry point: ``fxbot`` (or ``python -m fxbot``) serves the API with uvicorn."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import uvicorn
from pydantic import ValidationError

from fxbot import __version__
from fxbot.api.app import create_app
from fxbot.config import get_settings
from fxbot.logging import configure_logging, get_logger


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="fxbot",
        description="Run the Altimate FX API server. Configuration comes from FXBOT_* "
        "environment variables and an optional .env file.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)

    try:
        settings = get_settings()
    except ValidationError as exc:
        sys.stderr.write(f"fxbot: invalid configuration\n{exc}\n")
        raise SystemExit(2) from None

    configure_logging(settings.log_level, json=settings.log_json)
    log = get_logger(__name__)
    if settings.trading_mode == "live":
        log.warning("live trading mode enabled: orders will be placed with real money")
    log.info(
        "starting api",
        version=__version__,
        mode=settings.trading_mode,
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
