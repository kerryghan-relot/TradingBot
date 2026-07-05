"""
Weekly TopX symbol scorer — lucas-live-trading
===============================================
Fetches recent 1-minute bars for every candidate symbol, simulates
the same vote-based strategy used by ``bot.py``, ranks symbols by
annualised Sharpe ratio, and updates ``config.json["symbols"]`` with
the top-X winners.

Run this script once a week (see ``run_scorer.ps1`` for a Windows
scheduled-task wrapper).  The bot hot-reloads the new symbol list
within ~30 s: added symbols are subscribed live, removed symbols are
liquidated — no restart needed.

Usage:
    # Preview results without modifying config.json
    python scorer.py --dry-run

    # Apply top-5 (default) to config.json
    python scorer.py

    # Override top-X and lookback at runtime
    python scorer.py --top 3 --days 14

Requirements:
    pip install alpaca-py python-dotenv

Environment variables (.env):
    ALPACA_API_KEY
    ALPACA_SECRET_KEY
"""

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, UTC
from pathlib import Path

from dotenv import load_dotenv

from alpaca.data.enums import DataFeed
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from constants import SYMBOLS, BARS_PER_YEAR_CRYPTO, BARS_PER_YEAR_STOCK
from engine import SignalState, evaluate_bar


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_crypto(symbol: str) -> bool:
    """Return True for crypto pairs (e.g. ``"BTC/USD"``), False for stocks."""
    return "/" in symbol


# ── Static config ─────────────────────────────────────────────────────────────

load_dotenv()

API_KEY:    str | None = os.getenv("ALPACA_API_KEY")
API_SECRET: str | None = os.getenv("ALPACA_SECRET_KEY")
if not API_KEY or not API_SECRET:
    raise RuntimeError(
        "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env"
    )

CONFIG_FILE: Path = Path(__file__).parent / "config.json"
LOG_FILE:    Path = Path(__file__).parent / "scorer.log"

# BARS_PER_YEAR_CRYPTO / BARS_PER_YEAR_STOCK imported from constants.py.
# Using the wrong constant inflates Sharpe by ×2.3 for US stocks.

# Core bot defaults — mirrors bot.py's DEFAULT_CONFIG so scorer.py
# can be run without importing the live-bot module (which checks .env
# at import time and creates Alpaca clients).
_BOT_DEFAULTS: dict = {
    "symbols": list(SYMBOLS),   # own copy — never mutate SYMBOLS constant
    # Capital & sizing — mirrors bot.py DEFAULT_CONFIG.  The scorer
    # ranks by per-bar return (size-independent), so these do not affect
    # the ranking; they are kept here only so the merged config round-
    # trips every key the bot expects.
    "total_capital":      100000.0,
    "sizing_mode":        "confidence",
    "min_position_pct":   0.05,
    "max_position_pct":   0.20,
    "order_qty":          {"BTC": 0.001, "ETH": 0.01},
    "order_qty_default":  1,
    "order_dollar_value": 500,  # kept in sync with bot.py DEFAULT_CONFIG
    "stop_loss_pct":      0.02,
    "max_open_positions": 10,   # kept in sync with bot.py DEFAULT_CONFIG
    "backfill_days":      7,    # kept in sync with bot.py DEFAULT_CONFIG
    "vote_threshold":     2,
    "active_signals":    ["BB", "OU", "VWAP", "VolSpike", "KalmanZ"],
    "bb_period":         200,
    "bb_std":            2.5,
    "ema_fast":          10,
    "ema_slow":          200,
    "macd_fast":         26,
    "macd_slow":         78,
    "zscore_window":     200,
    "zscore_threshold":  2.0,
    "rsi_period":        200,
    "rsi_buy":           25.0,
    "rsi_sell":          75.0,
    "vol_window":        20,
    "vol_factor":        2.0,
    "ou_window":         200,
    "ou_threshold":      2.0,
    "kalman_q":          1e-4,
    "kalman_r":          0.1,
    "kalman_roll_win":   100,
    "kalman_threshold":  2.0,
    "vwap_threshold":    0.005,
    "orb_bars":          6,
    "session_length":    1440,
    "time_skip":         6,
}

