---
paths:
  - "kerryghan_paper-trading/**"
---

# bars.db — Schema and Database Rules

SQLite database at `kerryghan_paper-trading/bars.db`.
All DB access goes through `sqlite3` — no ORM.

---

## Schema

### `bars` — raw, immutable OHLCVT data

One row per closed 1-minute candle per symbol. Written **before** any indicator
computation so the record survives even if signal logic fails.

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | TEXT | Asset identifier — `"BTC/USD"` or `"ETH/USD"` |
| `timestamp` | TEXT | ISO-8601 bar **open** time (from Alpaca's bar object) |
| `open` | REAL | First trade price of the minute |
| `high` | REAL | Highest trade price of the minute |
| `low` | REAL | Lowest trade price of the minute |
| `close` | REAL | Last trade price — consumed by all indicators |
| `volume` | REAL | Total quantity traded during the minute |

Primary key: `(symbol, timestamp)`

### `indicators` — derived analytical snapshot

One row per bar where indicators were successfully computed.
Linked to `bars` via foreign key — but see the timestamp warning below.

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | TEXT | Asset identifier |
| `timestamp` | TEXT | ISO-8601 **evaluation** time (`datetime.now(UTC)`) |
| `rsi` | REAL | RSI value (0–100) |
| `bb_mid` | REAL | Bollinger Band middle (rolling mean) |
| `bb_upper` | REAL | Upper band |
| `bb_lower` | REAL | Lower band |
| `bb_width` | REAL | `(upper − lower) / mid` — regime detector |
| `macd_line` | REAL | Fast EMA − slow EMA |
| `macd_signal` | REAL | EMA of the MACD line |
| `macd_hist` | REAL | `macd_line − macd_signal` |
| `ema_fast` | REAL | Fast EMA value |
| `ema_slow` | REAL | Slow EMA value |
| `volume_avg` | REAL | Rolling volume average over `volume_period` bars |
| `vol_spike` | INTEGER | `1` if volume spike detected, `0` otherwise |
| `regime` | TEXT | `"RANGING"` or `"TRENDING"` |
| `signal` | TEXT | `"BUY"`, `"SELL"`, or `"HOLD"` |

Primary key: `(symbol, timestamp)`
Foreign key: `(symbol, timestamp)` → `bars(symbol, timestamp)`

---

## Behavioral rules

**INSERT OR IGNORE on all writes.**
Both `save_bar()` and `save_indicators()` use `INSERT OR IGNORE`. This silently
discards duplicate rows that arrive on WebSocket reconnect. Never use `INSERT OR REPLACE`
or `INSERT OR UPDATE` — raw data is immutable once written.

**`save_bar()` must be called before `_evaluate()` in `on_bar()`.**
The raw OHLCVT record must hit the database before any signal logic runs. If
`_evaluate()` raises, the bar is still persisted and can be replayed.

**Shutdown order: `stream.stop()` → `conn.close()`.**
Stopping the stream first releases Alpaca's WebSocket connection slot immediately.
Reversing the order risks a `connection limit exceeded` error on the next restart.

**Never JOIN `bars` and `indicators` on `timestamp`.**
`bars.timestamp` is the bar's open time (from Alpaca). `indicators.timestamp` is
`datetime.now(UTC)` at evaluation time — always a few seconds later. A direct
equality JOIN will silently return zero rows. Query each table independently or
use a range/approximate match if cross-table lookups are needed.

**DDL trace callback is for `init_db()` only.**
`sqlite3.set_trace_callback(_ddl_trace)` is registered during schema setup and
removed immediately after. Do not re-enable it for per-bar DML — it would log
every INSERT and flood the log file.
