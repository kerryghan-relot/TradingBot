"""
Strategies de trading – vote majoritaire – données 5min
=======================================================
1 journée US ≈ 78 bougies | 1 semaine ≈ 390 bougies

Signaux de base (10 total) :
  RSI, Bollinger, EMA_Cross, MACD_Zero, MACD_Signal,
  EMA_Trend, Zscore, BB_Squeeze, Donchian, RSI_Slope

Combinaisons générées :
  - 10 stratégies individuelles
  - toutes les paires     (seuil 2/2) :  45 stratégies
  - tous les triplets 2/3 (majorité)  :  120 stratégies
  - tous les triplets 3/3 (unanimité) :  120 stratégies
  - quadruplets 3/4                   :  210 stratégies
  - quintuplets 3/5                   :  252 stratégies
  → ~760 stratégies au total
"""

import numpy as np
import pandas as pd
import vectorbt as vbt
from itertools import combinations

# ──────────────────────────────────────────────────────────────
# PARAMÈTRES
# ──────────────────────────────────────────────────────────────

# Héritage original
RSI_PERIOD  = 200
RSI_BUY     = 25
RSI_SELL    = 75
BB_PERIOD   = 750
BB_STD      = 3

# Nouveaux signaux
EMA_FAST    = 10     # ~1h
EMA_SLOW    = 500    # ~4h
MACD_F      = 26     # ~3h
MACD_S      = 78     # ~8h (ratio 1:3)
MACD_SIG    = 14
ZSCORE_WIN  = 390    # ~1 semaine
ZSCORE_TH   = 3.0
BB_SQ_WIN   = 100    # fenêtre squeeze
BB_SQ_STD   = 2.0
DONCH_EN    = 40     # lookback entrée breakout (~4h)
DONCH_EX    = 20     # lookback sortie
RSI_SL_WIN  = 14     # RSI pour slope
RSI_SL_LB   = 5      # lookback pente RSI


# ──────────────────────────────────────────────────────────────
# HELPER
# ──────────────────────────────────────────────────────────────

def _disc(s: pd.Series) -> pd.Series:
    """Premier True d'une série de True consécutifs."""
    s = s.fillna(False)
    return s & ~s.shift(1).fillna(False)


# ──────────────────────────────────────────────────────────────
# SIGNAUX DE BASE
# Retournent (entry: pd.Series[bool], exit: pd.Series[bool])
# Séries continues — la discrétisation est faite par le vote.
# ──────────────────────────────────────────────────────────────

def _sig_rsi(close):
    """RSI survendu/suracheté (paramètres originaux)."""
    rsi   = vbt.RSI.run(close, window=RSI_PERIOD).rsi
    return rsi < RSI_BUY, rsi > RSI_SELL

def _sig_bollinger(close):
    """Close sous/sur les bandes BB (paramètres originaux)."""
    bb    = vbt.BBANDS.run(close, window=BB_PERIOD, alpha=BB_STD)
    return close < bb.lower, close > bb.upper

def _sig_ema_cross(close):
    """EMA rapide croise au-dessus/en-dessous de l'EMA lente."""
    ema_f = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_s = close.ewm(span=EMA_SLOW, adjust=False).mean()
    return ema_f > ema_s, ema_f < ema_s

def _sig_macd_zero(close):
    """MACD line au-dessus/en-dessous de zéro."""
    macd  = vbt.MACD.run(close, fast_window=MACD_F,
                         slow_window=MACD_S, signal_window=MACD_SIG).macd
    return macd > 0, macd < 0

def _sig_macd_signal(close):
    """MACD line au-dessus/en-dessous de sa signal line."""
    ind   = vbt.MACD.run(close, fast_window=MACD_F,
                         slow_window=MACD_S, signal_window=MACD_SIG)
    return ind.macd > ind.signal, ind.macd < ind.signal

def _sig_ema_trend(close):
    """Prix au-dessus/en-dessous de l'EMA lente (filtre tendance)."""
    ema_s = close.ewm(span=EMA_SLOW, adjust=False).mean()
    return close > ema_s, close < ema_s

def _sig_zscore(close):
    """
    Z-score : prix à > ZSCORE_TH écarts-types sous sa moyenne.
    Entrée mean-reversion (survente statistique).
    """
    mu    = close.rolling(ZSCORE_WIN).mean()
    sigma = close.rolling(ZSCORE_WIN).std()
    z     = (close - mu) / sigma.replace(0, np.nan)
    return z < -ZSCORE_TH, z > ZSCORE_TH

