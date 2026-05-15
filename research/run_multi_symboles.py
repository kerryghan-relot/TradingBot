"""
Lance la récupération Twelve Data pour une liste d'actions.
Prérequis : twelve_data_5min_3ans.py dans le même dossier.
"""

from datetime import datetime
from twelve_data_5min_3ans import recuperer_historique

# ── Liste des symboles à télécharger ──────────────────────────
SYMBOLES = [
    "AAPL",
    "MSFT",
    "NVDA",
    #"GOOGL",
    #"AMZN",
    # Ajoute autant de symboles que tu veux
]

# ── Boucle principale ──────────────────────────────────────────
succes = []
echecs = []
debut_global = datetime.now()

print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  {len(SYMBOLES)} actions à télécharger")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

for idx, symbol in enumerate(SYMBOLES, 1):
    print(f"\n[{idx}/{len(SYMBOLES)}] Démarrage de {symbol}...")
    try:
        recuperer_historique(symbol)
        succes.append(symbol)
    except Exception as e:
        print(f"  ✗ {symbol} a échoué : {e}")
        echecs.append(symbol)

# ── Résumé ─────────────────────────────────────────────────────
duree = datetime.now() - debut_global
print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  Terminé en {str(duree).split('.')[0]}")
print(f"  ✓ Succès : {len(succes)} — {', '.join(succes)}")
if echecs:
    print(f"  ✗ Échecs : {len(echecs)} — {', '.join(echecs)}")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")