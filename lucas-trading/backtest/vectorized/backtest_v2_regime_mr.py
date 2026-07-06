"""
Regime-gated mean-reversion (v2) with an honest train/test protocol.
=====================================================================

Strategy (long-only, 15-minute bars resampled from the 5-min CSVs):

  ENTRY  - z-score of close vs its rolling mean crosses below -Z_ENTRY
           (price statistically stretched to the downside), AND
         - Efficiency Ratio < ER_MAX (market is ranging, not trending:
           mean reversion is only traded in its favourable regime), AND
         - relative volatility >= MIN_SIGMA_REL (the expected snap-back
           to the mean is large enough to pay the round-trip cost).

  EXIT   - take-profit when z >= Z_EXIT (price is back at its mean:
           the reversion edge has been consumed), OR
         - time stop after MAX_HOLD bars (the thesis has expired), OR
         - stop-loss at entry - STOP_MULT * sigma (the "rubber band"
           broke: this is a trend, not a stretch).

Protocol
--------
1. Load every symbol, drop corrupt bars (rolling-median glitch filter),
   resample to 15-minute bars.
2. Split the timeline 70 % train / 30 % test.  A small parameter grid
   is scored on the TRAIN portfolio only; the winning parameter set is
   then evaluated ONCE on the untouched TEST period.
3. On the test period the strategy is also compared with random
   entries of identical count and duration (edge vs luck check).

Costs: 0.10 % per side (fee + slippage), same as backtest_scorer_oos.

Usage::

    python -m backtest.vectorized.backtest_v2_regime_mr

Outputs::

    results/v2_regime_mr_results.csv
    results/v2_regime_mr_equity.csv
"""

import logging
import time
from dataclasses import dataclass, replace
from itertools import product

import numpy as np
import pandas as pd

from core.constants import DATA_DIR, FEES, OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Fixed configuration ──────────────────────────────────────────
COST_PER_SIDE: float = FEES + 0.0005   # 0.10 % per side, as scorer OOS
TRAIN_RATIO: float = 0.70              # first 70 % of time = train
N_RANDOM_DRAWS: int = 200              # random-entry benchmark draws
RANDOM_SEED: int = 7

# Indicator windows (15-min bars) — fixed, NOT part of the grid, to
# keep the number of tested combinations small and honest.
SMA_WIN: int = 100        # z-score mean/std window (~2-4 days)
ER_WIN: int = 48          # Efficiency Ratio lookback (~1-2 days)


@dataclass(frozen=True)
class Params:
    """Tunable thresholds of the v2 strategy.

    Attributes:
        z_entry (float): Z-score entry trigger (cross below -z_entry).
        z_exit (float): Take-profit z level (price back at the mean).
        er_max (float): Maximum Efficiency Ratio allowed at entry.
        min_sigma_rel (float): Minimum sigma/price at entry so the
            expected reversion covers transaction costs.
        max_hold (int): Time stop, in bars.
        stop_mult (float): Stop-loss distance in entry sigmas.
    """

    z_entry: float
    z_exit: float
    er_max: float
    min_sigma_rel: float
    max_hold: int
    stop_mult: float


BASE = Params(
    z_entry=2.0, z_exit=0.0, er_max=0.30,
    min_sigma_rel=0.003, max_hold=96, stop_mult=3.0,
)

# Small grid: 3 x 2 x 2 = 12 combinations, scored on TRAIN only.
GRID: list[Params] = [
    replace(BASE, z_entry=z, er_max=e, min_sigma_rel=s)
    for z, e, s in product(
        (1.5, 2.0, 2.5), (0.25, 0.35), (0.002, 0.003)
    )
]


# ══════════════════════════════════════════════════════════════════
#  Data loading
# ══════════════════════════════════════════════════════════════════

