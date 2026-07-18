"""
Weekly TopX symbol scorer — src/live
====================================
Fetches recent 1-minute bars for every candidate symbol, simulates
the same vote-based strategy used by ``bot.py``, ranks symbols by
annualised Sharpe ratio, and updates ``config/config.json["symbols"]``
with the top-X winners.

Run this script once a week (see ``deploy/scripts/run_scorer.ps1``
for a Windows scheduled-task wrapper).  The bot hot-reloads the new
symbol list within ~30 s: added symbols are subscribed live, removed
symbols are liquidated — no restart needed.

Usage (from ``src/``):
    # Preview results without modifying config.json
    python -m live.scorer --dry-run

    # Apply top-5 (default) to config.json
    python -m live.scorer

    # Override top-X and lookback at runtime
    python -m live.scorer --top 3 --days 14

Requirements:
    pip install alpaca-py python-dotenv

Environment variables (.env):
    ALPACA_API_KEY
    ALPACA_SECRET_KEY
"""

import argparse
import logging
from datetime import datetime, timedelta, UTC
from pathlib import Path

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient

from core.broker import fetch_bars, is_crypto, make_data_clients
from core.config import DEFAULT_CONFIG, SCORER_DEFAULTS, write_symbols
from core.config import load_config as _load_config
from core.constants import (
    BARS_PER_YEAR_CRYPTO,
    BARS_PER_YEAR_STOCK,
    ROOT_DIR,
)
from core.metrics import max_drawdown, sharpe, total_return, trade_count
from core.simulation import simulate


# ── Static config ─────────────────────────────────────────────────────────────

LOG_FILE: Path = ROOT_DIR / "scorer.log"

# ── Logging ───────────────────────────────────────────────────────────────────

def _setup_logging() -> logging.Logger:
    """Configure module-level logger with console and rotating file handlers.

    Returns:
        logging.Logger: Logger named ``"scorer"``.
    """
    log = logging.getLogger("scorer")
    log.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))

    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    log.addHandler(console)
    log.addHandler(fh)
    return log


log: logging.Logger = _setup_logging()


