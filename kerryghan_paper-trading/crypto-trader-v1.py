"""
Multi-Asset Crypto Trading Bot — powered by alpaca-py
======================================================
Assets  : BTC/USD and ETH/USD (shared config, independent state)

Strategy: Regime-aware signal engine
─────────────────────────────────────────────────────────────────
  The bot classifies every 1-minute bar into one of two market
  regimes based on Bollinger Band width, then applies the
  strategy best suited to that regime:

  RANGING market  (BB width < bb_width_threshold)
    → Price oscillates within a band → trade mean reversals
    → BUY  signal : RSI < oversold   AND price ≤ lower BB  AND volume spike
    → SELL signal : RSI > overbought AND price ≥ upper BB  AND volume spike

  TRENDING market (BB width ≥ bb_width_threshold)
    → Price is breaking out → ride the momentum
    → BUY  signal : fast EMA crossed above slow EMA  AND MACD bullish  AND volume spike
    → SELL signal : fast EMA crossed below slow EMA  AND MACD bearish  AND volume spike

  A stop-loss check always runs first, regardless of regime.

  Strength of the approach
  ────────────────────────
  Unlike single-indicator bots, requiring 2-out-of-2 signal
  confirmation per regime raises signal quality at the cost of
  trade frequency — each trade fired has higher conviction.
  Separating the two regimes prevents applying a reversal
  strategy during a trend (or vice versa), which is a common
  source of losses in naive RSI-only bots.

Database  : bars.db  (SQLite, auto-created on first run)
Config    : config.json (hot-reloaded every bar — no restart needed)
Log       : crypto_bot.log (rotating, 5 MB per file, 3 backups)

Requirements:
    pip install alpaca-py python-dotenv

Environment variables (set in .env):
    ALPACA_API_KEY
    ALPACA_SECRET_KEY

Alpaca docs: https://docs.alpaca.markets/
"""

import json
import math
import sqlite3
import logging
import os
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, UTC
from collections import deque

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.live.crypto import CryptoDataStream


# ── Static config (restart required to change) ────────────────────────────────

load_dotenv()

API_KEY:    str | None = os.getenv("ALPACA_API_KEY")
API_SECRET: str | None = os.getenv("ALPACA_SECRET_KEY")
if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env")

PAPER: bool = True   # True = paper trading, False = live (use with caution)

SYMBOLS:     list[str] = ["BTC/USD", "ETH/USD"]
CONFIG_FILE: Path      = Path(__file__).parent / "config.json"
DB_FILE:     Path      = Path(__file__).parent / "bars.db"
LOG_FILE:    Path      = Path(__file__).parent / "crypto_bot.log"
DEQUE_SIZE:  int       = 200  # Maximum number of bars kept in memory per symbol


# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """Configure and return the application logger with two output handlers.

    Sets up a dual-handler logging configuration:
      - ``StreamHandler``       → terminal, INFO and above, raw message (no timestamp prefix)
      - ``RotatingFileHandler`` → ``crypto_bot.log``, DEBUG and above, with timestamp and level.
        Rotates at 5 MB and retains up to 3 backup files
        (``crypto_bot.log``, ``crypto_bot.log.1``, ``crypto_bot.log.2``).

    Returns:
        logging.Logger: Configured logger instance named ``"cryptobot"``.
    """
    log = logging.getLogger("cryptobot")
    log.setLevel(logging.DEBUG)  # Master level — individual handlers filter further

    # ── Terminal handler ──────────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))  # Raw message, no prefix

    # ── File handler ──────────────────────────────────────────────────────────
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes    = 5 * 1024 * 1024,  # 5 MB per file
        backupCount = 3,                 # Retain crypto_bot.log + 3 rotated files
        encoding    = "utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    log.addHandler(console)
    log.addHandler(file_handler)
    return log


log: logging.Logger = setup_logging()

# ── Default hyperparameters ────────────────────────────────────────────────────

DEFAULT_CONFIG: dict[str, float | int] = {
    # Position sizing & risk
    "order_qty_btc":      0.001,   # BTC quantity per order
    "order_qty_eth":      0.01,    # ETH quantity per order
    "stop_loss_pct":      0.02,    # Exit if price drops this fraction below entry (0.02 = 2%)

    # RSI — used in the RANGING regime
    "rsi_period":         14,      # Lookback period for Wilder's RSI
    "rsi_oversold":       30,      # RSI below this → oversold → BUY candidate
    "rsi_overbought":     70,      # RSI above this → overbought → SELL candidate

    # Bollinger Bands — regime detector AND ranging signal
    "bb_period":          20,      # Rolling window for band calculation
    "bb_std":             2.0,     # Number of standard deviations for band width
    "bb_width_threshold": 0.0065,  # Band width ratio: below = RANGING, above = TRENDING

    # MACD (trending regime)
    "macd_fast":          12,      # Fast EMA period
    "macd_slow":          26,      # Slow EMA period
    "macd_signal":        9,       # Signal line EMA period

    # EMA cross (trending regime)
    "ema_fast":           9,       # Fast EMA period for crossover detection
    "ema_slow":           21,      # Slow EMA period for crossover detection

    # Volume filter — applied in both regimes as a final confirmation gate
    "volume_factor":      1.5,     # Bar volume must exceed this multiple of the recent average
    "volume_period":      20,      # Number of bars used to compute the volume average
}


# ══════════════════════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict[str, float | int] | None:
    """Read hyperparameters from ``config.json`` and merge with defaults.

    If the file does not exist it is created with ``DEFAULT_CONFIG`` values.
    Any key present in ``DEFAULT_CONFIG`` but absent from the file is silently
    filled in from defaults, ensuring forward compatibility when new parameters
    are added.

    Returns:
        dict[str, float | int] | None: Merged configuration dictionary, or
            ``None`` if the file exists but is malformed JSON (e.g. mid-save).
            The caller is expected to retain the last valid config on ``None``.
    """
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=4))
        log.info(f"📝 Created default config at {CONFIG_FILE}")
        return DEFAULT_CONFIG.copy()
    try:
        return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text())}
    except json.JSONDecodeError:
        log.warning("⚠️  config.json parse error — keeping previous values")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Database
# ══════════════════════════════════════════════════════════════════════════════

def _ddl_trace(stmt: str) -> None:
    """SQLite trace callback that logs DDL statements (``CREATE``, ``DROP``, ``ALTER``) only.

    Registered temporarily via ``sqlite3.set_trace_callback()`` during schema
    initialisation. Routine DML is silently ignored.

    Args:
        stmt (str): Raw SQL statement string provided by SQLite.
    """
    keyword = stmt.strip().split()[0].upper()
    if keyword in ("CREATE", "DROP", "ALTER"):
        # Collapse whitespace so multi-line DDL fits on one log line
        one_line = " ".join(stmt.split())
        log.info(f"🗄️  DDL: {one_line}")


def init_db(conn: sqlite3.Connection) -> None:
    """Initialise the database schema, creating tables and indexes if absent.

    Creates two tables (idempotent — safe to call on every startup):

    **bars** — Raw, immutable OHLCVT market data. One row per closed 1-minute
    candle per symbol, written before any indicator computation. Serves as both
    an audit trail and a warmup-free restart mechanism (the bot reloads the
    last ``DEQUE_SIZE`` rows on startup). Columns:
    - ``symbol``    (TEXT) : Asset identifier, e.g. ``"BTC/USD"``
    - ``timestamp`` (TEXT) : ISO-8601 bar open time
    - ``open``      (REAL) : First trade price of the minute
    - ``high``      (REAL) : Highest trade price of the minute
    - ``low``       (REAL) : Lowest trade price of the minute
    - ``close``     (REAL) : Last trade price — consumed by all indicators
    - ``volume``    (REAL) : Total quantity traded during the minute

    **indicators** — Derived analytical snapshot linked to ``bars`` via foreign
    key. One row per bar where indicators were successfully computed. Enables
    post-hoc debugging and backtesting without re-running the bot. Columns:
    - ``symbol``              (TEXT) : Asset identifier, e.g. ``"BTC/USD"``
    - ``timestamp``           (TEXT) : ISO-8601 bar open time
    - ``rsi``                 (TEXT) : Relative Strength Index (0–100)
    - ``bb_mid/upper/lower``  (TEXT) : Bollinger Band levels
    - ``bb_width``            (TEXT) : ``(upper - lower) / mid`` — regime detector
    - ``macd_line``           (TEXT) : Fast EMA minus slow EMA
    - ``macd_signal``         (TEXT) : EMA of the MACD line
    - ``macd_hist``           (TEXT) : ``macd_line - macd_signal`` (momentum direction)
    - ``ema_fast / ema_slow`` (TEXT) : Raw EMA values at the configured periods
    - ``volume_avg``          (TEXT) : Rolling volume average over ``volume_period`` bars
    - ``vol_spike``        (INTEGER) : 1 if volume exceeded the spike threshold, else 0
    - ``regime``              (TEXT) : ``"RANGING"`` or ``"TRENDING"``
    - ``signal``              (TEXT) : ``"BUY"``, ``"SELL"``, or ``"HOLD"``

    Both tables use ``(symbol, timestamp)`` as a composite primary key.
    DDL statements are logged via ``_ddl_trace`` during this call only.

    Args:
        conn (sqlite3.Connection): Open SQLite connection to ``bars.db``.
    """
    # Register DDL trace for the duration of schema setup only
    conn.set_trace_callback(_ddl_trace)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bars (
            symbol     TEXT    NOT NULL,
            timestamp  TEXT    NOT NULL,
            open       REAL    NOT NULL,
            high       REAL    NOT NULL,
            low        REAL    NOT NULL,
            close      REAL    NOT NULL,
            volume     REAL    NOT NULL,
            PRIMARY KEY (symbol, timestamp)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indicators (
            symbol      TEXT    NOT NULL,
            timestamp   TEXT    NOT NULL,
            rsi         REAL,
            bb_mid      REAL,
            bb_upper    REAL,
            bb_lower    REAL,
            bb_width    REAL,
            macd_line   REAL,
            macd_signal REAL,
            macd_hist   REAL,
            ema_fast    REAL,
            ema_slow    REAL,
            volume_avg  REAL,
            vol_spike   INTEGER,
            regime      TEXT,
            signal      TEXT,
            PRIMARY KEY (symbol, timestamp),
            FOREIGN KEY (symbol, timestamp) REFERENCES bars (symbol, timestamp)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bars_symbol_ts
        ON bars (symbol, timestamp)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_indicators_symbol_ts
        ON indicators (symbol, timestamp)
    """)
    conn.commit()

    # Remove trace — DML from here on is not logged
    conn.set_trace_callback(None)


