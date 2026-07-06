"""
CLI — lance le bot live avec une stratégie donnée.
===================================================
Usage (depuis lucas-trading/)::

    python live.py vote_mr

Comportement config :

- ``config/config.json`` absent  → créé depuis la stratégie ;
- présent → les clés qui divergent de la stratégie sont signalées,
  mais le fichier fait foi (le bot le hot-reload en continu et le
  scorer y écrit la liste des symboles chaque semaine).
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
        # "symbols" diverge par construction: le scorer réécrit la
        # liste chaque semaine — ce n'est pas une dérive de stratégie.
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
    """Charge la stratégie, synchronise la config et démarre le bot."""
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

    # Importé ici seulement: live.bot vérifie .env et ouvre bars.db à
    # l'import — inutile avant d'avoir validé la stratégie demandée.
    from live.bot import main as run_bot
    run_bot()


if __name__ == "__main__":
    main()