# Scorer-specific defaults merged into the bot config on load
SCORER_DEFAULTS: dict = {
    # Candidate pool — single source of truth in constants.py
    "scorer_candidates": SYMBOLS,
    # Number of top symbols to trade
    "scorer_top_x":         5,
    # Historical lookback window in days
    "scorer_lookback_days": 30,
    # Minimum Sharpe to be eligible; symbols below this floor are excluded
    # even if they rank in the top-X
    "scorer_min_sharpe":    -99.0,
    # Transaction costs, applied once per side (entry AND exit) in the
    # simulation.  fee: broker/exchange commission (0.0005 = 0.05 %,
    # matches lucas-research FEES).  slippage: half-spread + market
    # impact estimate for market orders on 1-min bars.
    "scorer_fee_pct":       0.0005,
    "scorer_slippage_pct":  0.0005,
}


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
    # Start from combined defaults
    merged = {**_BOT_DEFAULTS, **SCORER_DEFAULTS}

    if not CONFIG_FILE.exists():
        return merged
    try:
        on_disk = json.loads(CONFIG_FILE.read_text())
        return {**merged, **on_disk}
    except json.JSONDecodeError:
        log.warning("⚠️  config.json parse error — using defaults")
        return merged


def _write_symbols(new_symbols: list[str]) -> None:
    """Update only the ``symbols`` key in ``config.json`` in-place.

    Reads the existing file, replaces ``symbols``, and writes back.
    All other keys are preserved unchanged.

    Args:
        new_symbols (list[str]): New symbol list, e.g.
            ``["BTC/USD", "ETH/USD", "SOL/USD"]``.
    """
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        cfg = {}
    cfg["symbols"] = new_symbols
    CONFIG_FILE.write_text(json.dumps(cfg, indent=4))


# ══════════════════════════════════════════════════════════════════════════════
#  Alpaca data fetching
# ══════════════════════════════════════════════════════════════════════════════

def fetch_bars(
    crypto_client: CryptoHistoricalDataClient,
    stock_client:  StockHistoricalDataClient,
    symbol: str,
    start:  datetime,
    end:    datetime,
) -> list[dict]:
    """Fetch 1-minute OHLCVT bars from Alpaca for one symbol.

    Routes to the correct Alpaca client based on the symbol type:
    crypto pairs (containing ``"/"``) use ``CryptoHistoricalDataClient``;
    stock tickers use ``StockHistoricalDataClient``.

    Args:
        crypto_client (CryptoHistoricalDataClient): Alpaca crypto client.
        stock_client  (StockHistoricalDataClient) : Alpaca stock client.
        symbol (str): Asset symbol, e.g. ``"BTC/USD"`` or ``"AAPL"``.
        start  (datetime): Inclusive start of the lookback window (UTC).
        end    (datetime): Exclusive end of the lookback window (UTC).

    Returns:
        list[dict]: Chronologically ordered bar dicts.  Empty on error.
    """
    try:
        if _is_crypto(symbol):
            bar_set = crypto_client.get_crypto_bars(
                CryptoBarsRequest(
                    symbol_or_symbols = symbol,
                    timeframe         = TimeFrame.Minute,
                    start             = start,
                    end               = end,
                )
            )
        else:
            bar_set = stock_client.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols = symbol,
                    timeframe         = TimeFrame.Minute,
                    start             = start,
                    end               = end,
                    feed              = DataFeed.IEX,
                )
            )
        raw = bar_set.data.get(symbol, [])
    except Exception as exc:
        log.error(f"  ❌ {symbol}: fetch failed — {exc}")
        return []

    bars = [
        {
            "timestamp": b.timestamp.isoformat(),
            "open":      float(b.open),
            "high":      float(b.high),
            "low":       float(b.low),
            "close":     float(b.close),
            "volume":    float(b.volume),
        }
        for b in raw
    ]
    log.debug(f"  {symbol}: fetched {len(bars)} bars")
    return bars


# ══════════════════════════════════════════════════════════════════════════════
#  Strategy simulation
# ══════════════════════════════════════════════════════════════════════════════

