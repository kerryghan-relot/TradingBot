"""
Trading strategy – XGBoost – 5-min bar data.
============================================

Replaces manual vote combinations with an XGBClassifier trained
on continuous technical features (not binary signals).

Features (continuous):
    - Returns at 1, 6, 24, 78 bars (multi-horizon momentum)
    - Rolling 20-bar volatility of returns
    - Continuous RSI value
    - Continuous Z-score (distance from rolling mean in std-devs)
    - Bollinger %b (position within the band, 0=lower, 1=upper)
    - Continuous MACD value
    - MACD − signal line distance
    - Normalised distance from slow EMA
    - Volume ratio vs rolling mean (if volume available)
    - Volume Z-score (if volume available)

Target:
    1 if future return over FUTURE_BARS > RETURN_TH, else 0.

Train/test split: chronological 70 / 15 (val) / 15 (test).
Early stopping uses the validation set to prevent overfitting.
Signals are only generated on the held-out test portion.
"""

import numpy as np
import pandas as pd
import vectorbt as vbt
from xgboost import XGBClassifier

# ──────────────────────────────────────────────────────────────
# PARAMETERS
# ──────────────────────────────────────────────────────────────

BB_PERIOD: int = 120
BB_STD: float = 2.0

EMA_FAST: int = 10
EMA_SLOW: int = 50

MACD_F: int = 8
MACD_S: int = 21
MACD_SIG: int = 5

RSI_PERIOD: int = 14
ZSCORE_WIN: int = 120

# ML
FUTURE_BARS: int = 6        # prediction horizon (~30 min)
RETURN_TH: float = 0.001    # +0.1% forward return to label as 1
TRAIN_RATIO: float = 0.70   # first 70% for train + validation
VAL_SPLIT: float = 0.80     # within train: 80% train, 20% val (early stop)

N_ESTIMATORS: int = 300
MAX_DEPTH: int = 6
LEARNING_RATE: float = 0.05
SUBSAMPLE: float = 0.8
COLSAMPLE_BYTREE: float = 0.8
MIN_CHILD_WEIGHT: int = 5
EARLY_STOPPING_ROUNDS: int = 20

ENTRY_TH: float = 0.55
EXIT_TH: float = 0.50


# ──────────────────────────────────────────────────────────────
# HELPER
# ──────────────────────────────────────────────────────────────

def _disc(s: pd.Series) -> pd.Series:
    """Return the first True of each run of consecutive True values."""
    s = s.fillna(False)
    return s & ~s.shift(1).fillna(False)


