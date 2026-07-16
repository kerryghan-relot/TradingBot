# GitHub workflow

Issues and branches. Commit messages, releases and the never-push rule live in `commits.md`.

## Read the comments before working an issue

Read the issue body **and its comments** before touching anything. Comments carry decisions that were never folded back into the body, and they are where the issue's real goal usually drifts to.

If anything is unsure or undecided after that, **interview the user** — ask until the goal is clear. Do not guess and do not encode a guess into code, a commit or an issue. An issue is allowed to record open questions; a silent assumption is not.

## Branch naming

Create branches with `gh issue develop`, never `git checkout -b`:

```bash
gh issue develop <n> --base main --name "<github-username>/<n>-<slug>" --checkout
```

- `<github-username>` — the full GitHub login (`kerryghan-relot`), not a shortened form.
- `<n>` — the issue number.
- `<slug>` — the issue title, lowercased, non-alphanumerics collapsed to single hyphens.

So issue #3 *Update claude settings* becomes `kerryghan-relot/3-update-claude-settings`.

`gh issue develop` is preferred over `git checkout -b` because it registers the branch as **linked** to the issue, which is what makes merging its PR close the issue automatically. `git checkout -b` creates an unlinked branch that looks identical and does not.

`--name` is not optional. GitHub's own *Create a branch* button names branches `<n>-<slug>` with no user prefix, and that default is not configurable — no repository, organisation or personal setting templates it. Passing `--name` is the only way to get this convention.

## Creating a branch still requires asking

`gh issue develop` writes a ref to `origin`. Branch actions need explicit human confirmation first — see *Claude asks before committing or branching* in `commits.md`. "Always use `gh issue develop`" settles **which command** creates a branch; it does not waive the prompt.

`.claude/settings.json` carries `ask` on `gh issue develop` for both the Bash and PowerShell tools.

## Permissions

Read-only subcommands are allowlisted in `.claude/settings.json`: `gh auth status`, `gh issue list`, `gh issue view`, `gh label list`, `gh pr list`, `gh pr view`, `gh pr diff`, `gh workflow list`, `gh workflow view`, `gh run list`, `gh run view`, `gh release list`, `gh release view`, `gh status`, and `gh help`.

The eight help topics (`accessibility`, `actions`, `environment`, `exit-codes`, `formatting`, `mintty`, `reference`, `telemetry`) are each allowlisted by name, because a topic is reachable **two** ways — `gh help <topic>` *and* `gh <topic> --help` — and `gh help:*` only covers the first. These are documentation-only commands with no executing subcommands, so the wildcard is safe.

`gh secret` and `gh ssh-key` are **denied** outright — they manage credentials, and `deny` outranks `ask`, so even their read forms are a hard no rather than a prompt.

The write verbs are in `ask`, so they prompt every time — `gh issue create` / `edit` / `close` / `reopen` / `delete`, `gh pr create` / `merge` / `close` / `edit`, `gh release create` / `delete`. Creating an issue or PR is never a silent side effect of some larger task; it stops for confirmation like a commit does. The writing `gh workflow` verbs (`run`, `enable`, `disable`) are not listed and prompt by default.

`gh api` is **never** allowlisted. It defaults to GET, but `--method POST` turns it into a write against any endpoint, and a prefix-matched permission rule cannot see a flag that far down the command. The same reasoning covers the whole family: the permission system matches command strings, so it cannot see a write reached indirectly. That is what these rules are for.