def simulate(bars: list[dict], cfg: dict) -> list[float]:
    """Simulate the vote strategy on historical bars and return per-bar returns.

    Runs ``engine.evaluate_bar()`` — the *same* code path the live bot
    executes — bar by bar, and layers the scorer-specific parts on top:

    - Returns are computed from position held going *into* each bar
      (entry and exit happen at the bar's closing price).
    - Stop-loss exits at the bar close; like the live bot, no re-entry
      can happen on the same bar.
    - Transaction costs (``scorer_fee_pct`` + ``scorer_slippage_pct``)
      are deducted from the return of every bar on which an entry or
      exit occurs — one cost per side.  Without them the ranking is
      biased toward high-turnover symbols.

    Args:
        bars (list[dict]): Chronologically ordered bar dicts as returned
            by ``fetch_bars()``.
        cfg  (dict): Merged configuration dict.

    Returns:
        list[float]: Per-bar strategy return series.  Zero when flat,
            ``close[t] / close[t-1] - 1`` when holding, minus costs on
            transaction bars.  Same length as ``bars``.
    """
    # Cost charged once per side (entry and exit each pay it once)
    cost_per_side: float = (
        float(cfg.get("scorer_fee_pct", 0.0))
        + float(cfg.get("scorer_slippage_pct", 0.0))
    )

    state = SignalState()

    in_position:       bool         = False
    entry_price:       float | None = None
    position_was_open: bool         = False  # held going into current bar
    prev_close:        float | None = None

    returns: list[float] = []

    for bar in bars:
        close = float(bar["close"])

        state.start_bar(bar["timestamp"][:10])
        state.append_bar(
            close,
            float(bar["high"]),
            float(bar["low"]),
            float(bar["volume"]),
        )
        result = evaluate_bar(state, cfg)

        # ── Bar return: based on whether we held going INTO this bar ──────────
        if position_was_open and prev_close is not None:
            returns.append(close / prev_close - 1.0)
        else:
            returns.append(0.0)

        # ── Stop-loss check (mirrors bot.py: no same-bar re-entry) ────────────
        stopped_out = False
        if in_position and entry_price is not None:
            drop = (entry_price - close) / entry_price
            if drop >= cfg["stop_loss_pct"]:
                in_position = False
                entry_price = None
                stopped_out = True
                returns[-1] -= cost_per_side

        # ── Apply votes ───────────────────────────────────────────────────────
        if (
            not stopped_out
            and result.warmed_up
            and result.in_window
            and result.n_signals
        ):
            if result.buy and not in_position:
                in_position = True
                entry_price = close
                returns[-1] -= cost_per_side
            elif result.sell and in_position:
                in_position = False
                entry_price = None
                returns[-1] -= cost_per_side

        position_was_open = in_position
        prev_close        = close

    return returns


# ══════════════════════════════════════════════════════════════════════════════
#  Metrics
# ══════════════════════════════════════════════════════════════════════════════

def sharpe(
    returns: list[float],
    bars_per_year: int = BARS_PER_YEAR_CRYPTO,
) -> float:
    """Compute annualised Sharpe ratio from a per-bar return series.

    Args:
        returns       (list[float]): Per-bar strategy returns.
        bars_per_year (int): 1-min bars per year for the asset class.
            Use ``BARS_PER_YEAR_CRYPTO`` (525 600) for crypto and
            ``BARS_PER_YEAR_STOCK`` (98 280) for US equities.
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
        kind = "crypto" if _is_crypto(symbol) else "stock"
        log.info(
            f"  📊 {symbol} [{kind}]: "
            f"fetching {lookback_days}-day history…"
        )
        bars = fetch_bars(crypto_client, stock_client, symbol, start, end)
        if not bars:
            log.warning(f"  ⚠️  {symbol}: no data — skipped")
            continue

        log.info(f"  📊 {symbol}: simulating on {len(bars)} bars…")
        rets = simulate(bars, cfg)

        # Use the correct annualisation factor per asset class
        bpy = BARS_PER_YEAR_CRYPTO if _is_crypto(symbol) else BARS_PER_YEAR_STOCK
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
        description="Rank crypto symbols by strategy Sharpe and update "
                    "config.json['symbols']."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print rankings without modifying config.json.",
    )
    parser.add_argument(
        "--top",  type=int, default=None,
        help="Override scorer_top_x from config.",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Override scorer_lookback_days from config.",
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

    crypto_client = CryptoHistoricalDataClient(API_KEY, API_SECRET)
    stock_client  = StockHistoricalDataClient(API_KEY, API_SECRET)

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
        _write_symbols(selected)
        log.info(
            f"✅ config.json updated with symbols: {selected}\n"
            f"   Le bot applique la nouvelle liste à chaud (~30 s) : "
            f"nouveaux symboles abonnés, retirés liquidés."
        )


if __name__ == "__main__":
    main()
