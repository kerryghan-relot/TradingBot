"""
Top-X symbol portfolio backtest — single strategy, multi-symbol.
=================================================================

One strategy (STRATEGY_NAME) is applied to every available symbol.
At each rebalance date, symbols are ranked by the strategy's recent
performance (composite Z-score of alpha, Sharpe, drawdown) over a
rolling lookback window.  The top-X symbols receive equal weights.
Between rebalances, the strategy's actual trade signals drive the
P&L — not buy-and-hold.

Usage::

    python -m backtest.vectorized.backtest_topx_portfolio

Outputs::

    results/scores_topx.csv
    results/weights_topx.csv
    results/equity_topx.csv
    results/topx_report.html
"""

import gc
import logging
import time

import numpy as np
import pandas as pd
import vectorbt as vbt

from core.constants import (
    ANNUALIZATION,
    BARS_PER_WEEK,
    CAPITAL_INITIAL,
    DATA_DIR,
    FEES,
    OUTPUT_DIR,
)
from backtest.vectorized.strategies_vbt import STRATEGIES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────
# Nom de la stratégie à utiliser — doit exister dans STRATEGIES.
STRATEGY_NAME: str = "VWAP+OU"

TOP_X: int = 5                  # nombre de symboles à sélectionner
REBALANCE_FREQ: str = "W-FRI"  # "D" daily | "W-FRI" weekly | "M" monthly
LOOKBACK_WEEKS: int = 4        # fenêtre de scoring (en semaines)
LOOKBACK_BARS: int = LOOKBACK_WEEKS * BARS_PER_WEEK

MIN_SCORE_TO_INVEST: float = 0.0   # score Z minimum pour investir
MIN_TRADES_IN_LOOKBACK: int = 3    # ignorer si moins de N trades sur la fenêtre

CSV_SCORE_OUT   = OUTPUT_DIR / "scores_topx.csv"
CSV_WEIGHTS_OUT = OUTPUT_DIR / "weights_topx.csv"
CSV_EQUITY_OUT  = OUTPUT_DIR / "equity_topx.csv"
HTML_REPORT_OUT = OUTPUT_DIR / "topx_report.html"


# ── Validate strategy ────────────────────────────────────────────
if STRATEGY_NAME not in STRATEGIES:
    available = list(STRATEGIES.keys())[:10]
    raise SystemExit(
        f"Stratégie inconnue : '{STRATEGY_NAME}'.\n"
        f"Exemples disponibles : {available}"
    )

fn_strat = STRATEGIES[STRATEGY_NAME]
logger.info("Stratégie sélectionnée : %s", STRATEGY_NAME)


# ── Helpers ──────────────────────────────────────────────────────

