---
paths:
  - "**/*.{py,pyi,pyw,ipynb,ts,tsx}"
  - "*.{py,pyi,pyw,ipynb,ts,tsx}"
---

# Project architecture

The reference map of the codebase: folder layout, the stack, the runtime topology, and the design patterns that hold it together. `CLAUDE.md` is the operating manual (commands, gotchas, the invariants you must not break); this file is the "where things live and why the structure is shaped this way" companion. When the two overlap, `CLAUDE.md` is authoritative on rules and this file is authoritative on the map.

## Languages and tooling

| Layer | Choice | Notes |
|---|---|---|
| Backend language | Python 3.13, `uv` for deps and locking | Commands run **from `src/`** so `core/`, `live/`, `web/`, `strategies/` resolve as top-level packages. Add deps with `uv add`, never `pip install`. |
| Broker / live data | Alpaca (`alpaca-py`) | 1-minute bars, paper trading (`PAPER = True` in `core/broker.py`). |
| Research data | Twelve Data | 5-minute CSVs, ~3 years, pulled by `tools/download_history.py`. |
| Storage | PostgreSQL 16 via `psycopg` 3 | Connection from `DATABASE_URL`; schema in `core/db.py`. |
| Research / backtest | vectorbt, pandas, numpy; XGBoost on one experimental script | Vectorized path is fast and approximate; event-driven path is the gate. |
| Web API | Flask, served by gunicorn | `web/server/`, JSON API + built SPA on one port. |
| Frontend | React 18 + TypeScript 5, built with Vite 5 | `web/frontend/`, package `tradingbot-dashboard`. |
| Research dashboard | Streamlit | `backtest/dashboard.py`, separate from the React one. |
| Containers | Docker Compose | Postgres, bot, web, nginx (TLS + basic auth), ofelia scheduler. |
| Commit governance | commitizen `commit-msg` hook via pre-commit; release-please | Message linting only — no test suite, no code linter. See `commits.md`. |

Two data resolutions coexist: **research is 5-minute** Twelve Data bars, **live is 1-minute** Alpaca bars. The refactor unified the code, not the data, so `core/constants.py` carries a separate annualisation factor for each — crossing them makes Sharpe wrong.

## Repository layout

Application code lives under `src/`. The repo root holds the shared venv (`.venv/`), the container stack, dependency manifests, the hand-maintained logs (`TODO.md` / `DONE.md`), and the `docs/` and `archive/` trees.

```
TradingBot/
├── src/
│   ├── core/            # shared by every caller — the single implementation
│   │   ├── signals.py       #   11 sig_* indicators + vote() + warmup_needed() (source of truth)
│   │   ├── engine.py        #   SignalState + evaluate_bar: warmup, time gate, vote count
│   │   ├── simulation.py    #   per-bar replay shared by backtest and scorer
│   │   ├── broker.py        #   Alpaca clients, crypto/stock routing, historical fetch
│   │   ├── db.py            #   PostgreSQL connection + schema (bars, indicators, trades)
│   │   ├── config.py        #   DEFAULT_CONFIG + SCORER_DEFAULTS + load/merge/write
│   │   ├── constants.py     #   paths, 30-symbol universe, annualisation factors
│   │   ├── data.py          #   CSV bar loading for backtests
│   │   └── metrics.py       #   sharpe, drawdown, return, trade count
│   ├── strategies/      # one file = one strategy (a frozen config, not code)
│   │   └── vote_mr.py       #   the live strategy: BB + OU + VWAP + VolSpike + KalmanZ
│   ├── live/            # bot.py (stream, orders, stop-loss, hot-reload) + scorer.py (weekly rank)
│   ├── backtest/
│   │   ├── event_driven.py  #   parity backtest — same code path as live
│   │   ├── dashboard.py     #   Streamlit research UI
│   │   └── vectorized/      #   vectorbt scripts (fast, approximate — may drift)
│   ├── web/
│   │   ├── server/          #   Flask JSON API (app.py) + assemble/data/demo/agents/…
│   │   ├── frontend/        #   React + TS + Vite SPA
│   │   └── run.py           #   dev entrypoint
│   ├── tools/           # download_history.py, seed_fake_data.py
│   ├── config/          # config.json (runtime, gitignored) + config.example.json
│   ├── data/            # 5-min CSVs (gitignored)
│   ├── results/         # backtest outputs (gitignored)
│   ├── deploy/          # Docker assets (nginx.conf, init_secrets.sh) + setup_vps.sh
│   ├── backtest.py      # CLI entrypoint: python backtest.py <strategy>
│   └── live.py          # CLI entrypoint: python live.py <strategy>
├── docs/
│   ├── GUIDE_SIGNAUX_METHODES.md     # signals reference (French — end-user domain doc)
│   ├── .architecture-design/         # design drafts (only README.md tracked; drafts gitignored)
│   └── .security-reports/            # security-analyst output (only README.md tracked)
├── archive/            # superseded files kept for verification — frozen, French, not live code
├── .claude/            # rules/, agents/, skills/, settings.json (permissions), launch.json
├── Dockerfile          # WORKDIR /app/src — mirrors the "run from src/" rule
├── docker-compose.yml  # db, bot, web, nginx, scheduler
└── pyproject.toml      # deps + commitizen config; version owned by release-please
```

