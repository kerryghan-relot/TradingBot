"""
Vote-based mean-reversion basket — the configuration currently live.
=====================================================================
Five mean-reversion signals vote on every bar (BB, OU, VWAP,
VolSpike, KalmanZ); two concurring votes trigger a market order and a
2 % stop-loss guards every position.
"""

from core.config import DEFAULT_CONFIG
from strategies import Strategy

STRATEGY = Strategy(
    name="vote_mr",
    description=(
        "BB + OU + VWAP + VolSpike + KalmanZ, seuil 2 votes, stop 2 %"
    ),
    # The canonical live defaults ARE this strategy.  A variant would
    # override keys: {**DEFAULT_CONFIG, "vote_threshold": 3, ...}.
    config=dict(DEFAULT_CONFIG),
)
