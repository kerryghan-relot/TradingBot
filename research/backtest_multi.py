"""
Backtest multi-stratégies / multi-actions avec vectorbt
Optimisé pour un grand nombre de stratégies (pas de crash RAM)

Optimisations :
  - Aucun graphique Plotly généré (source principale du crash)
  - Libération mémoire explicite après chaque portfolio
  - Sauvegarde CSV incrémentale (pas tout en mémoire)
  - Barre de progression + estimation du temps restant
  - Rapport HTML final léger (tableau, pas de graphiques)
"""

import gc
import os
import time
import pandas as pd
import numpy as np
from pathlib import Path
import vectorbt as vbt

from strategies import STRATEGIES

# ── Configuration ──────────────────────────────────────────────
DATA_DIR        = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR      = Path(__file__).resolve().parent.parent / "resultats"
OUTPUT_DIR.mkdir(exist_ok=True)

CAPITAL_INITIAL = 10_000
FEES            = 0.0005   # 0.05% par trade

CSV_OUT         = OUTPUT_DIR / "resultats_backtest.csv"
HTML_OUT        = OUTPUT_DIR / "resultats_backtest.html"

# ── Chargement des fichiers ────────────────────────────────────
csv_files = sorted(DATA_DIR.glob("*_5min_3ans.csv"))

if not csv_files:
    print(f"Aucun fichier CSV trouvé dans {DATA_DIR}")
    exit(1)

nb_actions  = len(csv_files)
nb_strats   = len(STRATEGIES)
nb_total    = nb_actions * nb_strats

print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  {nb_actions} actions × {nb_strats} stratégies = {nb_total} backtests")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

# ── CSV incrémental : écriture ligne par ligne ─────────────────
COLONNES = [
    "Symbole", "Stratégie", "Capital final", "Performance %",
    "Buy&Hold %", "Alpha vs B&H", "Sharpe", "Max Drawdown %",
    "Nb trades", "Win Rate %",
]

# Initialise le CSV avec l'en-tête
with open(CSV_OUT, "w", encoding="utf-8") as f:
    f.write(",".join(COLONNES) + "\n")

# ── Boucle principale ──────────────────────────────────────────
t_global   = time.time()
n_done     = 0
n_ok       = 0
n_err      = 0

for csv_file in csv_files:
    symbol = csv_file.stem.replace("_5min_3ans", "").replace("-", "/")

    df = pd.read_csv(csv_file, parse_dates=["datetime"])
    df = df.set_index("datetime").sort_index()
    df["close"] = df["close"].astype(float)
    close = df["close"]

    # Buy & Hold
    bh_perf = ((close.iloc[-1] - close.iloc[0]) / close.iloc[0]) * 100

    print(f"\n▶ {symbol}  (B&H : {bh_perf:+.1f}%)")
    print(f"  {'Stratégie':<35} {'Perf':>7}  {'Alpha':>7}  {'Sharpe':>7}  {'Trades':>6}")
    print(f"  {'-'*35} {'-'*7}  {'-'*7}  {'-'*7}  {'-'*6}")

    t_action = time.time()

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

            stats  = pf.stats()
            perf   = round(float(stats["Total Return [%]"]),  2)
            sharpe = round(float(stats["Sharpe Ratio"]),       3)
            dd     = round(float(stats["Max Drawdown [%]"]),   2)
            trades = int(stats["Total Trades"])
            wr     = round(float(stats["Win Rate [%]"]),       1)
            alpha  = round(perf - bh_perf,                     2)

            # Écriture immédiate dans le CSV (pas de liste en mémoire)
            ligne_csv = (
                f'"{symbol}","{nom_strat}",'
                f"{round(CAPITAL_INITIAL * (1 + perf/100), 2)},"
                f"{perf},{round(bh_perf,2)},{alpha},"
                f"{sharpe},{dd},{trades},{wr}\n"
            )
            with open(CSV_OUT, "a", encoding="utf-8") as f:
                f.write(ligne_csv)

            signe = "✓" if alpha >= 0 else "✗"
            print(f"  {nom_strat:<35} {perf:>+7.1f}%  {alpha:>+7.1f}%  {sharpe:>7.3f}  {trades:>6}  {signe}")

            n_ok += 1

        except Exception as e:
            print(f"  {nom_strat:<35} ✗ {e}")
            n_err += 1

        finally:
            # Libération mémoire critique
            try:
                del pf
            except Exception:
                pass
            gc.collect()

        n_done += 1

        # Estimation temps restant toutes les 50 itérations
        if n_done % 50 == 0:
            elapsed  = time.time() - t_global
            restant  = (elapsed / n_done) * (nb_total - n_done)
            print(f"\n  ⏱  {n_done}/{nb_total} — "
                  f"~{restant/60:.1f} min restantes\n")

    print(f"  → {symbol} terminé en {time.time()-t_action:.1f}s")
    del close, df
    gc.collect()

