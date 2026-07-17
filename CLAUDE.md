# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A paper-trading bot for US stocks and crypto, executing through Alpaca. It is built on a single principle: **a strategy is written once and runs identically in backtest and live**. The shared per-bar code path (`core/engine.py`) is the load-bearing piece of the design — see *Architecture* below before changing anything under `core/`.

All application code lives in `src/`. The repo root holds the shared venv, the container stack, and dependency management.

## Commands

Python commands run **from `src/`**, not from the repo root: imports resolve `core/`, `live/`, `web/` and `strategies/` as top-level packages, and running from the root raises `ModuleNotFoundError`. The Dockerfile does the same via `WORKDIR /app/src`.

```bash
uv sync                              # install deps (repo root)
..\.venv\Scripts\activate.ps1        # activate, from src/ (PowerShell)
uv add <package>                     # add a dep — never `pip install`
```

```bash
# Backtest / live — <name> is a module in strategies/, e.g. vote_mr
python backtest.py vote_mr                      # event-driven, all CSVs in data/
python backtest.py vote_mr --symbols AAPL NVDA  # subset
python live.py vote_mr                          # live bot (paper)
python -m live.scorer --dry-run                 # preview weekly ranking
python -m live.scorer                           # write top-X into config.json
python -m tools.download_history                # needs TWELVE_DATA_API_KEY in .env
python -m tools.seed_fake_data                  # populate DB without running the bot

# Vectorized research (fast, approximate — see Architecture)
python -m backtest.vectorized.backtest_multi
python -m backtest.vectorized.optimize
streamlit run backtest/dashboard.py

# Web dashboard
cd web/frontend && npm install && npm run build && cd ../..
python -m web.run                    # serves front + API on http://127.0.0.1:8501
cd web/frontend && npm run dev       # front hot-reload (proxies /api to Flask)
```

```bash
# Docker stack — from the repo root
docker compose up -d --build
docker compose logs -f bot
docker compose exec bot python -m live.scorer
docker compose exec db psql -U tradingbot -d tradingbot
```

**There is no test suite and no linter configured** — no pytest, no ruff. There is no test command to run; don't go looking for one. The `py_compile`-and-smoke-test approach in `REFACTOR_PLAN.md` phase 10 is the only verification precedent in the repo. `pre-commit` and `commitizen` are installed, but they lint **commit messages only** (see *Conventions*) — nothing runs at the `pre-commit` stage.

```bash
uv run pre-commit install            # once per clone — activates the commit-msg hook
```

## Architecture

### One strategy, two engines

`core/signals.py` + `core/engine.py` are the single implementation of the per-bar logic, and **three** callers share them:

- `live/bot.py` — live orders against Alpaca
- `live/scorer.py` — weekly symbol ranking by simulated Sharpe
- `backtest/event_driven.py` → `core/simulation.py` — historical replay

This is the whole point of the layout. Before the merge documented in `REFACTOR_PLAN.md`, the signals existed in three hand-maintained copies and silently drifted, so the scorer ranked symbols on a strategy that was no longer the one being traded. A change to `evaluate_bar` intentionally changes backtest, scorer and live at once — that is the design, not a hazard to route around.

`core/engine.py` deliberately owns **no** position tracking, order placement, stop-loss, or persistence. Those belong to the callers. Keep it that way.

### Adding signals vs. adding strategies

- **A new strategy** is a config, not code: copy `strategies/vote_mr.py`, override keys over `DEFAULT_CONFIG`, export `STRATEGY`. It is then available to both CLIs by module name.
- **A new signal type** requires two files: implement `sig_*` in `core/signals.py`, then wire it into `evaluate_bar` in `core/engine.py` (and into `warmup_needed` if it needs history). Stateful signals (VWAP, ORB, KalmanZ) additionally need state fields on `SignalState` and reset handling in `start_bar`.

### Config is the runtime source of truth

`config/config.json` (gitignored) outranks the strategy file once it exists:

- `live.py <name>` creates it from the strategy if absent; if present, it only *reports* divergences and the file wins.
- The bot **hot-reloads** it (~30 s) — `CryptoBot._reload_config()`.
- `live/scorer.py` rewrites its `symbols` key every Sunday.
- The dashboard's Configuration tab writes it over HTTP.

So editing a strategy file does not change a running bot, and three different writers touch that one file.

### The vectorized replica can drift

`backtest/vectorized/strategies_vbt.py` re-implements the signals vectorized (vectorbt) for speed. It is a *second* implementation and parity with `core/signals.py` was **not** re-validated by the refactor (`REFACTOR_PLAN.md` §5). Use the vectorized scripts for exploration; final validation of a strategy always goes through `python backtest.py <name>`, which is slower but divergence-free by construction.

