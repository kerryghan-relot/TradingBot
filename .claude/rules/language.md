# Language: English for the machine, French for the end-user

One question decides the language of any piece of text: **who reads it?**

- **The developer or the machine** (code, its history, its internal logs) → **English**.
- **The end-user** (what they see on screen or in a terminal, and the domain knowledge written for them) → their language, which here is **French**. Do not translate it.

## English only — developer- and machine-facing

- All code: identifiers (files, classes, functions, variables), comments, docstrings.
- **App logs** — messages emitted through `logging` (`logger.*`, `log.*`). These are for whoever operates the bot, not for the trader.
- Technical documentation: every README (repo root, `src/`, `deploy/`, `archive/`), `TODO.md`, `DONE.md`, and process/architecture docs under `docs/.architecture-design/`.
- Commit messages and titles (see `commits.md`).
- Anything crossing a machine boundary: table/column names, stored values, config keys.

## French — end-user-facing (do NOT translate)

- **CLI output**: `print(...)` text, `argparse` descriptions and `help=` strings, and the console error messages a user sees (`raise SystemExit(...)`, `print("Erreur …")`). Anyone running `python live.py` or `python -m tools.seed_fake_data` reads these.
- **UI strings**: Streamlit widget text in `backtest/dashboard.py`, and the payloads `web/server/` returns for display (agent names, roles, demo data). The React front and the dashboards speak French to their user.
- **Non-technical documentation** — the trading domain written for a human to learn from: `docs/GUIDE_SIGNAUX_METHODES.md` (the signals & methods guide), and any prose explaining a strategy, a signal, or a financial concept.

## The line inside a `.py` file, and the caveat

The same module mixes both. Translate its comments and docstrings to English; leave its `print`/`argparse`/`SystemExit` text and its UI string literals in French; write its `logger` calls in English. A comment explaining *how the code works* is English; a message *shown to the person running it* is French.

`archive/` holds frozen, superseded files kept for verification — leave them byte-for-byte as they are, French included. `archive/REFACTOR_PLAN.md` is a historical French document; do not translate it.

**Quote French code verbatim.** When an English comment or docstring *refers to* something that legitimately lives in French — a French identifier, a sidebar/UI label, a page name, a `print`/`SystemExit` message — keep that reference in its French form; do not translate it inline. The reference and its target must share one spelling so a plain-text search (Ctrl+F) links them. Example: `backtest/dashboard.py`'s English module docstring lists the sidebar pages by their exact French `PAGES` labels (`Stratégies Vote`, `Optimisation`, …), even though the docstring around them is English.

Match the file you are in, and fix a genuine mismatch (French log, English CLI prompt) rather than spreading it.
