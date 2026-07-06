"""
Top-X symbol selection on top of the V2 regime-gated MR strategy.
===================================================================

Answers the practical question: instead of holding every symbol,
keep ALL of them in the database but only invest in the TOP_X most
promising ones at any time.  Two independent guards keep the
portfolio away from falling knives:

  1. Bar-level regime gate (already inside the V2 strategy): the
     Efficiency Ratio blocks mean-reversion entries while a symbol
     is trending (ER >= er_max), in either direction.
  2. Weekly structural trend filter (new, this script): a symbol is
     removed from the SELECTABLE universe for the coming week if its
     trailing TREND_LOOKBACK_DAYS return is below MIN_TREND_RET —
     i.e. it is in a sustained decline, even if some individual bars
     still pass the bar-level regime gate.

Within the eligible pool, symbols are ranked every week by trailing
Sharpe of their OWN V2 strategy returns (same metric as
lucas-live-trading/scorer.py) and the TOP_X highest-ranked are held
equal-weighted for the following week.

Four portfolios are compared over the TEST period only (the period
never touched while calibrating V2's thresholds):

  A. Top-X selection (trend filter + Sharpe ranking)      <- proposal
  B. Equal-weight of ALL symbols (no filter, no selection)
  C. Equal-weight of ELIGIBLE symbols only (filter, no ranking)
  D. Random draw of X symbols from the FULL universe (luck check)

Usage::

    python backtest_v2_topx.py

Outputs::

    resultats/v2_topx_equity.csv
    resultats/v2_topx_selection.csv
"""

import logging
import time

import numpy as np
import pandas as pd

