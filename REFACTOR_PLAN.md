# Plan de fusion `lucas-research` + `lucas-live-trading`

> **Document historique.** Il décrit la fusion telle qu'elle a été décidée et exécutée le 2026-07-06 et conserve les noms de l'époque. Le dossier `lucas-trading/` a depuis été renommé `src/` (convention classique) — voir le [README racine](README.md) pour l'état actuel.

Branche de travail : `refactor/fusion-research-live`. Statut : **exécuté** (plan validé par Lucas le 2026-07-06). Décisions retenues : dossier `lucas-trading/`, `strategies_ml.py` conservé dans `backtest/vectorized/`, dashboards non fusionnés. Voir `src/README.md` pour le résultat final.

---

## 1. Inventaire

### `lucas-live-trading/` (exécution réelle — 3 900 lignes)

| Fichier | Lignes | Statut | Rôle |
|---|---|---|---|
| `bot.py` | 1 485 | **utilisé** | Bot live : stream Alpaca, ordres, SQLite, stop-loss |
| `dashboard.py` | 857 | **utilisé** | Dashboard Streamlit temps réel (lit `bars.db`) |
| `scorer.py` | 655 | **utilisé** | Sélection hebdo top-X par Sharpe (réutilise `engine.py`) |
| `signals.py` | 505 | **utilisé** | 12 signaux stateful bar-par-bar — source de vérité |
| `engine.py` | 409 | **utilisé** | Moteur de vote partagé bot/scorer (`evaluate_bar`) |
| `seed_fake_data.py` | 369 | utilitaire | Données factices pour tester le dashboard |
| `constants.py` | 22 | **utilisé** | `SYMBOLS` + annualisation (`CRYPTO_SYMBOLS` = mort) |
| `deploy/` | — | **utilisé** | systemd + nginx + scripts VPS |
| `run_scorer.ps1` | — | **utilisé** | Lancement scorer sous Windows |
| `bars.db`, `*.log`, `config.json` | — | runtime | Non versionnés (gitignorés) |

### `lucas-research/research/` (backtesting — 6 700 lignes)

| Fichier | Lignes | Statut | Rôle |
|---|---|---|---|
| `dashboard.py` | 1 966 | **utilisé** | Dashboard Streamlit des résultats de backtests |
| `backtest_scorer_oos.py` | 675 | **utilisé** | Validation OOS de la sélection top-X du scorer |
| `backtest_topx_portfolio.py` | 542 | **utilisé** | Backtest portefeuille top-X hebdo |
| `strategies.py` | 532 | **utilisé** | 20 signaux vectorisés (vectorbt) + stratégie vote |
| `optimize_topx.py` | 490 | **utilisé** | Grid-search des hyperparamètres top-X |
| `backtest_v2_regime_mr.py` | 463 | **utilisé** | v2 : mean-reversion filtrée par régime (train/test) |
| `optimize.py` | 362 | **utilisé** | Grid-search hyperparamètres par stratégie |
| `backtest_multi.py` | 339 | **utilisé** | Backtest multi-actifs × multi-stratégies |
| `backtest_v2_topx.py` | 265 | **utilisé** | v2 : top-X sur la stratégie regime-MR |
| `strategies_ML.py` | 249 | conditionnel | XGBoost, chargé uniquement via `backtest_multi.py --ml` |
| `twelve_data_5min_3ans.py` | 176 | **utilisé** | Téléchargement CSV 5-min Twelve Data |
| `twelve_data_historique.py` | 92 | **obsolète** | Ancien exemple de téléchargement, remplacé |
| `backtest_rsi_vectorbt.py` | 76 | **obsolète** | Premier script de test RSI mono-symbole, remplacé |
| `run_multi_symboles.py` | 51 | **utilisé** | Boucle de téléchargement des 30 symboles |
| `teest.ipynb` | — | **obsolète** | Brouillon 3 cellules |
| `config.py` | 14 | **utilisé** | Chemins + capital + frais + annualisation |
| `GUIDE_SIGNAUX_METHODES.md` | — | **utilisé** | Documentation des signaux |
| `../data/*.csv` (30) | — | données | Non versionnés (gitignorés) |
| `../resultats/*` | — | sorties | Non versionnés, regénérables |

## 2. Code dupliqué identifié

1. **Signaux — implémentés 3 fois** (le problème principal) :
   - `lucas-live-trading/signals.py` : stateful, bar par bar (live) ;
   - `research/strategies.py` : vectorisé vectorbt (recherche) ;
   - `research/backtest_scorer_oos.py` : *seconde* réplique vectorisée (le docstring dit lui-même « vectorised replica of signals.py »).
2. **Stratégie de vote — 3 fois** : `engine.evaluate_bar` (live), `strategies._make_vote` (recherche), `backtest_scorer_oos.simulate`.
3. **Accès broker/données Alpaca — 2 fois** : `bot.py` et `scorer.py` dupliquent `_is_crypto`, `load_config`, la création des clients Alpaca et le fetch de barres historiques.
4. **Métriques — 4+ fois** : Sharpe, max drawdown, total return, trade count recodés dans `scorer.py`, `backtest_scorer_oos.py`, `backtest_topx_portfolio.py`, `optimize_topx.py`, `backtest_v2_*`.
5. **Univers de symboles — 3 fois** : `constants.SYMBOLS` (live), `config.json` (live), noms de fichiers CSV (recherche), plus une liste de prix en dur dans `seed_fake_data.py`.
6. **Deux dashboards Streamlit** indépendants (2 800 lignes cumulées), l'un lit `bars.db`, l'autre les CSV de `resultats/`.