# ── Lecture du CSV final et tri ────────────────────────────────
df_res = pd.read_csv(CSV_OUT)
df_res = df_res.sort_values("Alpha vs B&H", ascending=False)
df_res.to_csv(CSV_OUT, index=False)

# ── Rapport HTML léger (tableau, sans graphique) ───────────────
top50 = df_res.head(50)

rows_html = ""
for _, r in top50.iterrows():
    alpha  = r["Alpha vs B&H"]
    couleur = "#1a6e1a" if alpha >= 0 else "#8b1a1a"
    rows_html += (
        f"<tr>"
        f"<td>{r['Symbole']}</td>"
        f"<td>{r['Stratégie']}</td>"
        f"<td>{r['Performance %']:+.2f}%</td>"
        f"<td>{r['Buy&Hold %']:+.2f}%</td>"
        f"<td style='color:{couleur};font-weight:600'>{alpha:+.2f}%</td>"
        f"<td>{r['Sharpe']:.3f}</td>"
        f"<td>{r['Max Drawdown %']:.2f}%</td>"
        f"<td>{int(r['Nb trades'])}</td>"
        f"<td>{r['Win Rate %']:.1f}%</td>"
        f"</tr>\n"
    )

html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Backtest – Top 50</title>
<style>
  body  {{ font-family: sans-serif; margin: 2rem; color: #111; }}
  h1    {{ font-size: 1.4rem; border-bottom: 2px solid #333; padding-bottom:.4rem }}
  .meta {{ background:#f0f4ff; padding:.6rem 1rem; border-radius:6px;
           display:inline-block; margin-bottom:1.5rem; font-size:.9rem }}
  table {{ border-collapse: collapse; width: 100%; font-size: .85rem; }}
  th    {{ background:#222; color:#fff; padding:.5rem .8rem; text-align:left; }}
  td    {{ padding:.4rem .8rem; border-bottom:1px solid #ddd; }}
  tr:hover td {{ background:#f5f7ff; }}
</style>
</head>
<body>
<h1>Backtest – Top 50 stratégies par Alpha vs Buy &amp; Hold</h1>
<div class="meta">
  {nb_actions} actions &nbsp;×&nbsp; {nb_strats} stratégies
  &nbsp;|&nbsp; {n_ok} backtests réussis, {n_err} erreurs
  &nbsp;|&nbsp; Capital initial : {CAPITAL_INITIAL:,} $
  &nbsp;|&nbsp; Frais : {FEES*100:.3f}% / trade
</div>
<table>
<thead>
  <tr>
    <th>Symbole</th><th>Stratégie</th>
    <th>Perf %</th><th>Buy&amp;Hold %</th><th>Alpha</th>
    <th>Sharpe</th><th>Max DD %</th><th>Trades</th><th>Win Rate</th>
  </tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""

with open(HTML_OUT, "w", encoding="utf-8") as f:
    f.write(html)

# ── Résumé final ───────────────────────────────────────────────
elapsed_total = time.time() - t_global
print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  ✓ {n_ok} backtests réussis / {n_err} erreurs")
print(f"  ✓ Durée totale : {elapsed_total/60:.1f} min")
print(f"  ✓ CSV complet  : {CSV_OUT}")
print(f"  ✓ HTML top 50  : {HTML_OUT}")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

print("\n── Top 10 alpha vs Buy & Hold ──")
print(df_res.nlargest(10, "Alpha vs B&H")[
    ["Symbole", "Stratégie", "Performance %", "Buy&Hold %", "Alpha vs B&H", "Sharpe"]
].to_string(index=False))