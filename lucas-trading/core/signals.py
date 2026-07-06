"""
Streaming signal functions — lucas-trading/core.
=================================================

All functions are pure (no side effects) and operate on plain Python
lists of recent values (oldest first).  Each signal returns a
(buy: bool, sell: bool) pair.

Stateful signals (KalmanZ, VWAP, ORB) also return updated state so
the caller (AssetState) can persist it between bars.

Naming mirrors backtest/vectorized/strategies_vbt.py so parameters from the
research backtests can be transferred directly.
"""

import math


# ── Internal helpers ──────────────────────────────────────────────

def _ema(values: list[float], period: int) -> float | None:
    """Compute the EMA of the last `period` values (oldest-first list).

    Args:
        values (list[float]): Price series, oldest first.
        period (int): EMA window.

    Returns:
        float | None: EMA value, or None if insufficient data.
    """
    if len(values) < period:
        return None
    k      = 2.0 / (period + 1)
    result = values[-period]
    for v in values[-period + 1:]:
        result = v * k + result * (1.0 - k)
    return result


def _mean_std(values: list[float]) -> tuple[float, float]:
    """Return (mean, population std) of a non-empty list.

    Args:
        values (list[float]): Numeric values.

    Returns:
        tuple[float, float]: (mean, std). Returns (0.0, 0.0) if empty.
    """
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mu  = sum(values) / n
    var = sum((x - mu) ** 2 for x in values) / n
    return mu, var ** 0.5


# ── Stateless signals ─────────────────────────────────────────────

def sig_bb(
    closes: list[float],
    period: int,
    std: float,
) -> tuple[bool, bool]:
    """Bollinger Band mean-reversion.

    Buy  when close crosses below the lower band.
    Sell when close crosses above the upper band.

    Args:
        closes (list[float]): Close prices, oldest first.
        period (int): Rolling window (e.g. 200).
        std (float): Band width in standard deviations (e.g. 2.5).

    Returns:
        tuple[bool, bool]: (buy, sell).
    """
    if len(closes) < period + 1:
        return False, False
    mu, sigma = _mean_std(closes[-period:])
    lower = mu - std * sigma
    upper = mu + std * sigma
    prev  = closes[-2]
    curr  = closes[-1]
    # Rising-edge detection (mirrors vectorbt _disc)
    return (prev >= lower and curr < lower), (prev <= upper and curr > upper)


def sig_ema_cross(
    closes: list[float],
    fast: int,
    slow: int,
) -> tuple[bool, bool]:
    """EMA crossover: fast crosses above (buy) / below (sell) slow.

    Args:
        closes (list[float]): Close prices, oldest first.
        fast (int): Fast EMA period (e.g. 10).
        slow (int): Slow EMA period (e.g. 200).

    Returns:
        tuple[bool, bool]: (buy, sell). (False, False) if fast >= slow
            or insufficient data.
    """
    if len(closes) < slow + 1 or fast >= slow:
        return False, False
    ef_now  = _ema(closes,      fast)
    es_now  = _ema(closes,      slow)
    ef_prev = _ema(closes[:-1], fast)
    es_prev = _ema(closes[:-1], slow)
    if None in (ef_now, es_now, ef_prev, es_prev):
        return False, False
    buy  = ef_prev <= es_prev and ef_now  > es_now
    sell = ef_prev >= es_prev and ef_now  < es_now
    return buy, sell


def sig_macd_zero(
    closes: list[float],
    fast: int,
    slow: int,
) -> tuple[bool, bool]:
    """MACD line crosses above (buy) / below (sell) zero.

    MACD = EMA(fast) − EMA(slow).  No signal line needed here — the
    zero-cross is sufficient for mean-reversion / trend confirmation.

    Args:
        closes (list[float]): Close prices, oldest first.
        fast (int): Fast EMA period (e.g. 26).
        slow (int): Slow EMA period (e.g. 78).

    Returns:
        tuple[bool, bool]: (buy, sell).
    """
    if len(closes) < slow + 1 or fast >= slow:
        return False, False
    ef_now  = _ema(closes,      fast)
    es_now  = _ema(closes,      slow)
    ef_prev = _ema(closes[:-1], fast)
    es_prev = _ema(closes[:-1], slow)
    if None in (ef_now, es_now, ef_prev, es_prev):
        return False, False
    macd_now  = ef_now  - es_now
    macd_prev = ef_prev - es_prev
    return (macd_prev <= 0 and macd_now > 0), (macd_prev >= 0 and macd_now < 0)


