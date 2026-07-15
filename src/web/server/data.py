"""Read-only data loaders for the web dashboard.

Pull live state from PostgreSQL (bars, indicators, trades) and from
the Alpaca paper account (balance, open positions, portfolio history).
Every loader degrades gracefully: an unreachable database, absent API
keys or a network error yields an empty result rather than an
exception, so ``app.py`` can fall back to demo data section by section.
"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import requests

from core import db
from core.constants import LOG_FILE

CRYPTO_BASES: set[str] = {"BTC", "ETH"}
ALPACA_PAPER_URL: str = "https://paper-api.alpaca.markets"

NAMES: dict[str, str] = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "NVDA": "Nvidia",
    "AAPL": "Apple", "TSLA": "Tesla", "MSFT": "Microsoft",
    "AMZN": "Amazon", "GOOGL": "Alphabet", "META": "Meta",
    "AMD": "AMD", "SPY": "S&P 500 ETF", "QQQ": "Nasdaq ETF",
}


# ── Symbol helpers ────────────────────────────────────────────────────

def base_symbol(symbol: str) -> str:
    """Return the display ticker, stripping any ``/USD`` quote suffix."""
    return symbol.split("/")[0]


def is_crypto(symbol: str) -> bool:
    """Return True when the symbol is a crypto pair (BTC/ETH)."""
    return "/" in symbol or base_symbol(symbol) in CRYPTO_BASES


def display_name(symbol: str) -> str:
    """Return a human-friendly instrument name for a symbol."""
    return NAMES.get(base_symbol(symbol), base_symbol(symbol))


# ── Database access ───────────────────────────────────────────────────

def db_available() -> bool:
    """Return True when the database is reachable and holds ``bars``.

    Before the bot has created the schema (or when Postgres is
    unreachable) this returns False, so ``app.py`` falls back to demo
    data — the same behaviour the old on-disk check produced.
    """
    try:
        conn = _connect()
        ok = _table_exists(conn, "bars")
        conn.close()
        return ok
    except psycopg.Error:
        return False


def _connect() -> psycopg.Connection:
    """Open a read-only PostgreSQL connection with dict-row access."""
    return db.connect(read_only=True)


def _table_exists(conn: psycopg.Connection, name: str) -> bool:
    """Return True when a table called ``name`` exists in the schema."""
    row = conn.execute(
        "SELECT to_regclass(%s) AS reg", (name,)
    ).fetchone()
    return bool(row and row["reg"] is not None)


# ── Bot health ────────────────────────────────────────────────────────

def bot_status() -> dict:
    """Infer the bot's health from the freshness of the latest bar.

    Returns:
        dict: ``{"state": "active"|"paused"|"error", "label": str}``.
            ``active`` when a bar landed in the last 10 minutes,
            ``error`` when the log tail shows a recent traceback,
            ``paused`` otherwise (or when no data exists yet).
    """
    if not db_available():
        return {"state": "paused", "label": "Aucune donnée"}
    try:
        conn = _connect()
        if not _table_exists(conn, "bars"):
            conn.close()
            return {"state": "paused", "label": "En attente"}
        row = conn.execute("SELECT MAX(timestamp) AS ts FROM bars").fetchone()
        conn.close()
        if not row or not row["ts"]:
            return {"state": "paused", "label": "En attente"}
        last = datetime.fromisoformat(row["ts"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        age = datetime.now(UTC) - last
        if _log_has_recent_error():
            return {"state": "error", "label": "Erreur détectée"}
        if age <= timedelta(minutes=10):
            return {"state": "active", "label": "Bot actif"}
        mins = int(age.total_seconds() // 60)
        return {"state": "paused", "label": f"Silencieux {mins} min"}
    except psycopg.Error:
        return {"state": "error", "label": "Erreur base"}


def _log_has_recent_error() -> bool:
    """Return True when the tail of ``bot.log`` shows a traceback."""
    if not LOG_FILE.exists():
        return False
    try:
        tail = LOG_FILE.read_text(errors="ignore").splitlines()[-40:]
    except OSError:
        return False
    return any(
        "Traceback" in ln or " ERROR " in ln or "CRITICAL" in ln
        for ln in tail
    )


# ── Tickers (latest price + day change) ───────────────────────────────

def tickers(symbols: list[str]) -> list[dict]:
    """Return the latest price and 24 h change for each requested symbol.

    The change compares the newest close against the close closest to
    24 hours earlier.  Symbols with no bars are skipped.

    Args:
        symbols (list[str]): Symbols to report, e.g. ``["BTC/USD"]``.

    Returns:
        list[dict]: One dict per symbol with keys ``sym``, ``name``,
            ``price``, ``chgPct``, ``isCrypto``.  Empty if no data.
    """
    if not db_available():
        return []
    out: list[dict] = []
    try:
        conn = _connect()
        if not _table_exists(conn, "bars"):
            conn.close()
            return []
        for symbol in symbols:
            rows = conn.execute(
                "SELECT timestamp, close FROM bars WHERE symbol = %s "
                "ORDER BY timestamp DESC LIMIT 1600",
                (symbol,),
            ).fetchall()
            if not rows:
                continue
            price = rows[0]["close"]
            newest = datetime.fromisoformat(rows[0]["timestamp"])
            ref = price
            for r in rows:
                ts = datetime.fromisoformat(r["timestamp"])
                if newest - ts >= timedelta(hours=24):
                    ref = r["close"]
                    break
            else:
                ref = rows[-1]["close"]
            chg = (price - ref) / ref * 100 if ref else 0.0
            out.append({
                "sym": base_symbol(symbol),
                "name": display_name(symbol),
                "price": price,
                "chgPct": chg,
                "isCrypto": is_crypto(symbol),
            })
        conn.close()
    except psycopg.Error:
        return []
    return out


# ── Journal (bot decisions) ───────────────────────────────────────────

def journal(open_symbols: set[str], limit: int = 40) -> list[dict]:
    """Return recent bot decisions from executed trades and signals.

    Executed orders (``trades`` table) become BUY/SELL rows; strong but
    un-executed signals (``indicators`` table) become HOLD rows.  A
    trade is marked ``Ouvert`` when its symbol still has an open
    position, otherwise ``Fermé``.

    Args:
        open_symbols (set[str]): Base tickers currently held.
        limit (int, optional): Max rows to return. Defaults to 40.

    Returns:
        list[dict]: Decision rows sorted newest-first.
    """
    if not db_available():
        return []
    rows: list[dict] = []
    try:
        conn = _connect()
        if _table_exists(conn, "trades"):
            for r in conn.execute(
                "SELECT symbol, timestamp, side, qty, price, reason "
                "FROM trades ORDER BY timestamp DESC LIMIT %s",
                (limit,),
            ).fetchall():
                sym = base_symbol(r["symbol"])
                buy = r["side"].upper() == "BUY"
                held = sym in open_symbols
                rows.append({
                    "time": _fmt_time(r["timestamp"]),
                    "ts": r["timestamp"],
                    "sym": sym,
                    "cat": "Crypto" if is_crypto(r["symbol"]) else "Action",
                    "signal": "Achat" if buy else "Vente",
                    "reason": r["reason"] or "vote",
                    "entry": r["price"],
                    "size": _fmt_size(r["symbol"], r["qty"]),
                    "status": "Ouvert" if (buy and held) else "Fermé",
                })
        conn.close()
    except psycopg.Error:
        return []
    rows.sort(key=lambda x: x["ts"], reverse=True)
    return rows[:limit]


def closed_trades(limit: int = 200) -> list[dict]:
    """Return closed round-trips from the ``trades`` table (SELL rows).

    Each SELL that carries an ``entry_price`` and ``pnl_pct`` is one
    completed trade.  Absolute P&L is derived from quantity and prices.

    Args:
        limit (int, optional): Max rows to return. Defaults to 200.

    Returns:
        list[dict]: Closed-trade rows, newest-first.
    """
    if not db_available():
        return []
    out: list[dict] = []
    try:
        conn = _connect()
        if not _table_exists(conn, "trades"):
            conn.close()
            return []
        for r in conn.execute(
            "SELECT symbol, timestamp, qty, price, entry_price, pnl_pct "
            "FROM trades WHERE side='SELL' AND entry_price IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT %s",
            (limit,),
        ).fetchall():
            entry = r["entry_price"]
            exit_px = r["price"]
            qty = r["qty"] or 0.0
            out.append({
                "sym": base_symbol(r["symbol"]),
                "cat": "Crypto" if is_crypto(r["symbol"]) else "Action",
                "side": "long",
                "entry": entry,
                "exit": exit_px,
                "size": qty,
                "pnl": (exit_px - entry) * qty,
            })
        conn.close()
    except psycopg.Error:
        return []
    return out


def trade_stats() -> dict:
    """Aggregate win rate, trade count and per-symbol P&L from trades.

    Returns:
        dict: ``{"wins", "losses", "trades", "winRate", "bySymbol",
            "realizedPnl"}``.  Zeroed when no closed trades exist.
    """
    empty = {
        "wins": 0, "losses": 0, "trades": 0, "winRate": 0.0,
        "bySymbol": {}, "realizedPnl": 0.0,
    }
    if not db_available():
        return empty
    try:
        conn = _connect()
        if not _table_exists(conn, "trades"):
            conn.close()
            return empty
        rows = conn.execute(
            "SELECT symbol, qty, price, entry_price, pnl_pct FROM trades "
            "WHERE side='SELL' AND pnl_pct IS NOT NULL"
        ).fetchall()
        conn.close()
    except psycopg.Error:
        return empty
    if not rows:
        return empty
    wins = sum(1 for r in rows if r["pnl_pct"] > 0)
    by_symbol: dict[str, float] = {}
    realized = 0.0
    for r in rows:
        pnl = (r["price"] - (r["entry_price"] or r["price"])) * (r["qty"] or 0)
        sym = base_symbol(r["symbol"])
        by_symbol[sym] = by_symbol.get(sym, 0.0) + pnl
        realized += pnl
    n = len(rows)
    return {
        "wins": wins,
        "losses": n - wins,
        "trades": n,
        "winRate": wins / n * 100 if n else 0.0,
        "bySymbol": by_symbol,
        "realizedPnl": realized,
    }


# ── Alpaca account / positions / equity ───────────────────────────────

def _alpaca_keys() -> tuple[str | None, str | None]:
    """Return the Alpaca API key id and secret from the environment."""
    return os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")


def alpaca_available() -> bool:
    """Return True when both Alpaca API credentials are present."""
    key, secret = _alpaca_keys()
    return bool(key and secret)


def _alpaca_headers() -> dict[str, str]:
    """Build the Alpaca REST auth headers from the environment."""
    key, secret = _alpaca_keys()
    return {"APCA-API-KEY-ID": key or "", "APCA-API-SECRET-KEY": secret or ""}


def account_and_positions() -> tuple[dict, list[dict]]:
    """Fetch account balance and open positions from Alpaca paper.

    Returns:
        tuple: ``(account, positions)``.  ``account`` carries equity,
            cash, last_equity and derived unrealized P&L; ``positions``
            is a list of open-position dicts.  Both empty on error or
            missing keys; ``account["_error"]`` is set on failure.
    """
    if not alpaca_available():
        return {}, []
    try:
        headers = _alpaca_headers()
        acct = requests.get(
            f"{ALPACA_PAPER_URL}/v2/account", headers=headers, timeout=8
        ).json()
        raw = requests.get(
            f"{ALPACA_PAPER_URL}/v2/positions", headers=headers, timeout=8
        ).json()
    except requests.RequestException as exc:
        return {"_error": str(exc)}, []
    if not isinstance(raw, list):
        return {"_error": str(acct)}, []

    def _f(obj: dict, key: str) -> float:
        val = obj.get(key)
        try:
            return float(val) if val is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    positions = [
        {
            "sym": base_symbol(p.get("symbol", "")),
            "name": display_name(p.get("symbol", "")),
            "cat": "Crypto" if is_crypto(p.get("symbol", "")) else "Action",
            "side": "short" if p.get("side") == "short" else "long",
            "entry": _f(p, "avg_entry_price"),
            "cur": _f(p, "current_price"),
            "size": _f(p, "qty"),
            "sizeStr": _fmt_size(p.get("symbol", ""), _f(p, "qty")),
            "marketValue": _f(p, "market_value"),
            "pnl": _f(p, "unrealized_pl"),
            "openedMs": 0,
        }
        for p in raw
    ]
    account = {
        "equity": _f(acct, "equity"),
        "cash": _f(acct, "cash"),
        "lastEquity": _f(acct, "last_equity"),
        "buyingPower": _f(acct, "buying_power"),
        "unrealizedPl": sum(p["pnl"] for p in positions),
    }
    return account, positions


def portfolio_history(period: str) -> list[float] | None:
    """Fetch the Alpaca equity curve for a dashboard period.

    Args:
        period (str): ``"day"``, ``"week"``, ``"month"`` or ``"all"``.

    Returns:
        list[float] | None: Equity values (nulls dropped), or ``None``
            when unavailable.
    """
    if not alpaca_available():
        return None
    span = {
        "day": ("1D", "5Min"),
        "week": ("1W", "1H"),
        "month": ("1M", "1D"),
        "all": ("1A", "1D"),
    }.get(period, ("1M", "1D"))
    try:
        resp = requests.get(
            f"{ALPACA_PAPER_URL}/v2/account/portfolio/history",
            headers=_alpaca_headers(),
            params={"period": span[0], "timeframe": span[1],
                    "intraday_reporting": "continuous"},
            timeout=8,
        ).json()
    except requests.RequestException:
        return None
    equity = resp.get("equity") if isinstance(resp, dict) else None
    if not equity:
        return None
    series = [float(v) for v in equity if v is not None]
    return series or None


# ── Formatting helpers ────────────────────────────────────────────────

def _fmt_time(ts: str) -> str:
    """Format an ISO timestamp as ``HH:MM:SS`` local-ish (UTC clock)."""
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except ValueError:
        return ts[-8:]


def _fmt_size(symbol: str, qty: float) -> str:
    """Format a position size with its unit (crypto ticker or shares)."""
    if is_crypto(symbol):
        num = f"{qty:.4f}".rstrip("0").rstrip(".")
        return f"{num} {base_symbol(symbol)}"
    return f"{qty:.0f} sh"
