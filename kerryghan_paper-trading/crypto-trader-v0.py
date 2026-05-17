"""
Multi-Asset Crypto Trading Bot — powered by alpaca-py
======================================================
Assets  : BTC/USD and ETH/USD (shared config, independent state)

Strategy: Regime-aware signal engine
─────────────────────────────────────────────────────────────────
  Bollinger Band width determines the market regime each bar:

  RANGING market (BB width < bb_width_threshold)
    → Price oscillates in a band → trade reversals
    → Signal: RSI extreme  AND  Bollinger Band touch  AND  volume spike

  TRENDING market (BB width ≥ bb_width_threshold)
    → Price is breaking out → ride momentum
    → Signal: EMA cross  AND  MACD crossover  AND  volume spike

  Stop-loss always active, regardless of regime.

Persistence: every bar is written to bars.db (SQLite) as full OHLCVT.
On startup the last DEQUE_SIZE rows per symbol are reloaded — no warmup wait.

Hyperparameters hot-reloaded from config.json every bar — no restart needed.

Requirements:
    pip install alpaca-py

Alpaca docs: https://docs.alpaca.markets/
"""

import json
import math
import sqlite3
from pathlib import Path
from datetime import datetime, UTC
from collections import deque
from typing import Tuple

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.live.crypto import CryptoDataStream


# ── Static config (restart required to change) ────────────────────────────────

from dotenv import load_dotenv
import os

load_dotenv()

API_KEY    = os.getenv("ALPACA_API_KEY")
API_SECRET = os.getenv("ALPACA_SECRET_KEY")
PAPER      = True

SYMBOLS     = ["BTC/USD", "ETH/USD"]
CONFIG_FILE = Path(__file__).parent / "config.json"
DB_FILE     = Path(__file__).parent / "bars.db"
DEQUE_SIZE  = 200   # bars kept in memory per symbol

# ── Default hyperparameters ────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    # Position sizing & risk
    "order_qty_btc":       0.001,   # BTC per order
    "order_qty_eth":       0.01,    # ETH per order
    "stop_loss_pct":       0.02,    # 2% drop from entry → emergency exit

    # RSI (ranging regime)
    "rsi_period":          14,
    "rsi_oversold":        30,
    "rsi_overbought":      70,

    # Bollinger Bands (regime detector + ranging signal)
    "bb_period":           20,
    "bb_std":              2.0,
    "bb_width_threshold":  0.03,    # <3% width = ranging, ≥3% = trending

    # MACD (trending regime)
    "macd_fast":           12,
    "macd_slow":           26,
    "macd_signal":         9,

    # EMA cross (trending regime)
    "ema_fast":            9,
    "ema_slow":            21,

    # Volume filter (both regimes)
    "volume_factor":       1.5,     # bar volume must be > 1.5× recent average
    "volume_period":       20,      # how many bars to average volume over
}


# ══════════════════════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict | None:
    """
    Read config.json.  Returns None on parse error (caller keeps previous cfg).
    Creates the file with defaults if it doesn't exist yet.
    """
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=4))
        print(f"📝 Created default config at {CONFIG_FILE}")
        return DEFAULT_CONFIG.copy()
    try:
        return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text())}
    except json.JSONDecodeError:
        print("⚠️  config.json parse error — keeping previous values")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Database
# ══════════════════════════════════════════════════════════════════════════════

def init_db(conn: sqlite3.Connection):
    """Create the bars table and index if they don't exist yet."""
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
    # Fast chronological lookups per symbol
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bars_symbol_ts
        ON bars (symbol, timestamp)
    """)
    conn.commit()


def save_bar(conn: sqlite3.Connection, symbol: str, bar):
    """
    Insert one full OHLCVT row.
    INSERT OR IGNORE means duplicates (e.g. the last bar re-sent on reconnect)
    are silently skipped — the DB never double-counts a bar.
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


def load_bars(conn: sqlite3.Connection, symbol: str, limit: int) -> list[dict]:
    """
    Return the most recent `limit` bars for a symbol, returned oldest-first
    so they can be appended to the deques in chronological order.
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
        for r in reversed(rows)   # oldest first
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  Indicators  (pure functions, no side effects)
# ══════════════════════════════════════════════════════════════════════════════

def ema(values: list[float], period: int) -> float | None:
    """Exponential moving average of the last `period` values."""
    if len(values) < period:
        return None
    k      = 2 / (period + 1)
    result = values[-period]
    for v in values[-period + 1:]:
        result = v * k + result * (1 - k)
    return result


def compute_rsi(closes: list[float], period: int) -> float | None:
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


def compute_bollinger(closes: list[float], period: int, num_std: float):
    """Returns (middle, upper, lower, width_pct) or None."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid    = sum(window) / period
    std    = math.sqrt(sum((x - mid) ** 2 for x in window) / period)
    upper  = mid + num_std * std
    lower  = mid - num_std * std
    width  = (upper - lower) / mid if mid else 0
    return mid, upper, lower, width


