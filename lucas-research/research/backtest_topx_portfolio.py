"""
Top X symbol portfolio backtest with dynamic scoring.
- Score computed per symbol at each rebalance using best strategy
- Weekly rebalance, weights proportional to score
"""

import time
import gc
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt

from strategies import STRATEGIES

# ------------------------------
# Configuration
# ------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "resultats"
OUTPUT_DIR.mkdir(exist_ok=True)

CAPITAL_INITIAL = 10_000
FEES = 0.0005  # 0.05% per trade notional

TOP_X = 5
# Use "D" for daily, "W-FRI" for weekly, "M" for monthly
REBALANCE_FREQ = "W-FRI"
LOOKBACK_WEEKS = 4
BARS_PER_WEEK = 5 * 78  # 5 trading days * 78 bars (5min) per day
LOOKBACK_BARS = LOOKBACK_WEEKS * BARS_PER_WEEK

# If True, only invest in symbols with score >= MIN_SCORE_TO_INVEST
# Remaining weight stays in cash.
INVEST_IF_SCORE_POSITIVE = True
MIN_SCORE_TO_INVEST = 0.0

CSV_SCORE_OUT = OUTPUT_DIR / "scores_topx.csv"
CSV_WEIGHTS_OUT = OUTPUT_DIR / "weights_topx.csv"
CSV_EQUITY_OUT = OUTPUT_DIR / "equity_topx.csv"
HTML_REPORT_OUT = OUTPUT_DIR / "topx_report.html"

# ------------------------------
# Helpers
# ------------------------------

def _zscore(mat: np.ndarray) -> np.ndarray:
    mean = np.nanmean(mat, axis=0)
    std = np.nanstd(mat, axis=0)
    std = np.where(std == 0, np.nan, std)
    return (mat - mean) / std


