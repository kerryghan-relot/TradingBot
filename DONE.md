# Done

This file lists completed work and briefly explains what changed. Update it after every addition or significant change to the project.
Each point must be concise (max 2 sentences); link a commit for full context when needed.

## 2026-07-15 — Renommage `lucas-trading/` → `src/`

- **Dossier renommé** en `src/` via `git mv`, pour suivre la convention classique et abandonner le nommage personnel. Aucun import ne change : les paquets (`core`, `live`, `web`, …) restent de premier niveau à l'intérieur du dossier.
- **Références mises à jour** : `Dockerfile`, `docker-compose.yml`, `.gitignore`, `.dockerignore`, `.claude/launch.json`, les README, `CLAUDE.md`, le skill `db-analyze`, les scripts de déploiement et les docstrings.
- **Paquet npm** `lucas-trading-dashboard` → `tradingbot-dashboard`, dans `package.json` et `package-lock.json`. Synchronisation vérifiée par `npm ci --dry-run`, dont dépend le build du front dans l'image.
- **`REFACTOR_PLAN.md`** garde les noms d'origine (document historique) et porte désormais un encart signalant le renommage.
- **Vérifié** : `compileall` sur tout `src/`, imports `core` / `strategies` / `web` depuis `src/`, et `docker compose config` qui résout bien les binds vers `./src/…`.

## 2026-07-15 — Conventions de rédaction des docs

- **Plus de retour à la ligne forcé** dans le markdown : un paragraphe ou une puce tient sur une seule ligne, l'éditeur se charge du rendu. Règle ajoutée dans `CLAUDE.md`, appliquée à `CLAUDE.md`, `README.md`, `TODO.md`, `DONE.md` et au skill `db-analyze`.
- **`TODO.md` / `DONE.md`** — règle de concision ajoutée en tête (2 phrases par point maximum, le contexte long va dans une issue ou un commit) et descriptions existantes raccourcies.

## 2026-07-15 — Documentation et nettoyage des skills (cb2f950)

- **`README.md` (racine)** — le placeholder d'une ligne devient la vue d'ensemble : principe « une stratégie, deux moteurs », features, stack, ofelia, structure. Renvoie vers `src/README.md` (workflow) et `deploy/README.md` (exploitation).
- **`CLAUDE.md`** — réécrit pour Claude Code : commandes réelles, moteur partagé et ses trois appelants, et les pièges non devinables (`config.json` fait foi et non le fichier stratégie, `indicators.timestamp` ≠ `bars.timestamp`, `core/broker.py` lève à l'import sans clés).
- **Skills supprimés** : `bot-status` et `tune-config`, écrits pour l'ancienne base SQLite `bars.db` et le dossier `kerryghan_paper-trading/`, tous deux supprimés depuis.
- **Skill `db-analyze` réécrit** pour PostgreSQL : connexion via `docker compose exec` (la base n'expose aucun port hôte), schéma réel, découverte dynamique des symboles et section P&L réalisé. Les colonnes `regime` / `rsi` / `bb_*` de l'ancienne version n'existent pas dans ce moteur de vote.
- **`TODO.md`** — analyse des points d'amélioration ajoutée (correctness, duplication, base de données, build, dérive des docs).

## 2026-07-15 — Convention de commits et releases automatisées (c375abc, 47dca39, c2b0b44)

- **`.claude/rules/commits.md`** (nouveau) — Conventional Commits : types autorisés, breaking changes, scopes, interdiction de `--no-verify`, critères Major/Minor/Patch. Règle reprise d'un autre projet (JS/Husky/commitlint) et adaptée à la stack Python/uv.
- **Scopes** = les modules de premier niveau (`core`, `backtest`, `live`, `strategies`, `web`, `tools`, `deploy`, `config`, `docs`) plus `infra` pour le stack conteneur et les dépendances de la racine.
- **Hook `commit-msg`** — commitizen via le framework `pre-commit`, avec un `schema_pattern` qui valide aussi les scopes. À activer une fois par clone : `uv run pre-commit install`.
- **Aucun hook au stade `pre-commit`** — il n'y a ni linter ni tests dans le repo, contrairement au projet d'origine.
- **release-please** (`release-type: python`) — bump du `version` de `pyproject.toml` et génération de `CHANGELOG.md` par PR de release sur `main`. `bump-minor-pre-major: false` : le premier breaking change sortira en `1.0.0`.
- **Token `GITHUB_TOKEN`** plutôt qu'un PAT, donc la case *Allow GitHub Actions to create and approve pull requests* doit être cochée une fois. Détaillé en commentaire en tête du workflow.
- **Dépendances dev hors de l'image** (47dca39) — `uv sync` installait le groupe dev dans le conteneur alors qu'aucun commit n'y est rédigé.
- **Commits confirmés, push bloqué** (c2b0b44) — règles de permission dans `.claude/settings.json` ; `commits.md` porte l'intention pour les pushes indirects.
