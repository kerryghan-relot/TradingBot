# Security reports

Reports produced by the `security-analyst` agent (`.claude/agents/security-analyst.md`). One file per review, `<topic>-<YYYY-MM-DD>.md`, findings ranked most-severe first with `file:line` and a proposed fix. The analyst is read-only; once a report here is approved, the `security-fixer` agent applies the fixes.

These are **committed** so collaborators share the review history. The repository is **public**, so a report must never contain a working exploit, a secret value, or a copy-pasteable attack — a weakness, its location, and its fix, no more. A severe finding that is not already public goes to a private GitHub Security Advisory instead of a file here.