def sig_zscore(
    closes: list[float],
    window: int,
    threshold: float,
) -> tuple[bool, bool]:
    """Z-score mean-reversion.

    Buy  when z crosses below −threshold (price far under rolling mean).
    Sell when z crosses above +threshold.

    Args:
        closes (list[float]): Close prices, oldest first.
        window (int): Rolling window for mean/std (e.g. 200).
        threshold (float): Z-score trigger level (e.g. 2.0).

    Returns:
        tuple[bool, bool]: (buy, sell).
    """
    if len(closes) < window + 1:
        return False, False
    mu_now,  sigma_now  = _mean_std(closes[-window:])
    mu_prev, sigma_prev = _mean_std(closes[-window - 1:-1])
    if sigma_now == 0 or sigma_prev == 0:
        return False, False
    z_now  = (closes[-1] - mu_now)  / sigma_now
    z_prev = (closes[-2] - mu_prev) / sigma_prev
    return (
        z_prev >= -threshold and z_now  < -threshold,
        z_prev <= +threshold and z_now  > +threshold,
    )


def sig_rsi(
    closes: list[float],
    period: int,
    buy_th: float,
    sell_th: float,
) -> tuple[bool, bool]:
    """RSI oversold (buy) / overbought (sell) using Wilder's smoothing.

    Args:
        closes (list[float]): Close prices, oldest first.
        period (int): RSI lookback (e.g. 200).
        buy_th (float): Oversold threshold — buy when RSI < this (e.g. 25).
        sell_th (float): Overbought threshold — sell when RSI > this (e.g. 75).

    Returns:
        tuple[bool, bool]: (buy, sell).
    """
    if len(closes) < period + 2:
        return False, False

    def _rsi(cs: list[float]) -> float:
        deltas   = [cs[i] - cs[i - 1] for i in range(1, len(cs))]
        avg_gain = sum(d for d in deltas[:period] if d > 0) / period
        avg_loss = sum(-d for d in deltas[:period] if d < 0) / period
        for d in deltas[period:]:
            avg_gain = (avg_gain * (period - 1) + max(d, 0.0))  / period
            avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
        return 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    rsi_now  = _rsi(closes)
    rsi_prev = _rsi(closes[:-1])
    return (rsi_prev >= buy_th  and rsi_now  < buy_th), \
           (rsi_prev <= sell_th and rsi_now  > sell_th)


def sig_vol_spike(
    closes: list[float],
    volumes: list[float],
    window: int,
    factor: float,
) -> tuple[bool, bool]:
    """Volume spike with price-direction confirmation.

    Buy  when volume > factor × rolling mean AND price rose.
    Sell when volume > factor × rolling mean AND price fell.

    Args:
        closes (list[float]): Close prices, oldest first.
        volumes (list[float]): Bar volumes, oldest first.
        window (int): Rolling mean window (e.g. 20).
        factor (float): Spike multiplier (e.g. 2.0).

    Returns:
        tuple[bool, bool]: (buy, sell).
    """
    if len(volumes) < window + 1 or len(closes) < 2:
        return False, False
    avg = sum(volumes[-window - 1:-1]) / window
    if avg == 0:
        return False, False
    spike = volumes[-1] > factor * avg
    if not spike:
        return False, False
    rising = closes[-1] > closes[-2]
    return rising, not rising


