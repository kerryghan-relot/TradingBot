"""
Grid search — Top-X portfolio framework over all strategy combinations.
=======================================================================

For every strategy defined in strategies.py, runs the Top-X portfolio
backtest (single strategy, multi-symbol) and records performance metrics.
Results are sorted by Sharpe ratio and written to CSV + HTML.

This is the TopX equivalent of optimize.py: same idea, different framework.

Usage::

    python optimize_topx.py

Outputs::

    resultats/optimize_topx_resultats.csv
    resultats/optimize_topx_top.html
"""

import gc
import logging
import time

import numpy as np
import pandas as pd
import vectorbt as vbt

from config import (
    ANNUALIZATION,
    BARS_PER_WEEK,
    CAPITAL_INITIAL,
    DATA_DIR,
    FEES,
    OUTPUT_DIR,
)
from strategies import STRATEGIES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Configuration (même que backtest_topx_portfolio.py) ──────────
TOP_X: int = 5
REBALANCE_FREQ: str = "W-FRI"
LOOKBACK_WEEKS: int = 4
LOOKBACK_BARS: int = LOOKBACK_WEEKS * BARS_PER_WEEK
MIN_TRADES_IN_LOOKBACK: int = 3
MIN_SCORE_TO_INVEST: float = 0.0

CSV_OUT  = OUTPUT_DIR / "optimize_topx_resultats.csv"
HTML_OUT = OUTPUT_DIR / "optimize_topx_top.html"

COLUMNS = [
    "Strategy",
    "Performance %",
    "Sharpe",
    "Max Drawdown %",
    "Avg Symbols Active",
    "Rebalances In Cash",
]


# ── Helpers ──────────────────────────────────────────────────────

def _zscore_cols(mat: np.ndarray) -> np.ndarray:
    """Z-score normalise a 2-D matrix column-wise, ignoring NaN."""
    with np.errstate(all="ignore"):
        mean = np.nanmean(mat, axis=0)
        std  = np.nanstd(mat, axis=0)
    std = np.where(std == 0, np.nan, std)
    return (mat - mean) / std


