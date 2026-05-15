"""
Récupération de données historiques avec Twelve Data
Exemple : 3 dernières années d'une action au format journalier
"""

import os

import requests
import json
from datetime import datetime, timedelta

# ── Configuration ──────────────────────────────────────────────

API_KEY = os.getenv("TWELVE_DATA_API_KEY")  # https://twelvedata.com → s'inscrire gratuitement
SYMBOL  = "AAPL"            # Symbole de l'action (ex : AAPL, MSFT, LVMH.PA)
INTERVAL = "15min"           # Intervalles dispo : 1min, 5min, 15min, 1h, 1day, 1week, 1month

# Calcul automatique des dates (3 dernières années)
end_date   = datetime.today().strftime("%Y-%m-%d")
start_date = (datetime.today() - timedelta(days=3*365)).strftime("%Y-%m-%d")

# ── Appel API ──────────────────────────────────────────────────
url = "https://api.twelvedata.com/time_series"

params = {
    "symbol":     SYMBOL,
    "interval":   INTERVAL,
    "start_date": start_date,
    "end_date":   end_date,
    "apikey":     API_KEY,
    "outputsize": 5000,      # Nombre max de bougies retournées
    "format":     "JSON",
}

print(f"Récupération des données pour {SYMBOL} du {start_date} au {end_date}...")

response = requests.get(url, params=params)
data = response.json()

# ── Vérification de la réponse ─────────────────────────────────
if data.get("status") == "error":
    print(f"Erreur API : {data.get('message')}")
    exit(1)

valeurs = data.get("values", [])
meta    = data.get("meta", {})

print(f"\n✓ {len(valeurs)} bougies récupérées")
print(f"  Symbole   : {meta.get('symbol')}")
print(f"  Exchange  : {meta.get('exchange')}")
print(f"  Devise    : {meta.get('currency')}")
print(f"  Intervalle: {meta.get('interval')}")
print(f"  Période   : {valeurs[-1]['datetime']} → {valeurs[0]['datetime']}")

# ── Affichage des 5 premières lignes ──────────────────────────
print("\n── Aperçu des données (5 derniers jours) ──")
print(f"{'Date':<12} {'Ouverture':>10} {'Haut':>10} {'Bas':>10} {'Clôture':>10} {'Volume':>14}")
print("─" * 68)
for row in valeurs[:5]:
    print(
        f"{row['datetime']:<12} "
        f"{float(row['open']):>10.2f} "
        f"{float(row['high']):>10.2f} "
        f"{float(row['low']):>10.2f} "
        f"{float(row['close']):>10.2f} "
        f"{int(row['volume']):>14,}"
    )

# ── Export CSV ─────────────────────────────────────────────────
import csv

nom_fichier = f"{SYMBOL}_{start_date}_{end_date}.csv"

with open(nom_fichier, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["datetime", "open", "high", "low", "close", "volume"])
    writer.writeheader()
    writer.writerows(reversed(valeurs))  # Ordre chronologique

print(f"\n✓ Données exportées dans : {nom_fichier}")

# ── Calculs simples ────────────────────────────────────────────
closes = [float(row["close"]) for row in valeurs]

print(f"\n── Statistiques sur {len(closes)} jours ──")
print(f"  Prix actuel  : {closes[0]:.2f}")
print(f"  Plus haut    : {max(closes):.2f}")
print(f"  Plus bas     : {min(closes):.2f}")
variation = ((closes[0] - closes[-1]) / closes[-1]) * 100
print(f"  Performance  : {variation:+.1f}% sur la période")