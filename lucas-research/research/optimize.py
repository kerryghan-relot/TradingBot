"""
Optimisation des hyperparamètres – BB, EMA_Cross, MACD_Zero, Zscore
====================================================================
Teste toutes les combinaisons de paramètres pour les 4 signaux actifs,
sur tous les CSV disponibles.

Sortie : hyperparams_resultats.csv  (trié par Alpha vs B&H moyen)
         hyperparams_top.html       (top 50 lisible)

Stratégie d'optimisation
-------------------------
- Grid search exhaustif sur chaque signal individuellement
- Puis les meilleures configs de chaque signal sont combinées par vote
- Écriture incrémentale CSV pour éviter le crash RAM
- gc.collect() après chaque portfolio
"""

import gc
import time
import itertools
import numpy as np
import pandas as pd
from pathlib import Path
import vectorbt as vbt

# ── Chemins ────────────────────────────────────────────────────
DATA_DIR   = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "resultats"
OUTPUT_DIR.mkdir(exist_ok=True)

CSV_OUT  = OUTPUT_DIR / "hyperparams_resultats.csv"
HTML_OUT = OUTPUT_DIR / "hyperparams_top.html"

CAPITAL_INITIAL = 10_000
FEES            = 0.0005

# ══════════════════════════════════════════════════════════════
# GRILLES DE PARAMÈTRES À TESTER
# ══════════════════════════════════════════════════════════════

# — Bollinger Bands ————————————————————————————————————————————
BB_PERIODS = [100, 200, 300, 500, 750]   # fenêtre
BB_STDS    = [1.5, 2.0, 2.5, 3.0]       # écart-type

# — EMA Crossover ——————————————————————————————————————————————
EMA_FASTS  = [20, 50, 100]              # EMA rapide
EMA_SLOWS  = [100, 200, 500]            # EMA lente

# — MACD Zero-cross ————————————————————————————————————————————
MACD_FASTS  = [12, 20, 26]             # fenêtre rapide
MACD_SLOWS  = [26, 52, 78]             # fenêtre lente
MACD_SIGS   = [9, 14, 18]             # signal

# — Z-score ————————————————————————————————————————————————————
ZSCORE_WINS = [195, 390, 585]          # fenêtre (~0.5 / 1 / 1.5 semaines)
ZSCORE_THS  = [1.5, 2.0, 2.5, 3.0]   # seuil d'entrée


# ══════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════

def _disc(s: pd.Series) -> pd.Series:
    s = s.fillna(False)
    return s & ~s.shift(1).fillna(False)

def _run_pf(close, entries, exits):
    """Lance un portfolio et retourne les stats clés. Lève si 0 trades."""
    pf    = vbt.Portfolio.from_signals(
        close, entries=entries, exits=exits,
        init_cash=CAPITAL_INITIAL, fees=FEES, freq="5min",
    )
    stats = pf.stats()
    result = {
        "perf":   round(float(stats["Total Return [%]"]),  2),
        "sharpe": round(float(stats["Sharpe Ratio"]),       3),
        "dd":     round(float(stats["Max Drawdown [%]"]),   2),
        "trades": int(stats["Total Trades"]),
        "wr":     round(float(stats["Win Rate [%]"]),       1),
    }
    del pf
    gc.collect()
    return result


# ══════════════════════════════════════════════════════════════
# GÉNÉRATEURS DE SIGNAUX PARAMÉTRÉS
# ══════════════════════════════════════════════════════════════

def sig_bb(close, period, std):
    bb = vbt.BBANDS.run(close, window=period, alpha=std)
    return _disc(close < bb.lower), _disc(close > bb.upper)

def sig_ema_cross(close, fast, slow):
    if fast >= slow:
        return None, None
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    e  = ef > es
    x  = ef < es
    return _disc(e), _disc(x)

def sig_macd_zero(close, fast, slow, sig):
    if fast >= slow:
        return None, None
    macd = vbt.MACD.run(close, fast_window=fast,
                        slow_window=slow, signal_window=sig).macd
    return _disc(macd > 0), _disc(macd < 0)