def compute_macd(closes: list[float], fast: int, slow: int, signal: int):
    """Returns (macd_line, signal_line, histogram) or None."""
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


def compute_ema_cross(closes: list[float], fast: int, slow: int):
    """Returns (ema_fast, ema_slow, crossed_up, crossed_down) or None."""
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
    """True if latest volume exceeds factor × recent average."""
    if len(volumes) < period + 1:
        return False
    avg = sum(volumes[-period-1:-1]) / period
    return volumes[-1] > factor * avg


# ══════════════════════════════════════════════════════════════════════════════
#  Per-asset state
# ══════════════════════════════════════════════════════════════════════════════

class AssetState:
    """Rolling data and position state for one symbol."""

    def __init__(self, symbol: str):
        self.symbol      = symbol
        self.closes      = deque(maxlen=DEQUE_SIZE)
        self.volumes     = deque(maxlen=DEQUE_SIZE)
        self.in_position = False
        self.entry_price = None

    @property
    def ticker(self) -> str:
        return self.symbol.split("/")[0]

    def preload(self, bars: list[dict]):
        """
        Populate deques from DB rows on startup.
        Only close + volume go into memory — the rest stays in the DB,
        available whenever you need O/H/L for future indicators.
        """
        for b in bars:
            self.closes.append(b["close"])
            self.volumes.append(b["volume"])


# ══════════════════════════════════════════════════════════════════════════════
#  Bot
# ══════════════════════════════════════════════════════════════════════════════

