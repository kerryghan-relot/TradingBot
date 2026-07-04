"""
Shared constants for lucas-live-trading.
=========================================
Single source of truth for the 30-symbol universe and
annualisation factors used across bot.py, scorer.py and
seed_fake_data.py.  Import from here instead of copy-pasting.
"""

SYMBOLS: list[str] = [
    "AAPL", "ABBV", "AMD",  "AMZN", "BAC",  "BTC/USD",
    "COP",  "CVX",  "DIS",  "ETH/USD", "GOOGL", "GS",
    "JPM",  "META", "MRK",  "MS",   "MSFT", "NFLX",
    "NVDA", "PLTR", "PYPL", "QQQ",  "ROKU", "SNAP",
    "SPY",  "SQ",   "TSLA", "UBER", "UNH",  "XOM",
]

CRYPTO_SYMBOLS: set[str] = {"BTC/USD", "ETH/USD"}

# 1-minute bars per trading year, by asset class.
# Critical for correct Sharpe annualisation in scorer.py.
BARS_PER_YEAR_CRYPTO: int = 525_600   # 24 h × 60 min × 365 days (24/7)
BARS_PER_YEAR_STOCK:  int = 98_280    # 390 min/day × 252 trading days