## Runtime topology

The Docker stack (`docker-compose.yml`) is five services sharing one image (`tradingbot-app`, built once) for the Python ones:

- **db** — `postgres:16-alpine`, the only stateful service; volumes `pgdata` and `backups`, the only service with a healthcheck.
- **bot** — `python -m live.bot`; streams Alpaca, writes bars/indicators/trades every minute. Mounts `./src/config` (to read `config.json`) and the shared `logs` volume.
- **web** — gunicorn serving `web.server.app:create_app()` on `:8501`; reads Postgres + Alpaca, mounts the same config and logs.
- **nginx** — TLS termination + basic auth in front of `web`, ports 80/443.
- **scheduler** — ofelia; runs no code of its own, fires commands by `docker exec` into the running containers, driven by labels: the weekly scorer (Sundays 18:00, on `bot`) and the nightly `pg_dump` backup (02:00, on `db`, 30-day retention).

The `logs` volume is shared writer→reader: the bot writes `bot.log`, the dashboard reads it to surface recent errors (`core/constants.py:LOG_FILE`).

## Design patterns

**One strategy, two engines — the load-bearing pattern.** `core/signals.py` + `core/engine.py` are the single implementation of the per-bar logic, and three callers share it: `live/bot.py` (live orders), `live/scorer.py` (weekly ranking), and `backtest/event_driven.py` → `core/simulation.py` (historical replay). Before the refactor these were three hand-maintained copies that silently drifted, so the scorer ranked symbols on a strategy no longer being traded. A change to `evaluate_bar` intentionally changes all three at once — that is the design, not a hazard. Touch anything under `core/` with this in mind.

**Dependency inversion at the core boundary.** `core/engine.py` deliberately owns **no** position tracking, order placement, stop-loss execution, or persistence. Those are the callers' job (`bot.AssetState` extends `SignalState` with position fields; `simulation.simulate` layers P&L and costs on top). The engine returns a pure `VoteResult`; side effects live outward. Keep it that way.

**A strategy is configuration, not code.** A strategy is a named, frozen dict of engine parameters (`strategies/vote_mr.py` exports `STRATEGY`). Adding a strategy is copying that file and overriding keys over `DEFAULT_CONFIG` — no new code. Adding a *signal type* is the code change: a `sig_*` in `core/signals.py` wired into `evaluate_bar` (and `warmup_needed`, and stateful signals also need `SignalState` fields + reset in `start_bar`). The `add-signal` skill enumerates every wiring site.

