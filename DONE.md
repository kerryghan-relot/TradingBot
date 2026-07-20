# Done

This file lists completed work and briefly explains what changed. Update it after every addition or significant change to the project.
Each point must be concise (max 2 sentences); link a commit for full context when needed.

## 2026-07-20 — `add-signal` skill + agent-authoring principle (issue #3)

- **`.claude/skills/add-signal/SKILL.md`** (new) — the full registration checklist for adding a signal type, spanning `core/signals.py` (`sig_*`, `warmup_needed`), `core/engine.py` (import, `evaluate_bar`, and `SignalState`/`start_bar` for stateful signals), `core/config.py` (`DEFAULT_CONFIG`) and `web/server/strategies.py` (`ALL_SIGNALS`/`EDITABLE`), plus the `py_compile → backtest.py` smoke test. Built because the drift it prevents has already shipped — the `EDITABLE` gap, still open in `TODO.md`.
- **No _bare_ Code Writer agent** (issue #3): a writer that only emits a diff compresses nothing (it must be reviewed in full regardless of author), so it was declined; the main thread implements for now, with a scope-locked, self-verifying build-loop agent (implement + `/simplify` + `/code-review` + tests, downstream of plan + `nemesis`) deliberately deferred to #9. The `add-signal` skill is the alternative the user preferred, `nemesis`-vetted before building.
- **Agent-authoring principle** (issue #3): `CLAUDE.md`'s Conventions gains a "Writing a new agent" bullet — generic method in the body, repo-specifics in a loaded skill/checklist — with `security-analyst` named as the deliberate repo-specific counter-example. Existing agents are not retrofitted.
- **`security-reports/` → `docs/.security-reports/`, now gitignored** (issue #3): the reports were committed for shared history, but on a public repo a report enumerating the bot's fragile spots is a recon map, so they become local analyst → fixer working notes (README tracked, reports ignored — same `/*` + `!` shape as `docs/.architecture-design/`). The two security agents, the `security-checklist` skill, `CLAUDE.md` and `.gitignore` were updated in lockstep.

## 2026-07-17 — Language convention + docs reorganisation

- **`.claude/rules/language.md`** (new) — formalises the split: English for machine- and developer-facing text (code, comments, docstrings, `logger` logs, READMEs, `TODO.md` / `DONE.md`, commits, DB), French for end-user-facing text (CLI output via `print`/`argparse`/`SystemExit`, dashboard UI strings, and domain docs). `CLAUDE.md`'s Language bullet now points here.
- **Technical docs translated to English**: `DONE.md`, `src/README.md`, `src/deploy/README.md`, and the root `README.md` references. In the `.py` code, comments, docstrings and `logger` messages are English; all CLI output (`print` / `argparse` / `SystemExit`) and Streamlit / `web/server` UI strings are French — several research scripts whose CLI output was originally English were standardised to French after a `nemesis` review flagged the inconsistency. The rule also requires English prose to quote French code references (e.g. sidebar page names) verbatim so Ctrl+F links them.
- **Docs promoted to a root `docs/`**: `src/docs/GUIDE_SIGNAUX_METHODES.md` → `docs/` (kept French — it explains the trading domain), joining the existing `docs/.architecture-design/`.
- **`archive/` promoted to the repo root** (`src/archive/` → `archive/`), and `REFACTOR_PLAN.md` moved into it. The archive is treated as frozen: its files, including the now-reverted French `REFACTOR_PLAN.md` (a historical document), are left in their original language.

## 2026-07-17 — Agents `software-architect` + `nemesis` (adversarial design loop)

- **`.claude/agents/software-architect.md`** (new) — senior architect under opus, **language-agnostic**: it reasons about boundaries, invariants and migration cost, not about Python idioms. It drafts into `docs/.architecture-design/` and does not implement (no `Edit` tool).
- **`.claude/agents/nemesis.md`** (new) — adversarial reviewer under sonnet, **generic**: you give it the path to a document (design, plan, migration) and it attacks its reasoning. Every objection must describe a concrete failure; if it finds nothing, it says so rather than padding.
- **Adjudication stays in the main conversation** — the architect does not grade the critique of its own work, and a supervisor agent was rejected since the main thread already fills that role. One round-trip at most, then the decision reaches the user.
- **Reserved for decisions that are expensive to reverse**: an ordinary architecture question is answered directly, without paying for two cold starts.
- **`docs/.architecture-design/`** — only the `README.md` is versioned (`docs/.architecture-design/*` then a `!` exception; the trailing `/` would have stopped git from descending into the folder). Drafts are written to be destroyed; a design worth keeping is promoted to its issue, `CLAUDE.md` or the code.
- **Tested twice on #6** (multi-tenant execution model, discarded work): nemesis found a false premise in the rejection of the process-per-user approach — a `:ro` mount of `docker.sock` does not prevent writes, and ofelia already does `job-exec` through it (`docker-compose.yml:34,57,103`).

## 2026-07-16 — Security agents (`security-analyst` + `security-fixer`) and write `gh` permissions

- **`.claude/agents/security-analyst.md`** (new, the repo's first agent) — security review under opus, **read-only** (no `Edit` tool): it runs `/security-review`, applies the `security-checklist` skill and writes a report into `security-reports/`. It never touches the code.
- **`.claude/agents/security-fixer.md`** (new) — applies the fixes from a report **already approved** by the user, one point at a time, without widening the scope. It neither commits nor pushes. The confirmation between the two happens in the main conversation, since a sub-agent does not have `AskUserQuestion`.
- **`.claude/skills/security-checklist/`** (new) — the repo's sensitive points: `.env` / Alpaca keys, the `/api/config` remote write, the import-time credential check, self-signed TLS + basic auth, and SQL construction in `core/db.py`. Complements `/security-review` (generic scanner) without duplicating it.
- **`security-reports/`** — versioned (shared history), but the repo is **public**: no exploit and no secret in a report, a severe non-public flaw goes through a private GitHub Security Advisory.
- **`.claude/settings.json`** — the write `gh` verbs (`issue create` / `edit` / `close` / `delete`, `pr create` / `merge` / `close`, `release create` / `delete`) move to `ask`: creating an issue or a PR now requires confirmation.

## 2026-07-16 — GitHub access (`gh`) and workflow rules

- **GitHub CLI installed** (`gh` 2.96.0, via winget) and authenticated over OAuth: the token lives in the Windows keychain rather than in a repo file. Claude can now read and create issues.
- **`.claude/settings.json`** — the read-only `gh` subcommands (`auth status`, `issue list` / `view`, `label list`, `pr list` / `view` / `diff`) move to `allow`, and `gh issue develop` to `ask`. `gh api` is deliberately kept off the list: `--method` turns it into a write that prefix matching cannot see.
- **`.claude/rules/github.md`** (new) — read an issue's comments before working on it, interview the user rather than guess, and create branches via `gh issue develop --name <login>/<number>-<slug>`. `git checkout -b` does not link the branch to its issue and therefore does not close it on merge.
- **`commits.md`** — `gh issue develop` added to the branch actions: the sanctioned way to create a branch, but it writes a ref to `origin` and therefore asks for confirmation like the others.
- **Open issues**: #4 (authentication + 2FA TOTP), #5 (real TLS via Certbot) and #6 (per-user config, multi-tenant), #6 being blocked by #4.

## 2026-07-15 — Renaming `lucas-trading/` → `src/`

- **Directory renamed** to `src/` via `git mv`, to follow the classic convention and drop the personal naming. No import changes: the packages (`core`, `live`, `web`, …) stay top-level inside the directory.
- **References updated**: `Dockerfile`, `docker-compose.yml`, `.gitignore`, `.dockerignore`, `.claude/launch.json`, the READMEs, `CLAUDE.md`, the `db-analyze` skill, the deployment scripts and the docstrings.
- **npm package** `lucas-trading-dashboard` → `tradingbot-dashboard`, in `package.json` and `package-lock.json`. Sync verified by `npm ci --dry-run`, on which the front build in the image depends.
- **`REFACTOR_PLAN.md`** keeps the original names (historical document) and now carries a note flagging the rename.
- **Verified**: `compileall` over all of `src/`, `core` / `strategies` / `web` imports from `src/`, and `docker compose config` which resolves the binds to `./src/…` correctly.

## 2026-07-15 — Docs writing conventions

- **No more forced line breaks** in markdown: a paragraph or a bullet fits on a single line, the editor handles the rendering. Rule added in `CLAUDE.md`, applied to `CLAUDE.md`, `README.md`, `TODO.md`, `DONE.md` and the `db-analyze` skill.
- **`TODO.md` / `DONE.md`** — conciseness rule added at the top (2 sentences per point maximum, long context goes into an issue or a commit) and existing descriptions shortened.

## 2026-07-15 — Documentation and skill cleanup (cb2f950)

- **`README.md` (root)** — the one-line placeholder becomes the overview: "one strategy, two engines" principle, features, stack, ofelia, structure. Points to `src/README.md` (workflow) and `deploy/README.md` (operations).
- **`CLAUDE.md`** — rewritten for Claude Code: real commands, the shared engine and its three callers, and the non-guessable traps (`config.json` wins over the strategy file, `indicators.timestamp` ≠ `bars.timestamp`, `core/broker.py` raises at import without keys).
- **Skills removed**: `bot-status` and `tune-config`, written for the old SQLite `bars.db` store and the `kerryghan_paper-trading/` directory, both since deleted.
- **`db-analyze` skill rewritten** for PostgreSQL: connection via `docker compose exec` (the database exposes no host port), real schema, dynamic symbol discovery and a realised P&L section. The `regime` / `rsi` / `bb_*` columns of the old version do not exist in this vote engine.
- **`TODO.md`** — improvement-point analysis added (correctness, duplication, database, build, docs drift).

## 2026-07-15 — Commit convention and automated releases (c375abc, 47dca39, c2b0b44)

- **`.claude/rules/commits.md`** (new) — Conventional Commits: allowed types, breaking changes, scopes, `--no-verify` ban, Major/Minor/Patch criteria. Rule carried over from another project (JS/Husky/commitlint) and adapted to the Python/uv stack.
- **Scopes** = the top-level modules (`core`, `backtest`, `live`, `strategies`, `web`, `tools`, `deploy`, `config`, `docs`) plus `infra` for the repo-root container stack and dependencies.
- **`commit-msg` hook** — commitizen via the `pre-commit` framework, with a `schema_pattern` that also validates the scopes. To be activated once per clone: `uv run pre-commit install`.
- **No hook at the `pre-commit` stage** — there is neither a linter nor tests in the repo, unlike the original project.
- **release-please** (`release-type: python`) — bumps the `version` in `pyproject.toml` and generates `CHANGELOG.md` via a release PR on `main`. `bump-minor-pre-major: false`: the first breaking change will ship as `1.0.0`.
- **`GITHUB_TOKEN` token** rather than a PAT, so the *Allow GitHub Actions to create and approve pull requests* box must be checked once. Detailed in a comment at the top of the workflow.
- **Dev dependencies out of the image** (47dca39) — `uv sync` was installing the dev group in the container even though no commit is written there.
- **Commits confirmed, push blocked** (c2b0b44) — permission rules in `.claude/settings.json`; `commits.md` carries the intent for indirect pushes.
