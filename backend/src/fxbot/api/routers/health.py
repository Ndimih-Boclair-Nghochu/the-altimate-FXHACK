"""Liveness endpoint. Reports only non-sensitive facts about the running service."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from fxbot import __version__
from fxbot.api.deps import SettingsDep
from fxbot.config import TradingMode

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    mode: TradingMode


@router.get("/health")
async def get_health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(version=__version__, mode=settings.trading_mode)
