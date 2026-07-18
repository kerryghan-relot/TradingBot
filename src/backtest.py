"""
CLI — backtest a strategy over the historical CSVs.
===================================================
Replays the strategy bar by bar via ``core.engine`` — exactly the
code the live bot runs.

Usage (from src/)::

    python backtest.py vote_mr
    python backtest.py vote_mr --symbols AAPL NVDA BTC/USD
"""

import argparse
import logging

from backtest.event_driven import run
from strategies import load_strategy


def main() -> None:
    """Parse the command line and run the event-driven backtest."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Backtest événementiel d'une stratégie "
                    "(même code que le bot live).",
    )
    parser.add_argument(
        "strategy",
        help="Nom de la stratégie, ex: vote_mr (fichier strategies/*.py)",
    )
    parser.add_argument(
        "--symbols", nargs="+", default=None, metavar="SYM",
        help="Limiter à ces symboles (défaut: tous les CSV de data/).",
    )
    args = parser.parse_args()

    strategy = load_strategy(args.strategy)
    run(strategy, symbols=args.symbols)


if __name__ == "__main__":
    main()