def load_clean_15min() -> dict[str, pd.DataFrame]:
    """Load every symbol CSV, drop glitch bars, resample to 15 min.

    A bar is a glitch when its close deviates more than 50 % from the
    centred 7-bar rolling median (e.g. the ETH-USD close of 6.7e-06 on
    2023-06-15).

    Returns:
        dict[str, pd.DataFrame]: Ticker -> OHLCV frame, 15-min bars.
    """
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(DATA_DIR.glob("*_5min_3ans.csv")):
        ticker = path.name.split("_")[0]
        df = (
            pd.read_csv(path, parse_dates=["datetime"])
            .set_index("datetime")
            .sort_index()
        )
        df = df[~df.index.duplicated(keep="first")]

        med = df["close"].rolling(7, center=True, min_periods=1).median()
        glitch = (df["close"] / med - 1.0).abs() > 0.5
        if glitch.any():
            logger.warning(
                "  %-8s %d glitch bar(s) dropped", ticker,
                int(glitch.sum()),
            )
            df = df[~glitch]

        df = (
            df.resample("15min")
            .agg({
                "open": "first", "high": "max",
                "low": "min", "close": "last", "volume": "sum",
            })
            .dropna(subset=["close"])
        )
        frames[ticker] = df
        logger.info("  %-8s %6d bars (15min)", ticker, len(df))
    return frames


