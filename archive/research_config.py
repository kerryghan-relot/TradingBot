"""Shared constants for the lucas-research backtesting suite."""

from pathlib import Path

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent / "resultats"
OUTPUT_DIR.mkdir(exist_ok=True)

CAPITAL_INITIAL: float = 10_000.0
FEES: float = 0.0005        # 0.05% per trade (realistic for 5-min intraday)

BARS_PER_DAY: int = 78      # US session bars at 5-min resolution
BARS_PER_WEEK: int = BARS_PER_DAY * 5
ANNUALIZATION: int = BARS_PER_DAY * 252  # 5-min bars per trading year
