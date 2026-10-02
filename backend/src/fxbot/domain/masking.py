"""Display-safe renderings of identifiers that must not be shown in full."""

from __future__ import annotations


def mask_account_id(account_id: str) -> str:
    """Keep only the last segment: ``101-004-1234567-001`` becomes ``***-***-*******-001``."""
    parts = account_id.split("-")
    if len(parts) < 2:
        return "***"
    return "-".join(["*" * len(part) for part in parts[:-1]] + [parts[-1]])
