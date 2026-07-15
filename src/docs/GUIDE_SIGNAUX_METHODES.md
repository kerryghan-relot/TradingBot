# Guide complet — Signaux et méthodes de backtesting

Ce document explique en détail chaque signal de trading utilisé dans ce projet, ainsi que chaque méthode de test et d'optimisation. Il est écrit pour être lu sans avoir le code sous la main.

---

## Table des matières

1. [Concepts fondamentaux](#1-concepts-fondamentaux)
2. [Signaux techniques classiques](#2-signaux-techniques-classiques)
   - RSI
   - Bollinger Bands
   - EMA Cross
   - MACD Zero
   - MACD Signal
   - EMA Trend
   - Z-score
   - BB Squeeze
   - Donchian
   - RSI Slope
   - Regime Trend / Regime Range
3. [Signaux avancés](#3-signaux-avancés)
   - VWAP
   - ORB (Opening Range Breakout)
   - VolSpike
   - Ornstein-Uhlenbeck (OU)
   - TimeFilter
   - KalmanZ
4. [Stratégie Machine Learning — XGBoost](#4-stratégie-machine-learning--xgboost)
5. [Mécanisme de vote (combinaisons de signaux)](#5-mécanisme-de-vote-combinaisons-de-signaux)
6. [Méthodes de backtesting](#6-méthodes-de-backtesting)
7. [Méthodes d'optimisation des paramètres](#7-méthodes-doptimisation-des-paramètres)
8. [Métriques de performance](#8-métriques-de-performance)
9. [Glossaire](#9-glossaire)

---

## 1. Concepts fondamentaux

### Barre 5 minutes
Toutes les données utilisées ici sont des bougies de 5 minutes. Chaque barre contient : Open, High, Low, Close, Volume (OHLCV). À titre de repère :
- 1 heure = 12 barres
- 1 jour de trading US (6h30) ≈ 78 barres
- 1 semaine ≈ 390 barres
- 1 mois ≈ 1 560 barres
- 3 ans ≈ ~115 000 barres (données crypto 24h/7j)

### Signal d'entrée vs signal de sortie
Chaque signal produit deux séries booléennes :
- **Entrée (entry)** : `True` au moment où il faut acheter
- **Sortie (exit)** : `True` au moment où il faut vendre / clôturer la position

### Discrétisation (_disc)
Tous les signaux passent par une fonction `_disc` qui ne garde que le **premier True de chaque séquence consécutive de True**. Cela évite d'envoyer des dizaines d'ordres d'achat sur plusieurs barres consécutives. Sans cela, une stratégie en zone de survente pendant 50 barres enverrait 50 ordres d'achat.

```
Signal brut : F F T T T F F T T F
Après _disc : F F T F F F F T F F
                  ↑ seul le 1er    ↑ seul le 1er
```

---

## 2. Signaux techniques classiques

---

### RSI — Relative Strength Index

**Catégorie :** Mean-reversion (retour à la moyenne)

**Principe :** Le RSI mesure la vitesse et l'amplitude des mouvements de prix récents. Il oscille entre 0 et 100. Une valeur basse signifie que le prix a beaucoup baissé récemment (survente), une valeur haute qu'il a beaucoup monté (surachat).

**Formule :**
```
RSI = 100 - (100 / (1 + RS))
RS  = moyenne des hausses sur N barres / moyenne des baisses sur N barres
```

**Paramètres dans ce projet :**
- `RSI_PERIOD = 200` barres (~1 jour de trading crypto)
- `RSI_BUY = 25` — seuil de survente (achat)
- `RSI_SELL = 75` — seuil de surachat (vente)

**Logique de signal :**
- **Entrée** : RSI < 25 → le marché est considéré survendu → on anticipe un rebond
- **Sortie** : RSI > 75 → le marché est considéré suracheté → on clôture

**Intuition :** Imagine que le prix d'un actif a baissé brutalement pendant 3 jours. Le RSI sera très bas (< 25). On parie que la baisse est excessive et qu'un rebond va suivre. C'est une stratégie contrariante.

**Limites :**
- En tendance baissière forte, le RSI peut rester sous 25 très longtemps (on achète un couteau qui tombe)
- Très efficace en marché range, dangereux en marché directionnel

**Période choisie :** 200 barres est volontairement long. Un RSI court (14 barres standard) génère trop de faux signaux sur du 5 min. À 200 barres, seules les vraies situations de survente extrême déclenchent un signal.

---

### BB — Bollinger Bands (Bandes de Bollinger)

**Catégorie :** Mean-reversion

**Principe :** Les bandes de Bollinger forment un canal autour d'une moyenne mobile. La largeur du canal s'adapte à la volatilité : plus le marché est volatil, plus les bandes s'écartent. Quand le prix touche la bande basse, il est statistiquement "loin" de sa moyenne.

**Formule :**
```
Bande centrale = moyenne mobile sur N barres
Bande haute    = centrale + std × écart-type
Bande basse    = centrale - std × écart-type
```

**Paramètres dans ce projet :**
- `BB_PERIOD = 750` barres (~1 semaine en crypto 24h)
- `BB_STD = 3.0` — 3 écarts-types (intervalle très large)

**Logique de signal :**
- **Entrée** : Close < bande basse → prix statistiquement bas
- **Sortie** : Close > bande haute → prix statistiquement haut

**Intuition :** Statistiquement, si le prix suit une distribution normale, il ne doit se trouver en dehors de ±3 écarts-types que 0.3% du temps. Quand il franchit cette limite, on parie qu'il va revenir vers la moyenne.

**Pourquoi 750 barres et 3 std ?** Ces paramètres ont été testés (voir `optimize.py`). Une fenêtre longue (750 ≈ 1 semaine) calcule une "normale" sur un contexte de marché large. 3 std filtre les petites déviations et ne déclenche que lors d'événements vraiment extrêmes, réduisant les faux signaux.

**Limites :**
- En breakout haussier, le prix reste au-dessus de la bande haute longtemps → signal de vente prématuré
- Nécessite un marché range pour être pertinent

---

### EMA Cross — Croisement de moyennes exponentielles

**Catégorie :** Trend-following (suivi de tendance)

**Principe :** On calcule deux moyennes mobiles exponentielles (EMA) : une "rapide" sur peu de barres, une "lente" sur beaucoup de barres. Quand la rapide passe au-dessus de la lente, la tendance à court terme est haussière.

**Différence EMA vs SMA :** La SMA (moyenne simple) donne le même poids à toutes les barres. L'EMA donne plus de poids aux barres récentes, donc réagit plus vite aux changements de prix.

**Formule EMA :**
```
EMA_t = prix_t × (2 / (N+1)) + EMA_{t-1} × (1 - 2/(N+1))
```
Plus N est petit, plus l'EMA réagit vite aux mouvements récents.

**Paramètres dans ce projet :**
- `EMA_FAST = 10` barres (~50 minutes)
- `EMA_SLOW = 500` barres (~2.5 jours en crypto)

**Logique de signal :**
- **Entrée** : EMA_fast > EMA_slow → la tendance court-terme est haussière
- **Sortie** : EMA_fast < EMA_slow → tendance court-terme baissière

**Intuition :** La fast EMA capture les mouvements récents. La slow EMA représente la tendance de fond. Quand la fast passe au-dessus de la slow, c'est le "golden cross" classique en analyse technique.

**Limites :**
- Signal retardé : l'EMA croise après que le mouvement a commencé
- En marché choppy (range), génère de nombreux aller-retours (whipsaws)
- Le spread écart fast/slow (10 vs 500) est très large, ce qui réduit les entrées/sorties fréquentes mais peut manquer des mouvements

---

### MACD Zero — Croisement du zéro

**Catégorie :** Trend-following

**Principe :** Le MACD (Moving Average Convergence Divergence) est la différence entre deux EMA. Quand le MACD passe au-dessus de zéro, la EMA rapide est au-dessus de la EMA lente → tendance haussière.

**Formule :**
```
MACD = EMA(fast) - EMA(slow)
```

**Paramètres dans ce projet :**
- `MACD_F = 26` barres (~2h10)
- `MACD_S = 78` barres (~6h30, ratio 1:3 avec fast)
- `MACD_SIG = 14` barres (signal line, non utilisée ici)

**Logique de signal :**
- **Entrée** : MACD > 0 (fast EMA au-dessus de slow EMA)
- **Sortie** : MACD < 0 (fast EMA en dessous de slow EMA)

**Différence MACD Zero vs EMA Cross :** Conceptuellement identiques (MACD > 0 ↔ EMA_fast > EMA_slow), mais les paramètres par défaut diffèrent. MACD Zero utilise des périodes plus courtes (26/78 vs 10/500) → plus de signaux, plus sensible.

**Limites :** Mêmes que l'EMA Cross : retardé, sensible aux faux signaux en marché range.

---

### MACD Signal — Croisement de la ligne de signal

**Catégorie :** Trend-following

**Principe :** Même MACD, mais on compare la ligne MACD à sa propre moyenne mobile (la "signal line"). Le croisement MACD/signal est plus rapide que MACD/zéro.

**Formule :**
```
MACD        = EMA(fast) - EMA(slow)
Signal line = EMA(MACD, signal_window)
```

**Logique de signal :**
- **Entrée** : MACD > Signal line
- **Sortie** : MACD < Signal line

**Intuition :** C'est le signal MACD "classique" utilisé en analyse technique. Le croisement MACD/signal anticipe souvent le croisement MACD/zéro de quelques barres, donc entre légèrement plus tôt dans la tendance.

---

### EMA Trend — Filtre de tendance

**Catégorie :** Filtre directionnel

**Principe :** Simple comparaison du prix à la slow EMA. Si le prix est au-dessus, on est en tendance haussière.

**Logique de signal :**
- **Entrée** : Close > EMA_slow
- **Sortie** : Close < EMA_slow

**Usage typique :** Ce signal ne s'utilise généralement pas seul mais en combinaison avec un signal mean-reversion. Exemple : "RSI survendu ET prix au-dessus de la slow EMA" pour n'acheter que dans la direction de la tendance.

---

### Z-score — Mean reversion statistique

**Catégorie :** Mean-reversion

**Principe :** Le Z-score mesure à combien d'écarts-types le prix actuel se trouve de sa moyenne mobile. Il standardise la déviation, contrairement aux Bollinger Bands qui mesurent en unités de prix.

**Formule :**
```
Z = (prix - moyenne(N)) / écart-type(N)
```

**Paramètres dans ce projet :**
- `ZSCORE_WIN = 390` barres (~1 semaine en crypto)
- `ZSCORE_TH = 3.0` — seuil de déclenchement

**Logique de signal :**
- **Entrée** : Z < -3 → prix 3 std sous la moyenne sur 1 semaine
- **Sortie** : Z > +3 → prix 3 std au-dessus

**Différence BB vs Z-score :** Conceptuellement très similaires. BB travaille en espace prix (les bandes bougent avec la volatilité), le Z-score travaille en espace standardisé (toujours interprétable en "nombre d'écarts-types", indépendamment du niveau de volatilité). Le Z-score est plus facile à interpréter et à comparer entre actifs.

---

### BB Squeeze — Compression puis breakout

**Catégorie :** Breakout (sortie de compression)

**Principe :** La "squeeze" Bollinger est différente du signal BB classique. Ici, on détecte des périodes de faible volatilité (bandes très serrées = compression) suivies d'une expansion. On entre quand le prix sort par le haut après une compression.

**Formule :**
```
Width = (bande haute - bande basse) / bande centrale
Squeeze = Width < 20e percentile de Width sur 2×fenêtre barres
```

**Logique de signal :**
- **Entrée** : la barre précédente était en squeeze ET la barre actuelle ne l'est plus ET Close > bande haute
- **Sortie** : Close < bande centrale

**Intuition :** La volatilité est cyclique. Une longue période de calme (bandes serrées) est souvent suivie d'un mouvement directionnel fort. Ce signal cherche à capturer le début de ce mouvement.

**Différence avec BB classique :**
- BB classique : mean-reversion (achète quand le prix est bas)
- BB Squeeze : breakout (achète quand le prix sort par le haut d'une compression) Ces deux signaux ont des philosophies opposées.

---

### Donchian — Canal de breakout

**Catégorie :** Breakout / trend-following

**Principe :** Le canal de Donchian est simplement le plus haut et le plus bas sur N barres. Il capture les nouveaux plus hauts (breakout haussier) et plus bas.

**Formule :**
```
Canal haut  = max(Close, N_entry barres précédentes)
Canal bas   = min(Close, N_exit barres précédentes)
```

**Paramètres dans ce projet :**
- `DONCH_EN = 40` barres (entrée sur nouveau plus haut sur ~3h20)
- `DONCH_EX = 20` barres (sortie sous nouveau plus bas sur ~1h40)

**Logique de signal :**
- **Entrée** : Close > plus haut des 40 barres précédentes
- **Sortie** : Close < plus bas des 20 barres précédentes

**Intuition :** Si le prix atteint un nouveau plus haut sur 40 barres, c'est un signe de force. La sortie sur plus bas 20 barres est une gestion de trailing stop dynamique. C'est la base de la stratégie "Turtle Trading" des années 1980.

**Asymétrie entrée/sortie :** L'entrée utilise une fenêtre plus longue (40) que la sortie (20). Cela signifie qu'on entre prudemment (seulement sur de vrais nouveaux sommets) mais qu'on sort plus vite (protection des gains).

---

### RSI Slope — RSI avec momentum

**Catégorie :** Mean-reversion améliorée

**Principe :** Amélioration du RSI classique. Au lieu d'acheter dès que le RSI est bas, on attend que le RSI soit à la fois bas ET en train de remonter (slope positive). Cela évite d'acheter un actif encore en chute libre.

**Formule :**
```
RSI_slope = RSI(t) - RSI(t - lookback)
```

**Paramètres dans ce projet :**
- `RSI_SL_WIN = 14` barres (période RSI standard)
- `RSI_SL_LB = 5` barres (lookback du slope)

**Logique de signal :**
- **Entrée** : RSI < 40 ET slope > 0 (survendu mais momentum en retournement)
- **Sortie** : RSI > 60 ET slope < 0

**Avantage sur le RSI simple :** Le RSI simple achète quand le prix baisse fort. Le RSI Slope attend que la dynamique change de direction, réduisant l'entrée "couteau qui tombe".

---

### Regime Trend / Regime Range — Filtres de régime

**Catégorie :** Filtres (ne génèrent pas de trades seuls)

**Principe :** Ces deux signaux détectent le "régime" du marché : est-il en tendance (trending) ou en range (oscillant) ? Ils sont conçus pour être combinés avec d'autres signaux afin de ne trader que dans le bon contexte.

**Indicateur : Efficiency Ratio (ER) de Kaufman**
```
ER = |prix(t) - prix(t-N)| / somme des |variations absolues sur N barres|
```
- ER proche de 1 → mouvement très directionnel (tendance pure)
- ER proche de 0 → beaucoup de mouvement mais peu de déplacement net (range/noise)

**Paramètres dans ce projet :**
- `REGIME_ER_PERIOD = 20` barres (~1h40)
- `REGIME_TREND_TH = 0.50` (ER > 0.50 → tendance)
- `REGIME_RANGE_TH = 0.35` (ER < 0.35 → range)

**Regime Trend :**
- **Entrée** (actif) : ER > 0.50 → marché en tendance → OK pour EMA Cross, MACD
- **Sortie** (inactif) : ER < 0.35 → marché range → sortir des positions trend

**Regime Range :**
- **Entrée** (actif) : ER < 0.35 → marché range → OK pour BB, Z-score
- **Sortie** (inactif) : ER > 0.50 → tendance → sortir des positions mean-reversion

**Usage typique :**
```
# Ne trader la stratégie EMA Cross que si le marché est en tendance :
stratégie = EMA_Cross + Regime_Trend (vote 2/2)

# Ne trader le Z-score que si le marché range :
stratégie = Zscore + Regime_Range (vote 2/2)
```

**Intuition :** Un signal mean-reversion en plein trend perdra toujours. Un signal trend-following en marché range générera des whipsaws constants. Le filtre de régime sépare les contextes pour n'appliquer que la bonne stratégie au bon moment.

---

## 3. Signaux avancés

---

### VWAP — Volume Weighted Average Price

**Catégorie :** Mean-reversion intraday

**Principe :** Le VWAP est la moyenne pondérée par le volume du prix typique (H+L+C)/3. Il représente le prix "juste" auquel la majorité des échanges ont eu lieu dans la journée. Les institutional traders l'utilisent comme benchmark.

**Formule :**
```
Prix typique = (High + Low + Close) / 3
VWAP = Σ(prix_typique × volume) / Σ(volume)
```
Le VWAP se remet à zéro à chaque début de journée.

**Paramètres dans ce projet :**
- `VWAP_TH = 0.005` → seuil de ±0.5% de déviation

**Logique de signal :**
```
déviation = (Close - VWAP) / VWAP
Entrée : déviation < -0.5%  (prix 0.5% sous le VWAP)
Sortie : déviation > +0.5%  (prix 0.5% au-dessus du VWAP)
```

**Intuition :** Si le prix s'écarte significativement du VWAP vers le bas, les gros acteurs vont souvent le "ramener" vers la moyenne pondérée. C'est une mean-reversion par rapport à la valeur institutionnelle de la journée.

**Particularité crypto :** Le VWAP standard s'applique mieux aux marchés avec des heures d'ouverture définies (9h30-16h pour les US). Sur le crypto (24h/7j), le VWAP reset à minuit UTC. Le signal reste valable mais moins ancré dans un contexte "journée de trading" comme pour les actions.

---

### ORB — Opening Range Breakout

**Catégorie :** Breakout intraday

**Principe :** Les premières barres de la journée définissent un "range d'ouverture". Si le prix sort de ce range (au-dessus du plus haut, en dessous du plus bas), c'est un signal de momentum directionnel.

**Paramètres dans ce projet :**
- `ORB_BARS = 6` barres → les 30 premières minutes définissent le range

**Logique de signal :**
```
Range haut = max(High des 6 premières barres du jour)
Range bas  = min(Low des 6 premières barres du jour)

Entrée : après la 6e barre, Close > Range haut
Sortie : après la 6e barre, Close < Range bas
```

**Intuition :** Les 30 premières minutes reflètent l'équilibre entre acheteurs et vendeurs à l'ouverture (prise en compte des news overnight, du pre-market). Une sortie de ce range indique que l'un des deux camps prend le dessus.

**Limite sur crypto :** L'ORB est très efficace sur les marchés actions (ouverture 9h30) car il y a une vraie "information à digérer" à l'ouverture. Sur le crypto qui trade 24h, le reset à minuit UTC est arbitraire et le signal perd en pertinence.

---

### VolSpike — Volume spike avec confirmation directionnelle

**Catégorie :** Momentum

**Principe :** Détecte les pics de volume anormaux (le marché "s'active") et confirme la direction par le mouvement de prix. Un gros volume haussier → achat. Un gros volume baissier → vente.

**Formule :**
```
Vol_MA = moyenne(volume, 20 barres)
Spike  = volume > VOL_SPIKE_TH × Vol_MA
Ret    = (Close - Close_précédent) / Close_précédent
```

**Paramètres dans ce projet :**
- `VOL_ROLL_WIN = 20` barres (~1h40)
- `VOL_SPIKE_TH = 2.0` → volume 2× supérieur à la moyenne

**Logique de signal :**
```
Entrée : Spike ET return > 0  (volume anormal + prix monte)
Sortie : Spike ET return < 0  (volume anormal + prix baisse)
```

**Intuition :** Quand il y a soudainement 2× plus de volume que la normale, c'est souvent le signe d'une information nouvelle qui entre sur le marché (news, gros acteur qui agit). La direction du mouvement de prix confirme le sens du signal.

**Limite :** Génère peu de signaux car les deux conditions doivent être remplies simultanément. Sur des marchés peu liquides (peu de volume moyen), le seuil ×2 peut être atteint par simple bruit.

---

### OU — Ornstein-Uhlenbeck mean reversion

**Catégorie :** Mean-reversion statistique avancée

**Principe :** Le processus d'Ornstein-Uhlenbeck est un modèle mathématique de mean-reversion venant de la physique (mouvement brownien avec friction). Il suppose que le prix oscille autour d'un niveau d'équilibre μ avec une "force de rappel" κ.

**Formule simplifiée (OLS rolling) :**
```
log(P_t) = κ × log(P_{t-1}) + (1-κ) × μ + bruit
```
On estime κ et μ par régression OLS sur une fenêtre glissante. Puis :
```
Z_OU = (log(P_t) - μ_estimé) / écart-type des résidus
```

**Paramètres dans ce projet :**
- `OU_WINDOW = 200` barres (~16h)
- `OU_TH = 2.0` — seuil d'entrée

**Logique de signal :**
```
Entrée : Z_OU < -2.0  (prix bien en dessous de l'équilibre estimé)
Sortie : Z_OU > +2.0
```

**Différence avec Z-score classique :** Le Z-score classique utilise une moyenne simple et un écart-type fixe. L'OU modélise explicitement la force de rappel vers l'équilibre et utilise les log-prix (ce qui est plus approprié pour des actifs financiers qui ne peuvent pas devenir négatifs). C'est mathématiquement plus rigoureux.

**Limite :** L'hypothèse que le prix suit un processus OU est forte. Sur des actifs en tendance forte, μ peut dériver rapidement et l'estimation OLS sur fenêtre courte peut être instable.

---

### TimeFilter — Filtre temporel

**Catégorie :** Filtre (ne génère pas de trades seuls)

**Principe :** Évite de trader pendant les premières et dernières barres de chaque session. Ces périodes sont caractérisées par des spreads plus larges et une liquidité plus faible, ce qui augmente les coûts de transaction réels.

**Paramètres dans ce projet :**
- `TIME_SKIP_BARS = 6` → skip des 6 premières et 6 dernières barres (±30 min)

**Logique de signal :**
```
bar_rank     = position de la barre dans la journée (de 0 à N)
bar_rank_rev = position depuis la fin (de 0 à N)
Actif        = (bar_rank >= 6) ET (bar_rank_rev >= 6)

Entrée : Actif (on peut trader)
Sortie : non-Actif (fenêtre à éviter)
```

**Usage typique :** Toujours en combinaison avec d'autres signaux via le vote :
```
stratégie = BB + TimeFilter (vote 2/2)
→ n'entre que si BB signal ET hors des fenêtres d'ouverture/clôture
```

---

### KalmanZ — Z-score avec filtre de Kalman

**Catégorie :** Mean-reversion adaptative

**Principe :** Variante du Z-score qui remplace la moyenne mobile classique par une moyenne estimée via un filtre de Kalman. Le filtre de Kalman est un algorithme bayésien optimal qui estime l'état caché d'un système (ici : le "vrai" niveau de prix) à partir d'observations bruitées.

**Filtre de Kalman (simplifié) :**
```
Prédiction :  μ_pred  = μ_{t-1}
              P_pred  = P_{t-1} + Q      (Q = bruit de processus)

Correction :  K = P_pred / (P_pred + R)  (gain de Kalman)
              μ_t = μ_pred + K × (prix_t - μ_pred)
              P_t = (1 - K) × P_pred
```

**Paramètres dans ce projet :**
- `KALMAN_Q = 1e-4` → bruit de processus (faible = moyenne lente à bouger)
- `KALMAN_R = 0.1` → bruit de mesure (élevé = données très bruitées)
- `KZ_ROLL_WIN = 100` → fenêtre pour l'écart-type résiduel
- `KZ_TH = 2.0` → seuil d'entrée

**Logique de signal :**
```
σ_résidu = std(Close - μ_Kalman, 100 barres)
Z_Kalman = (Close - μ_Kalman) / σ_résidu

Entrée : Z_Kalman < -2.0
Sortie : Z_Kalman > +2.0
```

**Avantage sur Z-score classique :** Le filtre de Kalman s'adapte à la volatilité du marché. En période calme, il suit le prix de près. En période agitée, il "amortit" les chocs et évite de surréagir aux gros mouvements ponctuels. C'est une moyenne mobile adaptative avec une base théorique solide.

**Paramètre Q :** Plus Q est grand, plus la moyenne Kalman suit le prix rapidement (comme une EMA courte). Plus Q est petit, plus la moyenne est lente (comme une EMA longue). `Q = 1e-4` est très faible → moyenne très lisse.

---

## 4. Stratégie Machine Learning — XGBoost

**Catégorie :** Apprentissage supervisé

**Principe général :** Au lieu de définir manuellement des règles (RSI < 25 → achat), on laisse un algorithme de machine learning découvrir les patterns qui précèdent une hausse de prix. XGBoost est un algorithme de gradient boosting sur arbres de décision — l'un des plus efficaces sur des données tabulaires.

---

### Features (variables d'entrée)

On fournit au modèle des indicateurs techniques continus (pas des signaux binaires) calculés sur chaque barre :

| Feature | Description |
|---|---|
| `ret_1` | Rendement sur 1 barre (5 min) |
| `ret_6` | Rendement sur 6 barres (30 min) |
| `ret_24` | Rendement sur 24 barres (2h) |
| `ret_78` | Rendement sur 78 barres (1 jour) |
| `vol_20` | Volatilité réalisée sur 20 barres |
| `rsi` | Valeur continue du RSI (0-100) |
| `zscore` | Z-score continu (distance en std) |
| `bb_pct` | Position dans les BB (0=bande basse, 1=bande haute) |
| `macd` | Valeur du MACD |
| `macd_signal_diff` | MACD − ligne de signal |
| `ema_dist` | Distance du Close à la slow EMA |
| `vol_ratio` | Volume / moyenne du volume |
| `vol_zscore` | Z-score du volume |

**Pourquoi continus et non binaires ?** Un seuil binaire "RSI < 25" perd toute l'information : RSI=24 et RSI=5 donnent le même signal alors que ce sont des situations très différentes. Donner la valeur brute au XGBoost lui permet d'apprendre lui-même les seuils optimaux.

---

### Target (variable cible)

```
Target = 1 si rendement dans 6 barres (30 min) > +0.1%
Target = 0 sinon
```

C'est un problème de classification binaire : "est-ce que le prix va monter d'au moins 0.1% dans les 30 prochaines minutes ?"

---

### Split train / validation / test

```
Données complètes (3 ans)
│
├─── 70% train
│    ├─── 80% train pur (entraînement du modèle)
│    └─── 20% validation (early stopping)
│
└─── 30% test (OOS — signaux générés ici uniquement)
```

**Chrononologie respectée :** toujours passé → futur, jamais de leak.

**Early stopping :** L'entraînement s'arrête automatiquement si la performance sur la validation n'améliore pas pendant 20 rounds consécutifs. Cela évite l'overfitting sans avoir à choisir manuellement le nombre d'itérations.

---

### Génération des signaux

```
proba = XGBoost.predict_proba(X)[colonne "1"]
Entrée : proba > 0.55  (modèle confiant que le prix va monter)
Sortie : proba < 0.50
```

Les signaux ne sont générés que sur la partie test (30% OOS). Sur la partie train, le modèle "connaît" les données → ce ne sont pas des signaux valables.

---

### Paramètres XGBoost

| Paramètre | Valeur | Rôle |
|---|---|---|
| `n_estimators` | 300 | Nombre max d'arbres |
| `max_depth` | 6 | Profondeur max de chaque arbre |
| `learning_rate` | 0.05 | Taille des pas d'apprentissage |
| `subsample` | 0.8 | 80% des données par arbre |
| `colsample_bytree` | 0.8 | 80% des features par arbre |
| `min_child_weight` | 5 | Régularisation (évite les feuilles trop petites) |
| `early_stopping_rounds` | 20 | Patience avant arrêt |

---

## 5. Mécanisme de vote (combinaisons de signaux)

Au lieu d'utiliser un seul signal, on peut en combiner plusieurs et n'entrer que quand la majorité est d'accord. Cela réduit les faux signaux au prix de signaux moins fréquents.

### Principe du vote

```
Pour N signaux, seuil S :
Entrée = nombre de signaux d'achat >= S
Sortie = nombre de signaux de vente >= S
Conflit (achat ET vente simultanés) → la sortie a priorité
```

### Combinaisons générées automatiquement

Avec les signaux actifs dans `SIGNALS`, le code génère automatiquement :

| Type | Notation | Seuil | Exemple |
|---|---|---|---|
| Signal seul | `BB` | 1/1 | Un seul signal |
| Paires | `BB+Zscore` | 2/2 | Les deux doivent être d'accord |
| Triplets majoritaires | `BB+Zscore+OU_2v3` | 2/3 | Au moins 2 sur 3 |
| Triplets unanimes | `BB+Zscore+OU_3v3` | 3/3 | Les 3 doivent être d'accord |
| Quadruplets | `BB+Zscore+OU+VWAP_3v4` | 3/4 | Au moins 3 sur 4 |

### Interprétation du seuil

**2/2 (paire) :**
- Moins de signaux, mais plus fiables
- Meilleur win rate, moins de trades

**2/3 (majorité) :**
- Équilibre entre fréquence et fiabilité
- Un signal peut être "en désaccord" sans bloquer l'entrée

**3/3 (unanimité) :**
- Très peu de signaux, très sélectif
- Risque de rater des opportunités

**Exemple concret :**
```
Bar t :
  BB :     Entrée ✓  Sortie ✗
  Zscore : Entrée ✓  Sortie ✗
  VWAP :   Entrée ✗  Sortie ✗

Stratégie BB+Zscore+VWAP_2v3 :
  Votes d'achat = 2 (BB + Zscore) >= seuil 2 → ENTRÉE
  Votes de vente = 0 → pas de sortie
  → Signal d'achat déclenché ✓
```

---

## 6. Méthodes de backtesting

---

### In-Sample (IS) — Backtesting classique

**Principe :** On applique la stratégie sur l'intégralité des données historiques disponibles. Les signaux sont générés et évalués sur la même période.

```
Données : |━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3 ans ━━━|
IS :      |━━━━━━━━━━ génère ET évalue les signaux ━━━━━━━━━━|
```

**Ce que ça mesure :** La capacité de la stratégie à avoir fonctionné sur le passé connu.

**Biais fondamental :** Si tu as choisi tes paramètres en regardant ces mêmes données (même implicitement), les résultats sont optimistes. Le modèle "connaît" le passé.

**Quand utiliser l'IS :**
- Pour explorer rapidement si un signal a du potentiel
- Pour comprendre le comportement d'une stratégie
- JAMAIS pour estimer la performance future réelle

**Commandement :** L'IS seul ne prouve rien sur la performance future.

---

### Holdout Out-of-Sample — Ce que fait ton `--walk-forward`

**Note importante :** Ce que ton code appelle "walk-forward" est en réalité un **simple split train/test**. Le vrai walk-forward implique une ré-optimisation des paramètres à chaque fenêtre (voir section suivante). C'est néanmoins une méthode utile.

**Principe :** On divise les données en deux parties chronologiques :
- IS / "train" : les 70% premiers (signaux calculés ici pour le warmup)
- OOS / "test" : les 30% derniers (seule période évaluée)

```
Données : |━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━|
IS :      |━━━━━━━━━━━━━━━ 70% (warmup seulement) ━━━━━━━|
OOS :                                             |━ 30% ━|
          ← signaux calculés sur tout (warmup) →  ← évalué →
```

**Ce que ça mesure :** La performance sur une période récente que la stratégie n'a pas pu "voir" pendant la sélection des paramètres (si les paramètres ont été choisis sur l'IS).

**Pourquoi OOS > IS est possible ici :** Puisque les paramètres ne sont pas ré-optimisés, la différence IS/OOS vient uniquement des conditions de marché différentes entre les deux périodes. Un OOS > IS signifie que les 30% récents étaient statistiquement plus favorables à la stratégie — par chance ou par régime de marché.

**Interprétation :**
- OOS proche de IS → stratégie cohérente dans le temps
- OOS bien inférieur à IS → potentiel overfitting ou régime de marché défavorable récemment
- OOS supérieur à IS → régime récent favorable (ou hasard sur une courte période)

---

### Vrai Walk-Forward (non implémenté, pour référence)

**Principe :** C'est la méthode rigoureuse qui simule réellement le processus de re-calibration d'une stratégie en production.

```
Fenêtre 1 : |━━━━━ IS (optimise) ━━━━━|━ OOS (évalue) ━|
Fenêtre 2 :          |━━━━━ IS ━━━━━━━━━━|━ OOS ━|
Fenêtre 3 :                   |━━━━━ IS ━━━━━━━━━|━ OOS ━|

Résultat final = concaténation des OOS uniquement
```

**Différence fondamentale :** À chaque fenêtre, on ré-optimise les paramètres sur l'IS, puis on teste sur l'OOS suivant avec ces nouveaux paramètres. L'OOS n'a jamais été vu lors de l'optimisation → simulation réelle d'une décision en temps réel.

**Métriques clés du vrai walk-forward :**
```
WF Efficiency = Sharpe OOS / Sharpe IS
- < 0.3 : la stratégie ne généralise pas (overfitting)
- 0.3-0.7 : acceptable (dégradation normale)
- > 0.7 : robuste
- > 1.0 : suspect ou IS mal optimisé
```

---

## 7. Méthodes d'optimisation des paramètres

---

### Grid Search (ce que fait `optimize.py`)

**Principe :** On teste exhaustivement toutes les combinaisons de paramètres dans une grille prédéfinie. Pour chaque combinaison, on exécute un backtest complet et on note les résultats.

**Exemple concret pour BB :**
```
BB_PERIODS = [100, 200, 300, 500, 750]   → 5 valeurs
BB_STDS    = [1.5, 2.0, 2.5, 3.0]       → 4 valeurs

Grid BB = 5 × 4 = 20 combinaisons testées
```

**Résultat :** Un tableau avec la performance de chaque combinaison sur chaque symbole. On sélectionne les paramètres qui maximisent l'alpha (surperformance vs Buy&Hold) en moyenne sur tous les actifs.

**Avantage :** Simple, exhaustif, reproductible.

**Inconvénient :** Exponentiel en nombre de paramètres. Ajouter un paramètre avec 5 valeurs multiplie le temps de calcul par 5.

**Biais :** La sélection des meilleurs paramètres sur les données IS est une forme d'overfitting — les "meilleurs" paramètres ont pu être chanceux sur cette période spécifique.

---

### Grilles de paramètres utilisées

**Bollinger Bands :**
```
BB_PERIODS : [100, 200, 300, 500, 750]   (5 valeurs, de ~1h à ~1 semaine)
BB_STDS    : [1.5, 2.0, 2.5, 3.0]       (4 valeurs, de modéré à très large)
→ 20 combinaisons
```

**EMA Cross :**
```
EMA_FASTS : [20, 50, 100]               (de ~1h40 à ~8h)
EMA_SLOWS : [100, 200, 500]             (de ~8h à ~2.5 jours)
Contrainte : fast < slow → 7 combinaisons valides
```

**MACD Zero :**
```
MACD_FASTS : [12, 20, 26]
MACD_SLOWS : [26, 52, 78]
MACD_SIGS  : [9, 14, 18]
Contrainte : fast < slow → 18 combinaisons valides
```

**Z-score :**
```
ZSCORE_WINS : [195, 390, 585]           (~0.5 / 1 / 1.5 semaine)
ZSCORE_THS  : [1.5, 2.0, 2.5, 3.0]
→ 12 combinaisons
```

---

## 8. Métriques de performance

---

### Performance % (Total Return)

```
Performance = (capital_final / capital_initial - 1) × 100
```
Rendement total sur la période. Sans contexte, ce chiffre est peu informatif (une performance de +50% sur un actif qui a fait +200% est une sous-performance).

---

### Buy & Hold % (B&H)

```
B&H = (prix_final / prix_initial - 1) × 100
```
Ce qu'aurait rapporté une simple détention de l'actif sur toute la période. C'est le benchmark naturel.

---

### Alpha vs B&H

```
Alpha = Performance stratégie - Performance B&H
```
La surperformance par rapport au benchmark. C'est la vraie mesure de la valeur ajoutée de la stratégie. Un alpha négatif signifie qu'on aurait mieux fait de ne rien faire et juste acheter et tenir.

---

### Sharpe Ratio

```
Sharpe = (rendement moyen - taux sans risque) / volatilité des rendements
```
Mesure le rendement par unité de risque pris. Le taux sans risque est souvent 0 en crypto ou les T-bills en actions.

| Sharpe | Interprétation |
|---|---|
| < 0 | Perd de l'argent |
| 0 - 0.5 | Faible |
| 0.5 - 1.0 | Correct |
| 1.0 - 2.0 | Bon |
| > 2.0 | Excellent (souvent trop beau pour un vrai backtest) |

**Annualisation :** Le Sharpe est annualisé. Sur du 5-min, vectorbt utilise `ANNUALIZATION = sqrt(252 × 78 × 12)` pour convertir le Sharpe "par barre" en Sharpe annuel.

---

### Max Drawdown %

```
Max DD = max((pic - creux) / pic) × 100
```
La plus grande perte de la valeur de portefeuille depuis un sommet jusqu'au creux suivant. Un Max DD de 30% signifie que ton capital a perdu au maximum 30% à un moment donné.

C'est la métrique de risque la plus intuitive : "quelle est la pire période que tu aurais vécu ?"

---

### Trades

Nombre total d'allers-retours (entrée + sortie = 1 trade). Un nombre de trades trop faible (< 20-30) rend les métriques statistiquement non significatives. Un nombre trop élevé (> 1000) signifie que les frais de transaction impactent fortement la performance réelle.

---

### Win Rate %

```
Win Rate = trades gagnants / total trades × 100
```

**Attention :** Un win rate élevé n'est pas forcément bon si les gains sont petits et les pertes grandes. Un win rate de 40% peut être très profitable si le gain moyen est 3× la perte moyenne (ratio risk/reward de 1:3).

```
Espérance = (WR × gain_moyen) - ((1-WR) × perte_moyenne)
```
C'est l'espérance mathématique qui compte, pas le win rate seul.

---

## 9. Glossaire

**Alpha :** Surperformance par rapport au benchmark (B&H).

**Backtest :** Simulation d'une stratégie sur des données historiques.

**Bar / Barre :** Une unité de temps (ici : 5 minutes) contenant OHLCV.

**B&H (Buy & Hold) :** Stratégie passive : acheter au début et garder jusqu'à la fin.

**Breakout :** Signal déclenché quand le prix sort d'une zone de consolidation.

**Drawdown :** Perte depuis un sommet vers un creux.

**EMA :** Exponential Moving Average, moyenne mobile qui donne plus de poids aux données récentes.

**Efficiency Ratio :** Ratio de Kaufman mesurant le caractère directionnel d'un marché.

**Grid Search :** Recherche exhaustive des meilleurs paramètres sur une grille.

**In-Sample (IS) :** Période sur laquelle on calibre ET évalue — biais d'optimisme.

**Look-ahead bias :** Erreur qui consiste à utiliser des données futures pour prendre des décisions passées.

**MACD :** Moving Average Convergence Divergence — différence entre deux EMA.

**Mean-reversion :** Stratégie qui parie que le prix va revenir vers sa moyenne après s'en être écarté.

**OOS (Out-of-Sample) :** Période de test sur des données non vues lors de la calibration.

**Overfitting :** Quand un modèle performe bien en IS mais mal en OOS — il a mémorisé le bruit.

**RSI :** Relative Strength Index — oscillateur mesurant la vitesse et l'amplitude des mouvements.

**Sharpe Ratio :** Rendement ajusté du risque (rendement / volatilité).

**SMA :** Simple Moving Average — moyenne arithmétique sur N barres.

**Spread :** Différence entre le prix d'achat et de vente. Coût implicite de transaction.

**Trend-following :** Stratégie qui suit la direction du marché (achète ce qui monte).

**VWAP :** Volume Weighted Average Price — prix moyen pondéré par le volume depuis le début de la journée.

**Walk-Forward :** Méthode de test qui ré-optimise les paramètres sur des fenêtres glissantes et teste sur les OOS successifs.

**Whipsaw :** Série de faux signaux en marché range qui génère des pertes répétées pour un signal trend-following.

**Win Rate :** Proportion de trades gagnants sur le total des trades.

**XGBoost :** eXtreme Gradient Boosting — algorithme ML basé sur des arbres de décision boostés.

**Z-score :** Nombre d'écarts-types séparant une valeur de sa moyenne. `Z = (x - μ) / σ`.
