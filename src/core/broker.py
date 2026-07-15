"""
Alpaca API access shared by the live bot and the scorer.
=========================================================
Single owner of the ``.env`` credential check, Alpaca client
construction, the crypto/stock routing rule and historical bar
fetching.  Before this module existed, ``bot.py`` and ``scorer.py``
each carried their own copy of all four.

Order placement deliberately stays in ``live/bot.py`` — only the bot
trades.
"""

import logging
import os
from datetime import datetime

from alpaca.data.enums import DataFeed
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from dotenv import load_dotenv

load_dotenv()

API_KEY:    str | None = os.getenv("ALPACA_API_KEY")
API_SECRET: str | None = os.getenv("ALPACA_SECRET_KEY")
if not API_KEY or not API_SECRET:
    raise RuntimeError(
        "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env"
    )

PAPER: bool = True   # True = paper trading, False = live

_log: logging.Logger = logging.getLogger(__name__)


def is_crypto(symbol: str) -> bool:
    """Return True if the symbol is a crypto pair (contains ``/``).

    Alpaca crypto symbols use slash notation (``"BTC/USD"``); US stock
    tickers never contain a slash (``"AAPL"``).

    Args:
        symbol (str): Asset identifier.

    Returns:
        bool: ``True`` for crypto, ``False`` for stocks/ETFs.
    """
    return "/" in symbol


def make_data_clients() -> tuple[
    CryptoHistoricalDataClient, StockHistoricalDataClient
]:
    """Build the pair of Alpaca historical-data clients.

    Returns:
        tuple[CryptoHistoricalDataClient, StockHistoricalDataClient]:
            Crypto client first, stock client second.
    """
    return (
        CryptoHistoricalDataClient(API_KEY, API_SECRET),
        StockHistoricalDataClient(API_KEY, API_SECRET),
    )


def make_trading_client(paper: bool = PAPER) -> TradingClient:
    """Build the Alpaca REST trading client.

    Args:
        paper (bool, optional): Route orders to the paper account.
            Defaults to ``PAPER``.

    Returns:
        TradingClient: Authenticated Alpaca trading client.
    """
    return TradingClient(API_KEY, API_SECRET, paper=paper)


def fetch_bars(
    crypto_client: CryptoHistoricalDataClient,
    stock_client:  StockHistoricalDataClient,
    symbol: str,
    start:  datetime,
    end:    datetime,
    log: logging.Logger | None = None,
) -> list[dict]:
    """Fetch 1-minute OHLCVT bars from Alpaca for one symbol.

    Routes to the correct Alpaca client based on the symbol type:
    crypto pairs (containing ``"/"``) use ``CryptoHistoricalDataClient``;
    stock tickers use ``StockHistoricalDataClient``.

    Args:
        crypto_client (CryptoHistoricalDataClient): Alpaca crypto client.
        stock_client  (StockHistoricalDataClient) : Alpaca stock client.
        symbol (str): Asset symbol, e.g. ``"BTC/USD"`` or ``"AAPL"``.
        start  (datetime): Inclusive start of the lookback window (UTC).
        end    (datetime): Exclusive end of the lookback window (UTC).
        log (logging.Logger, optional): Logger for fetch diagnostics.
            Defaults to this module's logger.

    Returns:
        list[dict]: Chronologically ordered bar dicts.  Empty on error.
    """
    log = log or _log
    try:
        if is_crypto(symbol):
            bar_set = crypto_client.get_crypto_bars(
                CryptoBarsRequest(
                    symbol_or_symbols = symbol,
                    timeframe         = TimeFrame.Minute,
                    start             = start,
                    end               = end,
                )
            )
        else:
            bar_set = stock_client.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols = symbol,
                    timeframe         = TimeFrame.Minute,
                    start             = start,
                    end               = end,
                    feed              = DataFeed.IEX,
                )
            )
        raw = bar_set.data.get(symbol, [])
    except Exception as exc:
        log.error(f"  ❌ {symbol}: fetch failed — {exc}")
        return []

    bars = [
        {
            "timestamp": b.timestamp.isoformat(),
            "open":      float(b.open),
            "high":      float(b.high),
            "low":       float(b.low),
            "close":     float(b.close),
            "volume":    float(b.volume),
        }
        for b in raw
    ]
    log.debug(f"  {symbol}: fetched {len(bars)} bars")
    return bars
