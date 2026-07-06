"""
Shared vote engine — lucas-trading/core.
=========================================

Single implementation of the per-bar signal-evaluation loop used by
both the live bot (``bot.py``) and the offline scorer (``scorer.py``).

Before this module existed, ``scorer.simulate()`` was a hand-written
mirror of ``CryptoBot._evaluate()`` — every change to the bot had to
be copied by hand, and any silent divergence meant the scorer ranked
symbols on a strategy that was no longer the one being traded.

The engine owns:
- ``SignalState``   — rolling windows + stateful-signal state per asset
- ``evaluate_bar``  — stateful updates, warmup, time filter, vote count

It deliberately does NOT own position tracking, order placement,
stop-loss execution, or persistence — those belong to the callers
(live orders in ``bot.py``, simulated P&L in ``scorer.py``).
"""

from collections import deque
from dataclasses import dataclass

from core.signals import (
    sig_bb,
    sig_ema_cross,
    sig_kalman_zscore,
    sig_macd_zero,
    sig_orb,
    sig_ou,
    sig_rsi,
    sig_time_filter,
    sig_vol_spike,
    sig_vwap,
    sig_zscore,
    vote,
    warmup_needed,
)


# Capacity of every rolling price/volume deque per asset.
# Must be ≥ (largest configured window + 2).  Default windows top out
# at 200 bars; 500 provides a comfortable buffer.
DEQUE_SIZE: int = 500

# Kalman residual deque capacity (independent of DEQUE_SIZE).
# Sized at 2× the default roll window to retain enough history after
# roll_win changes in config without losing all prior residuals.
KF_RESIDUAL_SIZE: int = 1000


@dataclass(frozen=True)
class VoteResult:
    """Outcome of one ``evaluate_bar()`` call.

    Attributes:
        warmed_up  (bool): False while rolling windows lack history —
            no votes are collected and callers must not trade.
        in_window  (bool): False when the TimeFilter gate suppresses
            trading for this bar (always True when TimeFilter is
            inactive).  Votes are zeroed when False.
        buy        (bool): Buy vote threshold reached.
        sell       (bool): Sell vote threshold reached (priority on tie).
        buy_votes  (int): Number of signals that voted BUY.
        sell_votes (int): Number of signals that voted SELL.
        n_signals  (int): Total active signals evaluated.
        vol_avg    (float): Rolling volume average (0.0 if unavailable).
        vol_spike  (bool): Volume spike detected on the current bar.
        bars_seen   (int): Bars currently held in the rolling windows.
        bars_needed (int): Bars required before votes can be collected.
    """

    warmed_up:  bool
    in_window:  bool
    buy:        bool
    sell:       bool
    buy_votes:  int
    sell_votes: int
    n_signals:  int
    vol_avg:    float
    vol_spike:  bool
    bars_seen:   int
    bars_needed: int


_NO_VOTE = VoteResult(
    warmed_up=False, in_window=True,
    buy=False, sell=False,
    buy_votes=0, sell_votes=0, n_signals=0,
    vol_avg=0.0, vol_spike=False,
    bars_seen=0, bars_needed=0,
)


