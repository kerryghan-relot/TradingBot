"""
Trading strategies – majority vote – 5-min bar data.
=====================================================
1 US trading day ≈ 78 bars | 1 week ≈ 390 bars

All signal functions accept a pd.DataFrame with OHLCV columns
(open, high, low, close, volume) and return (entries, exits).

Base signals:
  RSI, Bollinger, EMA_Cross, MACD_Zero, MACD_Signal,
  EMA_Trend, Zscore, BB_Squeeze, Donchian, RSI_Slope,
  Regime_Trend, Regime_Range  (efficiency-ratio filters)
  VWAP, ORB, VolSpike, OU, TimeFilter, KalmanZscore  (new)

Generated combinations (active signals only):
  - individual strategies
  - all pairs     (threshold 2/2)
  - all triplets  2/3 (majority)
  - all triplets  3/3 (unanimity)
  - quadruplets   3/4
"""

from collections.abc import Callable
from itertools import combinations

import numpy as np
import pandas as pd
import vectorbt as vbt

# ──────────────────────────────────────────────────────────────
# PARAMETERS
# ──────────────────────────────────────────────────────────────

RSI_PERIOD: int = 200
RSI_BUY: float = 25.0
RSI_SELL: float = 75.0

BB_PERIOD: int = 750
BB_STD: float = 3.0

EMA_FAST: int = 10      # ~1h
EMA_SLOW: int = 500     # ~4h

MACD_F: int = 26        # ~3h
MACD_S: int = 78        # ~8h (ratio 1:3)
MACD_SIG: int = 14

ZSCORE_WIN: int = 390   # ~1 week
ZSCORE_TH: float = 3.0

BB_SQ_WIN: int = 100
BB_SQ_STD: float = 2.0

DONCH_EN: int = 40      # entry lookback (~4h)
DONCH_EX: int = 20      # exit lookback

RSI_SL_WIN: int = 14
RSI_SL_LB: int = 5      # RSI slope lookback

REGIME_ER_PERIOD: int = 20      # Efficiency Ratio window
REGIME_TREND_TH: float = 0.50   # ER above → trending
REGIME_RANGE_TH: float = 0.35   # ER below → ranging / choppy

# New signal parameters
VWAP_TH: float = 0.005      # ±0.5 % VWAP deviation threshold
ORB_BARS: int = 6            # Opening range = first 6 bars (~30 min)
VOL_ROLL_WIN: int = 20       # Volume rolling mean window (bars)
VOL_SPIKE_TH: float = 2.0   # Spike when volume > 2× rolling mean
OU_WINDOW: int = 200         # OU rolling OLS window (bars)
OU_TH: float = 2.0           # OU z-score entry threshold
TIME_SKIP_BARS: int = 6      # Skip first/last N bars per session
KALMAN_Q: float = 1e-4       # Kalman process noise variance
KALMAN_R: float = 0.1        # Kalman measurement noise variance
KZ_ROLL_WIN: int = 100       # Rolling std window for Kalman Z-score
KZ_TH: float = 2.0           # Kalman Z-score entry threshold


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def _disc(s: pd.Series) -> pd.Series:
    """Return the first True of each run of consecutive True values."""
    s = s.fillna(False)
    return s & ~s.shift(1).fillna(False)


def _efficiency_ratio(close: pd.Series, period: int) -> pd.Series:
    """
    Compute Kaufman's Efficiency Ratio over a rolling window.

    ER = |net_direction| / sum_of_absolute_moves
    ER near 1 → strongly trending; ER near 0 → choppy / ranging.

    Args:
        close (pd.Series): Close price series.
        period (int): Rolling lookback in bars.

    Returns:
        pd.Series: Efficiency Ratio in [0, 1], NaN during warmup.
    """
    direction = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period).sum()
    return direction / volatility.replace(0, np.nan)


def _kalman_mean(
    values: np.ndarray,
    q: float,
    r: float,
) -> np.ndarray:
    """
    Compute Kalman filter adaptive mean estimate in O(n).

    Args:
        values (np.ndarray): Input time series.
        q (float): Process noise variance (controls adaptivity).
        r (float): Measurement noise variance (controls smoothness).

    Returns:
        np.ndarray: Filtered mean estimates, same length as values.
    """
    n = len(values)
    mu_out = np.empty(n)
    p = 1.0
    mu_out[0] = values[0]
    for t in range(1, n):
        p_pred = p + q
        k = p_pred / (p_pred + r)
        mu_out[t] = mu_out[t - 1] + k * (values[t] - mu_out[t - 1])
        p = (1.0 - k) * p_pred
    return mu_out


# ──────────────────────────────────────────────────────────────
# BASE SIGNALS
# Each takes df: pd.DataFrame (OHLCV) and returns
# (entry: pd.Series[bool], exit: pd.Series[bool]).
# Continuous series — discretisation is handled by _disc / vote.
# ──────────────────────────────────────────────────────────────