# ──────────────────────────────────────────────────────────────
# FEATURE ENGINEERING
# ──────────────────────────────────────────────────────────────

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a continuous feature matrix from an OHLCV DataFrame.

    Using continuous values (not binary thresholds) gives XGBoost
    richer information and more split points to learn from.
    Volume features are added when the column is available.

    Args:
        df (pd.DataFrame): OHLCV DataFrame indexed by datetime.

    Returns:
        pd.DataFrame: Feature matrix, same index as ``df``.
    """
    close = df["close"]
    features = pd.DataFrame(index=close.index)

    # Multi-horizon returns (momentum)
    features["ret_1"] = close.pct_change(1)
    features["ret_6"] = close.pct_change(6)
    features["ret_24"] = close.pct_change(24)
    features["ret_78"] = close.pct_change(78)   # ~1 trading day

    # Short-term realised volatility
    features["vol_20"] = features["ret_1"].rolling(20).std()

    # Continuous RSI (not a binary oversold/overbought flag)
    features["rsi"] = vbt.RSI.run(close, window=RSI_PERIOD).rsi

    # Continuous Z-score (signed distance from rolling mean)
    mu = close.rolling(ZSCORE_WIN).mean()
    sigma = close.rolling(ZSCORE_WIN).std()
    features["zscore"] = (close - mu) / sigma.replace(0, np.nan)

    # Bollinger %b: 0 = at lower band, 1 = at upper band
    bb = vbt.BBANDS.run(close, window=BB_PERIOD, alpha=BB_STD)
    bb_range = (bb.upper - bb.lower).replace(0, np.nan)
    features["bb_pct"] = (close - bb.lower) / bb_range

    # Continuous MACD and distance to signal line
    macd_ind = vbt.MACD.run(
        close,
        fast_window=MACD_F,
        slow_window=MACD_S,
        signal_window=MACD_SIG,
    )
    features["macd"] = macd_ind.macd
    features["macd_signal_diff"] = macd_ind.macd - macd_ind.signal

    # Normalised distance of close from slow EMA
    ema_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()
    features["ema_dist"] = (close - ema_slow) / ema_slow.replace(0, np.nan)

    # Volume features (optional — skipped if column absent or all-NaN)
    if "volume" in df.columns and df["volume"].notna().any():
        vol = df["volume"].replace(0, np.nan)
        vol_ma = vol.rolling(20).mean()
        features["vol_ratio"] = vol / vol_ma.replace(0, np.nan)
        vol_std = vol.rolling(20).std()
        features["vol_zscore"] = (vol - vol_ma) / vol_std.replace(0, np.nan)

    return features


# ──────────────────────────────────────────────────────────────
# TARGET
# ──────────────────────────────────────────────────────────────

def build_target(close: pd.Series) -> pd.Series:
    """
    Build a binary classification target from future returns.

    Args:
        close (pd.Series): Close price series.

    Returns:
        pd.Series: 1 if FUTURE_BARS forward return > RETURN_TH, else 0.
    """
    future_ret = close.shift(-FUTURE_BARS) / close - 1
    return (future_ret > RETURN_TH).astype(int)


# ──────────────────────────────────────────────────────────────
# XGBOOST STRATEGY
# ──────────────────────────────────────────────────────────────

def xgboost_strategy(
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    """
    Train an XGBClassifier on the first TRAIN_RATIO of data and
    generate entry/exit signals on the held-out test portion only.

    A validation slice (last VAL_SPLIT of the training window) is used
    for early stopping to prevent overfitting without leaking test data.
    The chronological split ensures no future information leaks into
    the training set.

    Args:
        df (pd.DataFrame): Full OHLCV DataFrame (datetime index).

    Returns:
        tuple[pd.Series, pd.Series]: (entries, exits) boolean series.
    """
    close = df["close"]
    X = build_features(df)
    y = build_target(close)

    data = pd.concat([X, y.rename("target")], axis=1).dropna()
    X_clean = data.drop(columns="target")
    y_clean = data["target"]

    train_end = int(len(data) * TRAIN_RATIO)
    X_train = X_clean.iloc[:train_end]
    y_train = y_clean.iloc[:train_end]
    X_test = X_clean.iloc[train_end:]

    # Chronological train / validation split within the train window
    val_start = int(len(X_train) * VAL_SPLIT)
    X_tr, X_val = X_train.iloc[:val_start], X_train.iloc[val_start:]
    y_tr, y_val = y_train.iloc[:val_start], y_train.iloc[val_start:]

    model = XGBClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        learning_rate=LEARNING_RATE,
        subsample=SUBSAMPLE,
        colsample_bytree=COLSAMPLE_BYTREE,
        min_child_weight=MIN_CHILD_WEIGHT,
        n_jobs=-1,
        eval_metric="logloss",
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
    )
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    probs = model.predict_proba(X_clean)[:, 1]
    probas = pd.Series(probs, index=X_clean.index, name="proba_long")

    entries = probas > ENTRY_TH
    exits = probas < EXIT_TH

    # Align to the full close index (NaN rows were dropped in data)
    entries = entries.reindex(close.index).fillna(False)
    exits = exits.reindex(close.index).fillna(False)

    # Mask signals to the test period only (out-of-sample)
    if len(X_test) > 0:
        test_start = X_test.index[0]
        test_mask = close.index >= test_start
        entries = entries & test_mask
        exits = exits & test_mask

    return _disc(entries), _disc(exits)


# ──────────────────────────────────────────────────────────────
# STRATEGY REGISTRY
# ──────────────────────────────────────────────────────────────

STRATEGIES: dict[str, object] = {
    "XGBoost": xgboost_strategy,
}

print("[strategies_ML.py] Stratégie XGBoost chargée.")