class SignalState:
    """Rolling windows and stateful-signal state for one asset.

    Holds everything the vote engine needs between bars: price/volume
    history plus the per-session state required by stateful signals
    (VWAP, ORB, Kalman).  Each instance is entirely independent —
    two assets must never share a ``SignalState``.

    Position tracking (``in_position``, ``entry_price``) is *not* part
    of this class; it belongs to the caller (see ``bot.AssetState``).

    Attributes:
        closes  (deque[float]): Rolling closes, capped at DEQUE_SIZE.
        highs   (deque[float]): Rolling highs, same cap.
        lows    (deque[float]): Rolling lows, same cap.
        volumes (deque[float]): Rolling volumes, same cap.

        kf_mu          (float): Kalman mean estimate.
        kf_p           (float): Kalman error covariance.
        kf_initialized (bool): True once kf_mu has been seeded.
        kf_residuals   (deque[float]): Recent Kalman residuals for
            rolling-std computation.

        vwap_cum_pv  (float): Cumulative typical_price × volume for
            the current session.  Resets on session rollover.
        vwap_cum_vol (float): Cumulative session volume.

        orb_high     (float | None): Opening-range high.
        orb_low      (float | None): Opening-range low.
        orb_complete (bool): True once the opening range is set.

        bar_in_session (int): 0-based bar counter within the current
            session.  Resets on session rollover.
        session_date   (str | None): ISO date string of the current
            session (``"YYYY-MM-DD"``).  ``None`` before the first bar.
    """

    def __init__(self) -> None:
        self.closes:  deque[float] = deque(maxlen=DEQUE_SIZE)
        self.highs:   deque[float] = deque(maxlen=DEQUE_SIZE)
        self.lows:    deque[float] = deque(maxlen=DEQUE_SIZE)
        self.volumes: deque[float] = deque(maxlen=DEQUE_SIZE)

        # Kalman filter state
        self.kf_mu:          float        = 0.0
        self.kf_p:           float        = 1.0
        self.kf_initialized: bool         = False
        self.kf_residuals:   deque[float] = deque(maxlen=KF_RESIDUAL_SIZE)

        # VWAP session state
        self.vwap_cum_pv:  float = 0.0
        self.vwap_cum_vol: float = 0.0

        # ORB session state
        self.orb_high:     float | None = None
        self.orb_low:      float | None = None
        self.orb_complete: bool         = False

        # Session tracking
        self.bar_in_session: int        = 0
        self.session_date:   str | None = None

    def start_bar(self, bar_date: str) -> bool:
        """Advance session tracking for an incoming bar.

        Detects a session (date) rollover: resets VWAP accumulators,
        ORB range, and the bar-in-session counter when the date
        changes, otherwise increments the bar counter.

        Args:
            bar_date (str): ISO date of the bar, e.g. ``"2026-07-04"``.

        Returns:
            bool: True if a new session started (caller may log it).
        """
        if bar_date == self.session_date:
            self.bar_in_session += 1
            return False
        self.vwap_cum_pv    = 0.0
        self.vwap_cum_vol   = 0.0
        self.orb_high       = None
        self.orb_low        = None
        self.orb_complete   = False
        self.bar_in_session = 0
        self.session_date   = bar_date
        return True

    def append_bar(
        self,
        close: float,
        high: float,
        low: float,
        volume: float,
    ) -> None:
        """Append one bar's OHLCV values to the rolling windows.

        Args:
            close  (float): Bar close price.
            high   (float): Bar high price.
            low    (float): Bar low price.
            volume (float): Bar volume.
        """
        self.closes.append(close)
        self.highs.append(high)
        self.lows.append(low)
        self.volumes.append(volume)

    def preload(self, bars: list[dict]) -> None:
        """Populate rolling windows from historical bar dicts.

        Restores ``closes``, ``highs``, ``lows``, and ``volumes`` so
        that window-based indicators compute on the very first live bar
        after startup.  Also seeds the Kalman mean from the last close.

        Args:
            bars (list[dict]): Chronologically ordered bar dicts
                (oldest first) with keys ``close``, ``high``, ``low``,
                ``volume``.
        """
        for b in bars:
            self.closes.append(b["close"])
            self.highs.append(b["high"])
            self.lows.append(b["low"])
            self.volumes.append(b["volume"])
        if self.closes:
            self.kf_mu          = self.closes[-1]
            self.kf_p           = 1.0
            self.kf_initialized = True


