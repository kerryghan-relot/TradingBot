"""
BTC/USD RSI Trading Bot — powered by alpaca-py
================================================
Strategy:
  - RSI < rsi_oversold   →  BUY
  - RSI > rsi_overbought →  SELL
  - Price drops stop_loss_pct below entry → emergency SELL
  - Otherwise → hold

Hyperparameters are hot-reloaded from config.json every bar tick.
Edit config.json while the bot is running — no restart needed.

Requirements:
    pip install alpaca-py

Alpaca docs: https://docs.alpaca.markets/
"""

import json
from pathlib import Path
from datetime import datetime, UTC
from collections import deque

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.live.crypto import CryptoDataStream


# ── Static config (restart required to change these) ──────────────────────────

from dotenv import load_dotenv
import os

load_dotenv()

API_KEY    = os.getenv("ALPACA_API_KEY")
API_SECRET = os.getenv("ALPACA_SECRET_KEY")
PAPER      = True
SYMBOL     = "BTC/USD"

CONFIG_FILE = Path(__file__).parent / "config.json"

# ── Defaults written to config.json if the file doesn't exist yet ─────────────

DEFAULT_CONFIG = {
    "rsi_period":      14,
    "rsi_oversold":    30,
    "rsi_overbought":  70,
    "order_qty":       0.001,
    "stop_loss_pct":   0.02,
}


# ── Config loader ──────────────────────────────────────────────────────────────

def load_config() -> dict:
    """
    Read config.json from disk.
    - Creates it with defaults if it doesn't exist yet.
    - Falls back to defaults silently on parse errors (bad JSON while mid-edit).
    """
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=4))
        print(f"📝 Created default config at {CONFIG_FILE}")
        return DEFAULT_CONFIG.copy()

    try:
        cfg = json.loads(CONFIG_FILE.read_text())
        # Fill in any missing keys with defaults (forward compatibility)
        return {**DEFAULT_CONFIG, **cfg}
    except json.JSONDecodeError:
        # File is mid-save or malformed — keep using last known good config
        print("⚠️  config.json parse error — keeping previous values")
        return None   # Caller will retain the last valid config


# ── RSI Calculation ────────────────────────────────────────────────────────────

def compute_rsi(closes: list[float], period: int) -> float | None:
    """
    Classic Wilder RSI.
    Returns None if there aren't enough data points yet.
    """
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    avg_gain = sum(d for d in deltas[:period] if d > 0) / period
    avg_loss = sum(-d for d in deltas[:period] if d < 0) / period

    for delta in deltas[period:]:
        avg_gain = (avg_gain * (period - 1) + max(delta, 0))  / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0)) / period

    if avg_loss == 0:
        return 100.0

    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)


# ── Trading Bot ────────────────────────────────────────────────────────────────

class RSIBot:
    def __init__(self):
        self.trading_client = TradingClient(API_KEY, API_SECRET, paper=PAPER)
        self.stream         = CryptoDataStream(API_KEY, API_SECRET)

        self.cfg         = load_config()          # Current live config
        self.closes      = deque(maxlen=50)        # Rolling close prices
        self.in_position = False
        self.entry_price = None

        self._print_config("🤖 Bot started")

    # ── Config ────────────────────────────────────────────────────────────────

    def _reload_config(self):
        """Re-read config.json; log a message if any value changed."""
        new_cfg = load_config()
        if new_cfg is None:
            return  # Parse error mid-save — keep current config

        changed = [k for k in self.cfg if self.cfg[k] != new_cfg.get(k)]
        if changed:
            self.cfg = new_cfg
            self._print_config(f"🔄 Config reloaded ({', '.join(changed)} changed)")

    def _print_config(self, label: str):
        c = self.cfg
        print(f"{label} | RSI period={c['rsi_period']} "
              f"buy<{c['rsi_oversold']} sell>{c['rsi_overbought']} "
              f"qty={c['order_qty']} BTC  stop-loss={c['stop_loss_pct']*100:.0f}%")

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(self, side: OrderSide, close: float):
        action = "BUY 🟢" if side == OrderSide.BUY else "SELL 🔴"
        try:
            order = self.trading_client.submit_order(
                MarketOrderRequest(
                    symbol        = SYMBOL,
                    qty           = self.cfg["order_qty"],
                    side          = side,
                    time_in_force = TimeInForce.GTC,
                )
            )
            print(f"  ✅ Order submitted → {action}  id={order.id}")
            self.entry_price = close if side == OrderSide.BUY else None
        except Exception as e:
            print(f"  ❌ Order failed: {e}")

    # ── Bar handler ───────────────────────────────────────────────────────────

    async def on_bar(self, bar):
        """Fires every minute. Reloads config first, then evaluates strategy."""

        # 1. Hot-reload config — cheap file read, happens every bar
        self._reload_config()
        c = self.cfg

        close = float(bar.close)
        self.closes.append(close)
        ts = datetime.now(UTC).strftime("%H:%M:%S")

        rsi = compute_rsi(list(self.closes), c["rsi_period"])

        if rsi is None:
            needed = c["rsi_period"] + 1
            print(f"[{ts}] 📊 Collecting data... ({len(self.closes)}/{needed} bars)  close={close:.2f}")
            return

        # 2. Stop-loss (priority over RSI signals)
        if self.in_position and self.entry_price:
            drop = (self.entry_price - close) / self.entry_price
            if drop >= c["stop_loss_pct"]:
                print(f"[{ts}] 📊 RSI={rsi:5.1f}  close={close:.2f}"
                      f"  →  STOP-LOSS hit ({drop*100:.1f}% drop) → SELL 🛑")
                self.place_order(OrderSide.SELL, close)
                self.in_position = False
                return

        # 3. RSI signals
        print(f"[{ts}] 📊 RSI={rsi:5.1f}  close={close:.2f}", end="")

        if rsi < c["rsi_oversold"] and not self.in_position:
            print("  →  OVERSOLD → placing BUY")
            self.place_order(OrderSide.BUY, close)
            self.in_position = True

        elif rsi > c["rsi_overbought"] and self.in_position:
            print("  →  OVERBOUGHT → placing SELL")
            self.place_order(OrderSide.SELL, close)
            self.in_position = False

        else:
            print("  →  hold")

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self):
        self.stream.subscribe_bars(self.on_bar, SYMBOL)
        print(f"📡 Subscribed to {SYMBOL} bars. Watching {CONFIG_FILE.name} for changes...\n")
        self.stream.run()


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot = RSIBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped.")