## 3. Structure cible

```
lucas-trading/
├── strategies/            # une stratégie = un fichier, backtest ET live
│   ├── __init__.py        #   registre + interface Strategy (on_bar)
│   └── vote_mr.py         #   stratégie actuelle (BB+OU+VWAP+VolSpike+KalmanZ)
├── core/                  # code partagé, écrit UNE fois
│   ├── signals.py         #   ← live signals.py (source de vérité)
│   ├── engine.py          #   ← live engine.py (evaluate_bar, SignalState)
│   ├── broker.py          #   clients Alpaca + fetch extraits de bot/scorer
│   ├── data.py            #   chargement CSV recherche + bars.db
│   ├── metrics.py         #   sharpe, drawdown, return, trades (unifiés)
│   └── constants.py       #   ← live constants.py + research config.py
├── backtest/              # moteurs de backtest
│   ├── event_driven.py    #   rejoue les CSV bar-par-bar via core.engine
│   │                      #   (garantit parité backtest/live)
│   ├── vectorized/        #   outils vectorbt de recherche rapide
│   │   ├── strategies_vbt.py      ← research strategies.py
│   │   ├── backtest_multi.py, optimize.py, optimize_topx.py
│   │   ├── backtest_topx_portfolio.py, backtest_scorer_oos.py
│   │   └── backtest_v2_regime_mr.py, backtest_v2_topx.py
│   └── dashboard.py       #   ← research dashboard.py
├── live/
│   ├── bot.py             #   ← live bot.py (allégé de broker/config)
│   ├── scorer.py          #   ← live scorer.py (idem)
│   └── dashboard.py       #   ← live dashboard.py
├── config/
│   ├── config.json        #   runtime (gitignoré, comme aujourd'hui)
│   └── config.example.json#   modèle versionné
├── data/                  # CSV historiques (gitignoré)
├── results/               # sorties backtests (gitignoré)
├── tools/
│   ├── download_history.py  ← twelve_data_5min_3ans.py + run_multi_symboles.py
│   └── seed_fake_data.py
├── deploy/                # ← live deploy/ (chemins mis à jour)
├── archive/               # rien n'est supprimé
│   ├── backtest_rsi_vectorbt.py
│   ├── twelve_data_historique.py
│   ├── teest.ipynb
│   └── strategies_ML.py   (si abandon XGBoost confirmé)
├── docs/GUIDE_SIGNAUX_METHODES.md
├── backtest.py            # CLI : python backtest.py vote_mr
├── live.py                # CLI : python live.py vote_mr
└── README.md              # créer une stratégie → backtester → passer live
```

### Principe « une stratégie, deux moteurs »

Le couple `core/signals.py` + `core/engine.py` est déjà partagé entre `bot.py` et `scorer.py` en live — c'est lui qui devient l'interface commune. Une stratégie expose sa config de signaux et son seuil de vote ; `backtest/event_driven.py` la rejoue bar par bar sur les CSV historiques avec exactement le même code que le bot live. Les scripts vectorbt restent disponibles pour l'exploration rapide, mais la validation finale d'une stratégie passe par le moteur événementiel partagé (plus lent, zéro divergence).

## 4. Phases de migration (un commit par phase)

1. **Inventaire** : ce document.
2. **Squelette** : dossiers `lucas-trading/*`, `__init__.py`, `.gitignore` ajusté.
3. **Archive** : `git mv` des obsolètes vers `archive/`.
4. **Core** : `git mv` signals/engine/constants vers `core/`, fusion `config.py` + `constants.py`, suppression `CRYPTO_SYMBOLS` mort.
5. **Live** : `git mv` bot/scorer/dashboard vers `live/`, extraction de `core/broker.py` (code commun bot/scorer), imports corrigés.
6. **Backtest** : `git mv` des scripts recherche, extraction de `core/metrics.py`, imports corrigés.
7. **Stratégies** : interface `Strategy`, `strategies/vote_mr.py`, moteur `backtest/event_driven.py`.
8. **CLI + config** : `backtest.py`, `live.py`, `config.example.json`.
9. **Deploy** : mise à jour des chemins systemd/nginx/scripts.
10. **README + vérification** : `py_compile` sur tout, imports testés, smoke test du backtest événementiel.

Les fichiers non versionnés (`data/`, `resultats/`, `bars.db`, `config.json`, logs) sont déplacés à la main (pas de `git mv` possible).

## 5. Points d'attention

- **VPS** : si le bot tourne en prod, les templates systemd pointent vers `lucas-live-trading/` — il faudra redéployer après merge.
- Recherche = barres **5 min** Twelve Data ; live = barres **1 min** Alpaca. La fusion n'unifie pas les données, seulement le code.
- Les deux dashboards restent séparés dans un premier temps (fusion possible plus tard, hors périmètre).
- `strategies_ML.py` : archivé seulement si l'abandon de la piste XGBoost est confirmé (sinon `backtest/vectorized/`).
- Parité signals stateful ↔ vectorisés : non re-validée par ce refactor (déjà validée d'après le docstring de `backtest_scorer_oos`).

## 6. Décisions à valider

1. **Nom du dossier racine** : `lucas-trading/` proposé (le repo est partagé avec Kerry, convention `lucas-*`) au lieu de `trading/`.
2. **Sort de `strategies_ML.py`** : archive ou `backtest/vectorized/` ?
3. **Fusion des deux dashboards** : hors périmètre (proposé) ou inclus ?
4. Validation globale du plan ci-dessus.