def evaluate_bar(state: SignalState, cfg: dict) -> VoteResult:
    """Run the vote engine on the most recent bar in ``state``.

    Must be called after ``state.start_bar()`` and
    ``state.append_bar()`` for the current bar.  Execution order:

        1. Update stateful signal state (KalmanZ, VWAP, ORB) and
           capture their (buy, sell) outputs — always runs, even
           during warmup, so session state never lags.
        2. Compute rolling volume statistics.
        3. Warmup check — return early (no votes) if insufficient
           history.
        4. Time-filter gate — return early (votes zeroed) when the
           bar falls outside the trading window.
        5. Collect votes from all active signals and apply the
           vote threshold.

    Args:
        state (SignalState): Per-asset engine state (mutated in place).
        cfg   (dict): Merged configuration dict (signal parameters,
            ``active_signals``, ``vote_threshold``).

    Returns:
        VoteResult: Vote outcome and volume stats for the current bar.
    """
    closes = list(state.closes)
    if not closes:
        return _NO_VOTE

    highs  = list(state.highs)
    lows   = list(state.lows)
    vols   = list(state.volumes)

    close  = closes[-1]
    high   = highs[-1] if highs else close
    low    = lows[-1]  if lows  else close
    volume = vols[-1]  if vols  else 0.0

    active = set(cfg.get("active_signals", []))

    # ── Step 1: stateful signal updates (always run) ──────────────────────────
    kalman_signal: tuple[bool, bool] = (False, False)
    vwap_signal:   tuple[bool, bool] = (False, False)
    orb_signal:    tuple[bool, bool] = (False, False)

    if "KalmanZ" in active:
        if not state.kf_initialized:
            state.kf_mu          = close
            state.kf_p           = 1.0
            state.kf_initialized = True
        buy_k, sell_k, new_mu, new_p, residual = sig_kalman_zscore(
            close,
            state.kf_mu,
            state.kf_p,
            list(state.kf_residuals),
            cfg["kalman_q"],
            cfg["kalman_r"],
            int(cfg["kalman_roll_win"]),
            cfg["kalman_threshold"],
        )
        state.kf_mu = new_mu
        state.kf_p  = new_p
        state.kf_residuals.append(residual)
        kalman_signal = (buy_k, sell_k)

    if "VWAP" in active:
        buy_v, sell_v, new_pv, new_vol = sig_vwap(
            close, high, low, volume,
            state.vwap_cum_pv,
            state.vwap_cum_vol,
            cfg["vwap_threshold"],
        )
        state.vwap_cum_pv  = new_pv
        state.vwap_cum_vol = new_vol
        vwap_signal = (buy_v, sell_v)

    if "ORB" in active:
        buy_o, sell_o, new_oh, new_ol, new_cplt = sig_orb(
            close, high, low,
            state.orb_high,
            state.orb_low,
            state.orb_complete,
            state.bar_in_session,
            int(cfg["orb_bars"]),
        )
        state.orb_high     = new_oh
        state.orb_low      = new_ol
        state.orb_complete = new_cplt
        orb_signal = (buy_o, sell_o)

    # ── Step 2: volume stats ──────────────────────────────────────────────────
    vol_win = int(cfg["vol_window"])
    vol_avg = (
        sum(vols[-vol_win - 1:-1]) / vol_win
        if len(vols) >= vol_win + 1 else 0.0
    )
    vol_spike_flag = (
        vols[-1] > cfg["vol_factor"] * vol_avg if vol_avg > 0 else False
    )

    # ── Step 3: warmup check ──────────────────────────────────────────────────
    needed = warmup_needed(cfg, active)
    if len(closes) < needed:
        return VoteResult(
            warmed_up=False, in_window=True,
            buy=False, sell=False,
            buy_votes=0, sell_votes=0, n_signals=0,
            vol_avg=vol_avg, vol_spike=vol_spike_flag,
            bars_seen=len(closes), bars_needed=needed,
        )

    # ── Step 4: time-filter gate ──────────────────────────────────────────────
    if "TimeFilter" in active:
        in_window = sig_time_filter(
            state.bar_in_session,
            int(cfg["session_length"]),
            int(cfg["time_skip"]),
        )
        if not in_window:
            return VoteResult(
                warmed_up=True, in_window=False,
                buy=False, sell=False,
                buy_votes=0, sell_votes=0, n_signals=0,
                vol_avg=vol_avg, vol_spike=vol_spike_flag,
                bars_seen=len(closes), bars_needed=needed,
            )

    # ── Step 5: collect votes ─────────────────────────────────────────────────
    raw: list[tuple[bool, bool]] = []

    if "BB" in active:
        raw.append(sig_bb(
            closes, int(cfg["bb_period"]), cfg["bb_std"]
        ))
    if "EMA_Cross" in active:
        raw.append(sig_ema_cross(
            closes, int(cfg["ema_fast"]), int(cfg["ema_slow"])
        ))
    if "MACD_Zero" in active:
        raw.append(sig_macd_zero(
            closes, int(cfg["macd_fast"]), int(cfg["macd_slow"])
        ))
    if "Zscore" in active:
        raw.append(sig_zscore(
            closes,
            int(cfg["zscore_window"]),
            cfg["zscore_threshold"],
        ))
    if "RSI" in active:
        raw.append(sig_rsi(
            closes,
            int(cfg["rsi_period"]),
            cfg["rsi_buy"],
            cfg["rsi_sell"],
        ))
    if "VolSpike" in active:
        raw.append(sig_vol_spike(
            closes, vols,
            int(cfg["vol_window"]),
            cfg["vol_factor"],
        ))
    if "OU" in active:
        raw.append(sig_ou(
            closes, int(cfg["ou_window"]), cfg["ou_threshold"]
        ))
    if "KalmanZ" in active:
        raw.append(kalman_signal)
    if "VWAP" in active:
        raw.append(vwap_signal)
    if "ORB" in active:
        raw.append(orb_signal)

    buy_votes  = sum(1 for b, _ in raw if b)
    sell_votes = sum(1 for _, s in raw if s)
    buy, sell  = vote(raw, int(cfg["vote_threshold"]))

    return VoteResult(
        warmed_up=True, in_window=True,
        buy=buy, sell=sell,
        buy_votes=buy_votes, sell_votes=sell_votes,
        n_signals=len(raw),
        vol_avg=vol_avg, vol_spike=vol_spike_flag,
        bars_seen=len(closes), bars_needed=needed,
    )
