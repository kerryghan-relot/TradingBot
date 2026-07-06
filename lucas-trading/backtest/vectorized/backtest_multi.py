"""
Multi-strategy / multi-asset backtest with vectorbt.
=====================================================

Memory-optimised: no Plotly charts by default, incremental CSV
writes, explicit garbage collection after each portfolio.

Usage::

    python -m backtest.vectorized.backtest_multi                  # vote strategies, table only
    python -m backtest.vectorized.backtest_multi --html           # vote strategies + Plotly charts
    python -m backtest.vectorized.backtest_multi --ml             # RandomForest strategy
    python -m backtest.vectorized.backtest_multi --ml --html      # RF + Plotly charts
    python -m backtest.vectorized.backtest_multi --walk-forward   # out-of-sample last 30 %
    python -m backtest.vectorized.backtest_multi --walk-forward --test-ratio 0.25

Outputs:
    results/resultats_backtest.csv
    results/resultats_backtest.html
    results/{SYMBOL}_backtest.html  (only with --html)
"""

import argparse
import gc
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt

from core.constants import CAPITAL_INITIAL, DATA_DIR, FEES, OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── CLI ─────────────────────────────────────────────────────────
_parser = argparse.ArgumentParser(description="Multi-strategy backtest")
_parser.add_argument(
    "--ml",
    action="store_true",
    help="Use RandomForest strategy instead of vote strategies",
)
_parser.add_argument(
    "--html",
    action="store_true",
    help="Generate per-symbol Plotly charts (uses more RAM)",
)
_parser.add_argument(
    "--walk-forward",
    action="store_true",
    help=(
        "Compute signals on full series (warmup), "
        "evaluate metrics on last --test-ratio of data only"
    ),
)
_parser.add_argument(
    "--test-ratio",
    type=float,
    default=0.3,
    metavar="RATIO",
    help="Fraction of data used as out-of-sample test set (default: 0.3)",
)
args = _parser.parse_args()

if args.ml:
    from backtest.vectorized.strategies_ml import STRATEGIES
else:
    from backtest.vectorized.strategies_vbt import STRATEGIES

# Output filename encodes the run mode so multiple runs coexist
_suffix = ("_ml" if args.ml else "") + ("_wf" if args.walk_forward else "")
CSV_OUT = OUTPUT_DIR / f"resultats_backtest{_suffix}.csv"
HTML_OUT = OUTPUT_DIR / f"resultats_backtest{_suffix}.html"

# ── Load files ───────────────────────────────────────────────────
csv_files = sorted(DATA_DIR.glob("*_5min_3ans.csv"))
if not csv_files:
    raise SystemExit(f"No CSV files found in {DATA_DIR}")

nb_assets = len(csv_files)
nb_strats = len(STRATEGIES)
nb_total = nb_assets * nb_strats

logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info(
    "%d assets × %d strategies = %d backtests  [ml=%s | html=%s | wf=%s]",
    nb_assets, nb_strats, nb_total,
    args.ml, args.html, args.walk_forward,
)
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# ── CSV header ───────────────────────────────────────────────────
COLUMNS = [
    "Symbol", "Strategy", "Final Capital", "Performance %",
    "Buy&Hold %", "Alpha vs B&H", "Sharpe", "Max Drawdown %",
    "Trades", "Win Rate %",
]
with open(CSV_OUT, "w", encoding="utf-8") as _f:
    _f.write(",".join(COLUMNS) + "\n")

# ── Main loop ────────────────────────────────────────────────────
t_global = time.time()
n_done = 0
n_ok = 0
n_err = 0