class CryptoBot:

    def __init__(self):
        self.trading_client = TradingClient(API_KEY, API_SECRET, paper=PAPER)
        self.stream         = CryptoDataStream(API_KEY, API_SECRET)
        self.cfg            = load_config()
        self.assets         = {s: AssetState(s) for s in SYMBOLS}

        # ── Database setup + startup reload ───────────────────────────────────
        self.conn = sqlite3.connect(DB_FILE)
        init_db(self.conn)
        self._preload_from_db()

        self._print_config("🤖 Bot started")

    # ── Startup reload ────────────────────────────────────────────────────────

    def _preload_from_db(self):
        for symbol, asset in self.assets.items():
            bars = load_bars(self.conn, symbol, DEQUE_SIZE)
            if bars:
                asset.preload(bars)
                print(f"💾 {asset.ticker}: loaded {len(bars)} bars from DB "
                      f"(last close: {bars[-1]['timestamp'][:16]}  "
                      f"@ {bars[-1]['close']:.2f})")
            else:
                print(f"💾 {asset.ticker}: no history — starting fresh")

    # ── Config ────────────────────────────────────────────────────────────────

    def _reload_config(self):
        new_cfg = load_config()
        if new_cfg is None:
            return
        changed = [k for k in DEFAULT_CONFIG if self.cfg.get(k) != new_cfg.get(k)]
        if changed:
            self.cfg = new_cfg
            self._print_config(f"🔄 Config reloaded ({', '.join(changed)} changed)")

    def _print_config(self, label: str):
        c = self.cfg
        print(
            f"{label}\n"
            f"   Symbols : {', '.join(SYMBOLS)}  |  paper={PAPER}\n"
            f"   Sizes   : BTC={c['order_qty_btc']}  ETH={c['order_qty_eth']}"
            f"  |  stop-loss={c['stop_loss_pct']*100:.0f}%\n"
            f"   RSI     : period={c['rsi_period']}  buy<{c['rsi_oversold']}"
            f"  sell>{c['rsi_overbought']}\n"
            f"   BB      : period={c['bb_period']}  std={c['bb_std']}"
            f"  |  width threshold={c['bb_width_threshold']*100:.1f}%\n"
            f"   MACD    : {c['macd_fast']}/{c['macd_slow']}/{c['macd_signal']}"
            f"  |  EMA cross: {c['ema_fast']}/{c['ema_slow']}\n"
            f"   Volume  : spike if >{c['volume_factor']}× {c['volume_period']}-bar avg\n"
        )

    # ── Orders ────────────────────────────────────────────────────────────────

    def _order_qty(self, symbol: str) -> float:
        return self.cfg["order_qty_btc"] if "BTC" in symbol else self.cfg["order_qty_eth"]

    def place_order(self, asset: AssetState, side: OrderSide, close: float, reason: str):
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
            print(f"    ✅ {asset.ticker} {action}  ({reason})  id={order.id}")
            asset.entry_price = close if side == OrderSide.BUY else None
        except Exception as e:
            print(f"    ❌ {asset.ticker} order failed: {e}")

    # ── Signal engine ─────────────────────────────────────────────────────────

    def _evaluate(self, asset: AssetState, ts: str):
        c      = self.cfg
        closes = list(asset.closes)
        vols   = list(asset.volumes)
        close  = closes[-1]

        # ── Warmup check ──────────────────────────────────────────────────────
        needed = max(c["rsi_period"] + 1, c["bb_period"],
                     c["macd_slow"] + c["macd_signal"],
                     c["ema_slow"] + 1, c["volume_period"] + 1)
        if len(closes) < needed:
            print(f"[{ts}] {asset.ticker:3}  ⏳ warming up ({len(closes)}/{needed} bars)")
            return

        # ── Compute all indicators ────────────────────────────────────────────
        rsi    = compute_rsi(closes, c["rsi_period"])
        bb     = compute_bollinger(closes, c["bb_period"], c["bb_std"])
        macd   = compute_macd(closes, c["macd_fast"], c["macd_slow"], c["macd_signal"])
        cross  = compute_ema_cross(closes, c["ema_fast"], c["ema_slow"])
        vol_ok = volume_spike(vols, c["volume_period"], c["volume_factor"])

        if None in (rsi, bb, macd, cross):
            print(f"[{ts}] {asset.ticker:3}  ⏳ indicators initialising")
            return

        _, bb_upper, bb_lower, bb_width        = bb
        macd_line, signal_line, _              = macd
        _, _, ema_crossed_up, ema_crossed_down = cross

        # ── Stop-loss (always runs first) ─────────────────────────────────────
        if asset.in_position and asset.entry_price:
            drop = (asset.entry_price - close) / asset.entry_price
            if drop >= c["stop_loss_pct"]:
                print(f"[{ts}] {asset.ticker:3}  🛑 STOP-LOSS "
                      f"({drop*100:.1f}% drop)  close={close:.2f}")
                self.place_order(asset, OrderSide.SELL, close, "stop-loss")
                asset.in_position = False
                return

        # ── Regime detection ──────────────────────────────────────────────────
        ranging = bb_width < c["bb_width_threshold"]
        regime  = "RANGING" if ranging else "TRENDING"

        # ── Signal logic ──────────────────────────────────────────────────────
        buy_signal  = False
        sell_signal = False

        if ranging:
            buy_signal  = (rsi < c["rsi_oversold"]  and close <= bb_lower and vol_ok)
            sell_signal = (rsi > c["rsi_overbought"] and close >= bb_upper and vol_ok)
        else:
            macd_bull   = macd_line > signal_line
            macd_bear   = macd_line < signal_line
            buy_signal  = (ema_crossed_up   and macd_bull and vol_ok)
            sell_signal = (ema_crossed_down and macd_bear and vol_ok)

        # ── Print & execute ───────────────────────────────────────────────────
        vol_tag = "📶" if vol_ok else "  "
        print(
            f"[{ts}] {asset.ticker:3}  {regime:8}  "
            f"close={close:>10.2f}  RSI={rsi:5.1f}  "
            f"BB_w={bb_width*100:4.1f}%  "
            f"MACD={'▲' if macd_line > signal_line else '▼'}  "
            f"EMA={'▲' if cross[0] > cross[1] else '▼'}  {vol_tag}",
            end=""
        )

        if buy_signal and not asset.in_position:
            print(f"  →  BUY ({regime})")
            self.place_order(asset, OrderSide.BUY, close, regime.lower())
            asset.in_position = True

        elif sell_signal and asset.in_position:
            print(f"  →  SELL ({regime})")
            self.place_order(asset, OrderSide.SELL, close, regime.lower())
            asset.in_position = False

        else:
            in_pos = "📦 holding" if asset.in_position else "  "
            print(f"  →  hold  {in_pos}")

    # ── WebSocket handler ─────────────────────────────────────────────────────

    async def on_bar(self, bar):
        """Called for every 1-min bar on any subscribed symbol."""
        self._reload_config()

        symbol = bar.symbol
        if symbol not in self.assets:
            return

        asset = self.assets[symbol]

        # 1. Persist full OHLCVT to DB — before touching the deques
        save_bar(self.conn, symbol, bar)

        # 2. Update in-memory deques (close + volume — all current indicators need)
        asset.closes.append(float(bar.close))
        asset.volumes.append(float(bar.volume))

        ts = datetime.now(UTC).strftime("%H:%M:%S")
        self._evaluate(asset, ts)

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self):
        for symbol in SYMBOLS:
            self.stream.subscribe_bars(self.on_bar, symbol)
        print(f"📡 Subscribed to: {', '.join(SYMBOLS)}")
        print(f"   DB : {DB_FILE}")
        print(f"   Watching {CONFIG_FILE.name} for live config changes...\n")
        self.stream.run()

    def close(self):
        """Flush and close the DB connection on shutdown."""
        self.conn.close()


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot = CryptoBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped.")
    finally:
        bot.close()
        print("💾 Database closed.")