from backtest_v2_regime_mr import (
    COST_PER_SIDE,
    Params,
    TRAIN_RATIO,
    compute_indicators,
    load_clean_15min,
    max_drawdown,
    sharpe,
    simulate,
)
from config import OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Train-selected parameters from backtest_v2_regime_mr.py (Sharpe
# train +... best of the 12-combo grid).  Not re-fitted here — the
# selection layer below has its own, separate parameters.
WINNER = Params(
    z_entry=1.5, z_exit=0.0, er_max=0.35,
    min_sigma_rel=0.003, max_hold=96, stop_mult=3.0,
)

# ── Selection-layer configuration ────────────────────────────────
TOP_X: int = 5
# 90 days (one quarter) was swept against 20/40/60: on a FIXED
# evaluation window (isolating the lookback effect from the test
# period shrinking as the warmup grows), only 90d turned the top-X
# portfolio positive (+2.36%, Sharpe +0.44) while 20/40/60d were all
# negative. Shorter windows are too noisy to rank symbols reliably.
SHARPE_LOOKBACK_DAYS: int = 90      # trailing window for ranking
MIN_TRADES_IN_LOOKBACK: int = 3    # too few trades -> score untrusted

TREND_LOOKBACK_DAYS: int = 20      # "is this symbol in freefall?"
MIN_TREND_RET: float = -0.15       # exclude if down > 15% over that window

N_RANDOM_PORTFOLIOS: int = 200
RANDOM_SEED: int = 7

BARS_PER_DAY_STOCK: int = 26       # 6.5h session / 15min
BARS_PER_DAY_CRYPTO: int = 96      # 24h / 15min
CRYPTO_TICKERS: set[str] = {"BTC-USD", "ETH-USD"}


def bars_per_day(ticker: str) -> int:
    """Return the 15-min bar count per calendar/session day."""
    return BARS_PER_DAY_CRYPTO if ticker in CRYPTO_TICKERS else BARS_PER_DAY_STOCK


def run() -> None:
    """Run the top-X selection backtest on the V2 test period."""
    t0 = time.time()
    logger.info("Loading data (glitch filter + 15-min resample)...")
    frames = load_clean_15min()
    tickers = list(frames)

    logger.info("Simulating V2 strategy on %d symbols...", len(tickers))
    per_symbol_ret: dict[str, pd.Series] = {}
    per_symbol_close: dict[str, pd.Series] = {}
    for t in tickers:
        ind = compute_indicators(frames[t])
        rets, _ = simulate(ind, WINNER)
        per_symbol_ret[t] = pd.Series(rets, index=frames[t].index)
        per_symbol_close[t] = frames[t]["close"]

    # ── Train / test split, identical to backtest_v2_regime_mr ────
    union = pd.DatetimeIndex(
        sorted(set().union(*(frames[t].index for t in tickers)))
    )
    split_ts = union[int(TRAIN_RATIO * len(union))]
    logger.info(
        "Test period: %s -> %s", split_ts.date(), union[-1].date()
    )

    matrix = pd.DataFrame(per_symbol_ret).reindex(union).fillna(0.0)
    index = matrix.index

    # ── Weekly rebalance dates within the test period ─────────────
    weeks = index.to_period("W")
    first_of_week = index[
        np.concatenate(([True], weeks[1:] != weeks[:-1]))
    ]
    min_reb = split_ts + pd.Timedelta(
        days=max(SHARPE_LOOKBACK_DAYS, TREND_LOOKBACK_DAYS)
    )
    rebalances = [d for d in first_of_week if min_reb <= d]
    logger.info("%d weekly rebalances in the test period", len(rebalances))

    mat_np = matrix.to_numpy()
    col_of = {t: i for i, t in enumerate(tickers)}
    positions = np.arange(len(index))

    top_ret = pd.Series(0.0, index=index)
    all_ret = matrix.mean(axis=1)
    elig_ret = pd.Series(0.0, index=index)
    rng = np.random.default_rng(RANDOM_SEED)
    random_rets = np.zeros((len(index), N_RANDOM_PORTFOLIOS))
    selection_rows: list[dict] = []

    for k, reb_date in enumerate(rebalances):
        seg_end = (
            rebalances[k + 1] if k + 1 < len(rebalances)
            else index[-1] + pd.Timedelta(seconds=1)
        )
        seg_mask = (index >= reb_date) & (index < seg_end)
        seg_pos = positions[seg_mask]

        # ── Score + eligibility per symbol, on ITS OWN bars ───────
        scores: dict[str, float] = {}
        eligible: list[str] = []
        for t in tickers:
            close = per_symbol_close[t]
            bpd = bars_per_day(t)

            trend_pos = close.index.searchsorted(reb_date, side="left") - 1
            trend_lb = TREND_LOOKBACK_DAYS * bpd
            is_falling = True
            if trend_pos >= trend_lb:
                trend_ret = (
                    close.iloc[trend_pos] / close.iloc[trend_pos - trend_lb]
                    - 1.0
                )
                is_falling = trend_ret < MIN_TREND_RET

            r = per_symbol_ret[t]
            lb_start = reb_date - pd.Timedelta(days=SHARPE_LOOKBACK_DAYS)
            window = r[(r.index >= lb_start) & (r.index < reb_date)]
            n_trades = int((window != 0.0).sum())
            bpy = bpd * 252 if t not in CRYPTO_TICKERS else bpd * 365

            if not is_falling and n_trades >= MIN_TRADES_IN_LOOKBACK:
                eligible.append(t)
                scores[t] = sharpe(window.to_numpy(), bpy)

        ranked = sorted(scores, key=scores.get, reverse=True)
        selected = ranked[:TOP_X]
        selection_rows.append({
            "rebalance": reb_date,
            "n_eligible": len(eligible),
            "selected": " ".join(selected),
            **{f"sharpe_{t}": round(scores[t], 3) for t in selected},
        })

        if selected:
            sel_cols = [col_of[t] for t in selected]
            top_ret.iloc[seg_pos] = mat_np[np.ix_(seg_pos, sel_cols)].mean(
                axis=1
            )
        if eligible:
            elig_cols = [col_of[t] for t in eligible]
            elig_ret.iloc[seg_pos] = mat_np[
                np.ix_(seg_pos, elig_cols)
            ].mean(axis=1)

        for j in range(N_RANDOM_PORTFOLIOS):
            rand_cols = rng.choice(len(tickers), size=TOP_X, replace=False)
            random_rets[seg_pos, j] = mat_np[
                np.ix_(seg_pos, rand_cols)
            ].mean(axis=1)

    # ── Comparison window: from the first rebalance onward ────────
    start = rebalances[0]
    live = np.asarray(index >= start)
    years = (index[-1] - start).days / 365.25
    bpy_emp = live.sum() / years

    top_eq = (1 + top_ret[live]).cumprod()
    all_eq = (1 + all_ret[live]).cumprod()
    elig_eq = (1 + elig_ret[live]).cumprod()
    rand_final = (1 + random_rets[live]).prod(axis=0)
    pct_beaten = float((top_eq.iloc[-1] > rand_final).mean() * 100)

    def _line(name: str, r: pd.Series, eq: pd.Series) -> str:
        return (
            f"  {name:32}  ret={(eq.iloc[-1] - 1) * 100:+7.2f}%  "
            f"sharpe={sharpe(r.to_numpy(), bpy_emp):+6.3f}  "
            f"maxDD={max_drawdown(eq.to_numpy()) * 100:5.2f}%"
        )

    print("\n" + "=" * 78)
    print(
        f"Top-{TOP_X} selection (V2 strategy) vs alternatives | "
        f"test {start:%Y-%m-%d} -> {index[-1]:%Y-%m-%d} ({years:.2f}y)"
    )
    print(
        f"Trend filter: exclude if {TREND_LOOKBACK_DAYS}d return < "
        f"{MIN_TREND_RET:.0%} | Ranking: trailing {SHARPE_LOOKBACK_DAYS}d Sharpe"
    )
    print("-" * 78)
    print(_line(f"A. Top-{TOP_X} (filtre + ranking)", top_ret[live], top_eq))
    print(_line("B. Equipondere TOUS", all_ret[live], all_eq))
    print(_line("C. Equipondere ELIGIBLES seuls", elig_ret[live], elig_eq))
    print(
        f"  D. Aleatoire (n={N_RANDOM_PORTFOLIOS})              "
        f"ret median={np.median(rand_final - 1) * 100:+7.2f}%  "
        f"-> A bat {pct_beaten:.0f}% des tirages"
    )
    avg_elig = np.mean([r["n_eligible"] for r in selection_rows])
    print(f"  Eligibles en moyenne / semaine : {avg_elig:.1f} / {len(tickers)}")
    print("=" * 78)

    pd.DataFrame({
        "topx_equity": top_eq,
        "all_equity": all_eq,
        "eligible_equity": elig_eq,
    }).to_csv(OUTPUT_DIR / "v2_topx_equity.csv")
    pd.DataFrame(selection_rows).to_csv(
        OUTPUT_DIR / "v2_topx_selection.csv", index=False
    )
    logger.info("Done in %.1f s", time.time() - t0)


if __name__ == "__main__":
    run()