def sig_zscore(close, window, threshold):
    mu    = close.rolling(window).mean()
    sigma = close.rolling(window).std()
    z     = (close - mu) / sigma.replace(0, np.nan)
    return _disc(z < -threshold), _disc(z > threshold)


# ══════════════════════════════════════════════════════════════
# CHARGEMENT DES CSV
# ══════════════════════════════════════════════════════════════

csv_files = sorted(DATA_DIR.glob("*_5min_3ans.csv"))
if not csv_files:
    print(f"Aucun CSV trouvé dans {DATA_DIR}")
    exit(1)

# Pré-calcul B&H par symbole
closes = {}
bh_perfs = {}
for f in csv_files:
    sym = f.stem.replace("_5min_3ans", "").replace("-", "/")
    df  = pd.read_csv(f, parse_dates=["datetime"])
    df  = df.set_index("datetime").sort_index()
    c   = df["close"].astype(float)
    closes[sym]   = c
    bh_perfs[sym] = ((c.iloc[-1] - c.iloc[0]) / c.iloc[0]) * 100

symboles = list(closes.keys())

# ══════════════════════════════════════════════════════════════
# GRILLES DE COMBINAISONS
# ══════════════════════════════════════════════════════════════

grid_bb   = list(itertools.product(BB_PERIODS, BB_STDS))
grid_ema  = [(f,s) for f,s in itertools.product(EMA_FASTS, EMA_SLOWS) if f < s]
grid_macd = [(f,s,sg) for f,s,sg in itertools.product(MACD_FASTS, MACD_SLOWS, MACD_SIGS) if f < s]
grid_z    = list(itertools.product(ZSCORE_WINS, ZSCORE_THS))

configs = (
    [("BB",        p, {"period": p[0], "std":   p[1]}) for p in grid_bb]  +
    [("EMA_Cross", p, {"fast":   p[0], "slow":  p[1]}) for p in grid_ema] +
    [("MACD_Zero", p, {"fast":   p[0], "slow":  p[1], "sig": p[2]}) for p in grid_macd] +
    [("Zscore",    p, {"window": p[0], "threshold": p[1]}) for p in grid_z]
)

nb_total = len(configs) * len(symboles)
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  {len(configs)} configs × {len(symboles)} symboles = {nb_total} backtests")
print(f"  BB:{len(grid_bb)}  EMA:{len(grid_ema)}  MACD:{len(grid_macd)}  Zscore:{len(grid_z)}")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

# ══════════════════════════════════════════════════════════════
# BOUCLE D'OPTIMISATION
# ══════════════════════════════════════════════════════════════

COLONNES = [
    "Signal", "Params", "Symbole",
    "Performance %", "Buy&Hold %", "Alpha vs B&H",
    "Sharpe", "Max Drawdown %", "Nb trades", "Win Rate %",
]
with open(CSV_OUT, "w", encoding="utf-8") as f:
    f.write(",".join(COLONNES) + "\n")

t0    = time.time()
n_ok  = 0
n_err = 0
n_done= 0

for signal_name, params_tuple, params_dict in configs:
    params_str = str(params_dict).replace(",", ";")

    for sym in symboles:
        close  = closes[sym]
        bh     = bh_perfs[sym]
        entries, exits = None, None

        try:
            if signal_name == "BB":
                entries, exits = sig_bb(close, **params_dict)
            elif signal_name == "EMA_Cross":
                entries, exits = sig_ema_cross(close, **params_dict)
            elif signal_name == "MACD_Zero":
                entries, exits = sig_macd_zero(close, **params_dict)
            elif signal_name == "Zscore":
                entries, exits = sig_zscore(close, **params_dict)

            if entries is None:
                n_err += 1
                continue

            res   = _run_pf(close, entries, exits)
            alpha = round(res["perf"] - bh, 2)

            ligne = (
                f'"{signal_name}","{params_str}","{sym}",'
                f'{res["perf"]},{round(bh,2)},{alpha},'
                f'{res["sharpe"]},{res["dd"]},{res["trades"]},{res["wr"]}\n'
            )
            with open(CSV_OUT, "a", encoding="utf-8") as f:
                f.write(ligne)
            n_ok += 1

        except Exception as e:
            n_err += 1

        finally:
            gc.collect()

        n_done += 1
        if n_done % 100 == 0:
            elapsed = time.time() - t0
            reste   = (elapsed / n_done) * (nb_total - n_done)
            print(f"  {n_done}/{nb_total} — {reste/60:.1f} min restantes "
                  f"| ok:{n_ok} err:{n_err}")