def _sig_rsi(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """RSI oversold / overbought entry-exit."""
    close = df["close"]
    rsi = vbt.RSI.run(close, window=RSI_PERIOD).rsi
    return rsi < RSI_BUY, rsi > RSI_SELL


def _sig_bollinger(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Close below / above Bollinger Bands."""
    close = df["close"]
    bb = vbt.BBANDS.run(close, window=BB_PERIOD, alpha=BB_STD)
    return close < bb.lower, close > bb.upper


def _sig_ema_cross(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Fast EMA crosses above / below slow EMA."""
    close = df["close"]
    ema_f = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_s = close.ewm(span=EMA_SLOW, adjust=False).mean()
    return ema_f > ema_s, ema_f < ema_s


def _sig_macd_zero(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """MACD line above / below zero."""
    close = df["close"]
    macd = vbt.MACD.run(
        close, fast_window=MACD_F, slow_window=MACD_S, signal_window=MACD_SIG
    ).macd
    return macd > 0, macd < 0


def _sig_macd_signal(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """MACD line above / below its signal line."""
    close = df["close"]
    ind = vbt.MACD.run(
        close, fast_window=MACD_F, slow_window=MACD_S, signal_window=MACD_SIG
    )
    return ind.macd > ind.signal, ind.macd < ind.signal


def _sig_ema_trend(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Price above / below slow EMA (trend filter)."""
    close = df["close"]
    ema_s = close.ewm(span=EMA_SLOW, adjust=False).mean()
    return close > ema_s, close < ema_s


def _sig_zscore(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Z-score mean-reversion: entry when statistically oversold.

    Entry when z < -ZSCORE_TH (price far below rolling mean).
    Exit  when z >  ZSCORE_TH.
    """
    close = df["close"]
    mu = close.rolling(ZSCORE_WIN).mean()
    sigma = close.rolling(ZSCORE_WIN).std()
    z = (close - mu) / sigma.replace(0, np.nan)
    return z < -ZSCORE_TH, z > ZSCORE_TH


def _sig_bb_squeeze(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Bollinger Squeeze: band compression followed by upside breakout.

    Entry when width exits its 20th-percentile squeeze and close
    breaks above the upper band.  Exit when close < BB middle.
    """
    close = df["close"]
    bb = vbt.BBANDS.run(close, window=BB_SQ_WIN, alpha=BB_SQ_STD)
    width = (bb.upper - bb.lower) / bb.middle.replace(0, np.nan)
    squeeze = width < width.rolling(BB_SQ_WIN * 2).quantile(0.20)
    entry = squeeze.shift(1).fillna(False) & ~squeeze & (close > bb.upper)
    exit_ = close < bb.middle
    return entry, exit_


def _sig_donchian(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Donchian channel breakout.

    Entry when close exceeds the DONCH_EN-bar high.
    Exit  when close falls below the DONCH_EX-bar low.
    """
    close = df["close"]
    highest = close.shift(1).rolling(DONCH_EN).max()
    lowest = close.shift(1).rolling(DONCH_EX).min()
    return close > highest, close < lowest


def _sig_rsi_slope(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    RSI slope: entry when oversold and slope is rising (momentum turning).

    Avoids entering on a still-falling RSI.
    """
    close = df["close"]
    rsi = vbt.RSI.run(close, window=RSI_SL_WIN).rsi
    slope = rsi - rsi.shift(RSI_SL_LB)
    entry = (rsi < 40) & (slope > 0)
    exit_ = (rsi > 60) & (slope < 0)
    return entry, exit_


def _sig_regime_trend(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Efficiency Ratio trend regime filter.

    Entry (regime active) when ER > REGIME_TREND_TH (trending market).
    Exit  (regime inactive) when ER < REGIME_RANGE_TH.

    Pair with trend-following signals (EMA_Cross, MACD_Zero) to avoid
    whipsaws in choppy markets.
    """
    er = _efficiency_ratio(df["close"], REGIME_ER_PERIOD)
    return er > REGIME_TREND_TH, er < REGIME_RANGE_TH


def _sig_regime_range(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Efficiency Ratio ranging regime filter.

    Entry (regime active) when ER < REGIME_RANGE_TH (choppy market).
    Exit  (regime inactive) when ER > REGIME_TREND_TH.

    Pair with mean-reversion signals (BB, Zscore) to avoid false entries
    during strong trends.
    """
    er = _efficiency_ratio(df["close"], REGIME_ER_PERIOD)
    return er < REGIME_RANGE_TH, er > REGIME_TREND_TH


# ── New signals ────────────────────────────────────────────────

def _sig_vwap(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    VWAP deviation mean-reversion signal.

    Entry when close is VWAP_TH below session VWAP (oversold vs market).
    Exit  when close is VWAP_TH above session VWAP.

    VWAP resets at the start of each calendar day.
    Requires volume column; returns all-False if volume is unavailable.
    """
    close = df["close"]
    if "volume" not in df.columns or df["volume"].isna().all():
        false_s = pd.Series(False, index=close.index)
        return false_s, false_s.copy()
    volume = df["volume"].replace(0, np.nan)
    typical = (df["high"] + df["low"] + close) / 3
    date_key = df.index.date
    cum_pv = (typical * volume).groupby(date_key).cumsum()
    cum_vol = volume.groupby(date_key).cumsum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    deviation = (close - vwap) / vwap.replace(0, np.nan)
    return deviation < -VWAP_TH, deviation > VWAP_TH


def _sig_orb(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Opening Range Breakout: first ORB_BARS bars define the range.

    Entry when close breaks above the opening-range high.
    Exit  when close breaks below the opening-range low.

    Works on both equity (9:30 am open) and 24/7 crypto (UTC day open).
    """
    date_key = df.index.date
    bar_rank = df.groupby(date_key).cumcount()
    in_range = bar_rank < ORB_BARS
    or_high = (
        df["high"]
        .where(in_range)
        .groupby(date_key)
        .transform("max")
    )
    or_low = (
        df["low"]
        .where(in_range)
        .groupby(date_key)
        .transform("min")
    )
    after_range = bar_rank >= ORB_BARS
    return (
        after_range & (df["close"] > or_high),
        after_range & (df["close"] < or_low),
    )


def _sig_vol_spike(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Volume spike with price-direction confirmation.

    Entry when volume > VOL_SPIKE_TH × rolling mean AND price rising.
    Exit  when volume > VOL_SPIKE_TH × rolling mean AND price falling.

    Requires volume column; returns all-False if volume is unavailable.
    """
    close = df["close"]
    if "volume" not in df.columns or df["volume"].isna().all():
        false_s = pd.Series(False, index=close.index)
        return false_s, false_s.copy()
    vol = df["volume"].replace(0, np.nan)
    vol_ma = vol.rolling(VOL_ROLL_WIN).mean()
    spike = vol > VOL_SPIKE_TH * vol_ma.replace(0, np.nan)
    ret = close.pct_change()
    return spike & (ret > 0), spike & (ret < 0)


def _sig_ou(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Ornstein-Uhlenbeck mean-reversion via rolling OLS on log prices.

    Estimates the OU equilibrium level μ and z-scores the deviation.
    Entry when z < -OU_TH (price well below equilibrium).
    Exit  when z >  OU_TH.
    """
    close = df["close"]
    log_p = np.log(close.replace(0, np.nan))
    lag = log_p.shift(1)
    cov = log_p.rolling(OU_WINDOW).cov(lag)
    var = lag.rolling(OU_WINDOW).var()
    b = (cov / var.replace(0, np.nan)).clip(1e-10, 1 - 1e-10)
    mu = (
        (log_p.rolling(OU_WINDOW).mean() - b * lag.rolling(OU_WINDOW).mean())
        / (1 - b)
    )
    sigma_ou = (log_p - b * lag).rolling(OU_WINDOW).std()
    z_ou = (log_p - mu) / sigma_ou.replace(0, np.nan)
    return z_ou < -OU_TH, z_ou > OU_TH


def _sig_time_filter(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Time-of-day filter: skip the first and last TIME_SKIP_BARS per session.

    Entry (active) after the opening skip window.
    Exit  (inactive) when entering the closing skip window.

    Designed to be combined with other signals via the vote framework
    to avoid the high-spread open and close periods.
    """
    date_key = df.index.date
    bar_rank = df.groupby(date_key).cumcount()
    bar_rank_rev = df.groupby(date_key).cumcount(ascending=False)
    active = (bar_rank >= TIME_SKIP_BARS) & (bar_rank_rev >= TIME_SKIP_BARS)
    return active.astype(bool), (~active).astype(bool)


def _sig_kalman_zscore(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Kalman-filtered Z-score mean-reversion signal.

    Uses an adaptive Kalman filter as the mean estimate instead of a
    fixed rolling window.  The Kalman mean tracks the price more
    responsively in fast markets and more slowly in quiet ones.

    Entry when z < -KZ_TH (price below adaptive mean).
    Exit  when z >  KZ_TH.
    """
    close = df["close"]
    values = close.values.astype(float)
    mu_arr = _kalman_mean(values, KALMAN_Q, KALMAN_R)
    mu = pd.Series(mu_arr, index=close.index)
    sigma = close.rolling(KZ_ROLL_WIN).std()
    z = (close - mu) / sigma.replace(0, np.nan)
    return z < -KZ_TH, z > KZ_TH


# ──────────────────────────────────────────────────────────────
# SIGNAL REGISTRY
# Comment / uncomment to enable or disable signals.
# More active signals → exponentially more strategy combinations.
# ──────────────────────────────────────────────────────────────

SIGNALS: dict[str, Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]]] = {
    # ── Original signals ──────────────────────────────────────
    # "RSI":          _sig_rsi,
    #2"BB":           _sig_bollinger,
    #2"EMA_Cross":    _sig_ema_cross,
    #2"MACD_Zero":    _sig_macd_zero,
    # "MACD_Sig":     _sig_macd_signal,
    # "EMA_Trend":    _sig_ema_trend,
    #2"Zscore":       _sig_zscore,
    # "BB_Squeeze":   _sig_bb_squeeze,
    # "Donchian":     _sig_donchian,
    # "RSI_Slope":    _sig_rsi_slope,
    # "Regime_Trend": _sig_regime_trend,   # pair with EMA_Cross / MACD_Zero
    # "Regime_Range": _sig_regime_range,   # pair with BB / Zscore

    # ── New signals (uncomment to test) ──────────────────────
    "VWAP":         _sig_vwap,           # mean-reversion vs session VWAP
    "ORB":          _sig_orb,            # opening range breakout
    "VolSpike":     _sig_vol_spike,      # volume spike + direction
    "OU":           _sig_ou,             # Ornstein-Uhlenbeck equilibrium
    "TimeFilter":   _sig_time_filter,    # avoid open/close spread windows
    "KalmanZ":      _sig_kalman_zscore,  # adaptive mean-reversion
}


# ──────────────────────────────────────────────────────────────
# STRATEGY FACTORY
# ──────────────────────────────────────────────────────────────

def _make_vote(
    names: list[str],
    seuil: int,
) -> Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]]:
    """
    Build a majority-vote strategy from a list of signal names.

    Entry when nb_bullish_signals >= seuil.
    Exit  when nb_bearish_signals >= seuil.
    Conflict (simultaneous entry + exit): exit takes priority.

    Args:
        names (list[str]): Signal names from the SIGNALS registry.
        seuil (int): Minimum votes required to trigger entry or exit.

    Returns:
        Callable: Strategy function ``(df) -> (entries, exits)``.
    """
    def strategie(
        df: pd.DataFrame,
    ) -> tuple[pd.Series, pd.Series]:
        e_votes, x_votes = [], []
        for n in names:
            e, x = SIGNALS[n](df)
            e_votes.append(e.fillna(False).astype(int))
            x_votes.append(x.fillna(False).astype(int))
        se = sum(e_votes)
        sx = sum(x_votes)
        raw_e = (se >= seuil) & (sx < seuil)
        raw_x = sx >= seuil
        return _disc(raw_e), _disc(raw_x)

    return strategie


# ──────────────────────────────────────────────────────────────
# BUILD STRATEGY REGISTRY
# ──────────────────────────────────────────────────────────────

STRATEGIES: dict[
    str, Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]]
] = {}
_names = list(SIGNALS.keys())


# — Individual signals ─────────────────────────────────────────
for _n in _names:
    def _make_single(
        name: str,
    ) -> Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]]:
        def strategie(
            df: pd.DataFrame,
        ) -> tuple[pd.Series, pd.Series]:
            e, x = SIGNALS[name](df)
            return _disc(e.fillna(False)), _disc(x.fillna(False))
        return strategie

    STRATEGIES[_n] = _make_single(_n)

# — Pairs 2/2 ──────────────────────────────────────────────────
for _n1, _n2 in combinations(_names, 2):
    STRATEGIES[f"{_n1}+{_n2}"] = _make_vote([_n1, _n2], seuil=2)

# — Triplets 2/3 (majority) ────────────────────────────────────
for _n1, _n2, _n3 in combinations(_names, 3):
    STRATEGIES[f"{_n1}+{_n2}+{_n3}_2v3"] = _make_vote(
        [_n1, _n2, _n3], seuil=2
    )

# — Triplets 3/3 (unanimity) ───────────────────────────────────
for _n1, _n2, _n3 in combinations(_names, 3):
    STRATEGIES[f"{_n1}+{_n2}+{_n3}_3v3"] = _make_vote(
        [_n1, _n2, _n3], seuil=3
    )

# — Quadruplets 3/4 ────────────────────────────────────────────
for _combo in combinations(_names, 4):
    STRATEGIES["+".join(_combo) + "_3v4"] = _make_vote(
        list(_combo), seuil=3
    )

# — Quintuplets 3/5 (uncomment to enable) ─────────────────────
for _combo in combinations(_names, 5):
    STRATEGIES["+".join(_combo) + "_3v5"] = _make_vote(list(_combo), seuil=3)


print(f"[strategies.py] {len(STRATEGIES)} strategies loaded.")