def _compute_metrics(
    close_arr: np.ndarray,
    equity_arr: np.ndarray,
    rets_arr: np.ndarray,
    rebalance_pos: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute strategy alpha, Sharpe, drawdown, trade count per rebalance.

    Args:
        close_arr (np.ndarray): Close price array aligned to common_index.
        equity_arr (np.ndarray): Strategy equity curve.
        rets_arr (np.ndarray): Strategy bar returns.
        rebalance_pos (np.ndarray): Integer positions of rebalance dates.

    Returns:
        tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
            alpha, sharpe, drawdown, trades — one value per rebalance.
    """
    n_reb      = len(rebalance_pos)
    alpha_arr  = np.full(n_reb, np.nan)
    sharpe_arr = np.full(n_reb, np.nan)
    dd_arr     = np.full(n_reb, np.nan)
    trades_arr = np.zeros(n_reb)

    for i, pos in enumerate(rebalance_pos):
        start = pos - LOOKBACK_BARS
        if start < 1:
            continue

        equity_win = equity_arr[start:pos + 1]
        if equity_win.size < 2 or equity_win[0] == 0:
            continue

        ret_win = rets_arr[start + 1:pos + 1]
        ret_win = ret_win[~np.isnan(ret_win)]
        if ret_win.size == 0:
            continue

        strat_ret = (equity_win[-1] / equity_win[0] - 1.0) * 100.0
        bh_ret    = (close_arr[pos] / close_arr[start] - 1.0) * 100.0

        std    = np.std(ret_win)
        sharpe = (
            0.0 if std == 0
            else (np.mean(ret_win) / std) * np.sqrt(ANNUALIZATION)
        )

        peak = np.maximum.accumulate(equity_win)
        dd   = (equity_win / peak - 1.0).min() * -100.0

        alpha_arr[i]  = strat_ret - bh_ret
        sharpe_arr[i] = sharpe
        dd_arr[i]     = dd
        in_pos   = (np.diff(equity_win) != 0).astype(int)
        n_trades = int(np.sum(np.diff(np.concatenate([[0], in_pos])) > 0))
        if in_pos.size > 0 and in_pos[0]:
            n_trades += 1
        trades_arr[i] = n_trades

    return alpha_arr, sharpe_arr, dd_arr, trades_arr


def _run_topx(
    strat_equity: dict[str, np.ndarray],
    strat_rets: dict[str, np.ndarray],
    close_df: pd.DataFrame,
    symbols: list[str],
    rebalance_pos: np.ndarray,
    rebalance_dates: pd.DatetimeIndex,
) -> dict[str, float]:
    """
    Run the Top-X portfolio simulation for one strategy and return metrics.

    Args:
        strat_equity (dict): Pre-computed equity arrays keyed by symbol.
        strat_rets (dict): Pre-computed return arrays keyed by symbol.
        close_df (pd.DataFrame): Aligned close price matrix.
        symbols (list[str]): Ordered list of symbol names.
        rebalance_pos (np.ndarray): Integer bar positions of rebalance dates.
        rebalance_dates (pd.DatetimeIndex): Corresponding datetime index.

    Returns:
        dict[str, float]: perf, sharpe, dd, avg_active, n_cash.
    """
    n_sym = len(symbols)
    n_reb = len(rebalance_pos)

    alpha_mat  = np.full((n_sym, n_reb), np.nan)
    sharpe_mat = np.full((n_sym, n_reb), np.nan)
    dd_mat     = np.full((n_sym, n_reb), np.nan)

    for s_idx, symbol in enumerate(symbols):
        close_arr  = close_df[symbol].values
        equity_arr = strat_equity[symbol]
        rets_arr   = strat_rets[symbol]

        a, sh, dd, tr = _compute_metrics(
            close_arr, equity_arr, rets_arr, rebalance_pos
        )

        insufficient        = tr < MIN_TRADES_IN_LOOKBACK
        a[insufficient]     = np.nan
        sh[insufficient]    = np.nan
        dd[insufficient]    = np.nan

        alpha_mat[s_idx]  = a
        sharpe_mat[s_idx] = sh
        dd_mat[s_idx]     = dd

    z_alpha  = _zscore_cols(alpha_mat)
    z_sharpe = _zscore_cols(sharpe_mat)
    z_dd     = _zscore_cols(dd_mat)
    score_mat = z_alpha + z_sharpe - z_dd

    # ── Weights ──────────────────────────────────────────────────
    weights_arr = np.zeros((n_reb, n_sym))
    for i in range(n_reb):
        col_scores = score_mat[:, i]
        eligible   = np.where(
            np.isfinite(col_scores) & (col_scores >= MIN_SCORE_TO_INVEST)
        )[0]
        if eligible.size == 0:
            continue
        top_idx = eligible[np.argsort(col_scores[eligible])[::-1][:TOP_X]]
        weights_arr[i, top_idx] = 1.0 / len(top_idx)

    # ── Portfolio equity ─────────────────────────────────────────
    portfolio_values = [CAPITAL_INITIAL]
    prev_weights     = np.zeros(n_sym)
    n_cash           = 0
    active_counts    = []

    for i in range(n_reb - 1):
        pos0 = rebalance_pos[i]
        pos1 = rebalance_pos[i + 1]
        w    = weights_arr[i]

        active = int(np.count_nonzero(w))
        active_counts.append(active)
        if active == 0:
            n_cash += 1

        turnover = np.sum(np.abs(w - prev_weights))
        fee_cost = turnover * FEES

        sym_rets = np.array([
            (strat_equity[sym][pos1] / strat_equity[sym][pos0] - 1.0)
            if strat_equity[sym][pos0] > 0 else 0.0
            for sym in symbols
        ])

        port_ret = float(np.dot(w, sym_rets))
        capital  = portfolio_values[-1] * (1.0 - fee_cost) * (1.0 + port_ret)
        portfolio_values.append(capital)
        prev_weights = w

    eq_arr  = np.array(portfolio_values)
    total_ret = (eq_arr[-1] / eq_arr[0] - 1.0) * 100.0

    peak   = np.maximum.accumulate(eq_arr)
    max_dd = float((eq_arr / peak - 1.0).min() * -100.0)

    period_rets = np.diff(eq_arr) / eq_arr[:-1]
    std_r = np.std(period_rets)
    sharpe = (
        0.0 if std_r == 0
        else float(np.mean(period_rets) / std_r * np.sqrt(52))
    )

    avg_active = float(np.mean(active_counts)) if active_counts else 0.0

    return {
        "perf":       round(total_ret, 2),
        "sharpe":     round(sharpe, 3),
        "dd":         round(max_dd, 2),
        "avg_active": round(avg_active, 2),
        "n_cash":     n_cash,
    }


# ── Load data ────────────────────────────────────────────────────
csv_files = sorted(DATA_DIR.glob("*_5min_3ans.csv"))
if not csv_files:
    raise SystemExit(f"Aucun CSV trouvé dans {DATA_DIR}")

symbols: list[str] = []
closes: dict[str, pd.Series] = {}
dfs: dict[str, pd.DataFrame] = {}
common_index = None

for _csv in csv_files:
    _symbol = _csv.stem.replace("_5min_3ans", "").replace("-", "/")
    _df = (
        pd.read_csv(_csv, parse_dates=["datetime"])
        .set_index("datetime")
        .sort_index()
    )
    for _col in ["open", "high", "low", "close", "volume"]:
        if _col in _df.columns:
            _df[_col] = _df[_col].astype(float)

    symbols.append(_symbol)
    closes[_symbol] = _df["close"]
    dfs[_symbol]    = _df
    common_index = (
        _df["close"].index if common_index is None
        else common_index.intersection(_df["close"].index)
    )

symbols = sorted(symbols)
close_df = pd.DataFrame(
    {s: closes[s].reindex(common_index) for s in symbols}
).ffill()

# ── Rebalance schedule (calculé une seule fois) ──────────────────
rebalance_dates = (
    pd.Series(common_index, index=common_index)
    .resample(REBALANCE_FREQ).last()
    .dropna()
    .index
)
min_index       = common_index[min(LOOKBACK_BARS, len(common_index) - 1)]
rebalance_dates = rebalance_dates[rebalance_dates >= min_index]

rebalance_pos = (
    np.searchsorted(common_index.values, rebalance_dates.values, side="right") - 1
)
valid_mask      = (
    (rebalance_pos >= LOOKBACK_BARS) & (rebalance_pos < len(common_index))
)
rebalance_pos   = rebalance_pos[valid_mask]
rebalance_dates = common_index[rebalance_pos]

logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info(
    "%d symboles | %d stratégies | %d rebalancements",
    len(symbols), len(STRATEGIES), len(rebalance_dates),
)
logger.info(
    "Top-X=%d | Lookback=%d semaines | Freq=%s",
    TOP_X, LOOKBACK_WEEKS, REBALANCE_FREQ,
)
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# ── CSV header ───────────────────────────────────────────────────
with open(CSV_OUT, "w", encoding="utf-8") as _f:
    _f.write(",".join(COLUMNS) + "\n")

# ── Main loop ────────────────────────────────────────────────────
t_global  = time.time()
n_ok      = 0
n_err     = 0
n_total   = len(STRATEGIES)

for strat_idx, (strat_name, fn_strat) in enumerate(STRATEGIES.items()):
    try:
        # 1. Calcul des signaux et equity sur tous les symboles
        strat_equity: dict[str, np.ndarray] = {}
        strat_rets:   dict[str, np.ndarray] = {}

        for symbol in symbols:
            df_sym  = dfs[symbol].reindex(common_index).ffill()
            entries, exits = fn_strat(df_sym)

            pf = vbt.Portfolio.from_signals(
                closes[symbol].reindex(common_index).ffill(),
                entries=entries,
                exits=exits,
                init_cash=CAPITAL_INITIAL,
                fees=FEES,
                freq="5min",
            )
            strat_equity[symbol] = pf.value().values
            strat_rets[symbol]   = pf.returns().values
            del pf
            gc.collect()

        # 2. TopX simulation
        res = _run_topx(
            strat_equity=strat_equity,
            strat_rets=strat_rets,
            close_df=close_df,
            symbols=symbols,
            rebalance_pos=rebalance_pos,
            rebalance_dates=rebalance_dates,
        )

        # 3. Écriture CSV incrémentale
        ligne = (
            f'"{strat_name}",'
            f'{res["perf"]},{res["sharpe"]},{res["dd"]},'
            f'{res["avg_active"]},{res["n_cash"]}\n'
        )
        with open(CSV_OUT, "a", encoding="utf-8") as _f:
            _f.write(ligne)

        sign = "✓" if res["perf"] >= 0 else "✗"
        logger.info(
            "  [%d/%d] %-40s  %+7.2f%%  Sharpe %.3f  DD %.2f%%  %s",
            strat_idx + 1, n_total,
            strat_name, res["perf"], res["sharpe"], res["dd"], sign,
        )
        n_ok += 1

    except Exception as exc:
        logger.warning("  [%d/%d] %-40s ✗ %s", strat_idx + 1, n_total, strat_name, exc)
        n_err += 1

    finally:
        try:
            del strat_equity, strat_rets
        except Exception:
            pass
        gc.collect()

    if (strat_idx + 1) % 10 == 0:
        elapsed   = time.time() - t_global
        remaining = (elapsed / (strat_idx + 1)) * (n_total - strat_idx - 1)
        logger.info(
            "  ⏱  %d/%d — ~%.1f min restantes",
            strat_idx + 1, n_total, remaining / 60,
        )

# ── Sort & save CSV ──────────────────────────────────────────────
df_res = pd.read_csv(CSV_OUT)
df_res = df_res.sort_values("Sharpe", ascending=False)
df_res.to_csv(CSV_OUT, index=False)

elapsed_total = time.time() - t_global
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info("✓ %d stratégies testées / %d erreurs", n_ok, n_err)
logger.info("✓ Durée totale : %.1f min", elapsed_total / 60)

# ── Top 10 dans les logs ─────────────────────────────────────────
logger.info("\n── Top 10 par Sharpe ──")
logger.info(
    "\n%s",
    df_res.head(10)[
        ["Strategy", "Performance %", "Sharpe", "Max Drawdown %"]
    ].to_string(index=False),
)

# ── HTML report — top 50 ─────────────────────────────────────────
top50 = df_res.head(50)
rows_html = ""
for _, r in top50.iterrows():
    color = "#1a6e1a" if r["Performance %"] >= 0 else "#8b1a1a"
    rows_html += (
        f"<tr>"
        f"<td><code>{r['Strategy']}</code></td>"
        f"<td style='color:{color};font-weight:600'>"
        f"{r['Performance %']:+.2f}%</td>"
        f"<td>{r['Sharpe']:.3f}</td>"
        f"<td>{r['Max Drawdown %']:.2f}%</td>"
        f"<td>{r['Avg Symbols Active']:.1f} / {TOP_X}</td>"
        f"<td>{int(r['Rebalances In Cash'])}</td>"
        f"</tr>\n"
    )

html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Optimize TopX — Top 50</title>
<style>
  body  {{ font-family: sans-serif; margin: 2rem; color: #111; }}
  h1    {{ font-size: 1.4rem; border-bottom: 2px solid #333;
           padding-bottom: .4rem; }}
  .meta {{ background: #f0f4ff; padding: .6rem 1rem; border-radius: 6px;
           display: inline-block; margin-bottom: 1.5rem; font-size: .9rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .82rem; }}
  th    {{ background: #222; color: #fff; padding: .5rem .7rem;
           text-align: left; }}
  td    {{ padding: .35rem .7rem; border-bottom: 1px solid #ddd; }}
  tr:hover td {{ background: #f5f7ff; }}
  code  {{ font-size: .78rem; background: #f0f0f0;
           padding: .1rem .3rem; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Optimize TopX — Top 50 stratégies par Sharpe</h1>
<div class="meta">
  {n_ok} stratégies testées &nbsp;|&nbsp;
  Top-X = {TOP_X} &nbsp;|&nbsp;
  Lookback = {LOOKBACK_WEEKS} semaines &nbsp;|&nbsp;
  Rebalancement = {REBALANCE_FREQ} &nbsp;|&nbsp;
  Capital = {CAPITAL_INITIAL:,.0f} $ &nbsp;|&nbsp;
  Frais = {FEES * 100:.3f}%
</div>
<table>
<thead>
  <tr>
    <th>Stratégie</th>
    <th>Performance %</th>
    <th>Sharpe</th>
    <th>Max DD %</th>
    <th>Symboles actifs (moy)</th>
    <th>Rebal. en cash</th>
  </tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""

with open(HTML_OUT, "w", encoding="utf-8") as _f:
    _f.write(html)

logger.info("✓ CSV  : %s", CSV_OUT)
logger.info("✓ HTML : %s", HTML_OUT)