**Config is the runtime source of truth.** `config/config.json` (gitignored) outranks the strategy file once it exists. `live.py <name>` seeds it from the strategy if absent, otherwise only reports divergences and the file wins. Three writers touch that one file — the bot hot-reloads it (~30 s, `CryptoBot._reload_config`), the scorer rewrites its `symbols` key every Sunday, and the dashboard's Configuration tab writes it over HTTP. Editing a strategy file therefore does not change a running bot.

**Single source of truth for shared constants.** `core/constants.py` owns filesystem paths, the 30-symbol `SYMBOLS` universe, and the annualisation factors; `core/config.py` owns every hyperparameter. Import from there rather than copy-pasting — the refactor existed to kill exactly the copies that drifted.

**Fail-fast on missing credentials.** `core/broker.py` raises `RuntimeError` at **import** if `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` are absent, so anything importing `live.bot` or `live.scorer` needs a populated `.env`. The backtest path and `web/` avoid this by not importing it — the web layer talks to Alpaca over raw `requests` (`web/server/data.py`) instead of `alpaca-py`.

**A designated authority when there are two implementations.** `backtest/vectorized/strategies_vbt.py` re-implements the signals in vectorbt for speed; parity with `core/signals.py` was never re-validated and can drift. The rule: vectorized for exploration, `python backtest.py <name>` (event-driven, divergence-free by construction) as the final gate.

**Demo-fallback web layer.** `web/server/app.py` serves real data when Postgres or Alpaca is configured (`use_real_data()`), and generated demo data otherwise, so the UI is never blank. Each route branches on that check.

## Data model

PostgreSQL, three tables (`core/db.py`), all timestamps ISO-8601 **`TEXT`** (deliberate SQLite carry-over — lexicographic order matches chronological, so `ORDER BY timestamp` and `fromisoformat` keep working):

- **bars** — raw immutable OHLCV, one row per closed 1-min candle per symbol. PK `(symbol, timestamp)`.
- **indicators** — per-bar vote snapshot. PK `(symbol, timestamp)`, but **`timestamp` is the evaluation time, not the bar close time** — it intentionally differs from `bars.timestamp`, there is deliberately no foreign key, and joining the two on timestamp silently returns zero rows.
- **trades** — one row per accepted Alpaca order, keyed on a synthetic `id`, with realised `pnl_pct` on exits.

## Data and control flow

- **Research / backtest:** CSV bars (`core/data.py`) → `core/simulation.py` or `backtest/event_driven.py` → `core/engine.evaluate_bar` → `core/metrics.py` → `results/`. Vectorized scripts bypass the engine for speed.
- **Live:** Alpaca 1-min stream → `live/bot.py` (backfills 7 days at startup so windows are warm) → `core/engine.evaluate_bar` → order placement + stop-loss in the bot → Postgres (`bars`, `indicators`, `trades`).
- **Weekly ranking:** `live/scorer.py` simulates each candidate over a 30-day lookback through `core/simulation.py` (the same engine), ranks by Sharpe with per-side fees/slippage, and writes the top-X `symbols` into `config.json`, which the bot picks up within ~30 s.
- **Monitoring:** the React dashboard reads Postgres + the Alpaca account through the Flask API; the Configuration tab writes back to `config.json`.

## Conventions and governance

Machine-facing text is **English**, end-user-facing text (CLI output, dashboard strings, domain docs) is **French** — `language.md` draws the line. Prose is never hard-wrapped (`prose.md`); Python follows PEP 8 + Google style, 80 cols, `X | None`, built-in generics (`code-style.md`, enforced by review only). Commits are Conventional Commits with a fixed scope list (`commits.md`); branches are created with `gh issue develop` (`github.md`). Claude asks before committing or branching and never pushes; `.claude/settings.json` enforces this through the permission system.

`.claude/agents/` holds four subagents: the `security-analyst` → `security-fixer` review pipeline (gated on user approval, adjudicated by the main thread) and the `software-architect` → `nemesis` design loop for expensive-to-reverse decisions. `.claude/skills/` holds `add-signal`, `db-analyze`, and `security-checklist`.