def _sig_bb_squeeze(close):
    """
    Bollinger Squeeze : compression des bandes → breakout.
    Entrée quand la largeur relative est dans son 20e percentile
    ET que le close dépasse la bande supérieure (cassure haussière).
    """
    bb     = vbt.BBANDS.run(close, window=BB_SQ_WIN, alpha=BB_SQ_STD)
    width  = (bb.upper - bb.lower) / bb.middle.replace(0, np.nan)
    # Squeeze actif quand largeur < percentile 20 sur 2× la fenêtre
    squeeze = width < width.rolling(BB_SQ_WIN * 2).quantile(0.20)
    # Breakout haussier = sortie du squeeze vers le haut
    entry  = squeeze.shift(1).fillna(False) & ~squeeze & (close > bb.upper)
    exit_  = close < bb.middle
    return entry, exit_

def _sig_donchian(close):
    """
    Donchian channel breakout.
    Entrée : close > plus haut des DONCH_EN dernières bougies.
    Sortie : close < plus bas des DONCH_EX dernières bougies.
    """
    highest = close.shift(1).rolling(DONCH_EN).max()
    lowest  = close.shift(1).rolling(DONCH_EX).min()
    return close > highest, close < lowest

def _sig_rsi_slope(close):
    """
    Pente du RSI : entre quand le RSI est survendu (< 40)
    ET sa pente sur RSI_SL_LB bougies est positive (momentum qui remonte).
    """
    rsi   = vbt.RSI.run(close, window=RSI_SL_WIN).rsi
    slope = rsi - rsi.shift(RSI_SL_LB)
    entry = (rsi < 40) & (slope > 0)
    exit_ = (rsi > 60) & (slope < 0)
    return entry, exit_


# ──────────────────────────────────────────────────────────────
# REGISTRE DES SIGNAUX
# ──────────────────────────────────────────────────────────────

SIGNALS = {
    #2"RSI":        _sig_rsi,
    "BB":         _sig_bollinger,
    "EMA_Cross":  _sig_ema_cross,
    "MACD_Zero":  _sig_macd_zero,
  #  "MACD_Sig":   _sig_macd_signal,
    #"EMA_Trend":  _sig_ema_trend,
    "Zscore":     _sig_zscore,
    #2"BB_Squeeze": _sig_bb_squeeze,
    #"Donchian":   _sig_donchian,
   # "RSI_Slope":  _sig_rsi_slope,
}


# ──────────────────────────────────────────────────────────────
# FABRIQUE DE VOTE
# ──────────────────────────────────────────────────────────────

def _make_vote(names: list, seuil: int):
    """
    Crée une stratégie par vote majoritaire.
    Entrée si nb_signaux_bullish >= seuil.
    Sortie si nb_signaux_bearish >= seuil.
    En cas de conflit simultané, la sortie a priorité.
    """
    def strategie(close: pd.Series):
        e_votes, x_votes = [], []
        for n in names:
            e, x = SIGNALS[n](close)
            e_votes.append(e.fillna(False).astype(int))
            x_votes.append(x.fillna(False).astype(int))
        se = sum(e_votes)
        sx = sum(x_votes)
        raw_e = (se >= seuil) & (sx < seuil)
        raw_x = (sx >= seuil)
        return _disc(raw_e), _disc(raw_x)
    return strategie


# ──────────────────────────────────────────────────────────────
# CONSTRUCTION DU REGISTRE STRATEGIES
# ──────────────────────────────────────────────────────────────

STRATEGIES = {}
noms = list(SIGNALS.keys())

# — Individuelles ——————————————————————————————————————————————
for n in noms:
    def _make_single(name):
        def strategie(close):
            e, x = SIGNALS[name](close)
            return _disc(e.fillna(False)), _disc(x.fillna(False))
        return strategie
    STRATEGIES[n] = _make_single(n)


# — Paires 2/2 ————————————————————————————————————————————————
for n1, n2 in combinations(noms, 2):
    STRATEGIES[f"{n1}+{n2}"] = _make_vote([n1, n2], seuil=2)

# — Triplets 2/3 (majorité) ———————————————————————————————————
for n1, n2, n3 in combinations(noms, 3):
    STRATEGIES[f"{n1}+{n2}+{n3}_2v3"] = _make_vote([n1, n2, n3], seuil=2)
# — Triplets 3/3 (unanimité) ——————————————————————————————————
for n1, n2, n3 in combinations(noms, 3):
    STRATEGIES[f"{n1}+{n2}+{n3}_3v3"] = _make_vote([n1, n2, n3], seuil=3)

# — Quadruplets 3/4 ———————————————————————————————————————————
for combo in combinations(noms, 4):
    STRATEGIES["+".join(combo) + "_3v4"] = _make_vote(list(combo), seuil=3)
"""
# — Quintuplets 3/5 ———————————————————————————————————————————
for combo in combinations(noms, 5):
    STRATEGIES["+".join(combo) + "_3v5"] = _make_vote(list(combo), seuil=3)

# — Tout (10 signaux) seuils variés ———————————————————————————
for s in [3, 4, 5, 6]:
    STRATEGIES[f"ALL_{s}v10"] = _make_vote(noms, seuil=s)
"""
print(f"[strategies.py] {len(STRATEGIES)} stratégies chargées.")