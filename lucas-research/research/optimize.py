"""
Hyperparameter grid search – BB, EMA_Cross, MACD_Zero, Zscore.
==============================================================

Tests all parameter combinations for the 4 active signals across
all available CSV symbols.

Outputs:
    resultats/hyperparams_resultats.csv  (sorted by mean Alpha vs B&H)
    resultats/hyperparams_top.html       (top-50 readable table)

Strategy:
    Exhaustive grid search per signal individually.
    Incremental CSV writes to avoid RAM spikes.
    gc.collect() after each portfolio.
"""

import gc
import itertools
import logging
import time

import numpy as np
import pandas as pd
import vectorbt as vbt

from config import ANNUALIZATION, CAPITAL_INITIAL, DATA_DIR, FEES, OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CSV_OUT = OUTPUT_DIR / "hyperparams_resultats.csv"
HTML_OUT = OUTPUT_DIR / "hyperparams_top.html"

# ══════════════════════════════════════════════════════════════
# PARAMETER GRIDS
# ══════════════════════════════════════════════════════════════

BB_PERIODS: list[int] = [100, 200, 300, 500, 750]
BB_STDS: list[float] = [1.5, 2.0, 2.5, 3.0]

EMA_FASTS: list[int] = [20, 50, 100]
EMA_SLOWS: list[int] = [100, 200, 500]

MACD_FASTS: list[int] = [12, 20, 26]
MACD_SLOWS: list[int] = [26, 52, 78]
MACD_SIGS: list[int] = [9, 14, 18]

ZSCORE_WINS: list[int] = [195, 390, 585]      # ~0.5 / 1 / 1.5 weeks
ZSCORE_THS: list[float] = [1.5, 2.0, 2.5, 3.0]


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _disc(s: pd.Series) -> pd.Series:
    """Return the first True of each run of consecutive True values."""
    s = s.fillna(False)
    return s & ~s.shift(1).fillna(False)


def _run_portfolio(
    close: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
) -> dict[str, float]:
    """
    Run a vectorbt portfolio and return key performance metrics.

    Args:
        close (pd.Series): Close price series.
        entries (pd.Series): Boolean entry signals.
        exits (pd.Series): Boolean exit signals.

    Returns:
        dict[str, float]: Keys: perf, sharpe, dd, trades, wr.

    Raises:
        RuntimeError: Propagated from vectorbt on bad inputs.
    """
    pf = vbt.Portfolio.from_signals(
        close,
        entries=entries,
        exits=exits,
        init_cash=CAPITAL_INITIAL,
        fees=FEES,
        freq="5min",
    )
    stats = pf.stats()
    result = {
        "perf":   round(float(stats["Total Return [%]"]), 2),
        "sharpe": round(float(stats["Sharpe Ratio"]), 3),
        "dd":     round(float(stats["Max Drawdown [%]"]), 2),
        "trades": int(stats["Total Trades"]),
        "wr":     round(float(stats["Win Rate [%]"]), 1),
    }
    del pf
    gc.collect()
    return result


# ══════════════════════════════════════════════════════════════
# PARAMETERISED SIGNAL GENERATORS
# ══════════════════════════════════════════════════════════════

def sig_bb(
    close: pd.Series,
    period: int,
    std: float,
) -> tuple[pd.Series, pd.Series]:
    """Bollinger Band mean-reversion signal."""
    bb = vbt.BBANDS.run(close, window=period, alpha=std)
    return _disc(close < bb.lower), _disc(close > bb.upper)


def sig_ema_cross(
    close: pd.Series,
    fast: int,
    slow: int,
) -> tuple[pd.Series, pd.Series] | tuple[None, None]:
    """
    EMA crossover signal.

    Returns:
        tuple[None, None]: When fast >= slow (invalid parameter pair).
    """
    if fast >= slow:
        return None, None
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    return _disc(ef > es), _disc(ef < es)


def sig_macd_zero(
    close: pd.Series,
    fast: int,
    slow: int,
    sig: int,
) -> tuple[pd.Series, pd.Series] | tuple[None, None]:
    """
    MACD zero-cross signal.

    Returns:
        tuple[None, None]: When fast >= slow (invalid parameter pair).
    """
    if fast >= slow:
        return None, None
    macd = vbt.MACD.run(
        close, fast_window=fast, slow_window=slow, signal_window=sig
    ).macd
    return _disc(macd > 0), _disc(macd < 0)


