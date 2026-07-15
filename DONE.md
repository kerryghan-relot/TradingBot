# Done

Here is a list and a short explanation that everything that has been done so far in the project. This file must be updated after every addition, or significant changes to the project.

## 2026-07-15 — Documentation et nettoyage des skills

- **`README.md` (racine)** — remplacé le placeholder d'une ligne par la vue d'ensemble du
  projet : ce que fait le bot, le principe « une stratégie, deux moteurs », les features
  implémentées, la stack technique, l'explication d'ofelia, et la structure des dossiers.
  Renvoie vers `lucas-trading/README.md` (workflow) et `deploy/README.md` (exploitation).
- **`CLAUDE.md`** — réécrit pour Claude Code : commandes réelles, architecture (le chemin de
  code partagé `core/engine.py` et ses trois appelants), les pièges non devinables
  (`config.json` fait foi et non le fichier stratégie ; `indicators.timestamp` ≠
  `bars.timestamp` ; `core/broker.py` lève à l'import sans clés ; la réplique vectorisée peut
  diverger), et les conventions du projet (style, français/anglais, TODO/DONE).
- **`lucas-trading/README.md`** — ajout d'un pointeur vers le README racine et deploy.
- **Skills supprimés** : `bot-status` et `tune-config` — écrits pour l'ancienne base SQLite
  `bars.db` et le dossier `kerryghan_paper-trading/`, tous deux supprimés.
- **Skill `db-analyze` réécrit** pour PostgreSQL : connexion via `docker compose exec db psql`
  (la base n'expose aucun port hôte), schéma réel (`bars` / `indicators` / `trades`),
  découverte dynamique des symboles (le scorer change le top-5 chaque semaine), et nouvelle
  section P&L réalisé depuis la table `trades` (absente de l'ancien schéma). Les colonnes
  `regime`, `rsi`, `bb_*`, `macd_*` de l'ancienne version n'existent pas dans ce moteur de
  vote — les évals couvrent désormais ce cas.
- **`TODO.md`** — ajout d'une analyse des points d'amélioration (correctness/risque,
  duplication réintroduite, base de données, dépendances/build, ergonomie/dérive docs).

## 2026-07-15 — Convention de commits et releases automatisées

Reprise de la règle de commits d'un autre projet (JS/Husky/commitlint/release-please),
adaptée à la stack Python/uv d'ici.

- **`.claude/rules/commits.md`** (nouveau) — Conventional Commits : les 9 types autorisés et
  leur effet sur la version, les breaking changes (`!` ou `BREAKING CHANGE:`), la liste des
  scopes, l'interdiction de `--no-verify`, et les critères Major/Minor/Patch. La section
  « CHANGELOG → modal in-app » de la règle d'origine a été retirée : sans équivalent ici.
- **Scopes** = les modules de premier niveau (`core`, `backtest`, `live`, `strategies`, `web`,
  `tools`, `deploy`, `config`, `docs`) plus `infra` pour le stack conteneur/dépendances de la
  racine.
- **Hook `commit-msg`** — commitizen via le framework `pre-commit` (`.pre-commit-config.yaml`),
  l'équivalent Python de Husky. `[tool.commitizen.customize].schema_pattern` dans
  `pyproject.toml` valide **aussi les scopes** et retire les types `style` / `revert` / `bump`
  que commitizen autorise par défaut. Merge et revert restent exemptés.
  À activer une fois par clone : `uv run pre-commit install`.
- **Aucun hook au stade `pre-commit`** — pas de linter ni de tests dans le repo, contrairement
  au projet d'origine (eslint / prettier / vitest).
- **release-please** (`.github/workflows/release-please.yml`, `release-please-config.json`,
  `.release-please-manifest.json`) — `release-type: python` : bump du `version` de
  `pyproject.toml` et génération de `CHANGELOG.md` par PR de release sur `main`. Premier
  workflow GitHub Actions du repo. `bump-minor-pre-major: false` — le premier breaking change
  sortira donc en `1.0.0` et non en `0.2.0`.
- **Token** : `GITHUB_TOKEN` par défaut, et non un PAT (contrairement à l'exemple du README de
  release-please). Conséquence : la case *Settings → Actions → General → Allow GitHub Actions
  to create and approve pull requests* doit être cochée une fois — sur un repo de compte
  perso, les workflows ne peuvent pas créer de PR par défaut. Un PAT échapperait à cette
  restriction : à reconsidérer si le repo gagne une CI qui doit tourner sur les PR de release
  (les PR créées par `GITHUB_TOKEN` ne déclenchent pas de workflow). Détaillé en commentaire
  en tête du workflow.
- **`CLAUDE.md`** — renvoi vers la nouvelle règle dans *Conventions*, et correction de la note
  « no `.pre-commit-config.yaml` » devenue fausse.
