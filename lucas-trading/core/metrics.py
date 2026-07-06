"""
Performance metrics on per-bar return series.
==============================================
Shared by the live scorer (``live/scorer.py``) and the event-driven
backtest (``backtest/event_driven.py``).  All functions take a plain
``list[float]`` of per-bar strategy returns as produced by
``core.simulation.simulate``.
"""

from core.constants import BARS_PER_YEAR_CRYPTO


def sharpe(
    returns: list[float],
    bars_per_year: int = BARS_PER_YEAR_CRYPTO,
) -> float:
    """Compute annualised Sharpe ratio from a per-bar return series.

    Args:
        returns       (list[float]): Per-bar strategy returns.
        bars_per_year (int): Bars per year for the asset class and bar
            interval.  For 1-min live bars use ``BARS_PER_YEAR_CRYPTO``
            (525 600) or ``BARS_PER_YEAR_STOCK`` (98 280); for 5-min
            research bars use ``ANNUALIZATION`` / ``ANNUALIZATION_CRYPTO``.
            Mixing these inflates stock Sharpe by ≈ ×2.3.

    Returns:
        float: Annualised Sharpe ratio.  0.0 if fewer than two bars or
            zero standard deviation.
    """
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var  = sum((r - mean) ** 2 for r in returns) / n
    std  = var ** 0.5
    if std == 0.0:
        return 0.0
    return mean / std * (bars_per_year ** 0.5)


def total_return(returns: list[float]) -> float:
    """Compute total compounded return from a per-bar return series.

    Args:
        returns (list[float]): Per-bar strategy returns.

    Returns:
        float: Total return as a decimal (e.g. 0.12 = +12 %).
    """
    equity = 1.0
    for r in returns:
        equity *= 1.0 + r
    return equity - 1.0


def max_drawdown(returns: list[float]) -> float:
    """Compute maximum drawdown from a per-bar return series.

    Args:
        returns (list[float]): Per-bar strategy returns.

    Returns:
        float: Max drawdown as a positive decimal (e.g. 0.15 = −15 %).
    """
    equity  = 1.0
    peak    = 1.0
    max_dd  = 0.0
    for r in returns:
        equity  *= 1.0 + r
        peak     = max(peak, equity)
        drawdown = (peak - equity) / peak
        max_dd   = max(max_dd, drawdown)
    return max_dd


def trade_count(returns: list[float]) -> int:
    """Count completed round-trips (entries) in a return series.

    A new trade starts whenever the return transitions from zero to
    non-zero (i.e. we moved from flat to in-position).

    Args:
        returns (list[float]): Per-bar strategy returns.

    Returns:
        int: Number of entries taken.
    """
    count = 0
    prev_active = False
    for r in returns:
        active = r != 0.0
        if active and not prev_active:
            count += 1
        prev_active = active
    return count