def _compute_metrics_by_rebalance(
    close: pd.Series,
    rebalance_pos: np.ndarray,
    annualization: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Return best alpha, sharpe, dd arrays per rebalance for one symbol.
    The best strategy is selected at each rebalance using a composite score.
    """
    n_reb = len(rebalance_pos)
    n_strat = len(STRATEGIES)

    alpha_mat = np.full((n_strat, n_reb), np.nan, dtype=float)
    sharpe_mat = np.full((n_strat, n_reb), np.nan, dtype=float)
    dd_mat = np.full((n_strat, n_reb), np.nan, dtype=float)

    close_arr = close.values

    for s_idx, (_, fn_strat) in enumerate(STRATEGIES.items()):
        entries, exits = fn_strat(close)
        pf = vbt.Portfolio.from_signals(
            close,
            entries=entries,
            exits=exits,
            init_cash=CAPITAL_INITIAL,
            fees=FEES,
            freq="5min",
        )

        equity = pf.value().reindex(close.index).values
        rets = pf.returns().reindex(close.index).values

        for i, pos in enumerate(rebalance_pos):
            start = pos - LOOKBACK_BARS
            if start < 1:
                continue

            equity_win = equity[start:pos + 1]
            if equity_win.size < 2:
                continue

            ret_win = rets[start + 1:pos + 1]
            ret_win = ret_win[~np.isnan(ret_win)]

            if ret_win.size == 0:
                continue

            strat_ret = (equity_win[-1] / equity_win[0] - 1.0) * 100.0
            bh_ret = (close_arr[pos] / close_arr[start] - 1.0) * 100.0
            alpha = strat_ret - bh_ret

            std = np.std(ret_win)
            sharpe = 0.0 if std == 0 else (np.mean(ret_win) / std) * np.sqrt(annualization)

            peak = np.maximum.accumulate(equity_win)
            dd = (equity_win / peak - 1.0).min() * -100.0

            alpha_mat[s_idx, i] = alpha
            sharpe_mat[s_idx, i] = sharpe
            dd_mat[s_idx, i] = dd

        del pf, equity, rets
        gc.collect()

    z_alpha = _zscore(alpha_mat)
    z_sharpe = _zscore(sharpe_mat)
    z_dd = _zscore(dd_mat)

    score_mat = z_alpha + z_sharpe - z_dd
    score_mat = np.nan_to_num(score_mat, nan=-np.inf)

    best_idx = np.argmax(score_mat, axis=0)
    cols = np.arange(n_reb)

    best_alpha = alpha_mat[best_idx, cols]
    best_sharpe = sharpe_mat[best_idx, cols]
    best_dd = dd_mat[best_idx, cols]

    return best_alpha, best_sharpe, best_dd


def _sparkline_svg(values: np.ndarray, width: int = 800, height: int = 200) -> str:
    clean = values[np.isfinite(values)]
    if clean.size == 0:
        return ""
    vmin = float(np.min(clean))
    vmax = float(np.max(clean))
    if vmax == vmin:
        vmax = vmin + 1.0

    pad = 10
    xs = np.linspace(pad, width - pad, num=values.size)
    ys = pad + (height - 2 * pad) * (1.0 - (values - vmin) / (vmax - vmin))

    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    return (
        f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
        f"xmlns='http://www.w3.org/2000/svg'>"
        f"<polyline fill='none' stroke='#1b3a57' stroke-width='2' "
        f"points='{points}' />"
        f"</svg>"
    )


# ------------------------------
# Load data
# ------------------------------

csv_files = sorted(DATA_DIR.glob("*_5min_3ans.csv"))
if not csv_files:
    raise SystemExit(f"No CSV files found in {DATA_DIR}")

symbols = []
closes = {}
common_index = None

for csv_file in csv_files:
    symbol = csv_file.stem.replace("_5min_3ans", "").replace("-", "/")
    df = pd.read_csv(csv_file, parse_dates=["datetime"]).set_index("datetime").sort_index()
    df["close"] = df["close"].astype(float)
    close = df["close"]

    symbols.append(symbol)
    closes[symbol] = close
    common_index = close.index if common_index is None else common_index.intersection(close.index)

symbols = sorted(symbols)
close_df = pd.DataFrame({s: closes[s].reindex(common_index) for s in symbols}).ffill()

# ------------------------------
# Rebalance schedule
# ------------------------------

rebalance_dates = (
    close_df.index.to_series().resample(REBALANCE_FREQ).last().dropna().index
)

if len(rebalance_dates) == 0:
    raise SystemExit("No rebalance dates found. Check REBALANCE_FREQ.")

min_index = common_index[min(LOOKBACK_BARS, len(common_index) - 1)]
rebalance_dates = rebalance_dates[rebalance_dates >= min_index]

rebalance_pos = np.searchsorted(
    common_index.values,
    rebalance_dates.values,
    side="right",
) - 1

valid_mask = (rebalance_pos >= LOOKBACK_BARS) & (rebalance_pos < len(common_index))
rebalance_pos = rebalance_pos[valid_mask]
rebalance_dates = common_index[rebalance_pos]

annualization = 252 * 78  # 5min bars per year

# ------------------------------
# Score per symbol
# ------------------------------

t_start = time.time()

best_alpha_df = pd.DataFrame(index=rebalance_dates, columns=symbols, dtype=float)
best_sharpe_df = pd.DataFrame(index=rebalance_dates, columns=symbols, dtype=float)
best_dd_df = pd.DataFrame(index=rebalance_dates, columns=symbols, dtype=float)

for symbol in symbols:
    print(f"Scoring {symbol}...")
    close = close_df[symbol]

    best_alpha, best_sharpe, best_dd = _compute_metrics_by_rebalance(
        close=close,
        rebalance_pos=rebalance_pos,
        annualization=annualization,
    )

    best_alpha_df[symbol] = best_alpha
    best_sharpe_df[symbol] = best_sharpe
    best_dd_df[symbol] = best_dd

# Normalize across symbols and compute score
alpha_z = _zscore(best_alpha_df.values.T).T
sharpe_z = _zscore(best_sharpe_df.values.T).T
dd_z = _zscore(best_dd_df.values.T).T

score_df = pd.DataFrame(
    alpha_z + sharpe_z - dd_z,
    index=rebalance_dates,
    columns=symbols,
)

if not score_df.index.is_unique:
    score_df = score_df[~score_df.index.duplicated(keep="last")]

score_df.to_csv(CSV_SCORE_OUT, index=True)

# ------------------------------
# Weights and portfolio equity
# ------------------------------

weights_df = pd.DataFrame(0.0, index=rebalance_dates, columns=symbols)

for dt in rebalance_dates:
    scores = score_df.loc[dt]
    if isinstance(scores, pd.DataFrame):
        scores = scores.iloc[-1]
    scores = scores.copy()
    top = scores.nlargest(TOP_X)

    if INVEST_IF_SCORE_POSITIVE:
        top = top[top >= MIN_SCORE_TO_INVEST]

    if top.empty:
        continue

    weights = np.maximum(top.values, 0.0)
    weights = weights / weights.sum()

    weights_df.loc[dt, top.index] = weights

weights_df.to_csv(CSV_WEIGHTS_OUT, index=True)

if not weights_df.index.is_unique:
    weights_df = weights_df[~weights_df.index.duplicated(keep="last")]

# Portfolio equity

portfolio_values = [CAPITAL_INITIAL]
prev_weights = pd.Series(0.0, index=symbols)

for i in range(len(rebalance_pos) - 1):
    pos0 = rebalance_pos[i]
    pos1 = rebalance_pos[i + 1]
    t0 = rebalance_dates[i]
    t1 = rebalance_dates[i + 1]

    w = weights_df.loc[t0]
    if isinstance(w, pd.DataFrame):
        w = w.iloc[-1]

    turnover = (w - prev_weights).abs().sum()
    fee_cost = turnover * FEES

    prices0 = close_df.iloc[pos0]
    prices1 = close_df.iloc[pos1]
    symbol_rets = (prices1 / prices0 - 1.0).astype(float)
    w = w.astype(float)

    port_ret = float((w * symbol_rets).sum())

    capital = portfolio_values[-1]
    capital = capital * (1.0 - fee_cost) * (1.0 + port_ret)

    portfolio_values.append(capital)
    prev_weights = w

portfolio_index = rebalance_dates[: len(portfolio_values)]

portfolio_df = pd.DataFrame(
    {
        "equity": portfolio_values,
    },
    index=portfolio_index,
)

portfolio_df.to_csv(CSV_EQUITY_OUT, index=True)

# ------------------------------
# HTML report
# ------------------------------

equity_series = portfolio_df["equity"].values
equity_svg = _sparkline_svg(equity_series)

latest_dt = portfolio_df.index[-1]
latest_equity = float(portfolio_df.loc[latest_dt, "equity"])
latest_weights = weights_df.loc[latest_dt]
if isinstance(latest_weights, pd.DataFrame):
        latest_weights = latest_weights.iloc[-1]
latest_weights = latest_weights[latest_weights > 0].sort_values(ascending=False)

latest_cash = float(max(0.0, 1.0 - latest_weights.sum()))

rows_latest = "".join(
        f"<tr><td>{sym}</td><td>{w*100:.2f}%</td></tr>" for sym, w in latest_weights.items()
)
if latest_cash > 0:
        rows_latest += f"<tr><td>CASH</td><td>{latest_cash*100:.2f}%</td></tr>"

rows_picks = []
for dt, row in weights_df.iterrows():
        picks = row[row > 0].sort_values(ascending=False)
        if picks.empty:
                picks_txt = "-"
        else:
                picks_txt = "; ".join(f"{s} {w*100:.1f}%" for s, w in picks.items())
        cash = max(0.0, 1.0 - float(picks.sum()))
        rows_picks.append(
                f"<tr><td>{dt}</td><td>{picks_txt}</td><td>{cash*100:.2f}%</td></tr>"
        )

rows_picks_html = "\n".join(rows_picks)

html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Top X Portfolio Report</title>
<style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #111; }}
    h1 {{ font-size: 1.4rem; border-bottom: 2px solid #333; padding-bottom: .4rem; }}
    .meta {{ background: #f0f4ff; padding: .6rem 1rem; border-radius: 6px;
                     display: inline-block; margin-bottom: 1.5rem; font-size: .9rem; }}
    table {{ border-collapse: collapse; width: 100%; font-size: .9rem; margin-bottom: 1.5rem; }}
    th {{ background: #222; color: #fff; padding: .5rem .8rem; text-align: left; }}
    td {{ padding: .4rem .8rem; border-bottom: 1px solid #ddd; vertical-align: top; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 1.2rem; }}
    .box {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem; }}
    .equity {{ background: #f8fafc; }}
</style>
</head>
<body>
<h1>Top {TOP_X} Portfolio - Rapport</h1>
<div class="meta">
    Rebalance: {REBALANCE_FREQ} | Lookback: {LOOKBACK_WEEKS} semaines
    | Capital initial: {CAPITAL_INITIAL:,} $ | Frais: {FEES*100:.3f}%
</div>

<div class="grid">
    <div class="box equity">
        <h2>Equity (dernier: {latest_equity:,.2f} $)</h2>
        {equity_svg}
    </div>

    <div class="box">
        <h2>Derniere allocation ({latest_dt})</h2>
        <table>
            <thead><tr><th>Symbole</th><th>Poids</th></tr></thead>
            <tbody>
                {rows_latest}
            </tbody>
        </table>
    </div>

    <div class="box">
        <h2>Choix d'investissement par rebalancement</h2>
        <table>
            <thead><tr><th>Date</th><th>Top {TOP_X} (poids)</th><th>Cash</th></tr></thead>
            <tbody>
                {rows_picks_html}
            </tbody>
        </table>
    </div>
</div>

</body>
</html>"""

with open(HTML_REPORT_OUT, "w", encoding="utf-8") as f:
        f.write(html)

elapsed = time.time() - t_start
print(f"Done. Elapsed: {elapsed/60:.1f} min")
print(f"Scores: {CSV_SCORE_OUT}")
print(f"Weights: {CSV_WEIGHTS_OUT}")
print(f"Equity: {CSV_EQUITY_OUT}")
print(f"Report: {HTML_REPORT_OUT}")