def sig_ou(
    closes: list[float],
    window: int,
    threshold: float,
) -> tuple[bool, bool]:
    """Ornstein-Uhlenbeck mean-reversion via rolling OLS on log prices.

    Estimates the OU equilibrium μ and z-scores the deviation.
    Buy  when z < −threshold.  Sell when z > +threshold.

    Args:
        closes (list[float]): Close prices, oldest first.
        window (int): OLS window in bars (e.g. 200).
        threshold (float): Z-score trigger (e.g. 2.0).

    Returns:
        tuple[bool, bool]: (buy, sell).
    """
    if len(closes) < window + 2:
        return False, False

    def _ou_z(cs: list[float]) -> float | None:
        log_p = [math.log(max(c, 1e-10)) for c in cs[-window - 1:]]
        x, x_lag = log_p[1:], log_p[:-1]
        n = len(x)
        mean_x,   _ = _mean_std(x)
        mean_lag, _ = _mean_std(x_lag)
        cov     = sum((x[i] - mean_x) * (x_lag[i] - mean_lag) for i in range(n)) / n
        var_lag = sum((v - mean_lag) ** 2 for v in x_lag) / n
        if var_lag == 0:
            return None
        b  = max(1e-10, min(1.0 - 1e-10, cov / var_lag))
        mu = (mean_x - b * mean_lag) / max(1.0 - b, 1e-10)
        residuals = [x[i] - b * x_lag[i] - (1.0 - b) * mu for i in range(n)]
        _, std_r = _mean_std(residuals)
        if std_r == 0:
            return None
        return (log_p[-1] - mu) / std_r

    z_now  = _ou_z(closes)
    z_prev = _ou_z(closes[:-1])
    if z_now is None or z_prev is None:
        return False, False
    return (
        z_prev >= -threshold and z_now  < -threshold,
        z_prev <= +threshold and z_now  > +threshold,
    )


# ── Stateful signals (return updated state alongside signal) ──────

