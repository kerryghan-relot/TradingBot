# src — code du bot

Projet unifié : recherche, backtesting et exécution live partagent le même moteur de signaux. Une stratégie s'écrit **une seule fois** et tourne à l'identique en backtest et en live.

Ce fichier décrit le **workflow** (créer → backtester → passer live). Pour la vue d'ensemble, la stack technique et l'architecture, voir le [README racine](../README.md) ; pour l'exploitation, voir [deploy/README.md](deploy/README.md).

## Structure

```
src/
├── strategies/        # une stratégie = un fichier (config du moteur de vote)
├── core/              # code partagé : signaux, moteur, broker, config, métriques
├── backtest/          # moteur événementiel + scripts vectorbt (recherche rapide)
├── live/              # bot Alpaca, scorer hebdo
├── web/               # dashboard temps réel (API Flask + front React)
├── tools/             # téléchargement d'historique, données factices
├── config/            # config.json (runtime, gitignoré) + exemple versionné
├── data/              # CSV 5-min 3 ans par symbole (gitignoré)
├── results/           # sorties de backtests (gitignoré)
├── deploy/            # Docker Compose : nginx + scheduler + setup VPS
├── docs/              # guide des signaux et méthodes
├── archive/           # fichiers retirés, gardés pour vérification
├── backtest.py        # CLI backtest
└── live.py            # CLI live
```

Toutes les commandes se lancent **depuis `src/`** avec le venv du repo activé (`..\.venv\Scripts\activate.ps1`).

## Workflow : créer → backtester → passer live

### 1. Créer une stratégie

Copier [strategies/vote_mr.py](strategies/vote_mr.py) sous un nouveau nom (ex. `strategies/ma_strat.py`) et surcharger les clés voulues :

```python
from core.config import DEFAULT_CONFIG
from strategies import Strategy

STRATEGY = Strategy(
    name="ma_strat",
    description="BB + OU seulement, seuil 2 votes",
    config={
        **DEFAULT_CONFIG,
        "active_signals": ["BB", "OU"],
        "vote_threshold": 2,
    },
)
```

Les signaux disponibles (BB, OU, VWAP, VolSpike, KalmanZ, RSI, EMA_Cross, MACD_Zero, Zscore, ORB, TimeFilter) et leurs paramètres sont documentés dans `core/config.py` et `docs/`. Un nouveau *type* de signal s'ajoute dans `core/signals.py` + `core/engine.py`.

### 2. Backtester

```bash
python backtest.py ma_strat                     # tous les CSV de data/
python backtest.py ma_strat --symbols AAPL NVDA # sous-ensemble
```

Le backtest événementiel rejoue l'historique bar par bar via `core/engine.py` — le code exact du bot live — et écrit `results/event_ma_strat.csv` (Sharpe, return, drawdown, trades par symbole). S'il manque des données : `python -m tools.download_history` (clé `TWELVE_DATA_API_KEY` dans `.env`).

Pour l'exploration rapide (grilles de paramètres, portefeuilles top-X), les scripts vectorisés restent disponibles :

```bash
python -m backtest.vectorized.backtest_multi
python -m backtest.vectorized.optimize
streamlit run backtest/dashboard.py     # visualisation des résultats
```

Ils vectorisent les maths des signaux pour la vitesse ; la validation finale passe toujours par `backtest.py` (zéro divergence possible).

### 3. Passer en live

```bash
python live.py ma_strat
```

- `config/config.json` absent → créé depuis la stratégie ;
- présent → les divergences stratégie/config sont affichées (le fichier fait foi : le bot le hot-reload, le scorer y écrit les symboles chaque semaine).

Clés Alpaca dans `.env` à la racine du repo (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`). Le bot est en paper trading (`PAPER = True` dans `core/broker.py`).

Suivi : dashboard web temps réel, logs dans `bot.log`.

### Dashboard web (live/monitoring)

Nouveau front (remplace l'ancien dashboard Streamlit) : API JSON Flask
+ interface React reprenant le design AlgoDesk. Il lit la base PostgreSQL + le compte Alpaca et bascule automatiquement en mode démonstration (données fictives) tant qu'aucune source réelle n'est disponible.

```bash
# 1. Builder le front une fois (ou après modif du front)
cd web/frontend && npm install && npm run build && cd ../..

# 2. Lancer le serveur (sert le front + l'API sur le même port)
python -m web.run                 # http://127.0.0.1:8501

# Développement du front avec hot-reload (proxy /api vers Flask) :
#   terminal A : python -m web.run
#   terminal B : cd web/frontend && npm run dev   # http://127.0.0.1:5173
```

L'onglet **Configuration** édite `config/config.json` (signaux, seuils, sizing, symboles) directement depuis le navigateur — le bot recharge à chaud.

## Scorer hebdomadaire

```bash
python -m live.scorer --dry-run   # aperçu du classement
python -m live.scorer             # écrit le top-X dans config.json
```

Planification : le service `scheduler` (ofelia) du stack Docker lance le scorer chaque dimanche 18h — voir [deploy/README.md](deploy/README.md).

## Déploiement (Docker Compose)

Tout le stack (PostgreSQL, bot, dashboard, nginx, scheduler) est conteneurisé. Démarrage rapide depuis la racine du repo :

```bash
cp .env.example .env                          # clés Alpaca + mots de passe
bash src/deploy/docker/init_secrets.sh   # certs + basic auth
docker compose up -d --build
```

Sur un VPS neuf : `sudo bash src/deploy/scripts/setup_vps.sh` (installe Docker puis démarre tout) — voir [deploy/README.md](deploy/README.md).
