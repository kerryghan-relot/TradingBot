"""
Backtest multi-stratégies / multi-actions avec vectorbt
Stratégies : RSI, SMA croisement, Bollinger Bands
Source      : fichiers CSV du dossier ../data/
Sorties     : resultats_backtest.csv + graphiques HTML par action
Inclut : benchmark Buy & Hold pour chaque action
"""

import os
import pandas as pd
import numpy as np
from pathlib import Path
import vectorbt as vbt

from strategies_ML import STRATEGIES

# ── Configuration ──────────────────────────────────────────────
DATA_DIR    = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR  = Path(__file__).resolve().parent.parent / "resultats"
OUTPUT_DIR.mkdir(exist_ok=True)

CAPITAL_INITIAL = 10_000
FEES            = 0.0005  # 0.05% par trade (réaliste sur 5min)

# ── Boucle principale ──────────────────────────────────────────

csv_files = sorted(DATA_DIR.glob("*_5min_3ans.csv"))

if not csv_files:
    print(f"Aucun fichier CSV trouvé dans {DATA_DIR}")
    exit(1)

print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  {len(csv_files)} actions × {len(STRATEGIES)} stratégies")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

toutes_lignes = []

for csv_file in csv_files:
    symbol = csv_file.stem.replace("_5min_3ans", "").replace("-", "/")
    print(f"\n▶ {symbol}")

    df = pd.read_csv(csv_file, parse_dates=["datetime"])
    df = df.set_index("datetime").sort_index()
    df["close"] = df["close"].astype(float)
    close = df["close"]

    # ── Buy & Hold ─────────────────────────────────────────────
    prix_debut   = close.iloc[0]
    prix_fin     = close.iloc[-1]
    bh_perf      = ((prix_fin - prix_debut) / prix_debut) * 100
    bh_capital   = CAPITAL_INITIAL * (1 + (prix_fin - prix_debut) / prix_debut)

    print(f"  {'Buy & Hold':<12} {bh_perf:>+7.1f}%   (référence)")

    figures = {}

    for nom_strat, fn_strat in STRATEGIES.items():
        try:
            entrees, sorties = fn_strat(close)

            pf = vbt.Portfolio.from_signals(
                close,
                entries=entrees,
                exits=sorties,
                init_cash=CAPITAL_INITIAL,
                fees=FEES,
                freq="5min",
            )

            stats = pf.stats()
            perf  = round(stats["Total Return [%]"], 2)
            vs_bh = perf - bh_perf  # Différence vs Buy & Hold

            ligne = {
                "Symbole":           symbol,
                "Stratégie":         nom_strat,
                "Capital final":     round(stats["End Value"], 2),
                "Performance %":     perf,
                "Buy&Hold %":        round(bh_perf, 2),
                "Alpha vs B&H":      round(vs_bh, 2),  # positif = meilleur que B&H
                "Sharpe":            round(stats["Sharpe Ratio"], 3),
                "Max Drawdown %":    round(stats["Max Drawdown [%]"], 2),
                "Nb trades":         int(stats["Total Trades"]),
                "Win Rate %":        round(stats["Win Rate [%]"], 1),
            }
            toutes_lignes.append(ligne)

            signe_alpha = "✓" if vs_bh >= 0 else "✗"
            print(f"  {nom_strat:<12} {perf:>+7.1f}%   vs B&H {vs_bh:>+6.1f}%  {signe_alpha}   Sharpe {ligne['Sharpe']:>6.2f}   Trades {ligne['Nb trades']:>4}")

            figures[nom_strat] = pf.plot()

        except Exception as e:
            print(f"  {nom_strat:<12} ✗ erreur : {e}")

    # ── Graphique HTML par action ───────────────────────────────
    if figures:
        safe_symbol = symbol.replace("/", "-")
        html_path = OUTPUT_DIR / f"{safe_symbol}_backtest.html"

        html_parts = [f"<html><head><meta charset='utf-8'><title>Backtest {symbol}</title>"]
        html_parts.append("<style>body{font-family:sans-serif;margin:2rem} h2{border-bottom:2px solid #333} .bh{background:#f0f4ff;padding:.5rem 1rem;border-radius:6px;display:inline-block;margin-bottom:1rem}</style>")
        html_parts.append("</head><body>")
        html_parts.append(f"<h2>{symbol} — Backtest multi-stratégies</h2>")
        html_parts.append(f"<div class='bh'>📈 Buy &amp; Hold sur la période : <strong>{bh_perf:+.1f}%</strong> → {bh_capital:,.0f} $</div>")

        for nom_strat, fig in figures.items():
            ligne_strat = next(l for l in toutes_lignes if l["Symbole"] == symbol and l["Stratégie"] == nom_strat)
            alpha = ligne_strat["Alpha vs B&H"]
            couleur = "#2a7a2a" if alpha >= 0 else "#a02020"
            html_parts.append(f"<h3>{nom_strat} — {ligne_strat['Performance %']:+.1f}% <span style='color:{couleur};font-size:.85em'>({alpha:+.1f}% vs B&H)</span></h3>")
            html_parts.append(fig.to_html(full_html=False, include_plotlyjs="cdn"))

        html_parts.append("</body></html>")

        with open(html_path, "w", encoding="utf-8") as f:
            f.write("\n".join(html_parts))

        print(f"  → graphique : {html_path.name}")


# ── Export CSV récapitulatif ───────────────────────────────────
df_resultats = pd.DataFrame(toutes_lignes)
df_resultats = df_resultats.sort_values(["Alpha vs B&H"], ascending=False)

csv_out = OUTPUT_DIR / "resultats_backtest.csv"
df_resultats.to_csv(csv_out, index=False)

print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  ✓ CSV récapitulatif : {csv_out}")
print(f"  ✓ Graphiques HTML   : {OUTPUT_DIR}/")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# ── Aperçu : top 10 stratégies qui battent le Buy & Hold ──────
print("\n── Top 10 : meilleur alpha vs Buy & Hold ──")
print(df_resultats.nlargest(10, "Alpha vs B&H")[
    ["Symbole", "Stratégie", "Performance %", "Buy&Hold %", "Alpha vs B&H", "Sharpe"]
].to_string(index=False))