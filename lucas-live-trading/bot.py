"""
Vote-based multi-asset trading bot — lucas-live-trading
========================================================
Assets  : configurable via ``config.json["symbols"]``
          (defaults: all 30 research symbols — 28 US stocks/ETFs +
          BTC/USD + ETH/USD; hot-reloaded like the rest of the
          config — added symbols are subscribed live, removed
          symbols are liquidated and unsubscribed, no restart)

Strategy: majority-vote signal engine
──────────────────────────────────────────────────────────────────
  Each 1-minute bar is evaluated by a configurable set of independent
  signals (BB, OU, VWAP, VolSpike, KalmanZ, …).  Each active signal
  casts one (buy, sell) vote.  When the number of buy or sell votes
  reaches ``vote_threshold`` a market order is placed.

  A stop-loss check always runs before any vote logic and exits the
  position immediately when the price falls ``stop_loss_pct`` below
  the recorded entry price.

  Session-stateful signals (VWAP, ORB, KalmanZ) update their state on
  every bar regardless of warmup or stop-loss — only trade execution
  is gated.

Active signals and all thresholds live in ``config.json`` and are
hot-reloaded on every bar tick — no restart required.

Database  : bars.db  (SQLite, auto-created on first run)
Config    : config.json (hot-reloaded every bar)
Log       : bot.log (rotating, 5 MB per file, 3 backups)

Requirements:
    pip install alpaca-py python-dotenv

Environment variables (.env):
    ALPACA_API_KEY
    ALPACA_SECRET_KEY
"""

import asyncio
import json
import sqlite3
import logging
import os
import time
from datetime import datetime, UTC
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from alpaca.data.enums import DataFeed
from alpaca.data.live.crypto import CryptoDataStream
from alpaca.data.live.stock import StockDataStream
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from constants import SYMBOLS
from engine import DEQUE_SIZE, SignalState, evaluate_bar


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_crypto(symbol: str) -> bool:
    """Return True if the symbol is a crypto pair (contains ``/``).

    Alpaca crypto symbols use slash notation (``"BTC/USD"``); US stock
    tickers never contain a slash (``"AAPL"``).

    Args:
        symbol (str): Asset identifier.

    Returns:
        bool: ``True`` for crypto, ``False`` for stocks/ETFs.
    """
    return "/" in symbol


# ── Static config (restart required to change) ────────────────────────────────

load_dotenv()

API_KEY:    str | None = os.getenv("ALPACA_API_KEY")
API_SECRET: str | None = os.getenv("ALPACA_SECRET_KEY")
if not API_KEY or not API_SECRET:
    raise RuntimeError(
        "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env"
    )

PAPER: bool = True   # True = paper trading, False = live

CONFIG_FILE: Path = Path(__file__).parent / "config.json"
DB_FILE:     Path = Path(__file__).parent / "bars.db"
LOG_FILE:    Path = Path(__file__).parent / "bot.log"

# DEQUE_SIZE (rolling-window capacity) lives in engine.py — shared
# with scorer.py so live bot and simulation always match.

# Minimum seconds between consecutive config.json disk reads.
# With 30 symbols each firing ~once per minute, throttling avoids
# reading the file 30× per minute; 30 s keeps latency under one bar.
_CONFIG_RELOAD_INTERVAL: float = 30.0


# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """Configure and return the application logger with dual handlers.

    Registers:
    - ``StreamHandler``       → terminal, INFO and above, raw message
    - ``RotatingFileHandler`` → ``bot.log``, DEBUG and above, timestamped
      (5 MB per file, 3 rotating backups)

    Returns:
        logging.Logger: Logger named ``"lucasbot"``.
    """
    log = logging.getLogger("lucasbot")
    log.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))

    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes    = 5 * 1024 * 1024,
        backupCount = 3,
        encoding    = "utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    log.addHandler(console)
    log.addHandler(fh)
    return log


log: logging.Logger = setup_logging()


# ── Default hyperparameters ────────────────────────────────────────────────────

DEFAULT_CONFIG: dict = {
    # Traded symbols — sourced from constants.py (single source of truth).
    # Hot-reloaded: edits to config.json["symbols"] (e.g. by scorer.py)
    # are applied live — see CryptoBot._apply_symbols().
    # list() ensures DEFAULT_CONFIG holds its own copy so that nothing
    # can accidentally mutate the shared SYMBOLS constant.
    "symbols": list(SYMBOLS),

    # Position sizing
    # Priority: order_qty (per-ticker) > order_dollar_value > order_qty_default
    "order_qty":          {"BTC": 0.001, "ETH": 0.01},
    "order_qty_default":  1,      # fallback qty for stocks (shares)
    "order_dollar_value": 500,    # target notional per trade in USD
                                  # (0 = disable, use order_qty_default)
    "stop_loss_pct":      0.02,   # 2 % drop from entry triggers exit
    "max_open_positions": 10,     # hard cap on simultaneous positions

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


# ══════════════════════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict | None:
    """Read hyperparameters from ``config.json`` and merge with defaults.

    Creates the file with defaults if absent.  Any key present in
    ``DEFAULT_CONFIG`` but missing from the file is filled in from
    defaults, ensuring forward compatibility when new parameters are
    added.

    Returns:
        dict | None: Merged configuration, or ``None`` on a JSON parse
            error (caller should retain the last valid config).
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
    """Log DDL statements (``CREATE``, ``DROP``, ``ALTER``) only.

    Registered temporarily via ``sqlite3.set_trace_callback()`` during
    schema initialisation.  Removed immediately after.

    Args:
        stmt (str): Raw SQL statement provided by SQLite.
    """
    keyword = stmt.strip().split()[0].upper()
    if keyword in ("CREATE", "DROP", "ALTER"):
        log.info(f"🗄️  DDL: {' '.join(stmt.split())}")


