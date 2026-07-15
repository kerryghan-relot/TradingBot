# TradingBot

A paper-trading bot for US stocks and crypto, executing through Alpaca, built around one principle: **a strategy is written once and runs identically in backtest and in live**.

Several mean-reversion signals vote on every 1-minute bar; when enough of them agree, an order goes out. The same voting engine that decides a live trade also replays three years of history in the backtester and ranks the tradeable universe every Sunday — one implementation, three callers, no drift.

- **Practical workflow** (create a strategy → backtest → go live): [`src/README.md`](src/README.md)
- **Deployment and operations**: [`src/deploy/README.md`](src/deploy/README.md)
- **Signals reference**: [`src/docs/GUIDE_SIGNAUX_METHODES.md`](src/docs/GUIDE_SIGNAUX_METHODES.md)

## Getting started

```bash
git clone git@github.com:kerryghan-relot/TradingBot.git
cd TradingBot
uv sync                            # install dependencies (repo root)
uv run pre-commit install          # once per clone — see below
.venv\Scripts\activate.ps1         # PowerShell
```

`uv sync` installs the `pre-commit` and `commitizen` tools, but it does **not** wire the git hook that runs them: `.git/hooks/` is local to a clone and never travels with the repo. `uv run pre-commit install` is therefore a separate one-time step in every clone, and until someone runs it commit messages are not checked at all. See [`.claude/rules/commits.md`](.claude/rules/commits.md).

Python commands run **from `src/`**, which is where `core/`, `live/` and `web/` resolve as top-level packages. Add dependencies with `uv add <package>`, never `pip install`.

```bash
# Or run the whole stack in containers (needs a repo-root .env)
cp .env.example .env
bash src/deploy/docker/init_secrets.sh
docker compose up -d --build
```

Alpaca keys go in `.env` at the repo root. The bot is in paper trading (`PAPER = True` in `core/broker.py`).

## How it works

A **strategy** is not code — it is a named, frozen configuration of the shared vote engine: which signals vote, their parameters, the vote threshold, the stop-loss. That single config dict drives both `python backtest.py <name>` and `python live.py <name>`.

The engine (`core/engine.py`) evaluates one bar at a time and is shared by three callers:

| Caller | Role |
|---|---|
| `live/bot.py` | Places real (paper) orders from the Alpaca stream |
| `live/scorer.py` | Ranks the universe weekly by simulated Sharpe |
| `backtest/event_driven.py` | Replays historical CSVs bar by bar |

This is the point of the layout. These three were once three hand-maintained copies of the same logic, and they drifted — the scorer ended up ranking symbols on a strategy that was no longer the one being traded. A change to `evaluate_bar` now changes all three at once.

The engine deliberately owns no positions, orders, stop-losses or persistence; those belong to the callers.

## Features

**Signal engine.** Eleven signals: Bollinger Bands, Ornstein-Uhlenbeck, VWAP deviation, volume spike, Kalman z-score, RSI, EMA cross, MACD zero-cross, z-score, opening-range breakout, and a session time filter. Some are stateful — Kalman, VWAP and ORB carry session state and reset on date rollover. The engine handles warmup, the time gate and vote counting.

The strategy currently live (`strategies/vote_mr.py`) is BB + OU + VWAP + VolSpike + KalmanZ, threshold 2 votes, 2 % stop.

**Live bot.** Streams Alpaca 1-minute bars; backfills 7 days of history at startup so indicators are warm from the first bar; restores open positions after a restart; hot-reloads `config.json` without restarting; sizes positions by conviction (5–20 % of capital, scaled by how strongly the signals agree); caps open positions at 10; enforces a 2 % stop-loss. Bars, per-bar vote snapshots and trades persist to PostgreSQL.

**Weekly scorer.** Simulates each of the 30 candidate symbols over a 30-day lookback through the shared engine, ranks by Sharpe with fees and slippage charged per side, and writes the top-5 into `config.json` — which the bot picks up within ~30 s.

**Backtesting, two speeds.** The vectorized scripts (vectorbt) explore parameter grids, top-X portfolios and out-of-sample selection fast. The event-driven backtest is slower but has zero live/backtest divergence by construction, and is the final gate before a strategy goes live.