def sig_zscore(
    close: pd.Series,
    window: int,
    threshold: float,
) -> tuple[pd.Series, pd.Series]:
    """Z-score mean-reversion signal."""
    mu = close.rolling(window).mean()
    sigma = close.rolling(window).std()
    z = (close - mu) / sigma.replace(0, np.nan)
    return _disc(z < -threshold), _disc(z > threshold)


# ══════════════════════════════════════════════════════════════
# LOAD DATA
# ══════════════════════════════════════════════════════════════

csv_files = sorted(DATA_DIR.glob("*_5min_3ans.csv"))
if not csv_files:
    raise SystemExit(f"No CSV found in {DATA_DIR}")

closes: dict[str, pd.Series] = {}
bh_perfs: dict[str, float] = {}
for _f in csv_files:
    _sym = _f.stem.replace("_5min_3ans", "").replace("-", "/")
    _df = pd.read_csv(_f, parse_dates=["datetime"])
    _df = _df.set_index("datetime").sort_index()
    _c = _df["close"].astype(float)
    closes[_sym] = _c
    bh_perfs[_sym] = (_c.iloc[-1] / _c.iloc[0] - 1) * 100

symbols = list(closes.keys())

# ══════════════════════════════════════════════════════════════
# BUILD GRID
# ══════════════════════════════════════════════════════════════

grid_bb = list(itertools.product(BB_PERIODS, BB_STDS))
grid_ema = [
    (f, s) for f, s in itertools.product(EMA_FASTS, EMA_SLOWS) if f < s
]
grid_macd = [
    (f, s, sg)
    for f, s, sg in itertools.product(MACD_FASTS, MACD_SLOWS, MACD_SIGS)
    if f < s
]
grid_z = list(itertools.product(ZSCORE_WINS, ZSCORE_THS))

configs: list[tuple[str, tuple, dict]] = (
    [("BB",        p, {"period": p[0], "std": p[1]})       for p in grid_bb]
    + [("EMA_Cross", p, {"fast": p[0], "slow": p[1]})      for p in grid_ema]
    + [("MACD_Zero", p, {"fast": p[0], "slow": p[1], "sig": p[2]})
       for p in grid_macd]
    + [("Zscore",    p, {"window": p[0], "threshold": p[1]}) for p in grid_z]
)

nb_total = len(configs) * len(symbols)
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info(
    "%d configs × %d symbols = %d backtests",
    len(configs), len(symbols), nb_total,
)
logger.info(
    "BB:%d  EMA:%d  MACD:%d  Zscore:%d",
    len(grid_bb), len(grid_ema), len(grid_macd), len(grid_z),
)
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# ══════════════════════════════════════════════════════════════
# OPTIMISATION LOOP
# ══════════════════════════════════════════════════════════════

COLUMNS = [
    "Signal", "Params", "Symbol",
    "Performance %", "Buy&Hold %", "Alpha vs B&H",
    "Sharpe", "Max Drawdown %", "Trades", "Win Rate %",
]
with open(CSV_OUT, "w", encoding="utf-8") as _f:
    _f.write(",".join(COLUMNS) + "\n")

t0 = time.time()
n_ok = 0
n_err = 0
n_done = 0

