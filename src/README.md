# src — bot code

Unified project: research, backtesting and live execution share the same signal engine. A strategy is written **once** and runs identically in backtest and in live.

This file describes the **workflow** (create → backtest → go live). For the overview, the technical stack and the architecture, see the [root README](../README.md); for operations, see [deploy/README.md](deploy/README.md).

## Structure

```
src/
├── strategies/        # one strategy = one file (vote engine config)
├── core/              # shared code: signals, engine, broker, config, metrics
├── backtest/          # event-driven engine + vectorbt scripts (fast research)
├── live/              # Alpaca bot, weekly scorer
├── web/               # real-time dashboard (Flask API + React front)
├── tools/             # history download, fake data
├── config/            # config.json (runtime, gitignored) + versioned example
├── data/              # 5-min 3-year CSVs per symbol (gitignored)
├── results/           # backtest outputs (gitignored)
└── deploy/            # Docker Compose: nginx + scheduler + VPS setup
```

The signals guide lives at the repo root in [`../docs/GUIDE_SIGNAUX_METHODES.md`](../docs/GUIDE_SIGNAUX_METHODES.md), and superseded files in `../archive/`.

All commands run **from `src/`** with the repo venv activated (`..\.venv\Scripts\activate.ps1`).

## Workflow: create → backtest → go live

### 1. Create a strategy

Copy [strategies/vote_mr.py](strategies/vote_mr.py) under a new name (e.g. `strategies/ma_strat.py`) and override the keys you want:

```python
from core.config import DEFAULT_CONFIG
from strategies import Strategy

STRATEGY = Strategy(
    name="ma_strat",
    description="BB + OU only, threshold 2 votes",
    config={
        **DEFAULT_CONFIG,
        "active_signals": ["BB", "OU"],
        "vote_threshold": 2,
    },
)
```

The available signals (BB, OU, VWAP, VolSpike, KalmanZ, RSI, EMA_Cross, MACD_Zero, Zscore, ORB, TimeFilter) and their parameters are documented in `core/config.py` and the repo-root `docs/`. A new signal *type* is added in `core/signals.py` + `core/engine.py`.

### 2. Backtest

```bash
python backtest.py ma_strat                     # all CSVs in data/
python backtest.py ma_strat --symbols AAPL NVDA # subset
```

The event-driven backtest replays history bar by bar via `core/engine.py` — the exact code of the live bot — and writes `results/event_ma_strat.csv` (Sharpe, return, drawdown, trades per symbol). If data is missing: `python -m tools.download_history` (`TWELVE_DATA_API_KEY` key in `.env`).

For fast exploration (parameter grids, top-X portfolios), the vectorized scripts remain available:

```bash
python -m backtest.vectorized.backtest_multi
python -m backtest.vectorized.optimize
streamlit run backtest/dashboard.py     # results visualization
```

They vectorize the signal maths for speed; the final validation always goes through `backtest.py` (zero divergence possible).

### 3. Go live

```bash
python live.py ma_strat
```

- `config/config.json` absent → created from the strategy;
- present → strategy/config divergences are reported (the file wins: the bot hot-reloads it, the scorer writes the symbols into it every week).

Alpaca keys in `.env` at the repo root (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`). The bot is in paper trading (`PAPER = True` in `core/broker.py`).

Monitoring: real-time web dashboard, logs in `bot.log`.

### Web dashboard (live/monitoring)

New front (replaces the old Streamlit dashboard): Flask JSON API
+ React interface reusing the AlgoDesk design. It reads the PostgreSQL database + the Alpaca account and automatically switches to demonstration mode (fake data) as long as no real source is available.

```bash
# 1. Build the front once (or after a front change)
cd web/frontend && npm install && npm run build && cd ../..

# 2. Start the server (serves the front + the API on the same port)
python -m web.run                 # http://127.0.0.1:8501

# Front development with hot-reload (proxies /api to Flask):
#   terminal A: python -m web.run
#   terminal B: cd web/frontend && npm run dev   # http://127.0.0.1:5173
```

The **Configuration** tab edits `config/config.json` (signals, thresholds, sizing, symbols) directly from the browser — the bot hot-reloads it.

## Weekly scorer

```bash
python -m live.scorer --dry-run   # ranking preview
python -m live.scorer             # writes the top-X into config.json
```

Scheduling: the `scheduler` service (ofelia) of the Docker stack runs the scorer every Sunday at 18:00 — see [deploy/README.md](deploy/README.md).

## Deployment (Docker Compose)

The whole stack (PostgreSQL, bot, dashboard, nginx, scheduler) is containerized. Quick start from the repo root:

```bash
cp .env.example .env                          # Alpaca keys + passwords
bash src/deploy/docker/init_secrets.sh   # certs + basic auth
docker compose up -d --build
```

On a fresh VPS: `sudo bash src/deploy/scripts/setup_vps.sh` (installs Docker then starts everything) — see [deploy/README.md](deploy/README.md).
