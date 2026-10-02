"""Structured logging (structlog over stdlib logging) with secret redaction.

Both structlog loggers and plain stdlib loggers (uvicorn, httpx, sqlalchemy, ...) are routed
through the same processor chain, so redaction applies to every line the process logs.
Redaction is a last line of defence: code should still never log credentials on purpose.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping
from typing import Any, Final, TextIO

import structlog
from pydantic import SecretBytes, SecretStr
from structlog.typing import EventDict, Processor, WrappedLogger

REDACTED: Final = "***REDACTED***"

HANDLER_NAME: Final = "fxbot"

SENSITIVE_KEY_PATTERN: Final = re.compile(
    r"token|secret|passw(?:or)?d|authori[sz]ation|api[_-]?key|account[_-]?id|cookie|credential",
    re.IGNORECASE,
)

# (pattern, replacement) pairs applied in order to every string that is logged.
_TEXT_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # OANDA v20 personal access token: two 32-hex-digit groups joined by a hyphen.
    (re.compile(r"\b[0-9a-f]{32}-[0-9a-f]{32}\b", re.IGNORECASE), REDACTED),
    # OANDA account id, e.g. 101-004-1234567-001 (it appears in every v20 request URL).
    (re.compile(r"\b\d{3}-\d{3}-\d{5,10}-\d{3}\b"), REDACTED),
    # HTTP auth schemes.
    (re.compile(r"\b(Bearer|Basic)\s+[\w.~+/=-]+", re.IGNORECASE), rf"\1 {REDACTED}"),
    # Credentials embedded in URLs: scheme://user:password@host
    (re.compile(r"(?<=://)([^:/@\s]+):[^@/\s]+@"), rf"\1:{REDACTED}@"),
    # key=value and "key": "value" pairs, e.g. query strings, JSON bodies, error messages.
    (
        re.compile(
            r"\b([\w-]*(?:token|secret|passw(?:or)?d|api[_-]?key)[\w-]*[\"']?\s*[=:]\s*[\"']?)"
            r"(?!\*\*\*)[^\s&,;\"']+",
            re.IGNORECASE,
        ),
        rf"\1{REDACTED}",
    ),
)


def is_sensitive_key(key: object) -> bool:
    return isinstance(key, str) and SENSITIVE_KEY_PATTERN.search(key) is not None


def redact_text(text: str) -> str:
    """Mask anything in ``text`` that looks like a credential."""
    for pattern, replacement in _TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _is_secret_free(value: object) -> bool:
    # Flags such as ``has_token=False`` or an unset ``api_token=None`` are useful and safe.
    return value is None or isinstance(value, bool)


def redact_mapping(mapping: Mapping[Any, Any]) -> dict[Any, Any]:
    """Return a copy of ``mapping`` with values under sensitive keys masked, recursively."""
    return {
        key: REDACTED
        if is_sensitive_key(key) and not _is_secret_free(value)
        else redact_value(value)
        for key, value in mapping.items()
    }


def redact_value(value: Any) -> Any:
    """Return a copy of ``value`` with credentials masked, recursing into containers."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, SecretStr | SecretBytes):
        return REDACTED
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, list | set | frozenset):
        return [redact_value(item) for item in value]
    if isinstance(value, BaseException):
        return redact_text(f"{type(value).__name__}: {value}")
    return value


def redact_sensitive(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor: mask sensitive keys and credential-like substrings."""
    redacted = redact_mapping(event_dict)
    if "exc_info" in event_dict:
        # Kept intact for format_exc_info; the rendered traceback is redacted after that.
        redacted["exc_info"] = event_dict["exc_info"]
    return redacted


def _drop_color_message(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """uvicorn attaches an ANSI-coloured duplicate of each message; it is noise in our output."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(
    level: str = "INFO", *, json: bool = False, stream: TextIO | None = None
) -> None:
    """Configure structlog and the stdlib root logger. Safe to call more than once."""
    stream = stream or sys.stdout
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        _drop_color_message,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            # Redact before the record reaches any handler, not only ours.
            redact_sensitive,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: Processor
    if json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=stream.isatty(), exception_formatter=structlog.dev.plain_traceback
        )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # Render tracebacks to text first so they are redacted like everything else;
            # this pass also covers records from stdlib loggers.
            structlog.processors.format_exc_info,
            redact_sensitive,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Route uvicorn's loggers through the root handler instead of their own.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def get_logger(name: str, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to the stdlib logger ``name`` (usually ``__name__``)."""
    return structlog.stdlib.get_logger(name, **initial_values)
