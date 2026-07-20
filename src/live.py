"""
CLI — run the live bot with a given strategy.
=============================================
Usage (from src/)::

    python live.py vote_mr

Config behaviour:

- ``config/config.json`` absent  → created from the strategy;
- present → the keys that diverge from the strategy are reported,
  but the file is authoritative (the bot hot-reloads it continuously
  and the scorer writes the symbol list into it every week).
"""

import argparse
import json

from core.constants import CONFIG_FILE
from strategies import Strategy, load_strategy


def _sync_config(strategy: Strategy) -> None:
    """Seed or diff ``config/config.json`` against the strategy config.

    Args:
        strategy (Strategy): Strategy about to be traded.
    """
    if not CONFIG_FILE.exists():
        CONFIG_FILE.parent.mkdir(exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(strategy.config, indent=4))
        print(f"📝 config créée depuis '{strategy.name}': {CONFIG_FILE}")
        return

    on_disk = json.loads(CONFIG_FILE.read_text())
    diffs = {
        k: (v, on_disk[k])
        for k, v in strategy.config.items()
        # "symbols" diverges by construction: the scorer rewrites the
        # list every week — it is not a strategy drift.
        if k != "symbols" and k in on_disk and on_disk[k] != v
    }
    if diffs:
        print(
            f"⚠️  config.json diverge de la stratégie "
            f"'{strategy.name}' (le fichier fait foi):"
        )
        for k, (want, got) in diffs.items():
            print(f"   {k}: stratégie={want!r}  config.json={got!r}")


def main() -> None:
    """Load the strategy, sync the config and start the bot."""
    parser = argparse.ArgumentParser(
        description="Démarre le bot live avec la stratégie donnée."
    )
    parser.add_argument(
        "strategy",
        help="Nom de la stratégie, ex: vote_mr (fichier strategies/*.py)",
    )
    args = parser.parse_args()

    strategy = load_strategy(args.strategy)
    _sync_config(strategy)

    # Imported here only: live.bot checks .env and connects to the
    # database at import — pointless before the requested strategy is validated.
    from live.bot import main as run_bot
    run_bot()


if __name__ == "__main__":
    main()
