# Python Code Style

Follow **PEP 8** and the **Google Python Style Guide**. The rules below capture
the project-specific decisions and the most commonly needed reminders.

## Type annotations

- Annotate all function signatures and module-level variables — no untyped public functions.
- Use Python 3.10+ union syntax: `X | Y` and `X | None` (never `Optional[X]` or `Union[X, Y]`).
- Use built-in generic types directly: `list[float]`, `dict[str, int]`, `tuple[float, ...]`
  (never `List`, `Dict`, `Tuple` from `typing`).

## Docstrings

- Use triple double-quotes `"""` on all non-trivial functions, classes, and modules.
- First line: one-sentence summary, ≤ 80 characters, imperative mood
  ("Compute the RSI value" not "Computes the RSI value").
- Follow with a blank line, then Google-style sections as needed:

```
Args:
    param_name (type): Description. Multi-line descriptions indent to
        align with the first line of the description.
    optional_param (type, optional): Description. Defaults to X.

Returns:
    type: Description of the return value.

Raises:
    ValueError: When and why this is raised.

Example:
    >>> result = my_function(42)
    >>> print(result)
    84
```

- Omit `self` from `Args`. Omit sections that don't apply.
- `@override` methods don't need docstrings unless behaviour differs materially.
- Attributes of a class are documented in the class docstring under `Attributes:`,
  not in `__init__`.

## Naming

| Kind | Convention | Example |
|------|-----------|---------|
| Functions & methods | `snake_case` | `compute_rsi` |
| Variables | `snake_case` | `avg_gain` |
| Classes | `PascalCase` | `CryptoBot` |
| Module-level constants | `UPPER_SNAKE_CASE` | `DEQUE_SIZE` |
| Internal / private members | `_single_underscore` prefix | `_evaluate` |

Never use single-character names except `i`, `j` (loop counters), `e` (caught exception),
`f` (file handle). Avoid `l`, `O`, `I` entirely (visual ambiguity with digits).

## Imports

Group imports in this order, separated by a blank line:

1. Standard library (`json`, `sqlite3`, `logging`, …)
2. Third-party packages (`alpaca`, `dotenv`, …)
3. Local modules

One import per line. Sort lexicographically within each group, ignoring case.
Never write `import os, sys` on one line.

## Formatting

- 4-space indentation — never tabs.
- Maximum line length: **80 characters** (docstring and comment text: 72 characters).
- Two blank lines around top-level function and class definitions.
- One blank line between method definitions inside a class.
- No trailing whitespace. No semicolons at line ends.
- Use f-strings for string interpolation (not `%` or `.format()`).
- Prefer implicit line continuation inside parentheses or brackets over backslashes.
- No mutable default arguments — use `None` and assign inside the body.
