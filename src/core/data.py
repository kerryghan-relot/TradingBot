"""
Historical CSV data access for backtests.
==========================================
Research data is 3 years of 5-minute bars per symbol, stored as
``data/<SYMBOL>_5min_3ans.csv``.  Crypto symbols use ``-`` instead of
``/`` in filenames (``BTC-USD_5min_3ans.csv`` holds ``BTC/USD``).
"""

import csv
from pathlib import Path

from core.constants import DATA_DIR


def list_symbol_csvs(data_dir: Path = DATA_DIR) -> dict[str, Path]:
    """Map trading symbols to their historical CSV files.

    Filenames like ``BTC-USD_5min_3ans.csv`` are mapped back to the
    live symbol notation ``BTC/USD``.

    Args:
        data_dir (Path, optional): Directory containing the CSVs.
            Defaults to ``core.constants.DATA_DIR``.

    Returns:
        dict[str, Path]: ``{"AAPL": ..., "BTC/USD": ...}`` sorted by
            symbol.  Empty when the directory does not exist.
    """
    mapping: dict[str, Path] = {}
    if not data_dir.exists():
        return mapping
    for path in sorted(data_dir.glob("*_5min_3ans.csv")):
        stem = path.name.split("_")[0]
        symbol = stem.replace("-", "/") if stem.endswith("-USD") else stem
        mapping[symbol] = path
    return mapping


def load_bars_csv(path: Path) -> list[dict]:
    """Load one historical CSV as a list of bar dicts.

    Output rows match ``core.broker.fetch_bars`` (``timestamp`` string
    plus float OHLCV) so they can be fed straight into
    ``core.simulation.simulate``.  Missing volume (crypto CSVs) becomes
    0.0.

    Args:
        path (Path): CSV file with columns
            ``datetime,open,high,low,close,volume``.

    Returns:
        list[dict]: Chronologically ordered bar dicts.
    """
    bars: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bars.append({
                "timestamp": row["datetime"],
                "open":      float(row["open"]),
                "high":      float(row["high"]),
                "low":       float(row["low"]),
                "close":     float(row["close"]),
                "volume":    float(row.get("volume") or 0.0),
            })
    return bars
