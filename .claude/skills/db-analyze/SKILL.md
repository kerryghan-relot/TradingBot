---
name: db-analyze
description: >
  Analyze the trading bot's PostgreSQL database and produce a structured per-symbol report.
  Use this skill whenever the user asks about bot performance, trade history, realised P&L,
  signal or vote counts, volume spikes, or anything involving stored trading data — even
  casually ("how many buys?", "show me the signals", "is the bot making money?", "analyze my
  trading data", "check the database"). Always prefer this skill over ad-hoc queries when the
  user wants a trading data summary. Read-only — never writes, never calls external APIs.
---

# db-analyze

Produce a structured report on the bot's stored trading data. Everything comes from
PostgreSQL — do not call Alpaca or any other API.

## Connecting

The database has **no host port mapping** (see `docker-compose.yml`), so it is reachable only
from inside the compose network. Query it through the `db` container:

```bash
docker compose exec -T db psql -U tradingbot -d tradingbot -c "SELECT ..."
```

Run from the **repo root** (where `docker-compose.yml` lives). Use `-t -A -F'|'` for
parseable output when you intend to post-process:

```bash
docker compose exec -T db psql -U tradingbot -d tradingbot -t -A -F'|' -c "SELECT ..."
```

If `POSTGRES_USER` / `POSTGRES_DB` are overridden in `.env`, substitute them. If the user runs
Postgres bare-metal instead (a `DATABASE_URL` pointing somewhere other than the `db` service),
query with psycopg from `lucas-trading/` instead:

```bash
python -c "
from core import db
with db.connect(read_only=True) as con:
    print(con.execute('SELECT ...').fetchall())
"
```

**Degrade gracefully.** If the stack is down, the database is unreachable, or a table is
empty, say so plainly ("the `db` container isn't running" / "no bars stored yet — the bot may
not have run") rather than surfacing a raw traceback.

## Schema

Defined in `lucas-trading/core/db.py`. Three tables:

**`bars`** — raw OHLCV candles, one row per closed 1-min bar per symbol.
`symbol` (TEXT), `timestamp` (TEXT, ISO-8601 UTC), `open`, `high`, `low`, `close`, `volume`
(DOUBLE PRECISION). PK `(symbol, timestamp)`.

**`indicators`** — per-bar vote snapshot.
`symbol`, `timestamp` (TEXT), `close`, `vol_avg` (DOUBLE PRECISION), `vol_spike` (INTEGER 0/1),
`buy_votes`, `sell_votes`, `n_signals` (INTEGER), `signal` (TEXT: `BUY`/`SELL`/`HOLD`).
PK `(symbol, timestamp)`.

**`trades`** — one row per order accepted by Alpaca.
`id` (BIGINT identity), `symbol`, `timestamp` (TEXT), `side` (TEXT: `BUY`/`SELL`), `qty`,
`price` (DOUBLE PRECISION), `reason` (TEXT), `order_id` (TEXT), `entry_price`, `pnl_pct`
(DOUBLE PRECISION — populated on exits only).

Three traps:

1. **Never join `bars` to `indicators` on `timestamp`.** `indicators.timestamp` is the
   *evaluation* time (`datetime.now(UTC)`), `bars.timestamp` is the bar close time. They
   differ by design and the join silently returns zero rows. Query each table separately.
2. **There is no `regime` column, and no `rsi`/`bb_*`/`macd_*`/`ema_*` columns.** This engine
   is a vote engine — it stores vote *counts*, not per-indicator values. If the user asks for
   a regime breakdown, tell them the bot doesn't track regimes (regime filtering exists only
   in the research script `backtest/vectorized/backtest_v2_regime_mr.py`, which is not
   persisted).
3. **Symbols are not fixed.** The universe is 30 candidates and `live/scorer.py` rewrites the
   traded top-5 every Sunday, so the symbol set changes over time. Never hard-code symbols —
   discover them:

```sql
SELECT symbol, COUNT(*) AS n FROM bars GROUP BY symbol ORDER BY n DESC
```

## Report structure

Cover every symbol that has data, ordered by bar count descending. If more than 8 symbols have
data, report the top 8 in full and list the rest in a single overflow table. Use `##` per
symbol and `###` per section. Round to 2 decimals. Lead the whole report with the P&L headline
— that is what the user actually wants to know.

For each symbol:

### 1. Data coverage
```sql
SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM bars WHERE symbol = %s
```
Report bar count, first and last timestamp. Flag if the last bar is more than a few hours old
(for stocks, account for market hours; crypto trades 24/7, so a stale crypto bar is a real
signal that the bot is down).

### 2. Vote / signal breakdown
```sql
SELECT signal, COUNT(*) FROM indicators WHERE symbol = %s GROUP BY signal
```
Markdown table (Signal | Count | %). Also report average `buy_votes` / `sell_votes` and the
typical `n_signals`, which tells you how close the strategy runs to its `vote_threshold`:

```sql
SELECT AVG(buy_votes), AVG(sell_votes), MAX(n_signals)
FROM indicators WHERE symbol = %s
```

### 3. Trades and realised P&L
The most important section — the old SQLite schema had no `trades` table, so this is where the
real answers live.

```sql
SELECT COUNT(*) FILTER (WHERE side = 'BUY')  AS buys,
       COUNT(*) FILTER (WHERE side = 'SELL') AS sells,
       COUNT(*) FILTER (WHERE pnl_pct > 0)   AS wins,
       COUNT(*) FILTER (WHERE pnl_pct <= 0)  AS losses,
       AVG(pnl_pct), SUM(pnl_pct), MIN(pnl_pct), MAX(pnl_pct)
FROM trades WHERE symbol = %s
```
Report entries, exits, win rate (wins / closed trades), average and total `pnl_pct`, best and
worst trade. Break exits down by `reason` — this separates stop-loss exits from signal exits:

```sql
SELECT reason, COUNT(*), AVG(pnl_pct)
FROM trades WHERE symbol = %s AND side = 'SELL' GROUP BY reason
```

### 4. Volume spike rate
```sql
SELECT AVG(vol_spike::float) AS spike_rate,
       COUNT(*) FILTER (WHERE vol_spike = 1 AND signal <> 'HOLD')::float
         / NULLIF(COUNT(*) FILTER (WHERE vol_spike = 1), 0) AS acted_on_rate
FROM indicators WHERE symbol = %s
```
Percentage of bars flagged as a spike, and what share of spike bars produced a BUY/SELL. Shows
whether the volume gate is too strict or too permissive.

**Caveat to mention if the symbol is crypto** (contains `/`): the research CSVs carry no
volume for crypto, so VolSpike and VWAP contribute nothing there in backtests — a live spike
rate on BTC/ETH has no backtested counterpart.

### 5. Recent activity
Last 5 non-HOLD decisions — query `indicators` directly, never joined:
```sql
SELECT timestamp, signal, close, buy_votes, sell_votes, n_signals
FROM indicators
WHERE symbol = %s AND signal IN ('BUY', 'SELL')
ORDER BY timestamp DESC LIMIT 5
```
And the last 5 actual trades:
```sql
SELECT timestamp, side, qty, price, reason, pnl_pct
FROM trades WHERE symbol = %s ORDER BY timestamp DESC LIMIT 5
```
Two markdown tables. If either is empty, say so explicitly.

### 6. Last 24 hours
Timestamps are ISO-8601 TEXT, so string comparison works and is index-friendly:
```sql
SELECT COUNT(*) FROM bars
WHERE symbol = %s AND timestamp >= %s   -- (now UTC - 24h).isoformat()
```
Report bar count plus the signal breakdown over the same window. No bars in 24 h for a crypto
symbol means the bot is almost certainly not running.

## Summary

Close with a short **Summary** (3–5 sentences): total realised P&L and win rate across all
symbols, which symbols carry the activity, how often the strategy actually fires versus holds,
whether stop-losses or signal exits dominate, and anything anomalous (a symbol with bars but
zero trades, a stale feed, a spike gate that never fires).
