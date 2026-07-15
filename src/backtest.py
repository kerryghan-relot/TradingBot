"""
CLI — backtest une stratégie sur les CSV historiques.
======================================================
Rejoue la stratégie bar par bar via ``core.engine`` — exactement le
code que le bot live exécute.

Usage (depuis src/)::

    python backtest.py vote_mr
    python backtest.py vote_mr --symbols AAPL NVDA BTC/USD
"""

import argparse
import logging

from backtest.event_driven import run
from strategies import load_strategy


def main() -> None:
    """Parse la ligne de commande et lance le backtest événementiel."""
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