def init_db(conn: sqlite3.Connection) -> None:
    """Initialise the database schema (idempotent — safe to call on every start).

    Creates three tables:

    **bars** — raw, immutable OHLCVT market data.  One row per closed
    1-minute candle per symbol.  Written before any signal logic so the
    record survives even if evaluation raises.

    **indicators** — per-bar snapshot of vote results.  Lighter than
    Kerry's schema — full indicator values live in ``bars``; we only
    store what's needed for post-hoc analysis of trade decisions.

    **trades** — one row per order accepted by Alpaca (BUY and SELL),
    with the realised P&L computed on exits.  This is the local source
    of truth for per-trade performance analysis in the dashboard,
    independent of the Alpaca order history.

    ``bars`` and ``indicators`` use ``(symbol, timestamp)`` as a
    composite primary key.  DDL statements are traced to the log
    during this call only.

    Args:
        conn (sqlite3.Connection): Open SQLite connection to ``bars.db``.
    """
    conn.set_trace_callback(_ddl_trace)

    # WAL mode: readers never block writers and vice-versa — critical
    # when the dashboard reads while the bot writes every minute.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

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
            symbol      TEXT     NOT NULL,
            timestamp   TEXT     NOT NULL,
            close       REAL,
            vol_avg     REAL,
            vol_spike   INTEGER,
            buy_votes   INTEGER,
            sell_votes  INTEGER,
            n_signals   INTEGER,
            signal      TEXT,
            PRIMARY KEY (symbol, timestamp),
            FOREIGN KEY (symbol, timestamp)
                REFERENCES bars (symbol, timestamp)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            timestamp   TEXT    NOT NULL,
            side        TEXT    NOT NULL,
            qty         REAL    NOT NULL,
            price       REAL    NOT NULL,
            reason      TEXT    NOT NULL,
            order_id    TEXT,
            entry_price REAL,
            pnl_pct     REAL
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
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts
        ON trades (symbol, timestamp)
    """)
    conn.commit()
    conn.set_trace_callback(None)


def save_bar(conn: sqlite3.Connection, symbol: str, bar) -> None:
    """Persist one raw OHLCVT bar to the ``bars`` table.

    Uses ``INSERT OR IGNORE`` — duplicate bars delivered on reconnect
    are silently skipped.  Must be called before ``_evaluate()``.

    Args:
        conn   (sqlite3.Connection): Open connection to ``bars.db``.
        symbol (str)               : Asset identifier, e.g. ``"BTC/USD"``.
        bar                        : Bar object from ``CryptoDataStream``
            with attributes ``timestamp``, ``open``, ``high``, ``low``,
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
    conn:       sqlite3.Connection,
    symbol:     str,
    timestamp:  str,
    close:      float,
    vol_avg:    float,
    vol_spike:  bool,
    buy_votes:  int,
    sell_votes: int,
    n_signals:  int,
    signal:     str,
) -> None:
    """Persist the vote-engine snapshot for one bar.

    Uses ``INSERT OR IGNORE`` so a double evaluation never overwrites
    the first result.

    Args:
        conn       (sqlite3.Connection): Open connection.
        symbol     (str): Asset identifier.
        timestamp  (str): ISO-8601 evaluation time (``datetime.now(UTC)``).
        close      (float): Bar closing price.
        vol_avg    (float): Rolling volume average.
        vol_spike  (bool): True if volume spike detected.
        buy_votes  (int): Number of signals that fired BUY.
        sell_votes (int): Number of signals that fired SELL.
        n_signals  (int): Total active signals evaluated.
        signal     (str): ``"BUY"``, ``"SELL"``, or ``"HOLD"``.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO indicators (
            symbol, timestamp, close,
            vol_avg, vol_spike,
            buy_votes, sell_votes, n_signals,
            signal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol, timestamp, close,
            vol_avg, int(vol_spike),
            buy_votes, sell_votes, n_signals,
            signal,
        ),
    )
    conn.commit()


def save_trade(
    conn:        sqlite3.Connection,
    symbol:      str,
    timestamp:   str,
    side:        str,
    qty:         float,
    price:       float,
    reason:      str,
    order_id:    str | None,
    entry_price: float | None,
    pnl_pct:     float | None,
) -> None:
    """Persist one executed order to the ``trades`` table.

    Called only after Alpaca accepted the order.  ``price`` is the bar
    close used to trigger the order — the actual fill price of the
    market order may differ slightly (slippage).

    Args:
        conn        (sqlite3.Connection): Open connection.
        symbol      (str): Asset identifier, e.g. ``"AAPL"``.
        timestamp   (str): ISO-8601 execution time (UTC).
        side        (str): ``"BUY"`` or ``"SELL"``.
        qty         (float): Order quantity in asset units.
        price       (float): Bar close at order time.
        reason      (str): Trigger description (``"vote"``,
            ``"stop-loss"``).
        order_id    (str | None): Alpaca order id.
        entry_price (float | None): Position entry close (SELL only).
        pnl_pct     (float | None): Realised P&L as a decimal
            (SELL only), e.g. 0.012 = +1.2 %.
    """
    conn.execute(
        """
        INSERT INTO trades (
            symbol, timestamp, side, qty, price,
            reason, order_id, entry_price, pnl_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol, timestamp, side, qty, price,
            reason, order_id, entry_price, pnl_pct,
        ),
    )
    conn.commit()


