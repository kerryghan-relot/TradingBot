# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

- `lucas-trading/` — Lucas's unified trading project: shared engine (`core/`), backtesting (`backtest/`), live execution (`live/`), strategies (`strategies/`) — see its `README.md`
- `.venv/` — shared virtual environment at the repo root
- `Dockerfile` / `docker-compose.yml` — full containerised stack (Postgres + bot + web + nginx + scheduler); see `lucas-trading/deploy/README.md`

## Data store

Live bars, indicators and trades are persisted in **PostgreSQL** (not the old SQLite `bars.db`). The access layer is `lucas-trading/core/db.py`; connection settings come from the `DATABASE_URL` env var (defaults to the compose `db` service). Timestamps are stored as ISO-8601 `TEXT`.

## Setup

```bash
# Local dev (bare metal): install dependencies
uv sync
.venv\Scripts\activate.ps1        # PowerShell

# Or run the whole stack in Docker (needs a repo-root .env)
docker compose up -d --build
```

Add new dependencies with `uv add <package>` rather than `pip install`.