def save_bar(conn: sqlite3.Connection, symbol: str, bar) -> None:
    """Persist one raw OHLCVT bar to the ``bars`` table.

    Written before any indicator computation so the historical record is
    preserved even if signal logic raises. Duplicate bars (e.g. re-delivered
    after a reconnect) are silently skipped via ``INSERT OR IGNORE``.

    Args:
        conn   (sqlite3.Connection): Open SQLite connection to ``bars.db``.
        symbol (str)               : Asset identifier, e.g. ``"BTC/USD"``.
        bar                        : Bar object from ``CryptoDataStream``
            with attributes: ``timestamp``, ``open``, ``high``, ``low``,
            ``close``, ``volume``.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO bars
            (symbol, timestamp, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol,
            bar.timestamp.isoformat(),
            float(bar.open),
            float(bar.high),
            float(bar.low),
            float(bar.close),
            float(bar.volume),
        ),
    )
    conn.commit()


def save_indicators(
    conn:      sqlite3.Connection,
    symbol:    str,
    timestamp: str,
    rsi:       float,
    bb:        tuple[float, float, float, float],  # (mid, upper, lower, width)
    macd:      tuple[float, float, float],          # (macd_line, signal_line, histogram)
    ema_cross: tuple[float, float, bool, bool],     # (ema_fast, ema_slow, crossed_up, crossed_down)
    vol_avg:   float,
    vol_spike: bool,
    regime:    str,
    signal:    str,
) -> None:
    """Persist all computed indicator values for one bar to the ``indicators`` table.

    Captures a complete analytical snapshot of the signal engine's state,
    enabling post-hoc debugging, backtesting, and charting without re-running
    the bot. Uses ``INSERT OR IGNORE`` — if the same bar is evaluated twice,
    the first write wins.

    Stored indicator groups:
    - **RSI**: Momentum oscillator 0–100. Drives buy/sell in RANGING regime.
    - **Bollinger Bands** (``bb_mid``, ``upper``, ``lower``, ``width``):
      Volatility envelope. ``bb_width`` is the primary regime detector.
    - **MACD** (``macd_line``, ``signal``, ``hist``): Momentum confirmation
      in TRENDING regime.
    - **EMA cross** (``ema_fast``, ``ema_slow``): Trend direction in TRENDING
      regime.
    - **Volume** (``volume_avg``, ``vol_spike``): Confirmation gate in both
      regimes.
    - **regime**: ``"RANGING"`` or ``"TRENDING"``.
    - **signal**: ``"BUY"``, ``"SELL"``, or ``"HOLD"``.

    Args:
        conn      (sqlite3.Connection) : Open SQLite connection.
        symbol    (str) : Asset identifier, e.g. ``"BTC/USD"``.
        timestamp (str) : ISO-8601 timestamp of the bar.
        rsi       (float) : RSI value (0–100).
        bb        (tuple[float, float, float, float]) : ``(mid, upper, lower, width)``.
        macd      (tuple[float, float, float]) : ``(macd_line, signal_line, histogram)``.
        ema_cross (tuple[float, float, bool, bool]) : ``(ema_fast, ema_slow, crossed_up, crossed_down)``.
        vol_avg   (float) : Rolling volume average.
        vol_spike (bool) : ``True`` if volume spike detected.
        regime    (str) : ``"RANGING"`` or ``"TRENDING"``.
        signal    (str) : ``"BUY"``, ``"SELL"``, or ``"HOLD"``.
    """
    bb_mid, bb_upper, bb_lower, bb_width = bb
    macd_line, macd_sig, macd_hist       = macd
    ema_fast_val, ema_slow_val, _, _     = ema_cross

    conn.execute(
        """
        INSERT OR IGNORE INTO indicators (
            symbol, timestamp,
            rsi,
            bb_mid, bb_upper, bb_lower, bb_width,
            macd_line, macd_signal, macd_hist,
            ema_fast, ema_slow,
            volume_avg, vol_spike,
            regime, signal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol, timestamp,
            rsi,
            bb_mid, bb_upper, bb_lower, bb_width,
            macd_line, macd_sig, macd_hist,
            ema_fast_val, ema_slow_val,
            vol_avg, int(vol_spike),
            regime, signal,
        ),
    )
    conn.commit()


