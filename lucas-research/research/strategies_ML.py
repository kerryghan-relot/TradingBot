"""
Stratégie de trading – Random Forest – données 5min
===================================================

Remplace les combinaisons de votes manuels par un modèle
RandomForestClassifier entraîné sur les signaux techniques.

Features utilisees :
    - Bollinger (signal bullish)
    - EMA cross (signal bullish)
    - MACD zero (signal bullish)
    - Z-score (signal bullish)

Le modèle prédit :
  1 = hausse future
  0 = baisse / neutre

Entrée :
  proba_long > seuil_long

Sortie :
  proba_long < seuil_exit
"""

import numpy as np
import pandas as pd
import vectorbt as vbt

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler


# ──────────────────────────────────────────────────────────────
# PARAMÈTRES
# ──────────────────────────────────────────────────────────────

BB_PERIOD  = 120
BB_STD     = 2

EMA_FAST   = 10
EMA_SLOW   = 50

MACD_F     = 8
MACD_S     = 21
MACD_SIG   = 5

ZSCORE_WIN = 120
ZSCORE_TH  = 1.5

# ML
FUTURE_BARS   = 6       # horizon prediction (~30min)
RETURN_TH     = 0.001   # +0.1%
TRAIN_RATIO   = 0.7

N_ESTIMATORS  = 300
MAX_DEPTH     = 8
RANDOM_STATE  = 42

ENTRY_TH      = 0.55
EXIT_TH       = 0.50


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def _disc(s: pd.Series) -> pd.Series:
    s = s.fillna(False)
    return s & ~s.shift(1).fillna(False)


# ──────────────────────────────────────────────────────────────
# FEATURES
# ──────────────────────────────────────────────────────────────

def build_features(close: pd.Series) -> pd.DataFrame:

    df = pd.DataFrame(index=close.index)

    # Bollinger signal bullish (close sous la bande basse)
    bb = vbt.BBANDS.run(close, window=BB_PERIOD, alpha=BB_STD)
    df["bb_bull"] = (close < bb.lower).astype(int)

    # EMA cross bullish (ema fast au-dessus ema slow)
    ema_fast = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()
    df["ema_cross_bull"] = (ema_fast > ema_slow).astype(int)

    # MACD zero bullish (macd > 0)
    macd_ind = vbt.MACD.run(
        close,
        fast_window=MACD_F,
        slow_window=MACD_S,
        signal_window=MACD_SIG
    )
    df["macd_zero_bull"] = (macd_ind.macd > 0).astype(int)

    # Z-score bullish (survente statistique)
    mu = close.rolling(ZSCORE_WIN).mean()
    sigma = close.rolling(ZSCORE_WIN).std()
    zscore = (close - mu) / sigma.replace(0, np.nan)
    df["zscore_bull"] = (zscore < -ZSCORE_TH).astype(int)

    return df


# ──────────────────────────────────────────────────────────────
# TARGET
# ──────────────────────────────────────────────────────────────

def build_target(close: pd.Series) -> pd.Series:
    """
    1 si rendement futur > RETURN_TH
    """

    future_ret = (
        close.shift(-FUTURE_BARS) / close - 1
    )

    y = (future_ret > RETURN_TH).astype(int)

    return y


# ──────────────────────────────────────────────────────────────
# RANDOM FOREST STRATEGY
# ──────────────────────────────────────────────────────────────

def random_forest_strategy(close: pd.Series):

    # Features
    X = build_features(close)

    # Target
    y = build_target(close)

    # Clean
    data = pd.concat([X, y.rename("target")], axis=1)
    data = data.dropna()

    X = data.drop(columns="target")
    y = data["target"]

    # Split train/test chronologique
    split = int(len(data) * TRAIN_RATIO)

    X_train = X.iloc[:split]
    y_train = y.iloc[:split]

    X_test = X.iloc[split:]

    # Scaling
    scaler = StandardScaler()

    X_train_scaled = scaler.fit_transform(X_train)
    X_all_scaled   = scaler.transform(X)

    # Model
    model = RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        min_samples_leaf=5,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        class_weight="balanced_subsample"
    )

    model.fit(X_train_scaled, y_train)

    # Predict probabilities
    probs = model.predict_proba(X_all_scaled)[:, 1]

    probas = pd.Series(
        probs,
        index=X.index,
        name="proba_long"
    )

    # Signals
    entries = probas > ENTRY_TH
    exits   = probas < EXIT_TH

    # Align index
    entries = entries.reindex(close.index).fillna(False)
    exits   = exits.reindex(close.index).fillna(False)

    # Backtest uniquement sur la partie test
    if len(X_test) > 0:
        test_start = X_test.index[0]
        test_mask = close.index >= test_start
        entries = entries & test_mask
        exits = exits & test_mask

    return _disc(entries), _disc(exits)


# ──────────────────────────────────────────────────────────────
# REGISTRE STRATEGIES
# ──────────────────────────────────────────────────────────────

STRATEGIES = {
    "RandomForest": random_forest_strategy
}

print("[strategies.py] RandomForest strategy loaded.")