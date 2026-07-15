"""Strategy discovery and config.json read/write for the dashboard.

Lists the strategies declared under ``strategies/*.py``, reports which
one the live ``config/config.json`` currently matches, and lets the UI
switch strategy or edit individual config keys.  All writes go through
``config/config.json`` — the same file the live bot hot-reloads.
"""

import importlib
import json
import pkgutil
from typing import Any

from core.config import DEFAULT_CONFIG
from core.constants import CONFIG_FILE
import strategies as strategies_pkg
from strategies import Strategy


def _universe(config: dict) -> str:
    """Classify a strategy universe from its symbol list.

    Returns:
        str: ``"crypto"`` (only BTC/ETH), ``"action"`` (no crypto) or
            ``"all"`` (mixed).
    """
    symbols = config.get("symbols", []) or []
    has_crypto = any("/" in s or s in {"BTC", "ETH"} for s in symbols)
    has_stock = any("/" not in s and s not in {"BTC", "ETH"} for s in symbols)
    if has_crypto and not has_stock:
        return "crypto"
    if has_stock and not has_crypto:
        return "action"
    return "all"


def discover() -> list[Strategy]:
    """Import every ``strategies/*.py`` module exposing a STRATEGY.

    Returns:
        list[Strategy]: All declared strategies, sorted by name. The
            canonical ``vote_mr`` is guaranteed present as a fallback.
    """
    found: list[Strategy] = []
    for mod in pkgutil.iter_modules(strategies_pkg.__path__):
        if mod.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"strategies.{mod.name}")
        except Exception:
            continue
        strat = getattr(module, "STRATEGY", None)
        if isinstance(strat, Strategy):
            found.append(strat)
    if not found:
        found.append(Strategy(
            name="vote_mr",
            description="Configuration par défaut",
            config=dict(DEFAULT_CONFIG),
        ))
    return sorted(found, key=lambda s: s.name)


def read_config() -> dict:
    """Return the live config merged over ``DEFAULT_CONFIG``.

    Returns:
        dict: The effective configuration the bot would load.
    """
    base = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            base.update(json.loads(CONFIG_FILE.read_text()))
        except json.JSONDecodeError:
            pass
    return base


def active_strategy_id() -> str:
    """Return the id of the strategy whose config matches disk best.

    Matches on the non-symbol keys (symbols drift via the scorer); the
    strategy sharing the most values with ``config.json`` wins.
    """
    cfg = read_config()
    best, best_score = "", -1
    for strat in discover():
        score = sum(
            1 for k, v in strat.config.items()
            if k != "symbols" and cfg.get(k) == v
        )
        if score > best_score:
            best, best_score = strat.name, score
    return best


def strategies_payload() -> dict:
    """Return the strategy list and the active id for the API.

    Returns:
        dict: ``{"active": str, "strategies": [{id, label, description,
            universe, config}]}``.
    """
    active = active_strategy_id()
    return {
        "active": active,
        "strategies": [
            {
                "id": s.name,
                "label": _pretty(s.name),
                "description": s.description,
                "universe": _universe(s.config),
                "config": s.config,
            }
            for s in discover()
        ],
    }


def _pretty(name: str) -> str:
    """Turn a module name into a title-cased label."""
    return name.replace("_", " ").title()


def select_strategy(strategy_id: str) -> dict:
    """Write a strategy's config to ``config.json`` (preserving symbols).

    The live symbol list is kept as-is when the target strategy shares
    the default universe, so switching a signal set never wipes the
    scorer's symbol selection.

    Args:
        strategy_id (str): Module name of the strategy to activate.

    Returns:
        dict: The config now on disk.

    Raises:
        KeyError: When no strategy matches ``strategy_id``.
    """
    match = next((s for s in discover() if s.name == strategy_id), None)
    if match is None:
        raise KeyError(strategy_id)
    new_cfg = dict(match.config)
    current = read_config()
    if current.get("symbols"):
        new_cfg["symbols"] = current["symbols"]
    _write(new_cfg)
    return new_cfg


# Keys the config editor is allowed to overwrite (typed for coercion).
EDITABLE: dict[str, type] = {
    "vote_threshold": int, "stop_loss_pct": float,
    "max_open_positions": int, "total_capital": float,
    "min_position_pct": float, "max_position_pct": float,
    "backfill_days": int, "bb_period": int, "bb_std": float,
    "ema_fast": int, "ema_slow": int, "rsi_period": int,
    "rsi_buy": float, "rsi_sell": float, "vol_window": int,
    "vol_factor": float, "ou_window": int, "ou_threshold": float,
    "zscore_window": int, "zscore_threshold": float,
    "vwap_threshold": float, "kalman_threshold": float,
    "sizing_mode": str,
}

ALL_SIGNALS: list[str] = [
    "BB", "EMA_Cross", "MACD_Zero", "Zscore", "RSI",
    "VolSpike", "OU", "KalmanZ", "VWAP", "ORB", "TimeFilter",
]


def update_config(patch: dict[str, Any]) -> dict:
    """Merge a validated patch into ``config.json`` and persist it.

    Only whitelisted keys are applied; ``active_signals`` and
    ``symbols`` accept lists of strings.  Numeric fields are coerced to
    their declared type.

    Args:
        patch (dict): Partial config from the editor.

    Returns:
        dict: The full config now on disk.

    Raises:
        ValueError: When a value cannot be coerced to its type.
    """
    cfg = read_config()
    for key, value in patch.items():
        if key == "active_signals" and isinstance(value, list):
            cfg[key] = [s for s in value if s in ALL_SIGNALS]
        elif key == "symbols" and isinstance(value, list):
            cfg[key] = [str(s).strip() for s in value if str(s).strip()]
        elif key in EDITABLE:
            caster = EDITABLE[key]
            try:
                cfg[key] = caster(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key}: {value!r}") from exc
    _write(cfg)
    return cfg


def _write(cfg: dict) -> None:
    """Persist a config dict to ``config.json`` with stable formatting."""
    CONFIG_FILE.parent.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=4))