def load_bars(conn: sqlite3.Connection, symbol: str, limit: int) -> list[dict]:
    """Retrieve the most recent bars for a symbol from the ``bars`` table.

    Fetches up to ``limit`` rows ordered chronologically (oldest first),
    ready to be appended directly into an ``AssetState`` deque. Used on
    startup to restore rolling windows from persisted history, eliminating
    the warmup period that would otherwise be required.

    Args:
        conn   (sqlite3.Connection): Open SQLite connection to ``bars.db``.
        symbol (str)               : Asset identifier, e.g. ``"BTC/USD"``.
        limit  (int)               : Maximum number of bars to return.
            Typically ``DEQUE_SIZE``.

    Returns:
        list[dict]: List of bar dictionaries with keys ``timestamp``,
            ``open``, ``high``, ``low``, ``close``, ``volume``.
            Empty list if no rows exist for the given symbol.
    """
    rows = conn.execute(
        """
        SELECT timestamp, open, high, low, close, volume
        FROM   bars
        WHERE  symbol = ?
        ORDER  BY timestamp DESC
        LIMIT  ?
        """,
        (symbol, limit),
    ).fetchall()

    return [
        {
            "timestamp": r[0],
            "open":      r[1],
            "high":      r[2],
            "low":       r[3],
            "close":     r[4],
            "volume":    r[5],
        }
        for r in reversed(rows)  # Reverse so index 0 is the oldest bar
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  Indicators  (pure functions, no side effects)
# ══════════════════════════════════════════════════════════════════════════════

def ema(values: list[float], period: int) -> float | None:
    """Compute the Exponential Moving Average (EMA) of the last ``period`` values.

    Uses the standard multiplier ``k = 2 / (period + 1)`` and seeds the
    calculation from the oldest value in the window, iterating forward.

    Args:
        values (list[float]): Time-ordered list of prices (oldest first).
        period (int)        : Number of values to include in the EMA window.

    Returns:
        float | None: EMA value, or ``None`` if ``len(values) < period``.
    """
    if len(values) < period:
        return None
    k      = 2 / (period + 1)
    result = values[-period]
    for v in values[-period + 1:]:
        result = v * k + result * (1 - k)
    return result


def compute_rsi(closes: list[float], period: int) -> float | None:
    """Compute Wilder's Relative Strength Index (RSI).

    Measures price momentum on a 0–100 scale. Values below 30 are oversold
    (buy candidate); above 70 are overbought (sell candidate). Uses Wilder's
    smoothing: simple average for the first ``period`` deltas, then
    ``(prev * (period - 1) + current) / period`` for each subsequent value.

    Args:
        closes (list[float]): Time-ordered closing prices (oldest first).
        period (int)        : Lookback period. Standard value is 14.

    Returns:
        float | None: RSI rounded to 2 decimal places, ``100.0`` if no losses,
            or ``None`` if ``len(closes) < period + 1``.
    """
    if len(closes) < period + 1:
        return None
    deltas   = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    avg_gain = sum(d for d in deltas[:period] if d > 0) / period
    avg_loss = sum(-d for d in deltas[:period] if d < 0) / period
    for d in deltas[period:]:
        avg_gain = (avg_gain * (period - 1) + max(d, 0))  / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 2)


def compute_bollinger(
    closes: list[float], period: int, num_std: float
) -> tuple[float, float, float, float] | None:
    """Compute Bollinger Bands and their relative width.

    Bollinger Bands are a volatility envelope: a rolling mean (middle band)
    with upper and lower bands at ``num_std`` standard deviations. The
    relative width ``(upper - lower) / mid`` is the primary regime detector
    in this bot — narrow bands indicate a ranging market, wide bands a trend.

    Args:
        closes  (list[float]): Time-ordered list of closing prices (oldest first).
        period  (int)        : Rolling window size. Standard value is 20.
        num_std (float)      : Number of standard deviations for band width.
            Standard value is 2.0.

    Returns:
        tuple[float, float, float, float] | None: ``(mid, upper, lower, width)``
            where ``width = (upper - lower) / mid``, or ``None`` if
            ``len(closes) < period``.
    """
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid    = sum(window) / period
    std    = math.sqrt(sum((x - mid) ** 2 for x in window) / period)
    upper  = mid + num_std * std
    lower  = mid - num_std * std
    width  = (upper - lower) / mid if mid else 0
    return mid, upper, lower, width


def compute_macd(
    closes: list[float], fast: int, slow: int, signal: int
) -> tuple[float, float, float] | None:
    """Compute the MACD line, signal line, and histogram.

    Subtracts a slow EMA from a fast EMA (MACD line), then computes an EMA
    of that line (signal line). The histogram shows their gap — positive
    values indicate bullish momentum, negative bearish. Used in the TRENDING
    regime to confirm EMA cross signals.

    A short MACD history (``signal + 5`` points) is built internally to
    seed the signal line EMA accurately.

    Args:
        closes (list[float]): Time-ordered closing prices (oldest first).
        fast   (int)        : Fast EMA period. Standard value is 12.
        slow   (int)        : Slow EMA period. Standard value is 26.
        signal (int)        : Signal line EMA period. Standard value is 9.

    Returns:
        tuple[float, float, float] | None: ``(macd_line, signal_line, histogram)``
            or ``None`` if ``len(closes) < slow + signal``.
    """
    if len(closes) < slow + signal:
        return None
    macd_line   = ema(closes, fast) - ema(closes, slow)
    macd_series = []
    for i in range(signal + 5):
        idx = len(closes) - (signal + 5 - i)
        if idx < slow:
            continue
        m = ema(closes[:idx+1], fast) - ema(closes[:idx+1], slow)
        if m is not None:
            macd_series.append(m)
    if len(macd_series) < signal:
        return None
    signal_line = ema(macd_series, signal)
    if signal_line is None:
        return None
    return macd_line, signal_line, macd_line - signal_line