def sig_kalman_zscore(
    close: float,
    kf_mu: float,
    kf_p: float,
    kf_residuals: list[float],
    q: float,
    r: float,
    roll_win: int,
    threshold: float,
) -> tuple[bool, bool, float, float, float]:
    """Kalman-filtered Z-score mean-reversion.

    Maintains an adaptive Kalman mean that tracks the price smoothly.
    The Z-score measures how far the current price is from this mean
    relative to recent residual volatility.

    Args:
        close (float): Current close price.
        kf_mu (float): Previous Kalman mean estimate.
        kf_p (float): Previous Kalman error covariance.
        kf_residuals (list[float]): Recent residuals (close − kf_mu)
            for rolling std computation (oldest first, caller manages).
        q (float): Process noise variance (controls adaptivity, e.g. 1e-4).
        r (float): Measurement noise variance (e.g. 0.1).
        roll_win (int): Rolling window for residual std (e.g. 100).
        threshold (float): Z-score trigger (e.g. 2.0).

    Returns:
        tuple[bool, bool, float, float, float]:
            (buy, sell, new_kf_mu, new_kf_p, residual).
            Caller appends residual to kf_residuals deque.
    """
    p_pred  = kf_p + q
    k_gain  = p_pred / (p_pred + r)
    new_mu  = kf_mu + k_gain * (close - kf_mu)
    new_p   = (1.0 - k_gain) * p_pred
    residual = close - new_mu

    win = kf_residuals[-roll_win:] if len(kf_residuals) >= roll_win else kf_residuals
    if len(win) < max(roll_win // 4, 5):
        return False, False, new_mu, new_p, residual

    _, std_r = _mean_std(list(win))
    if std_r == 0:
        return False, False, new_mu, new_p, residual

    # Previous residual for rising-edge detection
    prev_residual = kf_residuals[-1] if kf_residuals else 0.0
    z_now  = residual      / std_r
    z_prev = prev_residual / std_r
    return (
        z_prev >= -threshold and z_now  < -threshold,
        z_prev <= +threshold and z_now  > +threshold,
        new_mu,
        new_p,
        residual,
    )


def sig_vwap(
    close: float,
    high: float,
    low: float,
    volume: float,
    cum_pv: float,
    cum_vol: float,
    threshold: float,
) -> tuple[bool, bool, float, float]:
    """VWAP deviation mean-reversion.

    Entry when close deviates from the session VWAP by more than
    threshold.  Session VWAP state resets at midnight UTC — the
    caller is responsible for the reset (see AssetState.reset_session).

    Args:
        close, high, low, volume: Current bar OHLCV values.
        cum_pv (float): Cumulative (typical_price × volume) this session.
        cum_vol (float): Cumulative volume this session.
        threshold (float): Deviation threshold, e.g. 0.005 = 0.5%.

    Returns:
        tuple[bool, bool, float, float]:
            (buy, sell, new_cum_pv, new_cum_vol).
    """
    typical  = (high + low + close) / 3.0
    new_pv   = cum_pv  + typical * volume
    new_vol  = cum_vol + volume
    if new_vol == 0:
        return False, False, new_pv, new_vol
    vwap = new_pv / new_vol
    if vwap == 0:
        return False, False, new_pv, new_vol
    dev = (close - vwap) / vwap
    return dev < -threshold, dev > threshold, new_pv, new_vol


def sig_orb(
    close: float,
    high: float,
    low: float,
    orb_high: float | None,
    orb_low: float | None,
    orb_complete: bool,
    bar_in_session: int,
    orb_bars: int,
) -> tuple[bool, bool, float | None, float | None, bool]:
    """Opening Range Breakout.

    The first orb_bars bars of each session define the opening range.
    After that, a close above the range high is a buy; below the range
    low is a sell.

    Args:
        close, high, low: Current bar prices.
        orb_high (float | None): Running opening-range high (None = not set yet).
        orb_low  (float | None): Running opening-range low.
        orb_complete (bool): True once the opening range is established.
        bar_in_session (int): 0-based bar index within the current session.
        orb_bars (int): Number of bars that define the opening range (e.g. 6).

    Returns:
        tuple[bool, bool, float | None, float | None, bool]:
            (buy, sell, new_orb_high, new_orb_low, new_orb_complete).
    """
    if bar_in_session < orb_bars:
        new_high = max(orb_high, high) if orb_high is not None else high
        new_low  = min(orb_low,  low)  if orb_low  is not None else low
        return False, False, new_high, new_low, False
    if orb_high is None or orb_low is None:
        return False, False, orb_high, orb_low, True
    return close > orb_high, close < orb_low, orb_high, orb_low, True


def sig_time_filter(bar_in_session: int, session_length: int, skip: int) -> bool:
    """Return True when outside the opening and closing skip windows.

    Designed to be used as a gate (not a vote): if False, all signals
    are suppressed for the current bar regardless of their values.

    Args:
        bar_in_session (int): 0-based bar index within the current session.
        session_length (int): Total bars in the session (e.g. 1440 for 24h/1min).
        skip (int): Bars to skip at start and end of session (e.g. 6).

    Returns:
        bool: True = trading allowed, False = skip this bar.
    """
    tail = session_length - bar_in_session - 1
    return bar_in_session >= skip and tail >= skip


# ── Configuration helper ──────────────────────────────────────────

def warmup_needed(cfg: dict, active: set[str]) -> int:
    """Return minimum bars required before any window-based signal can fire.

    Only counts signals present in ``active``; session-based signals
    (KalmanZ, VWAP, ORB, TimeFilter) have no fixed-window warmup.

    Shared between ``bot.py`` (live engine) and ``scorer.py``
    (simulation) so the two never diverge silently.

    Args:
        cfg    (dict): Configuration dict with period parameters.
        active (set[str]): Names of currently active signals.

    Returns:
        int: Minimum bar count needed.  Returns 2 when no window
            signals are active (enough for basic edge detection).
    """
    reqs: list[int] = []
    if "BB"        in active: reqs.append(int(cfg["bb_period"]) + 1)
    if "EMA_Cross" in active: reqs.append(int(cfg["ema_slow"]) + 1)
    if "MACD_Zero" in active: reqs.append(int(cfg["macd_slow"]) + 1)
    if "Zscore"    in active: reqs.append(int(cfg["zscore_window"]) + 1)
    if "RSI"       in active: reqs.append(int(cfg["rsi_period"]) + 2)
    if "VolSpike"  in active: reqs.append(int(cfg["vol_window"]) + 1)
    if "OU"        in active: reqs.append(int(cfg["ou_window"]) + 2)
    return max(reqs, default=2)


# ── Vote aggregator ───────────────────────────────────────────────

def vote(
    signals: list[tuple[bool, bool]],
    threshold: int,
) -> tuple[bool, bool]:
    """Aggregate (buy, sell) votes and apply a minimum-vote threshold.

    Sell takes priority over buy on a simultaneous tie.

    Args:
        signals (list[tuple[bool, bool]]): List of (buy, sell) pairs
            from individual signal functions.
        threshold (int): Minimum votes required to trigger (e.g. 2).

    Returns:
        tuple[bool, bool]: (buy_triggered, sell_triggered).

    Example:
        >>> vote([(True, False), (True, False), (False, True)], threshold=2)
        (True, False)
    """
    buy_votes  = sum(1 for b, _ in signals if b)
    sell_votes = sum(1 for _, s in signals if s)
    sell = sell_votes >= threshold
    buy  = buy_votes  >= threshold and not sell
    return buy, sell
