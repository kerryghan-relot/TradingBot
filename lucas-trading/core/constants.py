"""
Shared constants for lucas-trading.
====================================
Single source of truth for filesystem paths, the 30-symbol universe
and the annualisation factors used by both the backtest side
(``backtest/``) and the live side (``live/``).  Import from here
instead of copy-pasting.
"""

from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────
# This file lives in lucas-trading/core/ — parent.parent is the
# lucas-trading/ root.
ROOT_DIR: Path = Path(__file__).resolve().parent.parent

DATA_DIR:    Path = ROOT_DIR / "data"                  # historical CSVs
OUTPUT_DIR:  Path = ROOT_DIR / "results"               # backtest outputs
CONFIG_FILE: Path = ROOT_DIR / "config" / "config.json"
# Live bar/indicator/trade storage now lives in PostgreSQL — see
# core/db.py.  Connection settings come from the DATABASE_URL env var.

# Log directory shared between the bot (writer) and the dashboard
# (reads bot.log to surface recent errors).  A named Docker volume is
# mounted here so both containers see the same file.
LOG_DIR:     Path = ROOT_DIR / "logs"
LOG_FILE:    Path = LOG_DIR / "bot.log"

OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# ── Symbol universe ───────────────────────────────────────────────────
SYMBOLS: list[str] = [
    "AAPL", "ABBV", "AMD",  "AMZN", "BAC",  "BTC/USD",
    "COP",  "CVX",  "DIS",  "ETH/USD", "GOOGL", "GS",
    "JPM",  "META", "MRK",  "MS",   "MSFT", "NFLX",
    "NVDA", "PLTR", "PYPL", "QQQ",  "ROKU", "SNAP",
    "SPY",  "SQ",   "TSLA", "UBER", "UNH",  "XOM",
]

CRYPTO_SYMBOLS: set[str] = {"BTC/USD", "ETH/USD"}

# ── Backtesting (5-minute research bars) ──────────────────────────────
CAPITAL_INITIAL: float = 10_000.0
FEES: float = 0.0005        # 0.05% per trade (realistic for 5-min intraday)

BARS_PER_DAY: int = 78      # US session bars at 5-min resolution
BARS_PER_WEEK: int = BARS_PER_DAY * 5
ANNUALIZATION: int = BARS_PER_DAY * 252     # stock 5-min bars per year
ANNUALIZATION_CRYPTO: int = 288 * 365       # crypto 5-min bars (24/7)

# ── Live (1-minute Alpaca bars) ───────────────────────────────────────
# Critical for correct Sharpe annualisation in live/scorer.py.
BARS_PER_YEAR_CRYPTO: int = 525_600   # 24 h × 60 min × 365 days (24/7)
BARS_PER_YEAR_STOCK:  int = 98_280    # 390 min/day × 252 trading days