# ══════════════════════════════════════════════════════════════
# ANALYSE : meilleurs paramètres par signal
# ══════════════════════════════════════════════════════════════

df = pd.read_csv(CSV_OUT)
df = df.sort_values("Alpha vs B&H", ascending=False)
df.to_csv(CSV_OUT, index=False)

print(f"\n━━ Meilleurs paramètres par signal (alpha moyen sur tous symboles) ━━")
for sig in ["BB", "EMA_Cross", "MACD_Zero", "Zscore"]:
    sub = df[df["Signal"] == sig].groupby("Params")["Alpha vs B&H"].mean()
    if sub.empty:
        continue
    best_p = sub.idxmax()
    best_v = sub.max()
    print(f"  {sig:<12} → {best_p}  (alpha moy: {best_v:+.2f}%)")

# ══════════════════════════════════════════════════════════════
# RAPPORT HTML – top 50
# ══════════════════════════════════════════════════════════════

top = df.head(50)
rows = ""
for _, r in top.iterrows():
    c = "#1a6e1a" if r["Alpha vs B&H"] >= 0 else "#8b1a1a"
    rows += (
        f"<tr><td>{r['Signal']}</td><td><code>{r['Params']}</code></td>"
        f"<td>{r['Symbole']}</td>"
        f"<td>{r['Performance %']:+.2f}%</td>"
        f"<td>{r['Buy&Hold %']:+.2f}%</td>"
        f"<td style='color:{c};font-weight:600'>{r['Alpha vs B&H']:+.2f}%</td>"
        f"<td>{r['Sharpe']:.3f}</td>"
        f"<td>{r['Max Drawdown %']:.2f}%</td>"
        f"<td>{int(r['Nb trades'])}</td>"
        f"<td>{r['Win Rate %']:.1f}%</td></tr>\n"
    )

html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Hyperparamètres – Top 50</title>
<style>
  body{{font-family:sans-serif;margin:2rem;color:#111}}
  h1{{font-size:1.4rem;border-bottom:2px solid #333;padding-bottom:.4rem}}
  table{{border-collapse:collapse;width:100%;font-size:.82rem}}
  th{{background:#222;color:#fff;padding:.5rem .7rem;text-align:left}}
  td{{padding:.35rem .7rem;border-bottom:1px solid #ddd}}
  tr:hover td{{background:#f5f7ff}}
  code{{font-size:.78rem;background:#f0f0f0;padding:.1rem .3rem;border-radius:3px}}
</style></head><body>
<h1>Optimisation hyperparamètres – Top 50 par Alpha vs B&H</h1>
<table><thead><tr>
  <th>Signal</th><th>Paramètres</th><th>Symbole</th>
  <th>Perf%</th><th>B&H%</th><th>Alpha</th>
  <th>Sharpe</th><th>Max DD%</th><th>Trades</th><th>Win Rate</th>
</tr></thead><tbody>
{rows}
</tbody></table></body></html>"""

with open(HTML_OUT, "w", encoding="utf-8") as f:
    f.write(html)

elapsed = time.time() - t0
print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  ✓ {n_ok} backtests réussis / {n_err} erreurs")
print(f"  ✓ Durée : {elapsed/60:.1f} min")
print(f"  ✓ CSV   : {CSV_OUT}")
print(f"  ✓ HTML  : {HTML_OUT}")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")