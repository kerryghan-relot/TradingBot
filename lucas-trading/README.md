# lucas-trading

Projet unifié : recherche, backtesting et exécution live partagent le
même moteur de signaux. Une stratégie s'écrit **une seule fois** et
tourne à l'identique en backtest et en live.

## Structure

```
lucas-trading/
├── strategies/        # une stratégie = un fichier (config du moteur de vote)
├── core/              # code partagé : signaux, moteur, broker, config, métriques
├── backtest/          # moteur événementiel + scripts vectorbt (recherche rapide)
├── live/              # bot Alpaca, scorer hebdo, dashboard temps réel
├── tools/             # téléchargement d'historique, données factices
├── config/            # config.json (runtime, gitignoré) + exemple versionné
├── data/              # CSV 5-min 3 ans par symbole (gitignoré)
├── results/           # sorties de backtests (gitignoré)
├── deploy/            # systemd + nginx + scripts VPS et Windows
├── docs/              # guide des signaux et méthodes
├── archive/           # fichiers retirés, gardés pour vérification
├── backtest.py        # CLI backtest
└── live.py            # CLI live
```

Toutes les commandes se lancent **depuis `lucas-trading/`** avec le
venv du repo activé (`..\.venv\Scripts\activate.ps1`).

## Workflow : créer → backtester → passer live

### 1. Créer une stratégie

Copier [strategies/vote_mr.py](strategies/vote_mr.py) sous un nouveau
nom (ex. `strategies/ma_strat.py`) et surcharger les clés voulues :

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

Les signaux disponibles (BB, OU, VWAP, VolSpike, KalmanZ, RSI,
EMA_Cross, MACD_Zero, Zscore, ORB, TimeFilter) et leurs paramètres
sont documentés dans `core/config.py` et `docs/`. Un nouveau *type*
de signal s'ajoute dans `core/signals.py` + `core/engine.py`.

### 2. Backtester

```bash
python backtest.py ma_strat                     # tous les CSV de data/
python backtest.py ma_strat --symbols AAPL NVDA # sous-ensemble
```

Le backtest événementiel rejoue l'historique bar par bar via
`core/engine.py` — le code exact du bot live — et écrit
`results/event_ma_strat.csv` (Sharpe, return, drawdown, trades par
symbole). S'il manque des données : `python -m tools.download_history`
(clé `TWELVE_DATA_API_KEY` dans `.env`).

Pour l'exploration rapide (grilles de paramètres, portefeuilles
top-X), les scripts vectorisés restent disponibles :

```bash
python -m backtest.vectorized.backtest_multi
python -m backtest.vectorized.optimize
streamlit run backtest/dashboard.py     # visualisation des résultats
```

Ils vectorisent les maths des signaux pour la vitesse ; la validation
finale passe toujours par `backtest.py` (zéro divergence possible).

### 3. Passer en live

```bash
python live.py ma_strat
```

- `config/config.json` absent → créé depuis la stratégie ;
- présent → les divergences stratégie/config sont affichées (le
  fichier fait foi : le bot le hot-reload, le scorer y écrit les
  symboles chaque semaine).

Clés Alpaca dans `.env` à la racine du repo (`ALPACA_API_KEY`,
`ALPACA_SECRET_KEY`). Le bot est en paper trading (`PAPER = True`
dans `core/broker.py`).

Suivi : `streamlit run live/dashboard.py`, logs dans `bot.log`.

## Scorer hebdomadaire

```bash
python -m live.scorer --dry-run   # aperçu du classement
python -m live.scorer             # écrit le top-X dans config.json
```

Planification : tâche Windows via
`deploy/scripts/run_scorer.ps1` (instructions en tête de fichier),
cron VPS via `deploy/scripts/run_scorer.sh`.

## Déploiement VPS

`sudo lucas-trading/deploy/scripts/setup_vps.sh` depuis la racine du
repo — voir [deploy/README.md](deploy/README.md).
