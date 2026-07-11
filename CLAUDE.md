# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

- `lucas-trading/` — Lucas's unified trading project: shared engine (`core/`), backtesting (`backtest/`), live execution (`live/`), strategies (`strategies/`) — see its `README.md`
- `.venv/` — shared virtual environment at the repo root

## Setup

```bash
# Install dependencies (if setting up fresh)
uv sync

# Activate the virtual environment (PowerShell)
.venv\Scripts\activate.ps1
```

Add new dependencies with `uv add <package>` rather than `pip install`.
