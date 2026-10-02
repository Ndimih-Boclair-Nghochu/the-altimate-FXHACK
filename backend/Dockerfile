# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.11
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------------------- build stage
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first, so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# -------------------------------------------------------------------------- runtime stage
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

RUN groupadd --system --gid 10001 fxbot \
    && useradd --system --uid 10001 --gid fxbot --home-dir /app --no-create-home \
       --shell /usr/sbin/nologin fxbot \
    && mkdir -p /app/data \
    && chown fxbot:fxbot /app/data

WORKDIR /app

# The project is installed non-editable, so the virtualenv is all the runtime needs.
COPY --from=builder /app/.venv /app/.venv

# Binding to all interfaces is only appropriate inside the container; the application
# default (used on a host machine) stays 127.0.0.1.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FXBOT_API_HOST=0.0.0.0 \
    FXBOT_API_PORT=8000 \
    FXBOT_LOG_JSON=true \
    FXBOT_DATABASE_URL=sqlite+aiosqlite:////app/data/fxbot.db

USER fxbot

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('FXBOT_API_PORT', '8000')}/api/health\", timeout=3)"]

CMD ["fxbot"]