for signal_name, params_tuple, params_dict in configs:
    params_str = str(params_dict).replace(",", ";")

    for sym in symbols:
        close = closes[sym]
        bh = bh_perfs[sym]
        entries, exits = None, None

        try:
            if signal_name == "BB":
                entries, exits = sig_bb(close, **params_dict)
            elif signal_name == "EMA_Cross":
                entries, exits = sig_ema_cross(close, **params_dict)
            elif signal_name == "MACD_Zero":
                entries, exits = sig_macd_zero(close, **params_dict)
            elif signal_name == "Zscore":
                entries, exits = sig_zscore(close, **params_dict)

            if entries is None:
                n_err += 1
                continue

            res = _run_portfolio(close, entries, exits)
            alpha = round(res["perf"] - bh, 2)

            ligne = (
                f'"{signal_name}","{params_str}","{sym}",'
                f'{res["perf"]},{round(bh, 2)},{alpha},'
                f'{res["sharpe"]},{res["dd"]},{res["trades"]},{res["wr"]}\n'
            )
            with open(CSV_OUT, "a", encoding="utf-8") as _f:
                _f.write(ligne)
            n_ok += 1

        except Exception:
            n_err += 1

        finally:
            gc.collect()

        n_done += 1
        if n_done % 100 == 0:
            elapsed = time.time() - t0
            remaining = (elapsed / n_done) * (nb_total - n_done)
            logger.info(
                "  %d/%d — %.1f min remaining | ok:%d err:%d",
                n_done, nb_total, remaining / 60, n_ok, n_err,
            )

# ══════════════════════════════════════════════════════════════
# ANALYSIS: best params per signal
# ══════════════════════════════════════════════════════════════

df = pd.read_csv(CSV_OUT)
df = df.sort_values("Alpha vs B&H", ascending=False)
df.to_csv(CSV_OUT, index=False)

logger.info("\n━━ Best parameters per signal (mean alpha across all symbols) ━━")
for sig in ["BB", "EMA_Cross", "MACD_Zero", "Zscore"]:
    sub = df[df["Signal"] == sig].groupby("Params")["Alpha vs B&H"].mean()
    if sub.empty:
        continue
    best_p = sub.idxmax()
    best_v = sub.max()
    logger.info("  %-12s → %s  (mean alpha: %+.2f%%)", sig, best_p, best_v)

# ══════════════════════════════════════════════════════════════
# HTML REPORT – top 50
# ══════════════════════════════════════════════════════════════

top = df.head(50)
rows = ""
for _, r in top.iterrows():
    c = "#1a6e1a" if r["Alpha vs B&H"] >= 0 else "#8b1a1a"
    rows += (
        f"<tr><td>{r['Signal']}</td>"
        f"<td><code>{r['Params']}</code></td>"
        f"<td>{r['Symbol']}</td>"
        f"<td>{r['Performance %']:+.2f}%</td>"
        f"<td>{r['Buy&Hold %']:+.2f}%</td>"
        f"<td style='color:{c};font-weight:600'>"
        f"{r['Alpha vs B&H']:+.2f}%</td>"
        f"<td>{r['Sharpe']:.3f}</td>"
        f"<td>{r['Max Drawdown %']:.2f}%</td>"
        f"<td>{int(r['Trades'])}</td>"
        f"<td>{r['Win Rate %']:.1f}%</td></tr>\n"
    )

html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Hyperparameters – Top 50</title>
<style>
  body{{font-family:sans-serif;margin:2rem;color:#111}}
  h1{{font-size:1.4rem;border-bottom:2px solid #333;padding-bottom:.4rem}}
  table{{border-collapse:collapse;width:100%;font-size:.82rem}}
  th{{background:#222;color:#fff;padding:.5rem .7rem;text-align:left}}
  td{{padding:.35rem .7rem;border-bottom:1px solid #ddd}}
  tr:hover td{{background:#f5f7ff}}
  code{{font-size:.78rem;background:#f0f0f0;
        padding:.1rem .3rem;border-radius:3px}}
</style></head><body>
<h1>Hyperparameter optimisation – Top 50 by Alpha vs B&H</h1>
<table><thead><tr>
  <th>Signal</th><th>Parameters</th><th>Symbol</th>
  <th>Perf%</th><th>B&amp;H%</th><th>Alpha</th>
  <th>Sharpe</th><th>Max DD%</th><th>Trades</th><th>Win Rate</th>
</tr></thead><tbody>
{rows}
</tbody></table></body></html>"""

with open(HTML_OUT, "w", encoding="utf-8") as _f:
    _f.write(html)

elapsed = time.time() - t0
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info("✓ %d backtests succeeded / %d errors", n_ok, n_err)
logger.info("✓ Time: %.1f min", elapsed / 60)
logger.info("✓ CSV:  %s", CSV_OUT)
logger.info("✓ HTML: %s", HTML_OUT)
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
