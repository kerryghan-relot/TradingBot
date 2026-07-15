# ToDo

This file list all features, ideas, point of improvement that could be added to the project. This file may be written both by the user and claude code.
Once a bullet point has been worked on, it must be moved into @DONE.md
Each individual point must be written in a concise manner. No more than 2 sentences. Longer description must not be needed, the description can eventually reference a GitHub issue to give the full context.

- [ ] add architect agent
- [ ] add 2FA (with topt code)

## Correctness / risk

- [ ] **No test suite.** The signal maths and vote engine are pure functions and they decide trades, yet `REFACTOR_PLAN.md` §5 leaves stateful ↔ vectorized parity unvalidated.
- [ ] **Crypto CSVs carry no volume**, so VolSpike and VWAP never vote on BTC/ETH in research (noted in `backtest_scorer_oos.py`). Two of the live strategy's five signals are therefore dead on crypto in every backtest.
- [ ] **`/api/config` has no demo path** — GET and POST always write the real `config.json`, even when the dashboard serves demo data. A demo UI can silently reconfigure a live bot.
- [ ] **Config editor gaps.** `macd_fast`/`macd_slow`, `kalman_q`/`kalman_r`/`kalman_roll_win`, `orb_bars` and `time_skip` are missing from `web/server/strategies.py:EDITABLE` although their signals are toggleable — enable from the browser, but no way to tune.
- [ ] **No healthcheck on `bot` / `web`** (only `db` has one). `restart: always` catches a crash but not a hung websocket that stays open while no bars arrive.

## Duplication creeping back

- [ ] **`web/server/data.py` re-implements Alpaca access** with raw `requests` and its own `is_crypto` instead of using `core/broker.py` — the duplication `REFACTOR_PLAN.md` §2.3 set out to kill.
- [ ] **`backtest/vectorized/optimize.py` re-implements** `sig_bb`, `sig_ema_cross`, `sig_macd_zero` and `sig_zscore` locally, without importing `strategies_vbt`. That is a fourth copy of the signal maths.
- [ ] **`core/broker.py` raises at import** when Alpaca keys are missing, so `live.bot` and `live.scorer` cannot be imported or tested without secrets. Moving the check into the `make_*` factories would fix it.

## Database

- [ ] **Redundant indexes.** `idx_bars_symbol_ts` and `idx_indicators_symbol_ts` duplicate the primary keys, for which PostgreSQL already builds a unique index (`idx_trades_symbol_ts` is legitimate — `trades` is keyed on `id`).
- [ ] **Timestamps are `TEXT`, not `TIMESTAMPTZ`** — a SQLite carry-over that forfeits time-zone semantics, time bucketing and range partitioning. At ~15 M rows/year it will start to matter.
- [ ] **No migration tooling.** `init_schema()` is `CREATE TABLE IF NOT EXISTS`, so any column change is a manual `ALTER`.

## Dependencies / build

- [ ] **The bot image ships the whole research stack** — `streamlit`, `dash`, `plotly`, `vectorbt`, `xgboost` and the Jupyter packages sit in main `dependencies`. Moving them to a `research` group would cut image size sharply (`requests` is also listed twice).
- [ ] **No linter enforces `.claude/rules/code-style.md`.** `ruff` could check nearly all of it mechanically (80 cols, PEP 8, `X | None`, built-in generics).
- [ ] **Two dashboards remain unfused** (Streamlit for research, React for live), deferred as out of scope by `REFACTOR_PLAN.md` §6.3.

## Ergonomics / docs drift

- [ ] **Vectorized scripts have no `main()` / `if __name__` guard**, so importing one runs it. That makes them un-importable and un-testable.
- [ ] **`backtest_topx_portfolio.py` needs a file edit** to change `STRATEGY_NAME`, and `backtest_v2_topx.py` hard-codes its winning params. Neither takes a flag.
- [ ] **`strategies_ml.py` is XGBoost but labelled "RandomForest"** in the `--ml` help text and the Streamlit page name.
- [ ] **Stale copy referencing the old SQLite store**: the demo banner claims "aucune base `bars.db`" when the check is actually PostgreSQL. `backtest/dashboard.py` also says 5 pages when `PAGES` has 9, and points at `python backtest_multi.py`.
- [ ] **Benchmarks only exist in demo mode** — `assemble.history()` always returns `bench: None`, so the S&P/Nasdaq/MSCI selector is inert on real data.
- [ ] **`active_strategy_id()` is a heuristic** that picks whichever strategy shares the most values with `config.json`. A hand-edited config can report a strategy never selected.
- [ ] **Self-signed TLS + shared basic-auth** on a dashboard that can write `config.json` remotely (flagged in `deploy/README.md`). The 2FA item above is the mitigation.