# ══════════════════════════════════════════════════════════════════
#  Indicators (computed once per symbol, thresholds applied later)
# ══════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Compute z-score, Efficiency Ratio, and volatility arrays.

    Args:
        df (pd.DataFrame): OHLCV frame indexed by timestamp.

    Returns:
        dict[str, np.ndarray]: close, z, z_prev, er, sigma, sigma_rel.
    """
    close = df["close"]
    mu = close.rolling(SMA_WIN).mean()
    sigma = close.rolling(SMA_WIN).std(ddof=0)
    z = ((close - mu) / sigma.replace(0.0, np.nan))

    direction = (close - close.shift(ER_WIN)).abs()
    path = close.diff().abs().rolling(ER_WIN).sum()
    er = direction / path.replace(0.0, np.nan)

    return {
        "close": close.to_numpy(dtype=float),
        "z": z.to_numpy(dtype=float),
        "z_prev": z.shift(1).to_numpy(dtype=float),
        "er": er.to_numpy(dtype=float),
        "sigma": sigma.to_numpy(dtype=float),
        "sigma_rel": (sigma / close).to_numpy(dtype=float),
    }


# ══════════════════════════════════════════════════════════════════
#  Simulation
# ══════════════════════════════════════════════════════════════════

def simulate(
    ind: dict[str, np.ndarray], p: Params
) -> tuple[np.ndarray, list[tuple[int, int, float]]]:
    """Simulate the strategy bar by bar on one symbol.

    Entries and exits execute at the close of the signal bar; one
    COST_PER_SIDE charge per entry and per exit (same conventions as
    backtest_scorer_oos.simulate_returns).

    Args:
        ind (dict[str, np.ndarray]): Arrays from compute_indicators.
        p (Params): Strategy thresholds.

    Returns:
        tuple[np.ndarray, list[tuple[int, int, float]]]: Per-bar net
            return array, and closed trades as (entry_i, exit_i,
            net_return).
    """
    close = ind["close"]
    z, z_prev = ind["z"], ind["z_prev"]
    er, sigma, sigma_rel = ind["er"], ind["sigma"], ind["sigma_rel"]

    n = len(close)
    rets = np.zeros(n)
    trades: list[tuple[int, int, float]] = []

    in_pos = False
    was_open = False
    entry_px = 0.0
    stop_px = 0.0
    entry_i = 0
    held = 0

    for t in range(n):
        c = close[t]
        if was_open and t > 0:
            rets[t] = c / close[t - 1] - 1.0

        if in_pos:
            held += 1
            if (
                z[t] >= p.z_exit
                or held >= p.max_hold
                or c <= stop_px
            ):
                in_pos = False
                rets[t] -= COST_PER_SIDE
                trades.append((
                    entry_i, t,
                    c / entry_px - 1.0 - 2.0 * COST_PER_SIDE,
                ))
        elif (
            z_prev[t] >= -p.z_entry
            and z[t] < -p.z_entry
            and er[t] < p.er_max
            and sigma_rel[t] >= p.min_sigma_rel
        ):
            in_pos = True
            entry_px = c
            stop_px = c - p.stop_mult * sigma[t]
            entry_i = t
            held = 0
            rets[t] -= COST_PER_SIDE

        was_open = in_pos

    return rets, trades


# ══════════════════════════════════════════════════════════════════
#  Metrics
# ══════════════════════════════════════════════════════════════════

def sharpe(returns: np.ndarray, bars_per_year: float) -> float:
    """Annualised Sharpe ratio; 0.0 when degenerate."""
    if len(returns) < 2:
        return 0.0
    std = returns.std()
    if std == 0.0:
        return 0.0
    return float(returns.mean() / std * np.sqrt(bars_per_year))


def max_drawdown(equity: np.ndarray) -> float:
    """Maximum drawdown of an equity curve, as a positive decimal."""
    peak = np.maximum.accumulate(equity)
    return float(((peak - equity) / peak).max())


# ══════════════════════════════════════════════════════════════════
#  Backtest driver
# ══════════════════════════════════════════════════════════════════

def portfolio_returns(
    per_symbol: dict[str, pd.Series]
) -> pd.Series:
    """Equal-weight portfolio: mean of per-bar returns, flat = 0."""
    return pd.DataFrame(per_symbol).fillna(0.0).mean(axis=1)


def run() -> None:
    """Run grid selection on train, final evaluation on test."""
    t0 = time.time()
    logger.info("Loading data (glitch filter + 15-min resample)...")
    frames = load_clean_15min()
    tickers = list(frames)

    indicators = {t: compute_indicators(frames[t]) for t in tickers}

    # ── Train / test split on the union timeline ──────────────────
    union = pd.DatetimeIndex(
        sorted(set().union(*(frames[t].index for t in tickers)))
    )
    split_ts = union[int(TRAIN_RATIO * len(union))]
    years_test = (union[-1] - split_ts).days / 365.25
    logger.info(
        "Train: %s -> %s | Test: -> %s (%.2f years)",
        union[0].date(), split_ts.date(), union[-1].date(), years_test,
    )

    # ── Grid search on TRAIN only ─────────────────────────────────
    logger.info("Grid search on train (%d combos)...", len(GRID))
    results_train: list[tuple[Params, float]] = []
    for p in GRID:
        per_sym = {
            t: pd.Series(
                simulate(indicators[t], p)[0], index=frames[t].index
            )
            for t in tickers
        }
        port = portfolio_returns(per_sym)
        train = port[port.index < split_ts]
        bpy = len(train) / max(
            (split_ts - union[0]).days / 365.25, 1e-9
        )
        s = sharpe(train.to_numpy(), bpy)
        results_train.append((p, s))
        logger.info(
            "  z=%.1f er<%.2f srel>=%.3f -> train sharpe %+6.3f",
            p.z_entry, p.er_max, p.min_sigma_rel, s,
        )

    best, best_sharpe = max(results_train, key=lambda r: r[1])
    logger.info(
        "Selected on train: z=%.1f er<%.2f srel>=%.3f (sharpe %+.3f)",
        best.z_entry, best.er_max, best.min_sigma_rel, best_sharpe,
    )

    # ── Final evaluation on TEST (touched once) ───────────────────
    per_sym_ret: dict[str, pd.Series] = {}
    test_trades: dict[str, list[tuple[int, int, float]]] = {}
    rows: list[dict] = []

    for t in tickers:
        rets, trades = simulate(indicators[t], best)
        idx = frames[t].index
        per_sym_ret[t] = pd.Series(rets, index=idx)

        test_start_i = int(idx.searchsorted(split_ts))
        tr_test = [tr for tr in trades if tr[0] >= test_start_i]
        test_trades[t] = tr_test

        nets = np.array([tr[2] for tr in tr_test])
        rows.append({
            "symbol": t,
            "test_trades": len(tr_test),
            "test_win_rate_%": (
                round(float((nets > 0).mean()) * 100, 1)
                if len(nets) else np.nan
            ),
            "test_avg_net_per_trade_%": (
                round(float(nets.mean()) * 100, 3)
                if len(nets) else np.nan
            ),
            "test_total_net_%": (
                round(float(np.prod(1 + nets) - 1) * 100, 2)
                if len(nets) else 0.0
            ),
        })

    port = portfolio_returns(per_sym_ret)
    test = port[port.index >= split_ts]
    bpy_test = len(test) / max(years_test, 1e-9)
    test_eq = (1 + test).cumprod()

    # ── Random-entry benchmark on TEST ────────────────────────────
    rng = np.random.default_rng(RANDOM_SEED)
    strat_draw = _portfolio_trade_return(
        {t: [tr[2] for tr in test_trades[t]] for t in tickers}
    )
    rand_totals = np.empty(N_RANDOM_DRAWS)
    for j in range(N_RANDOM_DRAWS):
        nets_by_sym: dict[str, list[float]] = {}
        for t in tickers:
            close = indicators[t]["close"]
            idx = frames[t].index
            start_i = int(idx.searchsorted(split_ts))
            nets: list[float] = []
            for e_i, x_i, _ in test_trades[t]:
                dur = max(x_i - e_i, 1)
                hi = len(close) - 1 - dur
                if hi <= start_i:
                    continue
                u = int(rng.integers(start_i, hi + 1))
                nets.append(
                    close[u + dur] / close[u] - 1.0
                    - 2.0 * COST_PER_SIDE
                )
            nets_by_sym[t] = nets
        rand_totals[j] = _portfolio_trade_return(nets_by_sym)
    pct_beaten = float((strat_draw > rand_totals).mean() * 100)

    # ── Report ────────────────────────────────────────────────────
    df_rows = pd.DataFrame(rows).sort_values(
        "test_total_net_%", ascending=False
    )
    print("\n" + "=" * 72)
    print(
        f"V2 regime-gated MR | params: z_entry={best.z_entry} "
        f"er_max={best.er_max} min_sigma_rel={best.min_sigma_rel}"
    )
    print(
        f"TEST {split_ts.date()} -> {union[-1].date()} "
        f"({years_test:.2f} years), cost {COST_PER_SIDE:.2%}/side"
    )
    print("-" * 72)
    print(df_rows.to_string(index=False))
    print("-" * 72)
    n_tr = int(df_rows["test_trades"].sum())
    all_nets = (
        np.array([
            tr[2] for t in tickers for tr in test_trades[t]
        ])
        if any(test_trades.values()) else np.empty(0)
    )
    print(
        f"Portfolio TEST: ret={float(test_eq.iloc[-1] - 1) * 100:+.2f}%  "
        f"sharpe={sharpe(test.to_numpy(), bpy_test):+.3f}  "
        f"maxDD={max_drawdown(test_eq.to_numpy()) * 100:.2f}%  "
        f"trades={n_tr}"
    )
    if len(all_nets):
        print(
            f"Per-trade (all symbols): avg net "
            f"{all_nets.mean() * 100:+.3f}%  "
            f"win rate {(all_nets > 0).mean() * 100:.1f}%"
        )
    print(
        f"Random-entry benchmark: strategy beats "
        f"{pct_beaten:.0f}% of {N_RANDOM_DRAWS} draws "
        f"(median random {np.median(rand_totals) * 100:+.2f}% "
        f"vs strategy {strat_draw * 100:+.2f}%)"
    )
    print("=" * 72)

    df_rows.to_csv(OUTPUT_DIR / "v2_regime_mr_results.csv", index=False)
    pd.DataFrame({"test_equity": test_eq}).to_csv(
        OUTPUT_DIR / "v2_regime_mr_equity.csv"
    )
    logger.info("Done in %.1f s", time.time() - t0)


def _portfolio_trade_return(
    nets_by_sym: dict[str, list[float]]
) -> float:
    """Average across symbols of the compounded per-trade returns."""
    totals = [
        float(np.prod([1.0 + r for r in nets]) - 1.0)
        for nets in nets_by_sym.values() if nets
    ]
    return float(np.mean(totals)) if totals else 0.0


if __name__ == "__main__":
    run()