**Web dashboard.** A Live view (open positions, bot decision journal), a History view (equity curve, closed trades), portfolio analysis charts, a strategy switcher, and a Configuration tab that edits `config.json` from the browser — the bot hot-reloads it. Falls back to generated demo data when no database or Alpaca key is configured, so the UI is never empty.

**Deployment.** The full stack runs in containers: PostgreSQL with nightly backups, the bot, the dashboard behind nginx (TLS + basic auth), and a scheduler. One script bootstraps a fresh VPS.

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.13, `uv` for dependencies and locking |
| Broker / market data | Alpaca (`alpaca-py`) — 1-min bars, paper trading |
| Research data | Twelve Data — 5-min CSVs, 3 years |
| Storage | PostgreSQL 16 via `psycopg` 3 |
| Research | vectorbt, pandas, numpy; XGBoost on one experimental branch |
| Web API | Flask, served by gunicorn |
| Frontend | React 18 + TypeScript, built with Vite |
| Research dashboard | Streamlit (separate from the React one) |
| Container stack | Docker Compose — Postgres, bot, web, nginx, ofelia |

Note the two resolutions: research runs on **5-minute** Twelve Data bars, live runs on **1-minute** Alpaca bars. The merge unified the code, not the data — hence the two annualisation factors in `core/constants.py`.

### What ofelia is

[ofelia](https://github.com/mcuadros/ofelia) is a lightweight job scheduler for Docker — a cron replacement that lives inside the stack instead of on the host. Rather than running its own copy of the code, it reads **labels off the other containers** and fires commands via `docker exec` into the already-running ones. Two jobs are declared in `docker-compose.yml`:

- `ofelia.job-exec.scorer` on the `bot` container — `python -m live.scorer`, Sundays 18:00
- `ofelia.job-exec.backup` on the `db` container — `pg_dump | gzip`, nightly at 02:00, with 30-day retention

The payoff is that scheduling ships with the repo. There is no host crontab and no systemd unit to keep in sync, the jobs run in the same image and environment as the services they belong to, and `docker compose up` on a fresh VPS brings the schedule with it. The tradeoff is that ofelia needs the Docker socket mounted (read-only here), and a job that fails is visible only in the scheduler's logs — nothing alerts.

## Structure

Everything lives under `src/`; the repo root holds the shared venv, the container stack and dependency management.

```
src/
├── core/         # shared by everything — the single implementation
│   ├── signals.py    #   11 stateful indicators (source of truth)
│   ├── engine.py     #   evaluate_bar: warmup, time gate, vote count
│   ├── broker.py     #   Alpaca clients + historical fetch
│   ├── db.py         #   PostgreSQL connection + schema
│   ├── config.py     #   every hyperparameter (DEFAULT_CONFIG)
│   ├── constants.py  #   paths, 30-symbol universe, annualisation
│   ├── metrics.py    #   sharpe, drawdown, return, trade count
│   └── simulation.py #   per-bar replay shared by backtest and scorer
├── strategies/   # one file = one strategy (a config, not code)
├── live/         # bot.py (stream, orders, stop-loss) + scorer.py
├── backtest/     # event_driven.py (parity) + vectorized/ (speed) + dashboard.py
├── web/          # Flask JSON API + React front
├── tools/        # history download, fake-data seeding
├── config/       # config.json (runtime, gitignored) + versioned example
├── data/         # 5-min CSVs (gitignored)
├── results/      # backtest outputs (gitignored)
├── deploy/       # Docker assets + VPS setup script
├── docs/         # signals guide
└── archive/      # superseded files, kept for verification
```

Two details that surprise people reading the code for the first time:

- **`config/config.json` is the runtime source of truth**, not the strategy file. `live.py` seeds it from the strategy on first run; after that the file wins, and three different writers touch it (the scorer, the dashboard, and you).
- **`indicators.timestamp` is the evaluation time, not the bar close time.** It differs from `bars.timestamp` by design, so joining the two tables on timestamp silently returns nothing.
