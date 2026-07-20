---
name: security-checklist
description: This repo's security hotspots and the rules for reviewing them — the .env / Alpaca-key handling, the /api/config remote-write endpoint, the import-time credential check, self-signed TLS + shared basic-auth, and SQL construction in core/db.py. Load when doing any security review, threat-modelling, or audit of the trading bot, and before writing a report to docs/.security-reports/.
---

# Security checklist — TradingBot

This is a paper-trading bot that holds **live broker credentials** and exposes a **remotely writable config** on a **public repository**. Those three facts drive every item below. Review against this list; it is not exhaustive, but these are the spots that have bitten before or are structurally fragile.

## Handling secrets — never exfiltrate

The single hard rule: **never read, echo, log, or write the *values* of secrets.** Verify how a secret is *handled* (is it gitignored, is it passed safely, is it logged by accident) without ever surfacing the secret itself into the transcript, a report, or a commit.

- `.env` (repo root) holds `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` today and will hold `TOTP_SECRET` after [#4]. `settings.json` denies the Read tool on `**/.env` — do not route around that with `cat` / `Get-Content` to see values. Confirm `.env` is gitignored and that no key is hardcoded anywhere in `src/`.
- Reports live in `docs/.security-reports/` and are **gitignored** — local to the analyst → fixer handoff, not published, because on a public repo a review that enumerates the fragile spots is a recon map. A report may name a weakness, its file/line, and the fix, but must still **not** contain a working exploit payload, a secret value, or a copy-pasteable attack. A severe, not-yet-public finding goes to a **private GitHub Security Advisory**, not a report file.

## The five hotspots

1. **`/api/config` is a remote write with no app auth.** The dashboard's Configuration tab POSTs to `/api/config`, rewriting `config/config.json` (active signals, thresholds, stop-loss), which the live bot hot-reloads within ~30 s. The only gate is nginx basic-auth (`deploy/docker/nginx.conf`); Flask itself authenticates nothing. Check: is the endpoint reachable without auth on the compose network (port 8501 direct)? Does it validate input, or write arbitrary JSON? Is there a demo-mode path that still writes the real file? Tracked in [#4].

2. **Self-signed TLS + one shared password.** `deploy/docker/init_secrets.sh` mints a self-signed cert and a single shared `.htpasswd`. Self-signed means a MITM can ride the session after a valid login — so 2FA alone ([#4]) does not close it. Check the cert handling and whether any real secret rides the unverified channel. Tracked in [#5].

3. **Import-time credential check in `core/broker.py`.** It raises `RuntimeError` at *import* when Alpaca keys are absent. Security-relevant because it couples "can this module be imported" to "are live secrets present" — any code path or test that imports `live.bot` / `live.scorer` needs real keys in the environment, which pushes people toward putting secrets where they should not be. Flag attempts to work around it by hardcoding or by committing a populated `.env`.

4. **SQL construction in `core/db.py`.** Three tables (`bars`, `indicators`, `trades`). Verify every query uses parameterised placeholders, never f-string / `%`-interpolation of untrusted values (symbols, timestamps, anything arriving from the web layer). Timestamps are `TEXT` and symbols flow in from config and the API — treat both as untrusted at the query boundary.

5. **The web layer talks to Alpaca over raw `requests`.** `web/server/data.py` builds its own Alpaca auth headers instead of going through `core/broker.py`. Check that credentials are read from the environment (not logged, not sent anywhere but Alpaca), that TLS verification is on, and that error paths do not leak the key in a message or stack trace.

## Public-repo blast radius

Because the repo is public: no secret, private URL, internal hostname, or exploit detail should ever be committed. When reviewing a diff, check that the change itself does not commit any of these — a leaked key in git history is compromised even if later removed.

## How a review runs

Two agents, split so analysis can never quietly edit code:

1. `security-analyst` (read-only) invokes `/security-review` on the pending diff, walks this checklist against the changed files and their blast radius, and writes findings to `docs/.security-reports/<topic>-<YYYY-MM-DD>.md` — ranked by severity, each with `file:line` and a concrete fix, within the disclosure limits above.
2. The user reviews that report. On approval, `security-fixer` applies the proposed fixes. The confirmation happens in the main conversation, because a subagent cannot prompt the user itself.

Links like [#4] / [#5] point at the GitHub issues that track the fixes for these hotspots; surface the hotspot, let the issue track the work.
