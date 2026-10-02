"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Request

from fxbot.config import Settings


def get_app_settings(request: Request) -> Settings:
    """Settings the running app was created with (see ``create_app``)."""
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