for csv_file in csv_files:
    symbol = csv_file.stem.replace("_5min_3ans", "").replace("-", "/")

    df = pd.read_csv(csv_file, parse_dates=["datetime"])
    df = df.set_index("datetime").sort_index()
    for _col in ["open", "high", "low", "close", "volume"]:
        if _col in df.columns:
            df[_col] = df[_col].astype(float)
    close_full: pd.Series = df["close"]
    df_full: pd.DataFrame = df

    bh_full = (close_full.iloc[-1] / close_full.iloc[0] - 1) * 100
    logger.info("\n▶ %s  (B&H full: %+.1f%%)", symbol, bh_full)
    logger.info(
        "  %-35s %7s  %7s  %7s  %6s",
        "Strategy", "Perf", "Alpha", "Sharpe", "Trades",
    )
    logger.info("  %s %s  %s  %s  %s", "-"*35, "-"*7, "-"*7, "-"*7, "-"*6)

    t_asset = time.time()
    figures: dict[str, object] = {}
    html_rows_asset: list[dict] = []

    for strat_name, fn_strat in STRATEGIES.items():
        pf = None
        try:
            if args.walk_forward:
                test_idx = int(len(close_full) * (1 - args.test_ratio))
                # Compute signals on the full series so indicators warm up
                entries_full, exits_full = fn_strat(df_full)
                close_eval = close_full.iloc[test_idx:]
                entries_eval = entries_full.iloc[test_idx:]
                exits_eval = exits_full.iloc[test_idx:]
                bh_eval = (close_eval.iloc[-1] / close_eval.iloc[0] - 1) * 100
            else:
                entries_eval, exits_eval = fn_strat(df_full)
                close_eval = close_full
                bh_eval = bh_full

            pf = vbt.Portfolio.from_signals(
                close_eval,
                entries=entries_eval,
                exits=exits_eval,
                init_cash=CAPITAL_INITIAL,
                fees=FEES,
                freq="5min",
            )

            stats = pf.stats()
            perf = round(float(stats["Total Return [%]"]), 2)
            sharpe = round(float(stats["Sharpe Ratio"]), 3)
            dd = round(float(stats["Max Drawdown [%]"]), 2)
            trades = int(stats["Total Trades"])
            wr = round(float(stats["Win Rate [%]"]), 1)
            alpha = round(perf - bh_eval, 2)

            row_csv = (
                f'"{symbol}","{strat_name}",'
                f"{round(CAPITAL_INITIAL * (1 + perf / 100), 2)},"
                f"{perf},{round(bh_eval, 2)},{alpha},"
                f"{sharpe},{dd},{trades},{wr}\n"
            )
            with open(CSV_OUT, "a", encoding="utf-8") as _f:
                _f.write(row_csv)

            sign = "✓" if alpha >= 0 else "✗"
            logger.info(
                "  %-35s %+7.1f%%  %+7.1f%%  %7.3f  %6d  %s",
                strat_name, perf, alpha, sharpe, trades, sign,
            )

            if args.html:
                figures[strat_name] = pf.plot()
                html_rows_asset.append(
                    {"strat": strat_name, "perf": perf, "alpha": alpha}
                )

            n_ok += 1

        except Exception as exc:
            logger.warning("  %-35s ✗ %s", strat_name, exc)
            n_err += 1

        finally:
            try:
                del pf
            except Exception:
                pass
            gc.collect()

        n_done += 1
        if n_done % 50 == 0:
            elapsed = time.time() - t_global
            remaining = (elapsed / n_done) * (nb_total - n_done)
            logger.info(
                "  ⏱  %d/%d — ~%.1f min remaining",
                n_done, nb_total, remaining / 60,
            )

    logger.info("  → %s done in %.1fs", symbol, time.time() - t_asset)

    # ── Per-symbol Plotly HTML (only with --html) ─────────────────
    if args.html and figures:
        safe = symbol.replace("/", "-")
        html_path = OUTPUT_DIR / f"{safe}_backtest.html"
        bh_capital = CAPITAL_INITIAL * (1 + bh_full / 100)
        parts = [
            "<html><head><meta charset='utf-8'>",
            f"<title>Backtest {symbol}</title>",
            "<style>body{font-family:sans-serif;margin:2rem} "
            "h2{border-bottom:2px solid #333} "
            ".bh{background:#f0f4ff;padding:.5rem 1rem;border-radius:6px;"
            "display:inline-block;margin-bottom:1rem}</style>",
            "</head><body>",
            f"<h2>{symbol} — multi-strategy backtest</h2>",
            f"<div class='bh'>Buy &amp; Hold: <strong>{bh_full:+.1f}%</strong>"
            f" → {bh_capital:,.0f} $</div>",
        ]
        for info in html_rows_asset:
            name = info["strat"]
            alpha = info["alpha"]
            color = "#2a7a2a" if alpha >= 0 else "#a02020"
            parts.append(
                f"<h3>{name} — {info['perf']:+.1f}% "
                f"<span style='color:{color};font-size:.85em'>"
                f"({alpha:+.1f}% vs B&H)</span></h3>"
            )
            fig = figures[name]
            parts.append(fig.to_html(full_html=False, include_plotlyjs="cdn"))
        parts.append("</body></html>")
        with open(html_path, "w", encoding="utf-8") as _f:
            _f.write("\n".join(parts))
        logger.info("  → chart: %s", html_path.name)

    del close_full, df, figures, html_rows_asset
    gc.collect()

