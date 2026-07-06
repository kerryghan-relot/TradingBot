"""
Strategy registry — one module per strategy, used by backtest AND live.
========================================================================
A strategy is a named, frozen configuration of the shared vote engine
(``core.engine``): which signals vote, their parameters, the vote
threshold and the stop-loss.  The SAME dict drives:

- the event-driven backtest — ``python backtest.py <name>`` — and
- the live bot — ``python live.py <name>`` — which seeds
  ``config/config.json`` with it.

To create a new strategy, copy ``vote_mr.py``, override the config
keys you want to change, and it becomes available to both CLIs under
its module name.  New signal *types* are added in ``core/signals.py``
and wired into ``core/engine.py`` first.
"""

import importlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Strategy:
    """A named configuration of the shared vote engine.

    Attributes:
        name        (str) : Module name, e.g. ``"vote_mr"``.
        description (str) : One-line human description.
        config      (dict): Full engine configuration (see
            ``core.config.DEFAULT_CONFIG`` for every key).
    """

    name: str
    description: str
    config: dict = field(default_factory=dict)


def load_strategy(name: str) -> Strategy:
    """Import ``strategies.<name>`` and return its ``STRATEGY`` object.

    Args:
        name (str): Strategy module name, e.g. ``"vote_mr"``.

    Returns:
        Strategy: The strategy declared by the module.

    Raises:
        SystemExit: When the module or its ``STRATEGY`` is missing.
    """
    try:
        module = importlib.import_module(f"strategies.{name}")
    except ModuleNotFoundError as e:
        raise SystemExit(
            f"Stratégie inconnue: '{name}' — attendu strategies/{name}.py"
        ) from e
    strategy = getattr(module, "STRATEGY", None)
    if strategy is None:
        raise SystemExit(f"strategies/{name}.py ne définit pas STRATEGY")
    return strategy