def _zscore_cols(mat: np.ndarray) -> np.ndarray:
    """
    Z-score normalise a 2-D matrix column-wise, ignoring NaN.

    Args:
        mat (np.ndarray): Shape (n_symbols, n_rebalances).

    Returns:
        np.ndarray: Z-scored matrix, same shape.
    """
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
    Compute strategy alpha, Sharpe, drawdown, and trade count per rebalance.

    For each rebalance position, performance is measured over the
    rolling lookback window ending at that position.

    Args:
        close_arr (np.ndarray): Close price array aligned to common_index.
        equity_arr (np.ndarray): Strategy equity curve aligned to common_index.
        rets_arr (np.ndarray): Strategy bar returns aligned to common_index.
        rebalance_pos (np.ndarray): Integer bar positions of rebalance dates.

    Returns:
        tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
            alpha_arr, sharpe_arr, dd_arr, trades_arr — one value per rebalance.
    """
    n_reb = len(rebalance_pos)
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
        alpha     = strat_ret - bh_ret

        std    = np.std(ret_win)
        sharpe = (
            0.0 if std == 0
            else (np.mean(ret_win) / std) * np.sqrt(ANNUALIZATION)
        )

        peak = np.maximum.accumulate(equity_win)
        dd   = (equity_win / peak - 1.0).min() * -100.0

        in_pos   = (np.diff(equity_win) != 0).astype(int)
        n_trades = int(np.sum(np.diff(np.concatenate([[0], in_pos])) > 0))
        if in_pos.size > 0 and in_pos[0]:
            n_trades += 1

        alpha_arr[i]  = alpha
        sharpe_arr[i] = sharpe
        dd_arr[i]     = dd
        trades_arr[i] = n_trades

    return alpha_arr, sharpe_arr, dd_arr, trades_arr


def _sparkline_svg(
    values: np.ndarray,
    width: int = 800,
    height: int = 200,
) -> str:
    """
    Render a simple SVG polyline sparkline from a 1-D array.

    Args:
        values (np.ndarray): Data to plot; NaN values are ignored.
        width (int, optional): SVG width in pixels. Defaults to 800.
        height (int, optional): SVG height in pixels. Defaults to 200.

    Returns:
        str: SVG markup string, or empty string if no finite values.
    """
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
        f"<svg width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' "
        f"xmlns='http://www.w3.org/2000/svg'>"
        f"<polyline fill='none' stroke='#1b3a57' stroke-width='2' "
        f"points='{points}' />"
        f"</svg>"
    )


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

logger.info(
    "%d symboles chargés | %d barres communes",
    len(symbols), len(common_index),
)


# ── Run strategy on every symbol ─────────────────────────────────
logger.info("Calcul de la stratégie '%s' sur tous les symboles...", STRATEGY_NAME)
t_start = time.time()

strat_equity: dict[str, np.ndarray] = {}
strat_rets:   dict[str, np.ndarray] = {}

for symbol in symbols:
    df_sym = dfs[symbol].reindex(common_index).ffill()
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
    logger.info("  ✓ %s", symbol)


# ── Rebalance schedule ───────────────────────────────────────────
rebalance_dates = (
    pd.Series(common_index, index=common_index)
    .resample(REBALANCE_FREQ).last()
    .dropna()
    .index
)

min_index    = common_index[min(LOOKBACK_BARS, len(common_index) - 1)]
rebalance_dates = rebalance_dates[rebalance_dates >= min_index]

rebalance_pos = (
    np.searchsorted(common_index.values, rebalance_dates.values, side="right") - 1
)
valid_mask    = (rebalance_pos >= LOOKBACK_BARS) & (rebalance_pos < len(common_index))
rebalance_pos = rebalance_pos[valid_mask]
rebalance_dates = common_index[rebalance_pos]

logger.info("%d dates de rebalancement", len(rebalance_dates))


# ── Score per symbol ─────────────────────────────────────────────
n_sym = len(symbols)
n_reb = len(rebalance_pos)

alpha_mat  = np.full((n_sym, n_reb), np.nan)
sharpe_mat = np.full((n_sym, n_reb), np.nan)
dd_mat     = np.full((n_sym, n_reb), np.nan)
trades_mat = np.zeros((n_sym, n_reb))

for s_idx, symbol in enumerate(symbols):
    close_arr  = close_df[symbol].values
    equity_arr = strat_equity[symbol]
    rets_arr   = strat_rets[symbol]

    a, sh, dd, tr = _compute_metrics(
        close_arr, equity_arr, rets_arr, rebalance_pos
    )

    # Masquer les périodes avec trop peu de trades (non fiables)
    insufficient = tr < MIN_TRADES_IN_LOOKBACK
    a[insufficient]  = np.nan
    sh[insufficient] = np.nan
    dd[insufficient] = np.nan

    alpha_mat[s_idx]  = a
    sharpe_mat[s_idx] = sh
    dd_mat[s_idx]     = dd
    trades_mat[s_idx] = tr

# Score composite : Z(alpha) + Z(sharpe) - Z(drawdown)
z_alpha  = _zscore_cols(alpha_mat)
z_sharpe = _zscore_cols(sharpe_mat)
z_dd     = _zscore_cols(dd_mat)
score_mat = z_alpha + z_sharpe - z_dd

score_df = pd.DataFrame(score_mat.T, index=rebalance_dates, columns=symbols)
if not score_df.index.is_unique:
    score_df = score_df[~score_df.index.duplicated(keep="last")]
score_df.to_csv(CSV_SCORE_OUT)


# ── Weights — equal weight on top-X ─────────────────────────────
weights_df = pd.DataFrame(0.0, index=rebalance_dates, columns=symbols)

for dt in rebalance_dates:
    scores = score_df.loc[dt]
    if isinstance(scores, pd.DataFrame):
        scores = scores.iloc[-1]

    eligible = scores[scores >= MIN_SCORE_TO_INVEST].nlargest(TOP_X)
    if eligible.empty:
        continue

    # Poids égaux sur les symboles sélectionnés
    weights_df.loc[dt, eligible.index] = 1.0 / len(eligible)

if not weights_df.index.is_unique:
    weights_df = weights_df[~weights_df.index.duplicated(keep="last")]
weights_df.to_csv(CSV_WEIGHTS_OUT)


# ── Portfolio equity — strategy returns, not B&H ─────────────────
portfolio_values: list[float] = [CAPITAL_INITIAL]
prev_weights = pd.Series(0.0, index=symbols)

for i in range(len(rebalance_pos) - 1):
    pos0 = rebalance_pos[i]
    pos1 = rebalance_pos[i + 1]
    t0   = rebalance_dates[i]

    w = weights_df.loc[t0]
    if isinstance(w, pd.DataFrame):
        w = w.iloc[-1]
    w = w.astype(float)

    # Frais sur le turnover du portefeuille
    turnover = (w - prev_weights).abs().sum()
    fee_cost = turnover * FEES

    # Retour de la STRATÉGIE sur chaque symbole dans la période
    symbol_rets = pd.Series(dtype=float, index=symbols)
    for sym in symbols:
        eq = strat_equity[sym]
        eq0 = eq[pos0]
        symbol_rets[sym] = (eq[pos1] / eq0 - 1.0) if eq0 > 0 else 0.0

    port_ret = float((w * symbol_rets).sum())
    capital  = portfolio_values[-1] * (1.0 - fee_cost) * (1.0 + port_ret)
    portfolio_values.append(capital)
    prev_weights = w

portfolio_index = rebalance_dates[:len(portfolio_values)]
portfolio_df = pd.DataFrame(
    {"equity": portfolio_values}, index=portfolio_index
)
portfolio_df.to_csv(CSV_EQUITY_OUT)

# ── Performance summary ──────────────────────────────────────────
final_equity = portfolio_values[-1]
total_ret    = (final_equity / CAPITAL_INITIAL - 1.0) * 100.0

eq_arr  = np.array(portfolio_values)
peak    = np.maximum.accumulate(eq_arr)
max_dd  = float((eq_arr / peak - 1.0).min() * -100.0)

period_rets = np.diff(eq_arr) / eq_arr[:-1]
std_r       = np.std(period_rets)
sharpe_port = (
    0.0 if std_r == 0
    else float(np.mean(period_rets) / std_r * np.sqrt(52))  # weekly → annual
)

logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info("Stratégie      : %s", STRATEGY_NAME)
logger.info("Capital final  : %.2f $  (%+.2f%%)", final_equity, total_ret)
logger.info("Max Drawdown   : %.2f%%", max_dd)
logger.info("Sharpe annuel  : %.3f", sharpe_port)
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


# ── HTML report ──────────────────────────────────────────────────
equity_svg = _sparkline_svg(np.array(portfolio_values))

latest_dt      = portfolio_df.index[-1]
latest_equity  = float(portfolio_df.loc[latest_dt, "equity"])
latest_weights = weights_df.loc[latest_dt]
if isinstance(latest_weights, pd.DataFrame):
    latest_weights = latest_weights.iloc[-1]
latest_weights = latest_weights[latest_weights > 0].sort_values(ascending=False)
latest_cash    = float(max(0.0, 1.0 - latest_weights.sum()))

rows_latest = "".join(
    f"<tr><td>{sym}</td><td>{w * 100:.1f}%</td>"
    f"<td>{score_df.loc[latest_dt, sym]:+.3f}</td></tr>"
    for sym, w in latest_weights.items()
)
if latest_cash > 0:
    rows_latest += (
        f"<tr><td><em>CASH</em></td>"
        f"<td>{latest_cash * 100:.1f}%</td><td>—</td></tr>"
    )

rows_picks: list[str] = []
for dt, row in weights_df.iterrows():
    picks = row[row > 0].sort_values(ascending=False)
    picks_txt = (
        "; ".join(f"{s} {w * 100:.0f}%" for s, w in picks.items())
        if not picks.empty else "—"
    )
    cash = max(0.0, 1.0 - float(picks.sum()))
    rows_picks.append(
        f"<tr><td>{dt}</td><td>{picks_txt}</td>"
        f"<td>{cash * 100:.0f}%</td></tr>"
    )

html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Top {TOP_X} Portfolio — {STRATEGY_NAME}</title>
<style>
  body  {{ font-family: Arial, sans-serif; margin: 2rem; color: #111; }}
  h1    {{ font-size: 1.4rem; border-bottom: 2px solid #333;
           padding-bottom: .4rem; }}
  h2    {{ font-size: 1.1rem; margin-top: 1.5rem; }}
  .meta {{ background: #f0f4ff; padding: .6rem 1rem; border-radius: 6px;
           display: inline-block; margin-bottom: 1.5rem; font-size: .9rem; }}
  .kpi  {{ display: flex; gap: 1.5rem; margin-bottom: 1.5rem; }}
  .kpi-box {{ background: #f8fafc; border: 1px solid #ddd;
              border-radius: 8px; padding: .8rem 1.2rem; min-width: 130px; }}
  .kpi-label {{ font-size: .75rem; color: #555; }}
  .kpi-value {{ font-size: 1.3rem; font-weight: 700; }}
  .pos {{ color: #1a6e1a; }} .neg {{ color: #8b1a1a; }}
  table {{ border-collapse: collapse; width: 100%;
           font-size: .85rem; margin-bottom: 1.5rem; }}
  th  {{ background: #222; color: #fff; padding: .5rem .8rem;
         text-align: left; }}
  td  {{ padding: .4rem .8rem; border-bottom: 1px solid #ddd; }}
  tr:hover td {{ background: #f5f7ff; }}
  .box {{ border: 1px solid #ddd; border-radius: 8px;
          padding: 1rem; margin-bottom: 1.5rem; }}
</style>
</head>
<body>
<h1>Top {TOP_X} Portfolio — stratégie : <code>{STRATEGY_NAME}</code></h1>

<div class="meta">
  Rebalancement : {REBALANCE_FREQ} &nbsp;|&nbsp;
  Lookback : {LOOKBACK_WEEKS} semaines &nbsp;|&nbsp;
  Capital initial : {CAPITAL_INITIAL:,.0f} $ &nbsp;|&nbsp;
  Frais : {FEES * 100:.3f}% / trade
</div>

<div class="kpi">
  <div class="kpi-box">
    <div class="kpi-label">Capital final</div>
    <div class="kpi-value">{latest_equity:,.0f} $</div>
  </div>
  <div class="kpi-box">
    <div class="kpi-label">Performance totale</div>
    <div class="kpi-value {'pos' if total_ret >= 0 else 'neg'}">{total_ret:+.2f}%</div>
  </div>
  <div class="kpi-box">
    <div class="kpi-label">Max Drawdown</div>
    <div class="kpi-value neg">{max_dd:.2f}%</div>
  </div>
  <div class="kpi-box">
    <div class="kpi-label">Sharpe annuel</div>
    <div class="kpi-value">{sharpe_port:.3f}</div>
  </div>
</div>

<div class="box">
  <h2>Courbe d'equity</h2>
  {equity_svg}
</div>

<h2>Allocation actuelle ({latest_dt})</h2>
<table>
  <thead>
    <tr><th>Symbole</th><th>Poids</th><th>Score Z</th></tr>
  </thead>
  <tbody>{rows_latest}</tbody>
</table>

<h2>Historique des allocations</h2>
<table>
  <thead>
    <tr>
      <th>Date</th>
      <th>Top {TOP_X} (poids égaux)</th>
      <th>Cash</th>
    </tr>
  </thead>
  <tbody>
    {"".join(rows_picks)}
  </tbody>
</table>

</body>
</html>"""

with open(HTML_REPORT_OUT, "w", encoding="utf-8") as _f:
    _f.write(html)

elapsed = time.time() - t_start
logger.info("Terminé en %.1f min", elapsed / 60)
logger.info("Scores  : %s", CSV_SCORE_OUT)
logger.info("Weights : %s", CSV_WEIGHTS_OUT)
logger.info("Equity  : %s", CSV_EQUITY_OUT)
logger.info("Report  : %s", HTML_REPORT_OUT)
