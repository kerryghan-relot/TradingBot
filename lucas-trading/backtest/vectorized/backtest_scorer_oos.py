"""
Out-of-sample validation of the scorer's top-X symbol selection.
=================================================================

Question answered: does re-selecting the top-X symbols every week by
trailing Sharpe (the method used by lucas-live-trading/scorer.py) beat
simply trading the same vote strategy on ALL symbols equal-weighted?

Method
------
1. For every symbol CSV in ``data/``, simulate the live bot's
   vote strategy (BB + OU + VWAP + VolSpike + KalmanZ, threshold 2,
   2 % stop-loss) bar by bar with transaction costs, producing a
   per-bar strategy return series.  The signal math is a vectorised
   replica of ``lucas-live-trading/signals.py`` (validated for parity
   against the live engine).
2. Every Monday, rank symbols by annualised Sharpe over the previous
   ``LOOKBACK_DAYS`` days (exactly what scorer.py does) and hold the
   top-X equal-weighted for the following week.
3. Compare against (a) an equal-weight portfolio of all symbols and
   (b) the distribution of randomly selected top-X portfolios.

Caveats
-------
- Research data is 5-minute bars; the live bot runs on 1-minute bars.
  This validates the *selection mechanism*, not exact live P&L.
- Crypto CSVs have no volume, so VolSpike and VWAP never vote on
  BTC/ETH here (they still count in ``n_signals``).

Usage::

    python -m backtest.vectorized.backtest_scorer_oos

Outputs::

    results/scorer_oos_equity.csv
    results/scorer_oos_selection.csv
    results/scorer_oos_report.html
"""

import logging
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from core.constants import DATA_DIR, FEES, OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Strategy configuration (mirrors lucas-live-trading defaults) ─────
CFG: dict = {
    "active_signals": ["BB", "OU", "VWAP", "VolSpike", "KalmanZ"],
    "vote_threshold": 2,
    "stop_loss_pct":  0.02,
    "bb_period":      200,
    "bb_std":         2.5,
    "ou_window":      200,
    "ou_threshold":   2.0,
    "vol_window":     20,
    "vol_factor":     2.0,
    "kalman_q":       1e-4,
    "kalman_r":       0.1,
    "kalman_roll_win": 100,
    "kalman_threshold": 2.0,
    "vwap_threshold": 0.005,
}

# Cost per side: research fee constant + slippage estimate
# (matches scorer_fee_pct + scorer_slippage_pct defaults).
COST_PER_SIDE: float = FEES + 0.0005

# ── Selection configuration (mirrors scorer.py defaults) ─────────────
TOP_X: int = 5
LOOKBACK_DAYS: int = 30
N_RANDOM_PORTFOLIOS: int = 200
RANDOM_SEED: int = 7

# 5-minute bars per year, by asset class (for trailing Sharpe).
BARS_PER_YEAR_CRYPTO_5MIN: int = 105_120   # 288 × 365
BARS_PER_YEAR_STOCK_5MIN:  int = 19_656    # 78 × 252

CRYPTO_TICKERS: set[str] = {"BTC-USD", "ETH-USD"}


# ══════════════════════════════════════════════════════════════════════
#  Vectorised signal replicas (parity-checked vs live engine)
# ══════════════════════════════════════════════════════════════════════

