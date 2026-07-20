---
name: add-signal
description: >
  Walk the complete registration checklist for adding a new signal type to the vote engine, so no wiring site is silently missed. Use this skill whenever you add — or help add — a new `sig_*` signal to the trading strategy: it names every place a signal must be registered across `core/signals.py`, `core/engine.py`, `core/config.py` and the web editor (a signal wired in one place but forgotten in another has already shipped as a bug here), then gives the `py_compile` → `backtest.py` smoke-test recipe. Load it before writing the signal, not after.
---

# add-signal

Adding a signal is a lockstep edit across four files, not a one-file change. Miss a site and the failure is silent: the signal computes but never votes, or votes but can't be tuned from the dashboard. The `EDITABLE` gap in `TODO.md` is exactly this class of bug — parameters wired into the engine but missed in the web editor.

Two facts frame every step:

- **`core/signals.py` + `core/engine.py` are the single per-bar implementation** shared by the live bot, the weekly scorer, and the event-driven backtest. Editing them changes all three at once — that is the design, not a hazard. Validate through the backtest (below), which exercises the same path.
- **Run every command from `src/`**, never the repo root (imports resolve `core/`, `live/`, `web/` as top-level packages).

## First decide: stateless or stateful

- **Stateless** (BB, EMA_Cross, MACD_Zero, Zscore, RSI, VolSpike, OU) — a pure function of `closes`/`vols` + params returning `(buy: bool, sell: bool)`. Wired in **one** place: Step 5 of `evaluate_bar`.
- **Stateful** (KalmanZ, VWAP, ORB) — also carries per-asset/per-session state between bars. It returns `(buy, sell, *updated_state)` and needs three extra sites: fields on `SignalState`, a reset in `start_bar`, and a Step 1 update block in `evaluate_bar`. `TimeFilter` is a special case — a gate, not a vote.

Pick two identifiers up front and keep them consistent everywhere:

- the **signal name**, e.g. `"MACD_Zero"` — used in `active_signals`, the `if "<Name>" in active` checks, `warmup_needed`, and the web `ALL_SIGNALS`.
- the **config prefix**, e.g. `macd_` — used for every parameter key in `DEFAULT_CONFIG` and `EDITABLE`.

## Registration checklist

### `core/signals.py`

1. **Implement `sig_<name>(...)`.** Pure, no side effects, oldest-first lists, returns `tuple[bool, bool]`. Follow an existing signal of the same shape (`sig_bb` for stateless, `sig_vwap`/`sig_orb`/`sig_kalman_zscore` for stateful — those return updated state alongside the `(buy, sell)` pair). English docstring, `≤80` cols, per `.claude/rules/code-style.md`.
2. **`warmup_needed`** (only if the signal needs a rolling window). Add one line so it gates votes until enough history exists:
   ```python
   if "<Name>" in active: reqs.append(int(cfg["<prefix>_window"]) + 1)
   ```
   Session-based signals (Kalman/VWAP/ORB/TimeFilter) have no fixed-window warmup — skip this.

### `core/engine.py`

3. **Import.** Add `sig_<name>` to the `from core.signals import (...)` block, keeping it alphabetically sorted (the block already is).
4. **Vote wiring — Step 5 of `evaluate_bar`.** Append the vote when active:
   ```python
   if "<Name>" in active:
       raw.append(sig_<name>(closes, int(cfg["<prefix>_period"]), ...))
   ```
5. **Stateful only — three more edits:**
   - Add the state fields to `class SignalState.__init__` and document them under the class docstring's `Attributes:` (attributes are documented on the class, not in `__init__`).
   - Reset them on session rollover in `SignalState.start_bar` (the branch that zeroes VWAP/ORB state when the date changes).
   - Add a **Step 1** block in `evaluate_bar` that runs *before* the warmup check (so state never lags), updates the state on `state.<field>`, and captures the `(buy, sell)` tuple. In Step 5, append that captured tuple instead of calling `sig_<name>` again.

### `core/config.py`

6. **`DEFAULT_CONFIG`.** Add the signal's parameters under a comment header matching the existing style:
   ```python
   # <Human name>  (signal: "<Name>")
   "<prefix>_period": 200,
   "<prefix>_threshold": 2.0,
   ```
   Leave `<Name>` **out** of the default `active_signals` list unless the signal should trade by default — new signals are normally opt-in, enabled per-strategy or from the dashboard.

### `web/server/strategies.py`

7. **`ALL_SIGNALS`.** Add `"<Name>"` so the toggle appears in the dashboard.
8. **`EDITABLE`.** Add every tunable parameter with its coercion type — this is the step that has been missed before:
   ```python
   "<prefix>_period": int, "<prefix>_threshold": float,
   ```

## Verification (from `src/`)

No test suite or linter exists; the smoke test is the gate.

```bash
python -m py_compile core/signals.py core/engine.py core/config.py web/server/strategies.py
python -c "import core.engine, core.signals, core.config"
python backtest.py vote_mr --symbols AAPL      # runs the shared path end-to-end
```

`python backtest.py` is the divergence-free end-to-end check — the only place the engine is validated without approximation. To actually exercise the new signal, run a strategy (or a throwaway config) whose `active_signals` includes `"<Name>"`, and confirm it contributes votes rather than sitting idle.

## Don't forget

- **The vectorized replica** `backtest/vectorized/strategies_vbt.py` re-implements the signals for speed and is **not** parity-validated. Updating it there is optional and never the source of truth — mirror the signal there only if you use the vectorized research scripts, and trust `backtest.py` over it.
- **Language split** (`.claude/rules/language.md`): the `sig_*` code, comments, docstrings and any `logger` calls are **English**; only user-facing strings (a strategy's `description`, dashboard labels) are French.
- **Blast radius.** Because Step 4 touches the shared engine, a mistake affects live trading, the scorer's rankings, and every backtest simultaneously. If the change alters vote semantics for existing strategies (not just adds an opt-in signal), it is a breaking change — flag it.
