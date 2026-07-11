"""
PostgreSQL access layer for lucas-trading.
==========================================
Single source of truth for the database connection and schema.  The
live bot writes here every minute; the web dashboard reads concurrently
from a separate process — PostgreSQL handles both natively, so no WAL
tuning is needed (unlike the previous SQLite ``bars.db``).

Connection settings come from the ``DATABASE_URL`` environment variable
(a standard ``postgresql://user:pass@host:port/dbname`` DSN).  A sane
default targets the ``db`` service defined in ``docker-compose.yml``.

Timestamps are stored as ISO-8601 ``TEXT`` (not ``TIMESTAMPTZ``): the
lexicographic order of ISO strings matches chronological order, so
``ORDER BY timestamp`` and ``datetime.fromisoformat`` keep working
exactly as they did under SQLite.
"""

import os

import psycopg
from psycopg.rows import dict_row

# Default targets the compose ``db`` service; override with DATABASE_URL.
DEFAULT_DSN: str = "postgresql://tradingbot:tradingbot@db:5432/tradingbot"


def get_dsn() -> str:
    """Return the PostgreSQL DSN from the environment.

    Returns:
        str: The value of ``DATABASE_URL`` if set, else ``DEFAULT_DSN``.
    """
    return os.getenv("DATABASE_URL", DEFAULT_DSN)


def safe_dsn(dsn: str | None = None) -> str:
    """Return the DSN with its password masked, for safe logging.

    Args:
        dsn (str, optional): DSN to mask. Defaults to ``get_dsn()``.

    Returns:
        str: The DSN with any ``:password@`` segment replaced by
            ``:***@``.  Returned unchanged when no credentials are
            present.
    """
    dsn = dsn or get_dsn()
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    creds, host = rest.split("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        creds = f"{user}:***"
    return f"{scheme}://{creds}@{host}"


def connect(
    *, autocommit: bool = False, read_only: bool = False
) -> psycopg.Connection:
    """Open a psycopg 3 connection with dict-row access.

    Args:
        autocommit (bool, optional): Commit each statement immediately.
            The live bot uses this to mirror SQLite's per-write commit
            semantics and to avoid the aborted-transaction pitfall (a
            failing statement no longer invalidates later ones).
            Defaults to False.
        read_only (bool, optional): Open the session in read-only mode
            (used by the dashboard). Defaults to False.

    Returns:
        psycopg.Connection: Open connection with ``row_factory`` set to
            ``dict_row`` so rows are accessed by column name.
    """
    conn = psycopg.connect(
        get_dsn(), autocommit=autocommit, row_factory=dict_row
    )
    if read_only:
        conn.read_only = True
    return conn


def init_schema(conn: psycopg.Connection) -> None:
    """Initialise the database schema (idempotent — safe on every start).

    Creates three tables:

    **bars** — raw, immutable OHLCVT market data.  One row per closed
    1-minute candle per symbol, written before any signal logic.

    **indicators** — per-bar snapshot of vote results, for post-hoc
    analysis of trade decisions.  Its ``timestamp`` is the *evaluation*
    time (``datetime.now(UTC)``), which deliberately differs from the
    bar close time stored in ``bars`` — so there is intentionally no
    foreign key between the two (the old SQLite schema declared one but
    SQLite never enforced it, and it could never have held).

    **trades** — one row per order accepted by Alpaca (BUY and SELL),
    with realised P&L on exits.  Local source of truth for per-trade
    performance analysis, independent of Alpaca's order history.

    ``bars`` and ``indicators`` each use ``(symbol, timestamp)`` as a
    composite primary key.

    Args:
        conn (psycopg.Connection): Open connection to the database.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bars (
            symbol     TEXT             NOT NULL,
            timestamp  TEXT             NOT NULL,
            open       DOUBLE PRECISION NOT NULL,
            high       DOUBLE PRECISION NOT NULL,
            low        DOUBLE PRECISION NOT NULL,
            close      DOUBLE PRECISION NOT NULL,
            volume     DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (symbol, timestamp)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indicators (
            symbol      TEXT             NOT NULL,
            timestamp   TEXT             NOT NULL,
            close       DOUBLE PRECISION,
            vol_avg     DOUBLE PRECISION,
            vol_spike   INTEGER,
            buy_votes   INTEGER,
            sell_votes  INTEGER,
            n_signals   INTEGER,
            signal      TEXT,
            PRIMARY KEY (symbol, timestamp)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            symbol      TEXT             NOT NULL,
            timestamp   TEXT             NOT NULL,
            side        TEXT             NOT NULL,
            qty         DOUBLE PRECISION NOT NULL,
            price       DOUBLE PRECISION NOT NULL,
            reason      TEXT             NOT NULL,
            order_id    TEXT,
            entry_price DOUBLE PRECISION,
            pnl_pct     DOUBLE PRECISION
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bars_symbol_ts
        ON bars (symbol, timestamp)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_indicators_symbol_ts
        ON indicators (symbol, timestamp)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts
        ON trades (symbol, timestamp)
    """)
    if not conn.autocommit:
        conn.commit()