# ══════════════════════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    """Load and merge bot config with scorer defaults.

    Reads ``config.json`` (which the bot hot-reloads) and merges
    ``SCORER_DEFAULTS`` for scorer-specific keys not yet present.

    Returns:
        dict: Merged configuration dictionary.  Falls back to combined
            defaults if the file is absent or malformed.
    """
    defaults = {**DEFAULT_CONFIG, **SCORER_DEFAULTS}
    return _load_config(defaults=defaults, log=log) or defaults


# ══════════════════════════════════════════════════════════════════════════════
#  Scorer
# ══════════════════════════════════════════════════════════════════════════════

def score_all(
    crypto_client: CryptoHistoricalDataClient,
    stock_client:  StockHistoricalDataClient,
    cfg:           dict,
    lookback_days: int,
) -> list[dict]:
    """Fetch, simulate, and score all candidate symbols.

    For each symbol in ``cfg["scorer_candidates"]``:
    1. Fetch ``lookback_days`` of 1-minute bars (crypto or stock API).
    2. Simulate the vote strategy.
    3. Compute Sharpe, total return, max drawdown, and trade count.

    Args:
        crypto_client (CryptoHistoricalDataClient): Alpaca crypto client.
        stock_client  (StockHistoricalDataClient) : Alpaca stock client.
        cfg           (dict): Merged configuration.
        lookback_days (int): Calendar days of history to fetch.

    Returns:
        list[dict]: One result dict per candidate, sorted by Sharpe
            descending.  Keys: ``symbol``, ``sharpe``, ``total_return``,
            ``max_drawdown``, ``n_trades``, ``n_bars``.
    """
    end   = datetime.now(UTC)
    start = end - timedelta(days=lookback_days)

    candidates: list[str] = cfg.get(
        "scorer_candidates", SCORER_DEFAULTS["scorer_candidates"]
    )

    results: list[dict] = []

    for symbol in candidates:
        kind = "crypto" if is_crypto(symbol) else "stock"
        log.info(
            f"  📊 {symbol} [{kind}]: "
            f"fetching {lookback_days}-day history…"
        )
        bars = fetch_bars(
            crypto_client, stock_client, symbol, start, end, log=log
        )
        if not bars:
            log.warning(f"  ⚠️  {symbol}: no data — skipped")
            continue

        log.info(f"  📊 {symbol}: simulating on {len(bars)} bars…")
        rets = simulate(bars, cfg)

        # Use the correct annualisation factor per asset class
        bpy = BARS_PER_YEAR_CRYPTO if is_crypto(symbol) else BARS_PER_YEAR_STOCK
        s   = sharpe(rets, bpy)
        tr  = total_return(rets)
        mdd = max_drawdown(rets)
        ntd = trade_count(rets)
        log.info(
            f"  📊 {symbol}: Sharpe={s:.3f}  "
            f"ret={tr*100:.1f}%  "
            f"dd={mdd*100:.1f}%  "
            f"trades={ntd}"
        )

        results.append({
            "symbol":       symbol,
            "sharpe":       s,
            "total_return": tr,
            "max_drawdown": mdd,
            "n_trades":     ntd,
            "n_bars":       len(bars),
        })

    results.sort(key=lambda d: d["sharpe"], reverse=True)
    return results


def _print_table(results: list[dict], top_x: int, min_sharpe: float) -> None:
    """Print a formatted ranking table to stdout.

    Args:
        results    (list[dict]): Scored symbol dicts, sorted by Sharpe.
        top_x      (int)       : Number of top symbols highlighted.
        min_sharpe (float)     : Minimum Sharpe threshold line.
    """
    header = (
        f"{'Rank':>4}  {'Symbol':8}  {'Sharpe':>7}  "
        f"{'Return':>8}  {'MaxDD':>7}  {'Trades':>6}  {'Bars':>7}"
    )
    sep = "─" * len(header)
    print(f"\n{sep}")
    print(header)
    print(sep)
    for i, r in enumerate(results, start=1):
        flag = "←" if i <= top_x and r["sharpe"] >= min_sharpe else "  "
        print(
            f"{i:>4}  {r['symbol']:8}  "
            f"{r['sharpe']:>7.3f}  "
            f"{r['total_return']*100:>7.1f}%  "
            f"{r['max_drawdown']*100:>6.1f}%  "
            f"{r['n_trades']:>6}  "
            f"{r['n_bars']:>7}  {flag}"
        )
    print(sep)


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    """Run the scorer: rank candidates, optionally update config.json."""
    parser = argparse.ArgumentParser(
        description="Classe les symboles crypto par Sharpe de la stratégie "
                    "et met à jour config.json['symbols']."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche le classement sans modifier config.json.",
    )
    parser.add_argument(
        "--top",  type=int, default=None,
        help="Surcharge scorer_top_x de la config.",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Surcharge scorer_lookback_days de la config.",
    )
    args = parser.parse_args()

    cfg = load_config()

    top_x      = args.top  if args.top  is not None else int(cfg["scorer_top_x"])
    lookback   = args.days if args.days is not None else int(cfg["scorer_lookback_days"])
    min_sharpe = float(cfg["scorer_min_sharpe"])

    log.info(
        f"\n🔍 Scorer started\n"
        f"   Candidates : {cfg['scorer_candidates']}\n"
        f"   Lookback   : {lookback} days\n"
        f"   Top-X      : {top_x}\n"
        f"   Min Sharpe : {min_sharpe}\n"
        f"   Signals    : {cfg.get('active_signals', [])}\n"
        f"   Threshold  : {cfg.get('vote_threshold', 2)}\n"
        f"   Costs/side : fee={float(cfg.get('scorer_fee_pct', 0))*100:.3f}%  "
        f"slippage={float(cfg.get('scorer_slippage_pct', 0))*100:.3f}%\n"
        f"   Dry-run    : {args.dry_run}\n"
    )

    crypto_client, stock_client = make_data_clients()

    results = score_all(crypto_client, stock_client, cfg, lookback)

    if not results:
        log.error("❌ No results — all candidates failed to fetch or simulate.")
        return

    _print_table(results, top_x, min_sharpe)

    # Select top-X with Sharpe above floor
    selected = [
        r["symbol"]
        for r in results
        if r["sharpe"] >= min_sharpe
    ][:top_x]

    if not selected:
        log.warning(
            f"⚠️  No symbol passed the Sharpe floor ({min_sharpe:.2f}).  "
            f"config.json not updated."
        )
        return

    log.info(f"\n🏆 Selected top-{top_x}: {selected}")

    if args.dry_run:
        log.info("🔒 Dry-run mode — config.json not modified.")
    else:
        write_symbols(selected)
        log.info(
            f"✅ config.json updated with symbols: {selected}\n"
            f"   The bot applies the new list hot (~30 s): "
            f"new symbols subscribed, removed ones liquidated."
        )


if __name__ == "__main__":
    main()
