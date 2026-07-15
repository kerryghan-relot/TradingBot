# ToDo

This file list all features, ideas, point of improvement that could be added to the project. This file may be written both by the user and claude code.
Once a bullet point has been worked on, it must be moved into @DONE.md

- [ ] add architect agent
- [ ] add 2FA (with topt code)

## Correctness / risk

- [ ] **No test suite at all.** The signal maths and the vote engine are pure functions —
      the most testable code in the repo, and the code that decides trades. `REFACTOR_PLAN.md`
      §5 explicitly leaves "parité signals stateful ↔ vectorisés" un-revalidated, i.e. an
      unverified correctness claim in a system that places orders. Golden-file tests replaying
      one CSV through `core.simulation.simulate` would lock in behaviour cheaply.
- [ ] **Crypto CSVs carry no volume**, so VolSpike and VWAP never vote on BTC/ETH in research
      (documented in `backtest_scorer_oos.py`). The live strategy is BB+OU+VWAP+VolSpike+
      KalmanZ — meaning 2 of its 5 signals are silently dead on crypto in every backtest.
      Either source volume, or exclude crypto from the vote-strategy research.
- [ ] **`/api/config` has no demo path.** GET and POST always read/write the real
      `config/config.json` even when the dashboard is serving demo data, and the frontend does
      not disable saving on the `demo` flag. A "demo" UI can silently reconfigure a live bot.
- [ ] **Config editor gaps.** `macd_fast`/`macd_slow`, `kalman_q`/`kalman_r`/`kalman_roll_win`,
      `orb_bars` and `time_skip` are absent from `web/server/strategies.py:EDITABLE`, yet
      MACD_Zero, KalmanZ and ORB are all toggleable as chips. A user can enable a signal from
      the browser but cannot tune it — and `warmup_needed` reads `macd_slow`.
- [ ] **No healthcheck on `bot` / `web`** (only `db` has one). `restart: always` catches a
      crash, but not a hung websocket that stays open while no bars arrive — the exact failure
      a trading bot must notice. A liveness probe on "last bar written < N minutes ago" would
      close this.

## Duplication creeping back

- [ ] **`web/server/data.py` re-implements Alpaca access** with raw `requests` against
      `ALPACA_PAPER_URL`, and defines its own `is_crypto`, instead of using `core/broker.py`.
      This is exactly the duplication `REFACTOR_PLAN.md` §2.3 set out to kill.
- [ ] **`backtest/vectorized/optimize.py` locally re-implements** `sig_bb`, `sig_ema_cross`,
      `sig_macd_zero` and `sig_zscore` — it does not even import `strategies_vbt`. That is a
      *fourth* copy of the signal maths.
- [ ] **`core/broker.py` raises at import** when Alpaca keys are missing, so `live.bot` and
      `live.scorer` cannot be imported (or tested, or type-checked in CI) without secrets.
      Moving the check into a `make_*` factory would make the module importable.

## Database

- [ ] **Redundant indexes.** `idx_bars_symbol_ts` and `idx_indicators_symbol_ts` are on
      `(symbol, timestamp)` — already the PRIMARY KEY of both tables, for which PostgreSQL
      creates a unique btree index automatically. They cost write throughput and disk and buy
      nothing. (`idx_trades_symbol_ts` is legitimate: `trades` is keyed on `id`.)
- [ ] **Timestamps are `TEXT`, not `TIMESTAMPTZ`.** A deliberate SQLite carry-over, but now
      that the store is PostgreSQL it forfeits time-zone semantics, `date_trunc`/time bucketing,
      range partitioning, and compact index storage. At ~30 symbols × 1440 bars/day (~15 M
      rows/year) this will start to matter.
- [ ] **No migration tooling.** `init_schema()` is `CREATE TABLE IF NOT EXISTS`, which handles
      greenfield but not a column change — any schema evolution is a manual `ALTER`.

## Dependencies / build

- [ ] **The bot image ships the whole research stack.** `streamlit`, `dash`, `plotly`,
      `vectorbt`, `xgboost`, `ipykernel`, `ipywidgets` and `anywidget` are all in the main
      `dependencies`, so they install into the container that only needs `alpaca-py`, `psycopg`
      and `dotenv`. Moving them to a `[dependency-groups] research` extra would cut image size
      and build time substantially. (`requests` is also listed twice.)
- [ ] **`pre-commit` and `commitizen` are dev deps with no config** — no
      `.pre-commit-config.yaml`, no commitizen section. Dead configuration. Pairs naturally
      with the "commit conventions" TODO above.
- [ ] **No linter enforces `.claude/rules/code-style.md`.** The rules are detailed (80 cols,
      PEP 8 + Google, `X | None`, built-in generics) and entirely review-enforced. `ruff` can
      check nearly all of it mechanically.
- [ ] **Two dashboards remain unfused** (Streamlit for research, React for live) — explicitly
      deferred as out of scope by `REFACTOR_PLAN.md` §6.3, still open.

## Ergonomics / docs drift

- [ ] **Vectorized scripts have no `main()` / `if __name__` guard** — importing one runs it.
      This makes them un-importable and un-testable.
- [ ] **`backtest_topx_portfolio.py` requires editing the file** to change `STRATEGY_NAME`;
      `backtest_v2_topx.py` hard-codes its winning params. Neither takes a flag.
- [ ] **`strategies_ml.py` is XGBoost but is labelled "RandomForest"** in the `--ml` help text
      and in the Streamlit page name.
- [ ] **Stale copy referencing the old SQLite store**: the dashboard's demo banner says
      "aucune base `bars.db` ni clé Alpaca détectée" when the check is actually PostgreSQL;
      `backtest/dashboard.py`'s docstring lists 5 pages but `PAGES` has 9, and its error
      messages suggest `python backtest_multi.py` rather than the real module path.
- [ ] **Benchmarks only exist in demo mode.** `assemble.history()` always returns `bench: None`,
      so the S&P/Nasdaq/MSCI selector is inert against real data.
- [ ] **`active_strategy_id()` is a heuristic** — it picks whichever strategy shares the most
      values with `config.json`, so a hand-edited config can report a strategy never selected.
- [ ] **Self-signed TLS + shared basic-auth** on the dashboard, which can write `config.json`
      remotely (already flagged in `deploy/README.md`). The 2FA TODO above is the mitigation.