def load_bars(
    conn: sqlite3.Connection, symbol: str, limit: int
) -> list[dict]:
    """Return the most recent bars for a symbol, oldest first.

    Fetches up to ``limit`` rows and reverses them so index 0 is the
    oldest bar — ready to be appended directly into an ``AssetState``
    deque.

    Args:
        conn   (sqlite3.Connection): Open connection.
        symbol (str): Asset identifier.
        limit  (int): Maximum rows to return (typically ``DEQUE_SIZE``).

    Returns:
        list[dict]: Bar dicts with keys ``timestamp``, ``open``,
            ``high``, ``low``, ``close``, ``volume``.  Empty if no
            history exists for the symbol.
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
        for r in reversed(rows)
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  Per-asset state
# ══════════════════════════════════════════════════════════════════════════════

class AssetState(SignalState):
    """Per-asset live-trading state: engine state plus position tracking.

    Extends ``engine.SignalState`` (rolling windows, Kalman / VWAP /
    ORB session state — see that class for details) with what only the
    live bot needs: the symbol name and open-position tracking.  Each
    instance is entirely independent — BTC and ETH data must never
    cross-contaminate.

    Attributes:
        symbol      (str): Full symbol string, e.g. ``"BTC/USD"``.
        in_position (bool): Whether the bot currently holds this asset.
        entry_price (float | None): Close at which the position opened.
    """

    def __init__(self, symbol: str) -> None:
        super().__init__()
        self.symbol:      str          = symbol
        self.in_position: bool         = False
        self.entry_price: float | None = None

    @property
    def ticker(self) -> str:
        """Short display name, e.g. ``'BTC/USD'`` → ``'BTC'``.

        Returns:
            str: Base-currency portion of the symbol string.
        """
        return self.symbol.split("/")[0]


# ══════════════════════════════════════════════════════════════════════════════
#  Bot
# ══════════════════════════════════════════════════════════════════════════════

class CryptoBot:
    """Vote-based multi-asset trading bot (US stocks + crypto).

    Connects to **two** Alpaca WebSocket streams in parallel:

    - ``CryptoDataStream`` — for symbols containing ``"/"`` (BTC/USD, ETH/USD)
    - ``StockDataStream``  — for plain equity tickers (AAPL, NVDA, …)

    Both streams share the same ``on_bar`` handler.  The full config —
    including ``symbols`` — is hot-reloaded: when the symbol list
    changes on disk (typically written by ``scorer.py``), new symbols
    are subscribed live and removed symbols are liquidated and
    unsubscribed, without restarting the bot.

    Attributes:
        trading_client (TradingClient): Alpaca REST client for orders.
        crypto_stream  (CryptoDataStream): Crypto WebSocket.  Always
            created (connection only opens once it has symbols).
        stock_stream   (StockDataStream): Stock WebSocket, same lazy
            connection behaviour.
        cfg            (dict): Current hyperparameter configuration.
        assets         (dict[str, AssetState]): Per-symbol state.
        conn           (sqlite3.Connection): Open ``bars.db`` connection.
    """

    def __init__(self) -> None:
        self.trading_client: TradingClient = TradingClient(
            API_KEY, API_SECRET, paper=PAPER
        )
        # load_config() returns None on a JSON parse error; fall back to
        # defaults so the bot starts cleanly even with a malformed file.
        self.cfg: dict = load_config() or DEFAULT_CONFIG.copy()

        symbols: list[str] = self.cfg.get(
            "symbols", DEFAULT_CONFIG["symbols"]
        )
        self.assets: dict[str, AssetState] = {
            s: AssetState(s) for s in symbols
        }

        # Split symbols into their respective stream types
        self._crypto_syms: list[str] = [s for s in symbols if _is_crypto(s)]
        self._stock_syms:  list[str] = [s for s in symbols if not _is_crypto(s)]

        # Both stream objects are always created — no connection is
        # opened until their runner starts — so that symbols of either
        # class can be hot-added at runtime even when the initial
        # config contains none of that class.
        self.crypto_stream: CryptoDataStream = CryptoDataStream(
            API_KEY, API_SECRET
        )
        self.stock_stream: StockDataStream = StockDataStream(
            API_KEY, API_SECRET, feed=DataFeed.IEX
        )

        # Gate each stream's runner task: set once the stream has at
        # least one symbol (at startup or after a hot-add).  An idle
        # alpaca-py stream busy-waits until its first subscription, so
        # runners stay parked on these events instead.
        self._crypto_ready: asyncio.Event = asyncio.Event()
        self._stock_ready:  asyncio.Event = asyncio.Event()

        self.conn: sqlite3.Connection = sqlite3.connect(DB_FILE)
        log.info(f"🗄️  Database connected: {DB_FILE}")
        init_db(self.conn)
        # Initialise before any method that might eventually call _reload_config.
        self._last_config_reload: float = 0.0
        self._preload_from_db()
        self._restore_positions()
        self._log_config("🤖 Bot started")

    # ── Startup ───────────────────────────────────────────────────────────────

    def _preload_from_db(self) -> None:
        """Restore rolling windows for all assets from persisted bar history.

        Queries the last ``DEQUE_SIZE`` bars per symbol and calls
        ``AssetState.preload()`` so indicators compute on the first live
        bar — no warmup wait after restart.
        """
        for symbol, asset in self.assets.items():
            bars = load_bars(self.conn, symbol, DEQUE_SIZE)
            if bars:
                asset.preload(bars)
                log.info(
                    f"💾 {asset.ticker}: loaded {len(bars)} bars "
                    f"(last: {bars[-1]['timestamp'][:16]} "
                    f"@ {bars[-1]['close']:.2f})"
                )
            else:
                log.info(f"💾 {asset.ticker}: no history — starting fresh")

    # ── Startup helpers ───────────────────────────────────────────────────────

    def _restore_positions(self) -> None:
        """Sync in-memory ``in_position`` flags with live Alpaca positions.

        Called once at startup.  Without this, a restart while holding
        positions would set all assets flat and risk placing duplicate
        BUY orders on the next matching signal.

        Symbols present in Alpaca but not in the watchlist are logged
        and skipped — the bot never manages positions it didn't open.
        """
        try:
            open_pos = self.trading_client.get_all_positions()
        except Exception as exc:
            log.warning(f"⚠️  Could not fetch positions at startup: {exc}")
            return
        for p in open_pos:
            symbol = p.symbol
            if symbol not in self.assets:
                log.info(
                    f"💼 {symbol}: active Alpaca position "
                    "not in watchlist — ignored"
                )
                continue
            self.assets[symbol].in_position = True
            self.assets[symbol].entry_price = float(p.avg_entry_price)
            log.info(
                f"💼 {symbol}: position restored  "
                f"(qty={p.qty}  entry={p.avg_entry_price})"
            )

    # ── Config ────────────────────────────────────────────────────────────────

    def _reload_config(self) -> list[str] | None:
        """Re-read ``config.json`` at most once every 30 s.

        Throttled via ``_CONFIG_RELOAD_INTERVAL`` so that 30 symbols
        firing near-simultaneously don't trigger 30 disk reads per
        minute.  Retains the previous config silently on JSON parse
        errors.

        Returns:
            list[str] | None: The new symbol list when it changed
                (caller must pass it to ``_apply_symbols()``), else
                ``None``.
        """
        now = time.monotonic()
        if now - self._last_config_reload < _CONFIG_RELOAD_INTERVAL:
            return None
        self._last_config_reload = now
        new_cfg = load_config()
        if new_cfg is None:
            return None
        changed = [
            k for k in DEFAULT_CONFIG
            if self.cfg.get(k) != new_cfg.get(k)
        ]
        if not changed:
            return None
        self.cfg = new_cfg
        self._log_config(
            f"🔄 Config reloaded ({', '.join(changed)} changed)"
        )
        if "symbols" in changed:
            return list(new_cfg.get("symbols", []))
        return None

    async def _apply_symbols(self, new_symbols: list[str]) -> None:
        """Apply a changed symbol list live, without restarting.

        Removed symbols follow rotation semantics: an open position is
        liquidated at market first (leaving the top-X means exiting),
        then the stream subscription is dropped and the asset state
        discarded.  If the liquidation order fails, the symbol is kept
        subscribed and managed (votes + stop-loss) rather than left as
        an orphan position.

        Added symbols get a fresh ``AssetState`` preloaded from any
        ``bars.db`` history, then a live subscription.  A stream that
        had no symbols until now is started on the spot via its ready
        event.

        alpaca-py's ``subscribe_bars``/``unsubscribe_bars`` block on
        the stream's own event loop when it is running
        (``run_coroutine_threadsafe(...).result()``).  Since this
        method runs *on* that loop (called from ``on_bar``), the calls
        are dispatched through ``asyncio.to_thread`` — calling them
        directly would deadlock.

        Args:
            new_symbols (list[str]): Target symbol list from config.
        """
        added   = sorted(set(new_symbols) - set(self.assets))
        removed = sorted(set(self.assets) - set(new_symbols))
        if not added and not removed:
            return
        log.info(f"🔀 Rotation des symboles  +{added}  -{removed}")

        for symbol in removed:
            asset = self.assets[symbol]
            if asset.in_position:
                close = asset.closes[-1] if asset.closes else 0.0
                log.info(
                    f"🔀 {asset.ticker}: sorti de la sélection — "
                    f"liquidation de la position"
                )
                if not self.place_order(
                    asset, OrderSide.SELL, close, "rotation"
                ):
                    log.warning(
                        f"⚠️  {asset.ticker}: liquidation échouée — "
                        f"symbole conservé jusqu'à la prochaine rotation"
                    )
                    continue
                asset.in_position = False
            stream = (
                self.crypto_stream if _is_crypto(symbol)
                else self.stock_stream
            )
            try:
                await asyncio.to_thread(stream.unsubscribe_bars, symbol)
            except Exception as exc:
                log.warning(f"⚠️  {symbol}: unsubscribe failed: {exc}")
            del self.assets[symbol]
            log.info(f"➖ {symbol}: désabonné")

        for symbol in added:
            asset = AssetState(symbol)
            bars = load_bars(self.conn, symbol, DEQUE_SIZE)
            if bars:
                asset.preload(bars)
            self.assets[symbol] = asset
            stream = (
                self.crypto_stream if _is_crypto(symbol)
                else self.stock_stream
            )
            try:
                await asyncio.to_thread(
                    stream.subscribe_bars, self.on_bar, symbol
                )
            except Exception as exc:
                log.error(f"❌ {symbol}: subscribe failed: {exc}")
                del self.assets[symbol]
                continue
            log.info(
                f"➕ {symbol}: abonné ({len(bars)} barres préchargées)"
            )

        self._crypto_syms = [s for s in self.assets if _is_crypto(s)]
        self._stock_syms  = [s for s in self.assets if not _is_crypto(s)]

        # Start a stream that was idle until its first symbol arrived
        if self._crypto_syms and not self._crypto_ready.is_set():
            self._crypto_ready.set()
        if self._stock_syms and not self._stock_ready.is_set():
            self._stock_ready.set()

    def _log_config(self, label: str) -> None:
        """Log the current configuration in a compact summary block.

        Args:
            label (str): Prefix line, e.g. ``"🤖 Bot started"``.
        """
        cfg    = self.cfg
        active = cfg.get("active_signals", [])
        log.info(
            f"{label}\n"
            f"   Crypto  : {self._crypto_syms or '(none)'}  |  paper={PAPER}\n"
            f"   Stocks  : {self._stock_syms or '(none)'}\n"
            f"   Signals : {active}\n"
            f"   Threshold: {cfg['vote_threshold']} / {len(active)}\n"
            f"   Stop-loss: {cfg['stop_loss_pct'] * 100:.0f}%\n"
        )

    # ── Orders ────────────────────────────────────────────────────────────────

    def _order_qty(self, symbol: str, close: float = 0.0) -> float:
        """Return order quantity for the given symbol and current price.

        Resolution priority:

        1. **Per-ticker override** — explicit entry in
           ``config["order_qty"]`` (e.g. ``{"BTC": 0.001}``).
        2. **Dollar-value sizing** — ``config["order_dollar_value"]``
           divided by ``close``.  Rounds to the nearest whole share for
           stocks; keeps full fractional precision for crypto.
        3. **Fixed fallback** — ``config["order_qty_default"]`` (1 share).

        Args:
            symbol (str): Asset symbol, e.g. ``"BTC/USD"`` or ``"AAPL"``.
            close  (float): Current bar close price (required for
                dollar-value sizing; pass 0.0 to skip).

        Returns:
            float: Order quantity in asset units.
        """
        ticker  = symbol.split("/")[0]
        qty_map = self.cfg.get("order_qty", {})
        if ticker in qty_map:
            return float(qty_map[ticker])
        dollar_val = float(self.cfg.get("order_dollar_value", 0))
        if dollar_val > 0 and close > 0:
            qty = dollar_val / close
            return qty if _is_crypto(symbol) else max(1.0, round(qty))
        return float(self.cfg.get("order_qty_default", 1))

    def place_order(
        self,
        asset: AssetState,
        side:  OrderSide,
        close: float,
        reason: str,
    ) -> bool:
        """Submit a market order via the Alpaca trading API.

        Updates ``asset.entry_price`` on a successful BUY (set to
        ``close``) or SELL (reset to ``None``), and records the trade
        (with realised P&L on SELL) in the ``trades`` table.  Returns
        ``False`` without raising on failure — the bot continues
        running.

        Args:
            asset  (AssetState): Asset for which the order is placed.
            side   (OrderSide) : ``OrderSide.BUY`` or ``OrderSide.SELL``.
            close  (float)     : Current bar's closing price.
            reason (str)       : Trigger description logged with order.

        Returns:
            bool: ``True`` if Alpaca accepted the order, ``False`` on
                any error.  Callers must check the return value before
                updating ``in_position``.
        """
        action = "BUY  🟢" if side == OrderSide.BUY else "SELL 🔴"
        tif = (
            TimeInForce.GTC if _is_crypto(asset.symbol)
            else TimeInForce.DAY
        )
        qty = self._order_qty(asset.symbol, close)
        try:
            order = self.trading_client.submit_order(
                MarketOrderRequest(
                    symbol        = asset.symbol,
                    qty           = qty,
                    side          = side,
                    time_in_force = tif,
                )
            )
            log.info(
                f"    ✅ {asset.ticker} {action}  "
                f"({reason})  id={order.id}"
            )
        except Exception as e:
            log.error(f"    ❌ {asset.ticker} order failed: {e}")
            return False

        is_sell    = side == OrderSide.SELL
        prev_entry = asset.entry_price if is_sell else None
        pnl_pct: float | None = None
        if is_sell and prev_entry:
            pnl_pct = (close - prev_entry) / prev_entry
            log.info(
                f"    💹 {asset.ticker} P&L réalisé: {pnl_pct * 100:+.2f}%"
            )
        try:
            save_trade(
                conn        = self.conn,
                symbol      = asset.symbol,
                timestamp   = datetime.now(UTC).isoformat(),
                side        = "SELL" if is_sell else "BUY",
                qty         = float(qty),
                price       = close,
                reason      = reason,
                order_id    = str(order.id),
                entry_price = prev_entry,
                pnl_pct     = pnl_pct,
            )
        except Exception as e:
            # Order is already live — never let a DB error kill the bot.
            log.error(f"    ⚠️ {asset.ticker} trade not persisted: {e}")

        asset.entry_price = close if side == OrderSide.BUY else None
        return True

    # ── Signal engine ─────────────────────────────────────────────────────────

    def _evaluate(self, asset: AssetState, ts: str) -> None:
        """Run stop-loss and vote logic for one asset on the current bar.

        Signal evaluation is delegated to ``engine.evaluate_bar()`` —
        the exact code path the scorer simulates, so live behaviour and
        backtested ranking can never diverge.  Execution order:

            1. Evaluate signals via the shared engine (stateful
               updates, warmup, time filter, vote collection).
            2. Warmup check — skip trade logic if insufficient history.
            3. Stop-loss — exit immediately if drop exceeds threshold.
            4. Time-filter gate — skip if outside the trading window.
            5. Apply vote threshold; execute BUY / SELL as needed.
            6. Persist vote snapshot to ``indicators`` table.

        Args:
            asset (AssetState): The asset being evaluated.
            ts    (str): Current UTC time string (``"HH:MM:SS"``)
                for log output.
        """
        cfg = self.cfg
        if not asset.closes:
            return
        close = asset.closes[-1]

        # ── Step 1: shared engine evaluation ──────────────────────────────────
        result = evaluate_bar(asset, cfg)

        # ── Step 2: warmup check ──────────────────────────────────────────────
        if not result.warmed_up:
            log.debug(
                f"[{ts}] {asset.ticker:4}  "
                f"⏳ warming up ({result.bars_seen}/{result.bars_needed})"
            )
            return

        # ── Step 3: stop-loss ─────────────────────────────────────────────────
        if asset.in_position and asset.entry_price:
            drop = (asset.entry_price - close) / asset.entry_price
            if drop >= cfg["stop_loss_pct"]:
                log.warning(
                    f"[{ts}] {asset.ticker:4}  "
                    f"🛑 STOP-LOSS ({drop * 100:.1f}% drop)  "
                    f"close={close:.2f}"
                )
                if self.place_order(asset, OrderSide.SELL, close, "stop-loss"):
                    asset.in_position = False
                    # Persist stop-loss exits so the dashboard shows them
                    save_indicators(
                        conn=self.conn, symbol=asset.symbol,
                        timestamp=datetime.now(UTC).isoformat(),
                        close=close, vol_avg=result.vol_avg,
                        vol_spike=result.vol_spike,
                        buy_votes=0, sell_votes=0, n_signals=0,
                        signal="SELL",
                    )
                return

        # ── Step 4: time-filter gate ──────────────────────────────────────────
        if not result.in_window:
            log.debug(
                f"[{ts}] {asset.ticker:4}  ⏭ outside trading window"
            )
            return

        buy        = result.buy
        sell       = result.sell
        buy_votes  = result.buy_votes
        sell_votes = result.sell_votes
        n_sigs     = result.n_signals

        # ── Step 5: log + execute ─────────────────────────────────────────────
        v_tag    = "📶" if result.vol_spike else "  "
        log_line = (
            f"[{ts}] {asset.ticker:4}  close={close:>10.2f}  "
            f"B={buy_votes}/{n_sigs}  S={sell_votes}/{n_sigs}  {v_tag}"
        )

        signal_label = "HOLD"
        max_pos    = int(cfg.get("max_open_positions", 30))
        open_count = sum(1 for a in self.assets.values() if a.in_position)

        if buy and not asset.in_position:
            if open_count >= max_pos:
                log.info(
                    f"{log_line}  →  BUY blocked "
                    f"(max {max_pos} positions reached)"
                )
            elif self.place_order(asset, OrderSide.BUY, close, "vote"):
                asset.in_position = True
                signal_label      = "BUY"
                log.info(f"{log_line}  →  BUY")

        elif sell and asset.in_position:
            if self.place_order(asset, OrderSide.SELL, close, "vote"):
                asset.in_position = False
                signal_label      = "SELL"
                log.info(f"{log_line}  →  SELL")

        else:
            pos_tag = "📦 holding" if asset.in_position else "  "
            log.info(f"{log_line}  →  hold  {pos_tag}")

        # ── Step 6: persist ───────────────────────────────────────────────────
        save_indicators(
            conn       = self.conn,
            symbol     = asset.symbol,
            timestamp  = datetime.now(UTC).isoformat(),
            close      = close,
            vol_avg    = result.vol_avg,
            vol_spike  = result.vol_spike,
            buy_votes  = buy_votes,
            sell_votes = sell_votes,
            n_signals  = n_sigs,
            signal     = signal_label,
        )

    # ── WebSocket handler ─────────────────────────────────────────────────────

    async def on_bar(self, bar) -> None:
        """Handle an incoming 1-minute bar from the Alpaca WebSocket.

        Called by ``CryptoDataStream`` each time a bar closes for any
        subscribed symbol.  Execution order:

            1. Hot-reload ``config.json`` (symbol changes included —
               triggers live subscribe/unsubscribe + liquidation).
            2. Route bar to the correct ``AssetState``.
            3. Detect session date rollover → reset VWAP / ORB state.
            4. Persist the raw OHLCVT bar to ``bars.db``.
            5. Append OHLCV to the asset's rolling deques.
            6. Run ``_evaluate()``.

        Args:
            bar: Bar object from ``CryptoDataStream``.  Expected
                attributes: ``symbol``, ``timestamp``, ``open``,
                ``high``, ``low``, ``close``, ``volume``.
        """
        new_symbols = self._reload_config()
        if new_symbols is not None:
            await self._apply_symbols(new_symbols)

        symbol = bar.symbol
        if symbol not in self.assets:
            return

        asset    = self.assets[symbol]
        bar_date = bar.timestamp.strftime("%Y-%m-%d")

        if asset.start_bar(bar_date):
            log.debug(
                f"📅 {asset.ticker}: new session {bar_date} — VWAP/ORB reset"
            )

        save_bar(self.conn, symbol, bar)

        asset.append_bar(
            float(bar.close),
            float(bar.high),
            float(bar.low),
            float(bar.volume),
        )

        ts = datetime.now(UTC).strftime("%H:%M:%S")
        self._evaluate(asset, ts)

    # ── Entry point ───────────────────────────────────────────────────────────

    async def _run_with_retry(self, stream, name: str) -> None:
        """Run stream._run_forever() with exponential-backoff reconnect.

        If the stream crashes unexpectedly (network error, Alpaca
        maintenance…), waits and retries instead of letting the whole
        bot die.  Backoff caps at 60 s.  A clean stop() call raises
        CancelledError which propagates normally for graceful shutdown.

        Args:
            stream: ``CryptoDataStream`` or ``StockDataStream``.
            name (str): Stream label for log messages.
        """
        backoff = 5.0
        while True:
            try:
                await stream._run_forever()
                return  # stream.stop() was called — clean shutdown
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error(
                    f"❌ {name} stream crashed: {exc}  —  "
                    f"reconnecting in {backoff:.0f}s…"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)

    async def _stream_runner(
        self, stream, name: str, ready: asyncio.Event
    ) -> None:
        """Park until the stream has symbols, then run it forever.

        Both runners are created unconditionally at startup; a stream
        whose symbol class is absent from the config simply waits here
        until ``_apply_symbols()`` hot-adds one and sets the event.

        Args:
            stream: ``CryptoDataStream`` or ``StockDataStream``.
            name  (str): Stream label for log messages.
            ready (asyncio.Event): Set once the stream has ≥ 1 symbol.
        """
        await ready.wait()
        log.info(f"📡 {name.capitalize()} stream démarré")
        await self._run_with_retry(stream, name)

    def run(self) -> None:
        """Subscribe to all symbols and start both WebSocket streams concurrently.

        Crypto and stock streams are each subscribed on their respective
        ``DataStream`` objects and then run together in one asyncio event
        loop via ``asyncio.gather``.  Using a single event loop means
        the ``on_bar`` callback is always on the same thread — SQLite
        access is automatically serialised.

        Blocks until all streams end (``Ctrl+C``, network failure, or
        Alpaca disconnection).

        Raises:
            KeyboardInterrupt: Propagated from Ctrl+C for clean shutdown.
            Exception: Any stream or runtime error, after logging.
        """
        # ── Subscribe ─────────────────────────────────────────────────────────
        for s in self._crypto_syms:
            self.crypto_stream.subscribe_bars(self.on_bar, s)
        if self._crypto_syms:
            self._crypto_ready.set()
            log.info(f"📡 Crypto  stream → {self._crypto_syms}")

        for s in self._stock_syms:
            self.stock_stream.subscribe_bars(self.on_bar, s)
        if self._stock_syms:
            self._stock_ready.set()
            log.info(f"📡 Stock   stream → {self._stock_syms}")

        log.info(f"   DB  : {DB_FILE}")
        log.info(f"   Log : {LOG_FILE}")
        log.info(f"   Watching {CONFIG_FILE.name} for live config changes…\n")

        # ── Run both streams in one event loop ────────────────────────────────
        async def _gather() -> None:
            await asyncio.gather(
                self._stream_runner(
                    self.crypto_stream, "crypto", self._crypto_ready
                ),
                self._stream_runner(
                    self.stock_stream, "stock", self._stock_ready
                ),
            )

        try:
            asyncio.run(_gather())
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log.error(f"❌ Stream error: {e}", exc_info=True)
            raise

    def close(self) -> None:
        """Stop both WebSocket streams and close the database connection.

        Stops streams before closing the DB (releases connection slots
        immediately and prevents ``connection limit exceeded`` on restart).
        Each stop is wrapped in try/except so a dead stream does not
        prevent the other from being stopped.
        """
        for stream, name in (
            (self.crypto_stream, "crypto"),
            (self.stock_stream,  "stock"),
        ):
            try:
                stream.stop()
                log.info(f"🔌 {name.capitalize()} stream stopped.")
            except Exception as e:
                log.warning(f"⚠️  Error stopping {name} stream: {e}")
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
        log.info("💾 Shutdown complete.")
