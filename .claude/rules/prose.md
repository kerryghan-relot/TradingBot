---
paths:
  - "**/*.{md,txt}"
  - "*.{md,txt}"
---

# Writing prose

## Never hard-wrap

One paragraph is one line, one bullet is one line — however long. Editors soft-wrap. A hard break makes a one-word change re-diff the whole paragraph.

Prose has no column limit. The 80 cols in `code-style.md` are Python source only.

Exempt: code blocks, tables, frontmatter.

Applies to every `.md` and `.txt` here, and to commit bodies — which this rule cannot reach, since no file is opened when writing one. See `commits.md`.

## Be concise

Cut anything that doesn't change what the reader does next. Prefer the shorter word, the shorter sentence, no preamble.

`TODO.md` / `DONE.md` bullets: 2 sentences maximum. Link an issue or a commit instead of explaining at length.