def compute_ema_cross(
    closes: list[float], fast: int, slow: int
) -> tuple[float, float, bool, bool] | None:
    """Detect a crossover between a fast and slow EMA.

    ``crossed_up`` is ``True`` only on the bar where the fast EMA transitions
    from below to above the slow EMA; ``crossed_down`` is the reverse.
    Requires ``len(closes) >= slow + 1`` for cross detection across two bars.

    Args:
        closes (list[float]): Time-ordered closing prices (oldest first).
        fast   (int)        : Fast EMA period (e.g. 9).
        slow   (int)        : Slow EMA period (e.g. 21).

    Returns:
        tuple[float, float, bool, bool] | None:
            ``(ema_fast, ema_slow, crossed_up, crossed_down)`` or ``None``
            if insufficient data.
    """
    if len(closes) < slow + 1:
        return None
    ef_now  = ema(closes,      fast)
    es_now  = ema(closes,      slow)
    ef_prev = ema(closes[:-1], fast)
    es_prev = ema(closes[:-1], slow)
    if None in (ef_now, es_now, ef_prev, es_prev):
        return None
    crossed_up   = ef_prev <= es_prev and ef_now > es_now
    crossed_down = ef_prev >= es_prev and ef_now < es_now
    return ef_now, es_now, crossed_up, crossed_down


def volume_spike(volumes: list[float], period: int, factor: float) -> bool:
    """Return ``True`` if the latest bar's volume exceeds ``factor × recent average``.

    Acts as a confirmation gate in both regimes — signals on low volume are
    ignored. The current bar is excluded from the baseline average.

    Args:
        volumes (list[float]): Time-ordered bar volumes (oldest first).
        period  (int)        : Number of bars used for the baseline average.
        factor  (float)      : Multiplier threshold (e.g. ``1.5`` = 50% above average).

    Returns:
        bool: ``True`` if spike detected, ``False`` otherwise or if insufficient data.
    """
    if len(volumes) < period + 1:
        return False
    avg = sum(volumes[-period-1:-1]) / period
    return volumes[-1] > factor * avg


# ══════════════════════════════════════════════════════════════════════════════
#  Per-asset state
# ══════════════════════════════════════════════════════════════════════════════

class AssetState:
    """Encapsulates all mutable state for a single traded asset.

    The bot trades multiple assets simultaneously (BTC/USD and ETH/USD).
    Each asset requires its own independent rolling price history and
    position tracking — a BTC bar must never contaminate ETH's window,
    and holding ETH should not prevent a BTC entry signal from firing.

    ``AssetState`` solves this by acting as an isolated container. The
    ``CryptoBot`` class holds one instance per symbol in a ``dict`` keyed
    by symbol string, routing each incoming bar to the correct instance
    before any processing occurs.

    Attributes:
        symbol      (str)               : Full symbol string, e.g. ``"BTC/USD"``.
            Used for API order submission and database queries.
        closes      (deque[float])      : Rolling window of closing prices,
            capped at ``DEQUE_SIZE`` bars. Consumed by all indicator functions
            (RSI, Bollinger Bands, MACD, EMA cross). When the deque is full,
            the oldest value is automatically discarded.
        volumes     (deque[float])      : Rolling window of bar volumes, same
            cap. Used exclusively by ``volume_spike()`` for confirmation.
        in_position (bool)              : Whether the bot currently holds a
            long position in this asset. Prevents double-buying (a second BUY
            signal while already holding is ignored) and premature selling
            (a SELL signal when flat is ignored).
        entry_price (float | None)      : Closing price at which the current
            position was opened. Used by the stop-loss check to compute the
            percentage drop from entry. Set to ``None`` when flat.

    Example:
        >>> state = AssetState("BTC/USD")
        >>> state.closes.append(80000.0)
        >>> state.in_position
        False
        >>> state.ticker
        'BTC'
    """

    def __init__(self, symbol: str) -> None:
        self.symbol:      str               = symbol
        self.closes:      deque[float]      = deque(maxlen=DEQUE_SIZE)
        self.volumes:     deque[float]      = deque(maxlen=DEQUE_SIZE)
        self.in_position: bool              = False
        self.entry_price: float | None      = None

    @property
    def ticker(self) -> str:
        """Short display name extracted from the symbol (e.g. ``'BTC/USD'`` → ``'BTC'``).

        Used to keep log lines compact without storing a separate field.

        Returns:
            str: The base currency portion of the symbol string.
        """
        return self.symbol.split("/")[0]

    def preload(self, bars: list[dict]) -> None:
        """Populate rolling windows from historical database rows on startup.

        Restores ``closes`` and ``volumes`` from persisted bar data so that
        indicators can compute on the first live bar, eliminating the warmup
        period. Only ``close`` and ``volume`` are loaded — ``open``, ``high``,
        and ``low`` remain in the database for future indicators.

        Args:
            bars (list[dict]): Chronologically ordered bar dicts (oldest first)
                as returned by ``load_bars()``. Must contain ``"close"`` and
                ``"volume"`` keys.
        """
        for b in bars:
            self.closes.append(b["close"])
            self.volumes.append(b["volume"])


# ══════════════════════════════════════════════════════════════════════════════
#  Bot
# ══════════════════════════════════════════════════════════════════════════════

