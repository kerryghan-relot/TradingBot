"""
Backtest RSI avec Twelve Data + vectorbt
Stratégie : acheter en survente (RSI < 30), vendre en surachat (RSI > 70)
"""

import os

import pandas as pd
import vectorbt as vbt
from datetime import datetime, timedelta

# ── Configuration ──────────────────────────────────────────────
SYMBOL   = "AAPL"
INTERVAL = "1day"
CSV_FILENAME = "AAPL_2023-05-16_2026-05-15.csv"
CSV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", CSV_FILENAME)
)

RSI_PERIOD  = 14
RSI_SURVENTE  = 70   # Signal d'achat en dessous de ce seuil
RSI_SURACHAT  = 30   # Signal de vente au dessus de ce seuil

CAPITAL_INITIAL = 10_000  # en dollars

end_date   = datetime.today().strftime("%Y-%m-%d")
start_date = (datetime.today() - timedelta(days=3*365)).strftime("%Y-%m-%d")

# ── 1. Chargement des données locales ─────────────────────────
print(f"Chargement des données {SYMBOL} depuis {CSV_PATH}...")

df = pd.read_csv(CSV_PATH)
df["datetime"] = pd.to_datetime(df["datetime"])
df = df.set_index("datetime").sort_index()  # Ordre chronologique
df["close"] = df["close"].astype(float)

print(f"✓ {len(df)} bougies chargées\n")

close = df["close"]

# ── 3. Calcul du RSI avec vectorbt ────────────────────────────
rsi = vbt.RSI.run(close, window=RSI_PERIOD)

# ── 4. Génération des signaux ──────────────────────────────────
# Achat  : RSI passe sous RSI_SURVENTE (croisement vers le bas)
# Vente  : RSI passe au dessus RSI_SURACHAT (croisement vers le haut)
entrees = rsi.rsi_crossed_below(RSI_SURVENTE)
sorties = rsi.rsi_crossed_above(RSI_SURACHAT)

# ── 5. Backtest ────────────────────────────────────────────────
portfolio = vbt.Portfolio.from_signals(
    close,
    entries=entrees,
    exits=sorties,
    init_cash=CAPITAL_INITIAL,
    fees=0.001,        # 0.1% de frais par trade
    freq="1D",
)

# ── 6. Résultats ───────────────────────────────────────────────
stats = portfolio.stats()

print("══════════════════════════════════════════")
print(f"  Backtest RSI — {SYMBOL} ({start_date} → {end_date})")
print("══════════════════════════════════════════")
print(f"  Capital initial     : {CAPITAL_INITIAL:>10,.0f} $")
print(f"  Valeur finale       : {stats['End Value']:>10,.2f} $")
print(f"  Performance totale  : {stats['Total Return [%]']:>9.1f} %")
print(f"  Sharpe Ratio        : {stats['Sharpe Ratio']:>10.2f}")
print(f"  Max Drawdown        : {stats['Max Drawdown [%]']:>9.1f} %")
print(f"  Nombre de trades    : {stats['Total Trades']:>10}")
print(f"  Trades gagnants     : {stats['Win Rate [%]']:>9.1f} %")
print("══════════════════════════════════════════")

# ── 7. Graphique interactif ────────────────────────────────────
print("\nOuverture du graphique...")
portfolio.plot().show()