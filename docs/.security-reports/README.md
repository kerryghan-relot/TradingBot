# Security reports

Working reports from the `security-analyst` agent (`.claude/agents/security-analyst.md`). One file per review, `<topic>-<YYYY-MM-DD>.md`, findings ranked most-severe first with `file:line` and a proposed fix. The analyst is read-only; once the user approves a report here, the `security-fixer` agent applies the fixes.

**Only this README is tracked.** Every report is gitignored — they are a local analyst → approval → fixer handoff, not a published deliverable, and this repo is public, so a review that enumerates where the bot is fragile does not belong in its history. Expect the directory to be empty on a fresh clone.

Even unpublished, a report must never contain a secret value or a copy-pasteable exploit — that discipline guards the transcript and any future sharing, not only the git history. A severe finding that is not already public goes to a private GitHub Security Advisory, not a file here.