### Data store

PostgreSQL via `core/db.py`; connection from `DATABASE_URL` (defaults to the compose `db` service). Three tables: `bars` (raw OHLCV), `indicators` (per-bar vote snapshot), `trades` (one row per accepted order, with realised `pnl_pct` on exits).

Two traps:

- **`indicators.timestamp` is the evaluation time, not the bar close time** — it deliberately differs from `bars.timestamp`. Joining the two on `timestamp` silently returns zero rows. There is intentionally no foreign key.
- Timestamps are ISO-8601 **`TEXT`**, not `TIMESTAMPTZ` — a deliberate carry-over so that lexicographic order still matches chronological order after the SQLite migration.

### Import-time credential check

`core/broker.py` raises `RuntimeError` at **import** if `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` are absent. Anything importing `live.bot` or `live.scorer` therefore needs a populated `.env`. The backtest path and `web/` do not import it (the web layer talks to Alpaca over raw `requests` instead).

### Single source of truth

`core/constants.py` owns paths, the 30-symbol `SYMBOLS` universe, and the annualisation factors. The live/backtest annualisation split matters: research uses **5-min** Twelve Data bars, live uses **1-min** Alpaca bars, and Sharpe is wrong if the factors are crossed.

## Conventions

- **Prose**: `.claude/rules/prose.md` (loaded when touching any `.md` / `.txt`) — do not hard-wrap prose. One paragraph or bullet is one line, however long — editors soft-wrap it. Code blocks, tables and frontmatter are exempt; commit bodies are **not** exempt. There is no column limit on prose.
- **Code style**: `.claude/rules/code-style.md` (loaded when touching `.py` / `.pyi`) — PEP 8 + Google style, 80 cols, `X | None` never `Optional[X]`, built-in generics. It is enforced by review only.
- **Commits**: `.claude/rules/commits.md` (auto-loaded) — Conventional Commits, enforced by a commitizen `commit-msg` hook. Scopes are the top-level modules (`core`, `live`, `web`, …) plus `infra`. Never `--no-verify`; `pyproject.toml`'s `version` and `CHANGELOG.md` are owned by release-please, never bumped by hand.
- **GitHub**: `.claude/rules/github.md` — read an issue's **comments** before working it, and interview rather than guess when something is undecided. Branches are created with `gh issue develop --name <github-username>/<issue-number>-<slug>` (never `git checkout -b`, which does not link the branch to its issue) — and still ask first.
- **Agents**: `.claude/agents/` holds subagent definitions. Security review is a two-agent pipeline: `security-analyst` (opus, read-only) runs `/security-review` + the `security-checklist` skill and writes a report to `security-reports/`; then **you** (the main conversation) show it and ask the user to approve, and only on approval spawn `security-fixer` (opus) to apply it. The analyst can't ask for that approval itself — subagents have no `AskUserQuestion` — so the confirmation gate is the main thread's job. Delegate to `security-analyst` whenever the user asks if something is secure/safe, the risks of a change, or for a vulnerability review. Reports are committed but the repo is public, so they carry no exploit detail or secret values.
- **Design loop**: for a decision that is expensive to reverse, `software-architect` (opus, language-agnostic, no `Edit`) drafts into `docs/.architecture-design/<slug>.md` and `nemesis` (sonnet) attacks it — then **you** adjudicate, because the architect must never grade the critique of its own work. A supervisor agent was considered and rejected: the main thread already fills that role. One round-trip, then it reaches the user with what was raised and what you dismissed. Answer ordinary architecture questions ("is the current structure good?") directly — the loop is two cold starts and is not free. `nemesis` is generic: point it at any proposal, not just a design. Only `README.md` is tracked in that directory; drafts are gitignored and a design worth keeping is promoted to its issue, `CLAUDE.md` or code. **Verify a subagent's claims about the filesystem yourself** (`ls -lai`) — the architect has twice fabricated the state of its own output path, though never the content of its designs.
- **Language**: user-facing docs (`src/README.md`, `deploy/README.md`) are in **French**; code, docstrings and comments are in **English**. Match the file you are in.
- **`TODO.md` / `DONE.md`** (repo root) are a hand-maintained log. Both the user and Claude write to them: a worked-on TODO bullet moves to `DONE.md`, and `DONE.md` is to be updated after any significant change. **Keep every bullet to 2 sentences at most** — reference a GitHub issue (`TODO.md`) or a commit (`DONE.md`) instead of writing a long description. `DONE.md` entries are grouped newest-first under `## <date> — <title>` headings.
- `archive/` holds superseded files kept for verification — do not treat it as live code.
