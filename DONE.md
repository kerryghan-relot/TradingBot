# Done

A short, high-level log of completed work — one line per change, newest first. The commit history and the issues hold the detail; this is just the main things worth knowing at a glance. Add a bullet after any significant change.

- 2026-07-20 — Added the `add-signal` skill (full signal-registration checklist) and a "Writing a new agent" convention in `CLAUDE.md`; a bare Code Writer agent was declined (deferred to #9).
- 2026-07-17 — Added `.claude/rules/language.md` (English for machine/dev text, French for end-user text) and promoted `docs/` and `archive/` to the repo root.
- 2026-07-17 — Added the `software-architect` + `nemesis` adversarial design loop, adjudicated by the main conversation and reserved for hard-to-reverse decisions.
- 2026-07-16 — Added the two-agent security pipeline (`security-analyst` read-only + `security-fixer`) and the `security-checklist` skill; write `gh` verbs moved to `ask`.
- 2026-07-15 — Renamed `lucas-trading/` → `src/` and the npm package to `tradingbot-dashboard`, with no import changes.
- 2026-07-15 — Adopted the no-hard-wrap markdown convention and the 2-sentence limit for `TODO.md` / `DONE.md`.
- 2026-07-15 — Rewrote `README.md`, `CLAUDE.md` and the `db-analyze` skill for the PostgreSQL vote engine; removed the stale `bot-status` and `tune-config` skills.
- 2026-07-15 — Added Conventional Commits, the commitizen `commit-msg` hook, and release-please for automated versioning and `CHANGELOG.md`.
