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


# The strategy module set is fixed for the life of the process (modules
# are imported once and cached in sys.modules), yet ``discover`` is
# called several times per dashboard request.  Memoise the scan so it
# runs once instead of re-listing the package on every call.
_discover_cache: list[Strategy] | None = None

# ``read_config`` is likewise called many times per request (live
# payload, active-strategy match, each agent loader).  Cache the parsed
# JSON keyed on the file's mtime so an unchanged config is not re-read
# and re-parsed from disk each time; a write bumps the mtime and
# invalidates the cache automatically.
_config_cache: tuple[float, dict] | None = None


def discover() -> list[Strategy]:
    """Import every ``strategies/*.py`` module exposing a STRATEGY.

    The result is memoised after the first call (see ``_discover_cache``)
    — the module set does not change while the process runs.

    Returns:
        list[Strategy]: All declared strategies, sorted by name. The
            canonical ``vote_mr`` is guaranteed present as a fallback.
    """
    global _discover_cache
    if _discover_cache is not None:
        return _discover_cache
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
    _discover_cache = sorted(found, key=lambda s: s.name)
    return _discover_cache


def read_config() -> dict:
    """Return the live config merged over ``DEFAULT_CONFIG``.

    The parsed ``config.json`` is cached by file mtime, so repeated
    calls within a request avoid re-reading and re-parsing the file; a
    write bumps the mtime and refreshes the cache. A fresh merged dict
    is returned each call, so callers may safely mutate it.

    Returns:
        dict: The effective configuration the bot would load.
    """
    global _config_cache
    base = dict(DEFAULT_CONFIG)
    try:
        mtime = CONFIG_FILE.stat().st_mtime
    except OSError:
        return base
    cached = _config_cache
    if cached is not None and cached[0] == mtime:
        base.update(cached[1])
        return base
    try:
        loaded = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return base
    _config_cache = (mtime, loaded)
    base.update(loaded)
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
