"""
Récupération de 3 ans de données en 5min avec Twelve Data
Stratégie : découpage en chunks de ~5000 bougies, puis concaténation en un seul CSV
"""

import os
import requests
import csv
import time
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

API_KEY            = os.getenv("TWELVE_DATA_API_KEY")
INTERVAL           = "5min"
BOUGIES_PAR_CHUNK  = 5000
MINUTES_PAR_BOUGIE = 5
PAUSE_ENTRE_APPELS = 15


def recuperer_historique(symbol: str):
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    dossier_chunks = data_dir / f"chunks_{symbol}"
    fichier_final  = data_dir / f"{symbol}_5min_3ans.csv"

    end_date   = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=3 * 365)

    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  {symbol} — {INTERVAL} — {start_date.date()} → {end_date.date()}")
    print(f"  Mode chunk par outputsize = {BOUGIES_PAR_CHUNK}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    dossier_chunks.mkdir(exist_ok=True)

    fichiers_chunks = []
    cursor = end_date
    i = 1

    while cursor > start_date:
        nom_chunk = dossier_chunks / f"chunk_{i:03d}.csv"

        if nom_chunk.exists():
            print(f"  [{i}] chunk déjà présent, ignoré — fin {cursor.strftime('%Y-%m-%d %H:%M:%S')}")
            fichiers_chunks.append(nom_chunk)
            i += 1
            continue

        print(f"  [{i}] jusqu'à {cursor.strftime('%Y-%m-%d %H:%M:%S')}...", end=" ", flush=True)

        response = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol":     symbol,
            "interval":   INTERVAL,
            "end_date":   cursor.strftime("%Y-%m-%d %H:%M:%S"),
            "apikey":     API_KEY,
            "outputsize": BOUGIES_PAR_CHUNK,
            "format":     "JSON",
        })

        data = response.json()

        if data.get("status") == "error":
            print(f"\n  ✗ Erreur API : {data.get('message')}")
            raise RuntimeError(data.get("message"))

        valeurs = data.get("values", [])

        if not valeurs:
            print("aucune donnée (période hors marché ?), ignorée")
            cursor -= timedelta(minutes=MINUTES_PAR_BOUGIE)
            i += 1
            continue

        with open(nom_chunk, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["datetime", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerows(reversed(valeurs))

        fichiers_chunks.append(nom_chunk)
        print(f"✓ {len(valeurs)} bougies")

        plus_ancien = datetime.strptime(valeurs[-1]["datetime"], "%Y-%m-%d %H:%M:%S")
        cursor = plus_ancien - timedelta(minutes=MINUTES_PAR_BOUGIE)
        i += 1

        time.sleep(PAUSE_ENTRE_APPELS)

    print(f"\nConcaténation de {len(fichiers_chunks)} fichiers...")

    dfs = [pd.read_csv(f, parse_dates=["datetime"]) for f in fichiers_chunks]
    df_final = pd.concat(dfs, ignore_index=True)
    df_final = df_final.drop_duplicates(subset="datetime")
    df_final = df_final.sort_values("datetime").reset_index(drop=True)
    df_final.to_csv(fichier_final, index=False)

    print(f"✓ {len(df_final):,} bougies au total")
    print(f"  Période réelle : {df_final['datetime'].iloc[0]} → {df_final['datetime'].iloc[-1]}")
    print(f"  Fichier final  : {fichier_final}")

    for f in fichiers_chunks:
        f.unlink()
    dossier_chunks.rmdir()
    print("✓ Terminé.")


if __name__ == "__main__":
    recuperer_historique("AAPL")