class CryptoBot:
    """Regime-aware multi-asset cryptocurrency trading bot.

    Connects to Alpaca's WebSocket stream to receive real-time 1-minute
    OHLCVT bars for BTC/USD and ETH/USD, evaluates a regime-aware signal
    engine on each bar, and submits market orders via the Alpaca trading API.

    Strategy overview
    ─────────────────
    Each bar is classified into one of two regimes based on the relative
    width of its Bollinger Bands (``bb_width = (upper - lower) / mid``):

    **RANGING** (``bb_width < bb_width_threshold``):
        Markets coiling in a tight range. The reversal strategy fires:
        RSI must confirm an extreme (oversold/overbought), price must
        touch the corresponding Bollinger Band, and volume must spike.
        All three conditions are required simultaneously.

    **TRENDING** (``bb_width ≥ bb_width_threshold``):
        Markets breaking out with momentum. The momentum strategy fires:
        the fast EMA must have just crossed the slow EMA in the signal
        direction, MACD must confirm the same direction, and volume must
        spike. Again, all three conditions are required.

    In both regimes, a **stop-loss** check runs first and takes priority:
    if the current price has fallen ``stop_loss_pct`` below the entry
    price of an open position, a market sell is issued immediately,
    bypassing all signal logic.

    Strength of the approach
    ────────────────────────
    Requiring 2-out-of-2 indicator confirmation per regime (plus volume)
    raises signal quality at the cost of trade frequency — each trade
    that fires has high conviction. Separating regimes prevents applying
    reversal logic during a trend (where RSI can stay overbought for
    extended periods) and momentum logic in a range (where EMA crosses
    are frequent and false).

    Persistence & resilience
    ────────────────────────
    Every bar is written to ``bars.db`` before indicator computation.
    On restart, the last ``DEQUE_SIZE`` bars per symbol are reloaded from
    the database so indicators compute immediately — no warmup wait.
    All hyperparameters are read from ``config.json`` on every bar tick,
    allowing live tuning without restarting the process.

    Attributes:
        trading_client (TradingClient)      : Alpaca REST client for order submission.
        stream         (CryptoDataStream)   : Alpaca WebSocket stream for live bar data.
        cfg            (dict)               : Currently active hyperparameter configuration.
        assets         (dict[str, AssetState]): Per-symbol state, keyed by symbol string.
        conn           (sqlite3.Connection) : Open connection to ``bars.db``.
    """

    def __init__(self) -> None:
        self.trading_client: TradingClient = TradingClient(API_KEY, API_SECRET, paper=PAPER)
        self.stream: CryptoDataStream      = CryptoDataStream(API_KEY, API_SECRET)
        self.cfg: dict[str, float | int]   = load_config()
        self.assets: dict[str, AssetState] = {s: AssetState(s) for s in SYMBOLS}

        # ── Database setup + startup reload ───────────────────────────────────
        self.conn: sqlite3.Connection = sqlite3.connect(DB_FILE)
        log.info(f"🗄️  Database connected: {DB_FILE}")
        init_db(self.conn)
        self._preload_from_db()

        self._log_config("🤖 Bot started")

    # ── Startup reload ────────────────────────────────────────────────────────

    def _preload_from_db(self) -> None:
        """Restore rolling windows for all assets from persisted bar history.

        Queries the last ``DEQUE_SIZE`` bars per symbol from ``bars.db`` and
        calls ``AssetState.preload()`` on each, populating the ``closes`` and
        ``volumes`` deques so that all indicators can compute on the very
        first live bar after startup.
        """
        for symbol, asset in self.assets.items():
            bars = load_bars(self.conn, symbol, DEQUE_SIZE)
            if bars:
                asset.preload(bars)
                log.info(f"💾 {asset.ticker}: loaded {len(bars)} bars from DB "
                         f"(last close: {bars[-1]['timestamp'][:16]}  "
                         f"@ {bars[-1]['close']:.2f})")
            else:
                log.info(f"💾 {asset.ticker}: no history — starting fresh")

    # ── Config ────────────────────────────────────────────────────────────────

    def _reload_config(self) -> None:
        """Re-read ``config.json`` and apply any changed values immediately.

        Called on every bar tick before signal evaluation. If the file has
        changed since the last read, the new values are applied in-memory
        and logged. On JSON parse errors (e.g. mid-save), the previous
        config is retained silently.
        """
        new_cfg = load_config()
        if new_cfg is None:
            return
        changed = [k for k in DEFAULT_CONFIG if self.cfg.get(k) != new_cfg.get(k)]
        if changed:
            self.cfg = new_cfg
            self._log_config(f"🔄 Config reloaded ({', '.join(changed)} changed)")

    def _log_config(self, label: str) -> None:
        """Log the current hyperparameter configuration.

        Args:
            label (str): Prefix line for the log block, e.g. ``"🤖 Bot started"``
                or ``"🔄 Config reloaded"``.
        """
        cfg = self.cfg
        log.info(
            f"{label}\n"
            f"   Symbols : {', '.join(SYMBOLS)}  |  paper={PAPER}\n"
            f"   Sizes   : BTC={cfg['order_qty_btc']}  ETH={cfg['order_qty_eth']}"
            f"  |  stop-loss={cfg['stop_loss_pct']*100:.0f}%\n"
            f"   RSI     : period={cfg['rsi_period']}  buy<{cfg['rsi_oversold']}"
            f"  sell>{cfg['rsi_overbought']}\n"
            f"   BB      : period={cfg['bb_period']}  std={cfg['bb_std']}"
            f"  |  width threshold={cfg['bb_width_threshold']*100:.2f}%\n"
            f"   MACD    : {cfg['macd_fast']}/{cfg['macd_slow']}/{cfg['macd_signal']}"
            f"  |  EMA cross: {cfg['ema_fast']}/{cfg['ema_slow']}\n"
            f"   Volume  : spike if >{cfg['volume_factor']}× {cfg['volume_period']}-bar avg\n"
        )

    # ── Orders ────────────────────────────────────────────────────────────────

    def _order_qty(self, symbol: str) -> float:
        """Return the configured order quantity for the given symbol.

        Args:
            symbol (str): Asset symbol, e.g. ``"BTC/USD"`` or ``"ETH/USD"``.

        Returns:
            float: Order quantity in asset units (BTC or ETH).
        """
        return self.cfg["order_qty_btc"] if "BTC" in symbol else self.cfg["order_qty_eth"]

    def place_order(
        self, asset: AssetState, side: OrderSide, close: float, reason: str
    ) -> None:
        """Submit a market order via the Alpaca trading API.

        On success, logs the order ID and updates ``asset.entry_price``
        (set to ``close`` on BUY, reset to ``None`` on SELL). On failure,
        logs the error without raising — the bot continues running.

        Args:
            asset  (AssetState): The asset for which the order is placed.
            side   (OrderSide) : ``OrderSide.BUY`` or ``OrderSide.SELL``.
            close  (float)     : Current bar's closing price, recorded as
                entry price on BUY orders.
            reason (str)       : Human-readable trigger description logged
                alongside the order (e.g. ``"ranging"``, ``"stop-loss"``).
        """
        action = "BUY  🟢" if side == OrderSide.BUY else "SELL 🔴"
        try:
            order = self.trading_client.submit_order(
                MarketOrderRequest(
                    symbol        = asset.symbol,
                    qty           = self._order_qty(asset.symbol),
                    side          = side,
                    time_in_force = TimeInForce.GTC,
                )
            )
            log.info(f"    ✅ {asset.ticker} {action}  ({reason})  id={order.id}")
            asset.entry_price = close if side == OrderSide.BUY else None
        except Exception as e:
            log.error(f"    ❌ {asset.ticker} order failed: {e}")

    # ── Signal engine ─────────────────────────────────────────────────────────

    def _evaluate(self, asset: AssetState, ts: str) -> None:
        """Run the full signal engine for one asset on the current bar.

        Execution order:
            1. Warmup check — skip if insufficient bars for all indicators.
            2. Compute all indicators (RSI, BB, MACD, EMA cross, volume).
            3. Stop-loss check — sell immediately if drop exceeds threshold.
            4. Regime classification via Bollinger Band width.
            5. Signal logic — RANGING or TRENDING strategy depending on regime.
            6. Execute trade if signal fires and position state allows it.
            7. Persist all indicator values and the signal decision to DB.

        Args:
            asset (AssetState): The asset being evaluated.
            ts    (str)        : Current UTC time string (``HH:MM:SS``) for log output.
        """
        cfg    = self.cfg
        closes = list(asset.closes)
        vols   = list(asset.volumes)
        close  = closes[-1]

        # ── Warmup check ──────────────────────────────────────────────────────
        needed = max(cfg["rsi_period"] + 1, cfg["bb_period"],
                     cfg["macd_slow"] + cfg["macd_signal"],
                     cfg["ema_slow"] + 1, cfg["volume_period"] + 1)
        if len(closes) < needed:
            log.info(f"[{ts}] {asset.ticker:3}  ⏳ warming up ({len(closes)}/{needed} bars)")
            return

        # ── Compute all indicators ────────────────────────────────────────────
        rsi                = compute_rsi(closes, cfg["rsi_period"])
        bb                 = compute_bollinger(closes, cfg["bb_period"], cfg["bb_std"])
        macd               = compute_macd(closes, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"])
        cross              = compute_ema_cross(closes, cfg["ema_fast"], cfg["ema_slow"])
        vol_spike_detected = volume_spike(vols, cfg["volume_period"], cfg["volume_factor"])

        # Volume average stored alongside indicators for later analysis
        vol_avg = (sum(vols[-cfg["volume_period"]-1:-1]) / cfg["volume_period"]
                   if len(vols) >= cfg["volume_period"] + 1 else 0.0)

        if None in (rsi, bb, macd, cross):
            log.info(f"[{ts}] {asset.ticker:3}  ⏳ indicators initialising")
            return

        _, bb_upper, bb_lower, bb_width        = bb
        macd_line, signal_line, _              = macd
        _, _, ema_crossed_up, ema_crossed_down = cross

        # ── Stop-loss (always runs first, bypasses all signal logic) ──────────
        if asset.in_position and asset.entry_price:
            drop = (asset.entry_price - close) / asset.entry_price
            if drop >= cfg["stop_loss_pct"]:
                log.warning(f"[{ts}] {asset.ticker:3}  🛑 STOP-LOSS "
                            f"({drop*100:.1f}% drop)  close={close:.2f}")
                self.place_order(asset, OrderSide.SELL, close, "stop-loss")
                asset.in_position = False
                return

        # ── Regime classification ─────────────────────────────────────────────
        ranging = bb_width < cfg["bb_width_threshold"]
        regime  = "RANGING" if ranging else "TRENDING"

        # ── Signal logic ──────────────────────────────────────────────────────
        buy_signal  = False
        sell_signal = False

        if ranging:
            buy_signal  = (rsi < cfg["rsi_oversold"]  and close <= bb_lower and vol_spike_detected)
            sell_signal = (rsi > cfg["rsi_overbought"] and close >= bb_upper and vol_spike_detected)
        else:
            macd_bull   = macd_line > signal_line
            macd_bear   = macd_line < signal_line
            buy_signal  = (ema_crossed_up   and macd_bull and vol_spike_detected)
            sell_signal = (ema_crossed_down and macd_bear and vol_spike_detected)

        # ── Log & execute ─────────────────────────────────────────────────────
        vol_tag = "📶" if vol_spike_detected else "  "
        log_line = (
            f"[{ts}] {asset.ticker:3}  {regime:8}  "
            f"close={close:>10.2f}  RSI={rsi:5.1f}  "
            f"BB_w={bb_width*100:5.2f}%  "
            f"MACD={'▲' if macd_line > signal_line else '▼'}  "
            f"EMA={'▲' if cross[0] > cross[1] else '▼'}  {vol_tag}"
        )

        if buy_signal and not asset.in_position:
            log.info(f"{log_line}  →  BUY ({regime})")
            self.place_order(asset, OrderSide.BUY, close, regime.lower())
            asset.in_position = True
            signal_label = "BUY"

        elif sell_signal and asset.in_position:
            log.info(f"{log_line}  →  SELL ({regime})")
            self.place_order(asset, OrderSide.SELL, close, regime.lower())
            asset.in_position = False
            signal_label = "SELL"

        else:
            position_tag = "📦 holding" if asset.in_position else "  "
            log.info(f"{log_line}  →  hold  {position_tag}")
            signal_label = "HOLD"

        # ── Persist indicators ────────────────────────────────────────────────
        save_indicators(
            conn      = self.conn,
            symbol    = asset.symbol,
            timestamp = datetime.now(UTC).isoformat(),
            rsi       = rsi,
            bb        = bb,
            macd      = macd,
            ema_cross = cross,
            vol_avg   = vol_avg,
            vol_spike = vol_spike_detected,
            regime    = regime,
            signal    = signal_label,
        )

    # ── WebSocket handler ─────────────────────────────────────────────────────

    async def on_bar(self, bar) -> None:
        """Handle an incoming 1-minute bar from the Alpaca WebSocket stream.

        Called automatically by ``CryptoDataStream`` each time a bar closes
        for any subscribed symbol. Execution order:

            1. Hot-reload ``config.json``.
            2. Route the bar to the correct ``AssetState`` instance.
            3. Persist the full OHLCVT bar to ``bars.db``.
            4. Append close and volume to the asset's rolling deques.
            5. Run the signal engine via ``_evaluate()``.

        Args:
            bar: Bar object from ``CryptoDataStream``. Expected attributes:
                ``symbol``, ``timestamp``, ``open``, ``high``, ``low``,
                ``close``, ``volume``.
        """
        self._reload_config()

        symbol = bar.symbol
        if symbol not in self.assets:
            return

        asset = self.assets[symbol]

        # Persist raw bar first — before deque update or signal logic
        save_bar(self.conn, symbol, bar)

        # Update in-memory rolling windows (close + volume only)
        asset.closes.append(float(bar.close))
        asset.volumes.append(float(bar.volume))

        ts = datetime.now(UTC).strftime("%H:%M:%S")
        self._evaluate(asset, ts)

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """Subscribe to all configured symbols and start the WebSocket event loop.

        Blocks until the stream ends (``Ctrl+C``, network failure, or
        Alpaca-side disconnection). ``KeyboardInterrupt`` is re-raised so
        the ``__main__`` block can handle shutdown cleanly. All other
        exceptions are logged with a full traceback before being re-raised.
        """
        for symbol in SYMBOLS:
            self.stream.subscribe_bars(self.on_bar, symbol)
        log.info(f"📡 Subscribed to: {', '.join(SYMBOLS)}")
        log.info(f"   DB : {DB_FILE}")
        log.info(f"   Log: {LOG_FILE}")
        log.info(f"   Watching {CONFIG_FILE.name} for live config changes...\n")
        try:
            self.stream.run()
        except KeyboardInterrupt:
            # Intentional shutdown — re-raise for clean handling in __main__
            raise
        except Exception as e:
            # Connection limit exceeded, auth failure, network drop, etc.
            log.error(f"❌ Stream error: {e}", exc_info=True)
            raise

    def close(self) -> None:
        """Gracefully stop the WebSocket stream and close the database connection.

        Calls ``stream.stop()`` first to send a proper WebSocket close frame,
        releasing the Alpaca connection slot immediately and preventing
        ``connection limit exceeded`` errors on the next restart.
        ``stream.stop()`` is wrapped in try/except since it may raise if the
        stream already died.
        """
        try:
            self.stream.stop()
            log.info("🔌 Stream stopped.")
        except Exception as e:
            log.warning(f"⚠️  Error stopping stream: {e}")
        self.conn.close()
        log.info(f"🗄️  Database connection closed: {DB_FILE}")


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot = CryptoBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        log.info("\n👋 Bot stopped.")
    finally:
        bot.close()
        log.info("💾 Database closed.")