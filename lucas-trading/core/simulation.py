"""
Per-bar strategy simulation on historical bars.
================================================
Moved verbatim from ``scorer.simulate`` so the weekly scorer and the
event-driven backtest (``backtest/event_driven.py``) share one
implementation.  Runs ``core.engine.evaluate_bar`` — the *same* code
path the live bot executes.
"""

from core.engine import SignalState, evaluate_bar


def simulate(bars: list[dict], cfg: dict) -> list[float]:
    """Simulate the vote strategy on historical bars and return per-bar returns.

    Runs ``engine.evaluate_bar()`` — the *same* code path the live bot
    executes — bar by bar, and layers the simulation-specific parts on
    top:

    - Returns are computed from position held going *into* each bar
      (entry and exit happen at the bar's closing price).
    - Stop-loss exits at the bar close; like the live bot, no re-entry
      can happen on the same bar.
    - Transaction costs (``scorer_fee_pct`` + ``scorer_slippage_pct``)
      are deducted from the return of every bar on which an entry or
      exit occurs — one cost per side.  Without them the ranking is
      biased toward high-turnover symbols.

    Args:
        bars (list[dict]): Chronologically ordered bar dicts as
            returned by ``core.broker.fetch_bars`` or
            ``core.data.load_bars_csv``.
        cfg  (dict): Merged configuration dict.

    Returns:
        list[float]: Per-bar strategy return series.  Zero when flat,
            ``close[t] / close[t-1] - 1`` when holding, minus costs on
            transaction bars.  Same length as ``bars``.
    """
    # Cost charged once per side (entry and exit each pay it once)
    cost_per_side: float = (
        float(cfg.get("scorer_fee_pct", 0.0))
        + float(cfg.get("scorer_slippage_pct", 0.0))
    )

    state = SignalState()

    in_position:       bool         = False
    entry_price:       float | None = None
    position_was_open: bool         = False  # held going into current bar
    prev_close:        float | None = None

    returns: list[float] = []

    for bar in bars:
        close = float(bar["close"])

        state.start_bar(bar["timestamp"][:10])
        state.append_bar(
            close,
            float(bar["high"]),
            float(bar["low"]),
            float(bar["volume"]),
        )
        result = evaluate_bar(state, cfg)

        # ── Bar return: based on whether we held going INTO this bar ──────────
        if position_was_open and prev_close is not None:
            returns.append(close / prev_close - 1.0)
        else:
            returns.append(0.0)

        # ── Stop-loss check (mirrors bot.py: no same-bar re-entry) ────────────
        stopped_out = False
        if in_position and entry_price is not None:
            drop = (entry_price - close) / entry_price
            if drop >= cfg["stop_loss_pct"]:
                in_position = False
                entry_price = None
                stopped_out = True
                returns[-1] -= cost_per_side

        # ── Apply votes ───────────────────────────────────────────────────────
        if (
            not stopped_out
            and result.warmed_up
            and result.in_window
            and result.n_signals
        ):
            if result.buy and not in_position:
                in_position = True
                entry_price = close
                returns[-1] -= cost_per_side
            elif result.sell and in_position:
                in_position = False
                entry_price = None
                returns[-1] -= cost_per_side

        position_was_open = in_position
        prev_close        = close

    return returns
