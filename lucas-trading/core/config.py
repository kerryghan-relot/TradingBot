"""
Runtime configuration shared by the live bot and the scorer.
=============================================================
``DEFAULT_CONFIG`` holds every hyperparameter the bot understands;
``SCORER_DEFAULTS`` adds the scorer-specific keys.  Both programs read
the same ``config/config.json`` (hot-reloaded by the bot).

Before this module existed, ``scorer.py`` carried a hand-maintained
mirror of ``bot.py``'s defaults ("kept in sync with bot.py" comments
everywhere) — any drift silently changed what the scorer simulated.
"""

import json
import logging

from core.constants import CONFIG_FILE, SYMBOLS

_log: logging.Logger = logging.getLogger(__name__)


DEFAULT_CONFIG: dict = {
    # Traded symbols — sourced from constants.py (single source of truth).
    # Hot-reloaded: edits to config.json["symbols"] (e.g. by scorer.py)
    # are applied live — see CryptoBot._apply_symbols().
    # list() ensures DEFAULT_CONFIG holds its own copy so that nothing
    # can accidentally mutate the shared SYMBOLS constant.
    "symbols": list(SYMBOLS),

    # ── Capital & position sizing ─────────────────────────────────────
    # total_capital is the budget the bot manages itself: it never lets
    # the summed cost basis of open positions exceed this.  Set to match
    # the Alpaca paper account's default $100k starting balance so the
    # bot budget and the account equity line up.
    "total_capital": 100000.0,    # total budget in USD the bot deploys
    # sizing_mode:
    #   "confidence" → each BUY is sized between min_position_pct and
    #                  max_position_pct of total_capital, scaled by how
    #                  strongly the signals agree (vote conviction).
    #   "fixed"      → legacy behaviour (order_qty / order_dollar_value).
    "sizing_mode":       "confidence",
    "min_position_pct":  0.05,    # 5 % of capital at the vote threshold
    "max_position_pct":  0.20,    # 20 % of capital at full agreement

    # Legacy fixed-sizing knobs (used only when sizing_mode == "fixed",
    # and as the SELL fallback for positions with no recorded quantity).
    # Priority: order_qty (per-ticker) > order_dollar_value > order_qty_default
    "order_qty":          {"BTC": 0.001, "ETH": 0.01},
    "order_qty_default":  1,      # fallback qty for stocks (shares)
    "order_dollar_value": 500,    # target notional per trade in USD
                                  # (0 = disable, use order_qty_default)
    "stop_loss_pct":      0.02,   # 2 % drop from entry triggers exit
    "max_open_positions": 10,     # hard cap on simultaneous positions

    # ── Startup backfill ──────────────────────────────────────────────
    # On launch, fetch this many days of 1-min bars from Alpaca into
    # the bars table so the rolling windows preload fresh, continuous
    # history and the strategy can trade soundly from the first live
    # bar.  0 disables backfill (use only whatever is already stored).
    "backfill_days": 7,

    # Vote aggregation
    "vote_threshold":  2,
    "active_signals": ["BB", "OU", "VWAP", "VolSpike", "KalmanZ"],

    # Bollinger Band mean-reversion  (signal: "BB")
    "bb_period": 200,
    "bb_std":    2.5,

    # EMA crossover  (signal: "EMA_Cross")
    "ema_fast": 10,
    "ema_slow": 200,

    # MACD zero-cross  (signal: "MACD_Zero")
    "macd_fast": 26,
    "macd_slow": 78,

    # Z-score mean-reversion  (signal: "Zscore")
    "zscore_window":    200,
    "zscore_threshold": 2.0,

    # RSI extremes  (signal: "RSI")
    "rsi_period": 200,
    "rsi_buy":    25.0,
    "rsi_sell":   75.0,

    # Volume spike  (signal: "VolSpike")
    "vol_window": 20,
    "vol_factor": 2.0,

    # Ornstein-Uhlenbeck  (signal: "OU")
    "ou_window":    200,
    "ou_threshold": 2.0,

    # Kalman Z-score  (signal: "KalmanZ")
    "kalman_q":         1e-4,  # Process noise  (higher → more adaptive)
    "kalman_r":         0.1,   # Measurement noise
    "kalman_roll_win":  100,   # Rolling window for residual std
    "kalman_threshold": 2.0,

    # VWAP deviation  (signal: "VWAP")
    "vwap_threshold": 0.005,   # 0.5 % deviation from session VWAP

    # Opening Range Breakout  (signal: "ORB")
    "orb_bars": 6,             # First 6 bars define the opening range

    # Time filter gate  (signal: "TimeFilter")
    "session_length": 1440,    # Bars per session (1440 = 24 h at 1-min)
    "time_skip":      6,       # Skip first and last N bars of session
}


# Scorer-specific defaults merged into the bot config on load
SCORER_DEFAULTS: dict = {
    # Candidate pool — single source of truth in constants.py
    "scorer_candidates": SYMBOLS,
    # Number of top symbols to trade
    "scorer_top_x":         5,
    # Historical lookback window in days
    "scorer_lookback_days": 30,
    # Minimum Sharpe to be eligible; symbols below this floor are excluded
    # even if they rank in the top-X
    "scorer_min_sharpe":    -99.0,
    # Transaction costs, applied once per side (entry AND exit) in the
    # simulation.  fee: broker/exchange commission (0.0005 = 0.05 %,
    # matches the backtest FEES constant).  slippage: half-spread +
    # market impact estimate for market orders on 1-min bars.
    "scorer_fee_pct":       0.0005,
    "scorer_slippage_pct":  0.0005,
}


def load_config(
    defaults: dict | None = None,
    create_if_missing: bool = False,
    log: logging.Logger | None = None,
) -> dict | None:
    """Read ``config.json`` and merge it over ``defaults``.

    Any key present in ``defaults`` but missing from the file is filled
    in, ensuring forward compatibility when new parameters are added.

    Args:
        defaults (dict, optional): Base configuration the file overrides.
            Defaults to ``DEFAULT_CONFIG``.
        create_if_missing (bool, optional): Write ``defaults`` to disk
            when the file does not exist (bot behaviour).  Defaults to
            False.
        log (logging.Logger, optional): Logger for diagnostics.
            Defaults to this module's logger.

    Returns:
        dict | None: Merged configuration, or ``None`` on a JSON parse
            error (caller should retain the last valid config).
    """
    log = log or _log
    base = DEFAULT_CONFIG if defaults is None else defaults

    if not CONFIG_FILE.exists():
        if create_if_missing:
            CONFIG_FILE.parent.mkdir(exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(base, indent=4))
            log.info(f"📝 Created default config at {CONFIG_FILE}")
        return dict(base)
    try:
        return {**base, **json.loads(CONFIG_FILE.read_text())}
    except json.JSONDecodeError:
        log.warning("⚠️  config.json parse error — keeping previous values")
        return None


def write_symbols(new_symbols: list[str]) -> None:
    """Update only the ``symbols`` key in ``config.json`` in-place.

    Reads the existing file, replaces ``symbols``, and writes back.
    All other keys are preserved unchanged.

    Args:
        new_symbols (list[str]): New symbol list, e.g.
            ``["BTC/USD", "ETH/USD", "SOL/USD"]``.
    """
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        cfg = {}
    cfg["symbols"] = new_symbols
    CONFIG_FILE.parent.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=4))
