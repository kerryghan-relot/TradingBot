# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This is a collaborative project between two contributors, each working in their own folder:

- `kerryghan_paper-trading/` — Kerry's active trading bot (see its own `CLAUDE.md` for details)
- `lucas-trading/` — Lucas's unified trading project: shared engine (`core/`), backtesting (`backtest/`), live execution (`live/`), strategies (`strategies/`) — see its `README.md`
- `.venv/` — shared virtual environment at the repo root

Each folder is independently owned. When working with Kerry, stay inside `kerryghan_paper-trading/`. When working with Lucas, stay inside `lucas-trading/`. Do not cross-modify the other contributor's folder.

## Setup

```bash
# Install dependencies (if setting up fresh)
uv sync

# Activate the virtual environment (PowerShell)
.venv\Scripts\activate.ps1
```

Add new dependencies with `uv add <package>` rather than `pip install`.
