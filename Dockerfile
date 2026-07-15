# syntax=docker/dockerfile:1
#
# Multi-stage build for TradingBot.
# One image serves the bot, the web dashboard and the scorer — only the
# command differs (see docker-compose.yml).

# ── Stage 1: build the React front (Vite) ─────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /front
COPY src/web/frontend/package.json \
     src/web/frontend/package-lock.json ./
RUN npm ci
COPY src/web/frontend/ ./
RUN npm run build


# ── Stage 2: Python app (uv-managed venv) ─────────────────────────────
FROM python:3.13-slim AS app

# uv (fast, lockfile-driven installer)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependency layer — cached until the lockfile changes.
# --no-dev: the dev group is commit tooling (commitizen, pre-commit) and uv
# would otherwise install it here — no commits are ever authored in the image.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project --no-dev

# Application code.
COPY src/ ./src/

# Built front from stage 1.
COPY --from=frontend /front/dist ./src/web/frontend/dist

# Imports resolve as top-level packages (core/, live/, web/) from here.
WORKDIR /app/src

# Default command; overridden per-service in docker-compose.yml.
CMD ["python", "-m", "live.bot"]
