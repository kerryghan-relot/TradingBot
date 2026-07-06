"""
Event-driven backtest — replays historical CSVs through the live engine.
=========================================================================
For each symbol CSV in ``data/``, runs ``core.simulation.simulate``
(the exact per-bar code path shared with ``bot.py`` and ``scorer.py``)
over the full history and reports per-symbol metrics.

Slower than the vectorized research scripts in ``vectorized/``, but
zero backtest/live divergence by construction — this is the final
validation step before a strategy goes live.

Usage: ``python backtest.py <strategie>`` from ``lucas-trading/``.
"""

import logging
import time

from core.constants import (
    ANNUALIZATION,
    ANNUALIZATION_CRYPTO,
    FEES,
    OUTPUT_DIR,
)
from core.data import list_symbol_csvs, load_bars_csv
from core.metrics import max_drawdown, sharpe, total_return, trade_count
from core.simulation import simulate
from strategies import Strategy

logger = logging.getLogger(__name__)

CSV_HEADER = "symbol,sharpe,total_return,max_drawdown,n_trades,n_bars\n"


def run(
    strategy: Strategy,
    symbols: list[str] | None = None,
) -> list[dict]:
    """Backtest *strategy* on the historical CSVs, one symbol at a time.

    Args:
        strategy (Strategy): Strategy whose config drives the engine.
        symbols (list[str], optional): Subset of symbols to test.
            Defaults to every CSV found in ``data/``.

    Returns:
        list[dict]: Per-symbol result rows (``symbol``, ``sharpe``,
            ``total_return``, ``max_drawdown``, ``n_trades``,
            ``n_bars``) sorted by Sharpe descending.  Also written to
            ``results/event_<name>.csv``.

    Raises:
        SystemExit: When ``data/`` has no CSV for a requested symbol.
    """
    cfg = dict(strategy.config)
    # simulate() reads scorer_fee_pct / scorer_slippage_pct as the
    # per-side costs; default to the research constants when absent.
    cfg.setdefault("scorer_fee_pct", FEES)
    cfg.setdefault("scorer_slippage_pct", 0.0005)

    csvs = list_symbol_csvs()
    if symbols:
        missing = [s for s in symbols if s not in csvs]
        if missing:
            raise SystemExit(f"Pas de CSV dans data/ pour: {missing}")
        csvs = {s: csvs[s] for s in symbols}
    if not csvs:
        raise SystemExit(
            "Aucun CSV historique dans data/ — lance "
            "'python -m tools.download_history' d'abord."
        )

    logger.info(
        "Backtest événementiel '%s' — %d symbole(s), coûts %.3f%%/side",
        strategy.name, len(csvs),
        (cfg["scorer_fee_pct"] + cfg["scorer_slippage_pct"]) * 100,
    )

    results: list[dict] = []
    for symbol, path in csvs.items():
        t0 = time.perf_counter()
        bars = load_bars_csv(path)
        rets = simulate(bars, cfg)
        bpy = ANNUALIZATION_CRYPTO if "/" in symbol else ANNUALIZATION
        row = {
            "symbol":       symbol,
            "sharpe":       sharpe(rets, bpy),
            "total_return": total_return(rets),
            "max_drawdown": max_drawdown(rets),
            "n_trades":     trade_count(rets),
            "n_bars":       len(bars),
        }
        results.append(row)
        logger.info(
            "%-8s  sharpe=%7.3f  ret=%7.1f%%  dd=%5.1f%%  trades=%5d  "
            "(%d bars, %.1fs)",
            symbol, row["sharpe"], row["total_return"] * 100,
            row["max_drawdown"] * 100, row["n_trades"], row["n_bars"],
            time.perf_counter() - t0,
        )

    results.sort(key=lambda r: r["sharpe"], reverse=True)

    out = OUTPUT_DIR / f"event_{strategy.name}.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(CSV_HEADER)
        for r in results:
            f.write(
                f"{r['symbol']},{r['sharpe']:.4f},"
                f"{r['total_return']:.6f},{r['max_drawdown']:.6f},"
                f"{r['n_trades']},{r['n_bars']}\n"
            )
    logger.info("✓ Résultats écrits: %s", out)
    return results