def vec_sig_bb(
    close: pd.Series, period: int, n_std: float
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised Bollinger Band mean-reversion (mirrors sig_bb).

    Args:
        close (pd.Series): Close prices, oldest first.
        period (int): Rolling window.
        n_std (float): Band width in standard deviations.

    Returns:
        tuple[np.ndarray, np.ndarray]: (buy, sell) boolean arrays.
    """
    mu    = close.rolling(period).mean()
    sigma = close.rolling(period).std(ddof=0)
    lower = mu - n_std * sigma
    upper = mu + n_std * sigma
    prev  = close.shift(1)
    # sig_bb requires len >= period + 1  →  0-based index >= period
    valid = np.arange(len(close)) >= period
    buy   = (prev >= lower) & (close < lower) & valid
    sell  = (prev <= upper) & (close > upper) & valid
    return buy.to_numpy(dtype=bool), sell.to_numpy(dtype=bool)


def vec_sig_ou(
    close: pd.Series, window: int, threshold: float
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised Ornstein-Uhlenbeck z-score (mirrors sig_ou).

    Reproduces the rolling-OLS estimate on log prices using rolling
    sums.  The residual mean is zero by construction of μ, so the
    residual std reduces to sqrt(E[res²]).

    Args:
        close (pd.Series): Close prices, oldest first.
        window (int): OLS window in bars.
        threshold (float): Z-score trigger.

    Returns:
        tuple[np.ndarray, np.ndarray]: (buy, sell) boolean arrays.
    """
    logp = pd.Series(
        np.log(np.maximum(close.to_numpy(dtype=float), 1e-10)),
        index=close.index,
    )
    lag = logp.shift(1)

    mean_x   = logp.rolling(window).mean()
    mean_lag = lag.rolling(window).mean()
    e_x2     = (logp ** 2).rolling(window).mean()
    e_lag2   = (lag ** 2).rolling(window).mean()
    e_xlag   = (logp * lag).rolling(window).mean()

    cov     = e_xlag - mean_x * mean_lag
    var_lag = e_lag2 - mean_lag ** 2

    ok_var = var_lag > 0
    b  = (cov / var_lag.where(ok_var)).clip(1e-10, 1.0 - 1e-10)
    mu = (mean_x - b * mean_lag) / np.maximum(1.0 - b, 1e-10)
    c  = (1.0 - b) * mu

    e_res2 = (
        e_x2 + b ** 2 * e_lag2 + c ** 2
        - 2.0 * b * e_xlag - 2.0 * c * mean_x + 2.0 * b * c * mean_lag
    )
    std_r = np.sqrt(e_res2.clip(lower=0.0))
    ok    = ok_var & (std_r > 0)

    z      = ((logp - mu) / std_r.where(ok)).where(ok)
    z_prev = z.shift(1)

    # sig_ou requires len >= window + 2  →  index >= window + 1;
    # both z(t) and z(t-1) must be computable (matches the None check).
    valid = (
        (np.arange(len(close)) >= window + 1)
        & z.notna() & z_prev.notna()
    )
    buy  = (z_prev >= -threshold) & (z < -threshold) & valid
    sell = (z_prev <= threshold) & (z > threshold) & valid
    return (
        buy.fillna(False).to_numpy(dtype=bool),
        sell.fillna(False).to_numpy(dtype=bool),
    )


def vec_sig_vwap(
    df: pd.DataFrame, threshold: float
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised session-VWAP deviation (mirrors sig_vwap).

    Session = calendar date of the bar timestamp, matching the live
    engine's midnight-UTC reset.  Level-based (no edge detection).

    Args:
        df (pd.DataFrame): OHLCV frame indexed by timestamp.
        threshold (float): Deviation trigger, e.g. 0.005 = 0.5 %.

    Returns:
        tuple[np.ndarray, np.ndarray]: (buy, sell) boolean arrays.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    day     = df.index.normalize()
    cum_pv  = (typical * df["volume"]).groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum()

    ok   = cum_vol > 0
    vwap = (cum_pv / cum_vol.where(ok)).where(ok)
    ok   = ok & (vwap != 0)
    dev  = ((df["close"] - vwap) / vwap).where(ok)

    buy  = (dev < -threshold).fillna(False)
    sell = (dev > threshold).fillna(False)
    return buy.to_numpy(dtype=bool), sell.to_numpy(dtype=bool)


def vec_sig_vol_spike(
    close: pd.Series, volume: pd.Series, window: int, factor: float
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised volume spike with direction (mirrors sig_vol_spike).

    Args:
        close (pd.Series): Close prices, oldest first.
        volume (pd.Series): Bar volumes, oldest first.
        window (int): Rolling-mean window.
        factor (float): Spike multiplier.

    Returns:
        tuple[np.ndarray, np.ndarray]: (buy, sell) boolean arrays.
    """
    avg   = volume.shift(1).rolling(window).mean()
    valid = (np.arange(len(close)) >= window) & (avg > 0)
    spike = (volume > factor * avg) & valid
    rising = close > close.shift(1)
    buy  = (spike & rising).fillna(False)
    sell = (spike & ~rising).fillna(False)
    return buy.to_numpy(dtype=bool), sell.to_numpy(dtype=bool)


def vec_sig_kalman_zscore(
    close: pd.Series,
    q: float,
    r: float,
    roll_win: int,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised Kalman z-score (mirrors sig_kalman_zscore).

    The Kalman mean is inherently sequential, so residuals come from
    an O(n) Python loop; the rolling residual std and edge detection
    are vectorised.  The std at bar t covers the previous ``roll_win``
    residuals (excluding bar t), matching the live engine, which
    passes the residual deque *before* appending the current value.

    Args:
        close (pd.Series): Close prices, oldest first.
        q (float): Process noise variance.
        r (float): Measurement noise variance.
        roll_win (int): Rolling window for residual std.
        threshold (float): Z-score trigger.

    Returns:
        tuple[np.ndarray, np.ndarray]: (buy, sell) boolean arrays.
    """
    values = close.to_numpy(dtype=float)
    n = len(values)
    residuals = np.empty(n)

    kf_mu = values[0] if n else 0.0
    kf_p  = 1.0
    for i in range(n):
        p_pred = kf_p + q
        k_gain = p_pred / (p_pred + r)
        kf_mu  = kf_mu + k_gain * (values[i] - kf_mu)
        kf_p   = (1.0 - k_gain) * p_pred
        residuals[i] = values[i] - kf_mu

    res = pd.Series(residuals, index=close.index)
    min_len = max(roll_win // 4, 5)
    # std over the last <= roll_win residuals BEFORE the current bar;
    # the live deque caps at 1000 but roll_win <= 1000 keeps windows
    # identical.
    std_prior = (
        res.shift(1).rolling(roll_win, min_periods=min_len).std(ddof=0)
    )
    ok = std_prior > 0

    z      = (res / std_prior.where(ok)).where(ok)
    z_prev = (res.shift(1).fillna(0.0) / std_prior.where(ok)).where(ok)

    buy  = ((z_prev >= -threshold) & (z < -threshold)).fillna(False)
    sell = ((z_prev <= threshold) & (z > threshold)).fillna(False)
    return buy.to_numpy(dtype=bool), sell.to_numpy(dtype=bool)


# ══════════════════════════════════════════════════════════════════════
#  Per-symbol strategy simulation
# ══════════════════════════════════════════════════════════════════════

def vote_arrays(
    df: pd.DataFrame, cfg: dict
) -> tuple[np.ndarray, np.ndarray]:
    """Compute per-bar (buy_triggered, sell_triggered) vote arrays.

    Mirrors ``signals.vote()``: sell wins a simultaneous tie, and the
    warmup gate blocks all votes until every window signal has enough
    history.

    Args:
        df (pd.DataFrame): OHLCV frame indexed by timestamp.
        cfg (dict): Strategy configuration (see ``CFG``).

    Returns:
        tuple[np.ndarray, np.ndarray]: Boolean (buy, sell) arrays.
    """
    close = df["close"]
    pairs: list[tuple[np.ndarray, np.ndarray]] = []

    active = set(cfg["active_signals"])
    if active - {"BB", "OU", "VWAP", "VolSpike", "KalmanZ"}:
        raise ValueError(
            "Only the default live signal set is supported here: "
            f"{sorted(active)}"
        )

    if "BB" in active:
        pairs.append(vec_sig_bb(close, cfg["bb_period"], cfg["bb_std"]))
    if "OU" in active:
        pairs.append(
            vec_sig_ou(close, cfg["ou_window"], cfg["ou_threshold"])
        )
    if "VWAP" in active:
        pairs.append(vec_sig_vwap(df, cfg["vwap_threshold"]))
    if "VolSpike" in active:
        pairs.append(vec_sig_vol_spike(
            close, df["volume"], cfg["vol_window"], cfg["vol_factor"]
        ))
    if "KalmanZ" in active:
        pairs.append(vec_sig_kalman_zscore(
            close,
            cfg["kalman_q"], cfg["kalman_r"],
            cfg["kalman_roll_win"], cfg["kalman_threshold"],
        ))

    buy_votes  = np.sum([p[0] for p in pairs], axis=0)
    sell_votes = np.sum([p[1] for p in pairs], axis=0)

    threshold = int(cfg["vote_threshold"])
    sell_trig = sell_votes >= threshold
    buy_trig  = (buy_votes >= threshold) & ~sell_trig

    # Warmup gate: window signals need bb_period/ou_window + margin.
    needed = 2
    if "BB" in active:
        needed = max(needed, cfg["bb_period"] + 1)
    if "OU" in active:
        needed = max(needed, cfg["ou_window"] + 2)
    if "VolSpike" in active:
        needed = max(needed, cfg["vol_window"] + 1)
    warm = np.arange(len(close)) >= needed - 1
    return buy_trig & warm, sell_trig & warm


def simulate_returns(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """Simulate the vote strategy and return the per-bar return series.

    Position logic mirrors ``scorer.simulate()``: entries/exits at the
    bar close, stop-loss before vote application (no same-bar
    re-entry), one ``COST_PER_SIDE`` charge per entry and per exit.

    Args:
        df (pd.DataFrame): OHLCV frame indexed by timestamp.
        cfg (dict): Strategy configuration.

    Returns:
        pd.Series: Per-bar strategy returns (0.0 when flat).
    """
    buy_trig, sell_trig = vote_arrays(df, cfg)
    closes = df["close"].to_numpy(dtype=float)
    stop_pct = float(cfg["stop_loss_pct"])

    n = len(closes)
    returns = np.zeros(n)

    in_pos = False
    entry: float = 0.0
    was_open = False

    for t in range(n):
        close = closes[t]
        if was_open and t > 0:
            returns[t] = close / closes[t - 1] - 1.0

        stopped = False
        if in_pos and (entry - close) / entry >= stop_pct:
            in_pos = False
            stopped = True
            returns[t] -= COST_PER_SIDE

        if not stopped:
            if buy_trig[t] and not in_pos:
                in_pos = True
                entry = close
                returns[t] -= COST_PER_SIDE
            elif sell_trig[t] and in_pos:
                in_pos = False
                returns[t] -= COST_PER_SIDE

        was_open = in_pos

    return pd.Series(returns, index=df.index)


# ══════════════════════════════════════════════════════════════════════
#  Data loading
# ══════════════════════════════════════════════════════════════════════

def load_all_symbols() -> dict[str, pd.DataFrame]:
    """Load every ``*_5min_3ans.csv`` from the data directory.

    Corrupt bars (e.g. ETH-USD has a close of 6.7e-06 on 2023-06-15)
    are dropped: any close deviating more than 50 % from the centred
    7-bar rolling median is considered a data glitch.

    Returns:
        dict[str, pd.DataFrame]: Ticker → OHLCV frame indexed by
            timestamp, sorted, deduplicated, cleaned, volume NaN → 0.
    """
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(DATA_DIR.glob("*_5min_3ans.csv")):
        ticker = path.name.split("_")[0]
        df = pd.read_csv(path, parse_dates=["datetime"])
        df = (
            df.set_index("datetime")
            .sort_index()
            .loc[lambda d: ~d.index.duplicated(keep="first")]
        )
        med = df["close"].rolling(7, center=True, min_periods=1).median()
        glitch = (df["close"] / med - 1.0).abs() > 0.5
        if glitch.any():
            logger.warning(
                "  %-8s %d barre(s) corrompue(s) supprimee(s): %s",
                ticker, int(glitch.sum()),
                list(df.index[glitch].strftime("%Y-%m-%d %H:%M")),
            )
            df = df[~glitch]
        df["volume"] = df["volume"].fillna(0.0)
        frames[ticker] = df
        logger.info("  %-8s %6d barres", ticker, len(df))
    return frames


# ══════════════════════════════════════════════════════════════════════
#  Metrics
# ══════════════════════════════════════════════════════════════════════

def sharpe(returns: np.ndarray, bars_per_year: float) -> float:
    """Annualised Sharpe ratio (0.0 if degenerate) — mirrors scorer.py."""
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


# ══════════════════════════════════════════════════════════════════════
#  Portfolio backtest
# ══════════════════════════════════════════════════════════════════════

def run_backtest() -> None:
    """Run the full out-of-sample selection backtest and write reports."""
    t0 = time.time()
    logger.info("Chargement des donnees...")
    frames = load_all_symbols()
    tickers = list(frames)

    logger.info(
        "Simulation de la strategie sur %d symboles...", len(tickers)
    )
    per_symbol: dict[str, pd.Series] = {}
    for ticker, df in frames.items():
        rets = simulate_returns(df, CFG)
        n_active = int((rets != 0).sum())
        per_symbol[ticker] = rets
        logger.info(
            "  %-8s ret_total=%+7.2f%%  barres_actives=%d",
            ticker, ((1 + rets).prod() - 1) * 100, n_active,
        )

    # Wide matrix on the union index; missing bar = flat (0 return).
    matrix = pd.DataFrame(per_symbol).fillna(0.0)
    index = matrix.index
    logger.info(
        "Matrice: %d barres × %d symboles (%.1f s)",
        len(matrix), len(tickers), time.time() - t0,
    )

    # ── Weekly rebalance dates ────────────────────────────────────────
    weeks = index.to_period("W")
    first_of_week = index[
        np.concatenate(([True], weeks[1:] != weeks[:-1]))
    ]
    # Skip rebalances until a full lookback window exists.
    min_date = index[0] + pd.Timedelta(days=LOOKBACK_DAYS)
    rebalances = [d for d in first_of_week if d >= min_date]
    logger.info("%d rebalancements hebdomadaires", len(rebalances))
    logger.info("Boucle de selection...")

    bpy = {
        t: (
            BARS_PER_YEAR_CRYPTO_5MIN
            if t in CRYPTO_TICKERS else BARS_PER_YEAR_STOCK_5MIN
        )
        for t in tickers
    }

    # ── Selection loop ────────────────────────────────────────────────
    rng = np.random.default_rng(RANDOM_SEED)
    positions = np.arange(len(index))
    topx_ret = pd.Series(0.0, index=index)
    random_rets = np.zeros((len(index), N_RANDOM_PORTFOLIOS))
    selection_rows: list[dict] = []

    mat_np = matrix.to_numpy()
    col_of = {t: i for i, t in enumerate(tickers)}

    for k, reb_date in enumerate(rebalances):
        lb_start = reb_date - pd.Timedelta(days=LOOKBACK_DAYS)
        seg_end = (
            rebalances[k + 1] if k + 1 < len(rebalances)
            else index[-1] + pd.Timedelta(seconds=1)
        )

        # Trailing Sharpe per symbol on ITS OWN bars (like scorer.py)
        scores: dict[str, float] = {}
        for t in tickers:
            r = per_symbol[t]
            window = r[(r.index >= lb_start) & (r.index < reb_date)]
            scores[t] = sharpe(window.to_numpy(), bpy[t])

        ranked = sorted(scores, key=scores.get, reverse=True)
        selected = ranked[:TOP_X]
        selection_rows.append({
            "rebalance": reb_date,
            "selected": " ".join(selected),
            **{f"sharpe_{t}": round(scores[t], 3) for t in selected},
        })

        seg_mask = (index >= reb_date) & (index < seg_end)
        seg_pos = positions[seg_mask]
        sel_cols = [col_of[t] for t in selected]
        topx_ret.iloc[seg_pos] = mat_np[np.ix_(seg_pos, sel_cols)].mean(
            axis=1
        )

        # Random benchmark: same dates, random top-X draws
        for j in range(N_RANDOM_PORTFOLIOS):
            rand_cols = rng.choice(len(tickers), size=TOP_X, replace=False)
            random_rets[seg_pos, j] = mat_np[
                np.ix_(seg_pos, rand_cols)
            ].mean(axis=1)

    # ── Comparison window: from the first rebalance onward ───────────
    start = rebalances[0]
    live = np.asarray(index >= start)
    topx = topx_ret[live]
    eq_all = matrix[live].mean(axis=1)
    rand = random_rets[live]

    years = (index[-1] - start).days / 365.25
    bpy_emp = live.sum() / years

    topx_eq = (1 + topx).cumprod()
    all_eq = (1 + eq_all).cumprod()
    rand_final = (1 + rand).prod(axis=0)

    pct_beaten = float((topx_eq.iloc[-1] > rand_final).mean() * 100)

    # ── Console summary ───────────────────────────────────────────────
    def _line(name: str, r: pd.Series, eq: pd.Series) -> str:
        return (
            f"  {name:22}  ret={((eq.iloc[-1]) - 1) * 100:+7.2f}%  "
            f"sharpe={sharpe(r.to_numpy(), bpy_emp):+6.3f}  "
            f"maxDD={max_drawdown(eq.to_numpy()) * 100:5.2f}%"
        )

    print("\n" + "=" * 72)
    print(f"Selection top-{TOP_X} hebdo (Sharpe {LOOKBACK_DAYS}j) "
          f"vs equipondere {len(tickers)} symboles")
    print(f"Periode comparee : {start:%Y-%m-%d} -> {index[-1]:%Y-%m-%d} "
          f"({years:.2f} ans)")
    print("-" * 72)
    print(_line(f"Top-{TOP_X} (scorer)", topx, topx_eq))
    print(_line("Equipondere (tous)", eq_all, all_eq))
    print(
        f"  Aleatoire (n={N_RANDOM_PORTFOLIOS})     "
        f"ret median={np.median(rand_final - 1) * 100:+7.2f}%  "
        f"-> le scorer bat {pct_beaten:.0f}% des tirages"
    )
    print("=" * 72)

    # ── CSV outputs ───────────────────────────────────────────────────
    pd.DataFrame({
        "topx_equity": topx_eq,
        "equal_weight_equity": all_eq,
    }).to_csv(OUTPUT_DIR / "scorer_oos_equity.csv")
    pd.DataFrame(selection_rows).to_csv(
        OUTPUT_DIR / "scorer_oos_selection.csv", index=False
    )

    # ── HTML report ───────────────────────────────────────────────────
    fig_eq = go.Figure()
    step = max(len(topx_eq) // 5000, 1)   # decimate for file size
    fig_eq.add_scatter(
        x=topx_eq.index[::step], y=topx_eq.iloc[::step],
        name=f"Top-{TOP_X} (scorer)", line={"width": 2},
    )
    fig_eq.add_scatter(
        x=all_eq.index[::step], y=all_eq.iloc[::step],
        name=f"Équipondéré ({len(tickers)})", line={"width": 2},
    )
    fig_eq.update_layout(
        title="Équité — sélection scorer vs équipondéré (base 1.0)",
        yaxis_title="Équité", template="plotly_dark", height=500,
    )

    fig_hist = go.Figure()
    fig_hist.add_histogram(
        x=(rand_final - 1) * 100, nbinsx=40, name="Portefeuilles aléatoires"
    )
    fig_hist.add_vline(
        x=(topx_eq.iloc[-1] - 1) * 100, line_color="orange",
        annotation_text=f"Scorer top-{TOP_X}",
    )
    fig_hist.add_vline(
        x=(all_eq.iloc[-1] - 1) * 100, line_color="cyan",
        annotation_text="Équipondéré",
    )
    fig_hist.update_layout(
        title=(
            f"Rendement final de {N_RANDOM_PORTFOLIOS} sélections "
            f"aléatoires top-{TOP_X} (le scorer en bat "
            f"{pct_beaten:.0f} %)"
        ),
        xaxis_title="Rendement total (%)", template="plotly_dark",
        height=400,
    )

    html = (
        "<html><head><meta charset='utf-8'>"
        "<title>Scorer OOS</title></head>"
        "<body style='background:#111;color:#ddd;"
        "font-family:sans-serif'>"
        f"<h1>Validation out-of-sample de la sélection top-{TOP_X}</h1>"
        f"<p>Stratégie: {'+'.join(CFG['active_signals'])} "
        f"(seuil {CFG['vote_threshold']}), stop {CFG['stop_loss_pct']:.0%},"
        f" coût/side {COST_PER_SIDE:.2%}. Re-sélection hebdo par Sharpe "
        f"{LOOKBACK_DAYS}j glissants.</p>"
        + fig_eq.to_html(full_html=False, include_plotlyjs="cdn")
        + fig_hist.to_html(full_html=False, include_plotlyjs=False)
        + "</body></html>"
    )
    (OUTPUT_DIR / "scorer_oos_report.html").write_text(
        html, encoding="utf-8"
    )
    logger.info(
        "Rapport écrit: %s (%.1f s au total)",
        OUTPUT_DIR / "scorer_oos_report.html", time.time() - t0,
    )


if __name__ == "__main__":
    run_backtest()