# ── Sort CSV ─────────────────────────────────────────────────────
df_res = pd.read_csv(CSV_OUT)
df_res = df_res.sort_values("Alpha vs B&H", ascending=False)
df_res.to_csv(CSV_OUT, index=False)

# ── Lightweight HTML report ──────────────────────────────────────
top50 = df_res.head(50)
rows_html = ""
for _, r in top50.iterrows():
    alpha = r["Alpha vs B&H"]
    color = "#1a6e1a" if alpha >= 0 else "#8b1a1a"
    rows_html += (
        f"<tr>"
        f"<td>{r['Symbol']}</td><td>{r['Strategy']}</td>"
        f"<td>{r['Performance %']:+.2f}%</td>"
        f"<td>{r['Buy&Hold %']:+.2f}%</td>"
        f"<td style='color:{color};font-weight:600'>{alpha:+.2f}%</td>"
        f"<td>{r['Sharpe']:.3f}</td>"
        f"<td>{r['Max Drawdown %']:.2f}%</td>"
        f"<td>{int(r['Trades'])}</td>"
        f"<td>{r['Win Rate %']:.1f}%</td>"
        f"</tr>\n"
    )

walk_note = (
    f"Walk-forward: last {int(args.test_ratio * 100)}% out-of-sample"
    if args.walk_forward
    else "Full in-sample"
)

html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Backtest – Top 50</title>
<style>
  body  {{ font-family: sans-serif; margin: 2rem; color: #111; }}
  h1    {{ font-size: 1.4rem; border-bottom: 2px solid #333;
           padding-bottom: .4rem; }}
  .meta {{ background: #f0f4ff; padding: .6rem 1rem; border-radius: 6px;
           display: inline-block; margin-bottom: 1.5rem; font-size: .9rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .85rem; }}
  th    {{ background: #222; color: #fff; padding: .5rem .8rem;
           text-align: left; }}
  td    {{ padding: .4rem .8rem; border-bottom: 1px solid #ddd; }}
  tr:hover td {{ background: #f5f7ff; }}
</style>
</head>
<body>
<h1>Backtest – Top 50 strategies by Alpha vs Buy &amp; Hold</h1>
<div class="meta">
  {nb_assets} assets &nbsp;×&nbsp; {nb_strats} strategies
  &nbsp;|&nbsp; {n_ok} succeeded, {n_err} errors
  &nbsp;|&nbsp; Capital: {CAPITAL_INITIAL:,.0f} $
  &nbsp;|&nbsp; Fees: {FEES * 100:.3f}% / trade
  &nbsp;|&nbsp; {walk_note}
</div>
<table>
<thead>
  <tr>
    <th>Symbol</th><th>Strategy</th>
    <th>Perf %</th><th>B&amp;H %</th><th>Alpha</th>
    <th>Sharpe</th><th>Max DD %</th><th>Trades</th><th>Win Rate</th>
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

# ── Final summary ────────────────────────────────────────────────
elapsed_total = time.time() - t_global
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info("✓ %d backtests succeeded / %d errors", n_ok, n_err)
logger.info("✓ Total time: %.1f min", elapsed_total / 60)
logger.info("✓ CSV:  %s", CSV_OUT)
logger.info("✓ HTML: %s", HTML_OUT)
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

logger.info("\n── Top 10 by Alpha vs B&H ──")
logger.info(
    "\n%s",
    df_res.nlargest(10, "Alpha vs B&H")[
        ["Symbol", "Strategy", "Performance %",
         "Buy&Hold %", "Alpha vs B&H", "Sharpe"]
    ].to_string(index=False),
)
