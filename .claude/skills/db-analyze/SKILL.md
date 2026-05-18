---
name: db-analyze
description: >
  Analyze the crypto trading bot's SQLite database (bars.db) and produce a structured
  per-symbol report. Use this skill whenever the user asks about bot performance, trade
  history, signal counts, regime distribution, volume spikes, or anything involving
  historical data from bars.db — even casually ("how many buys?", "show me the signals",
  "what's the regime breakdown?", "analyze my trading data", "check the database").
  Always prefer this skill over ad-hoc queries when the user wants a trading data summary.
---

# db-analyze

Produce a structured trading database report for each tracked symbol (BTC/USD and ETH/USD).
The database lives at `kerryghan_paper-trading/bars.db` relative to the project root.
Do not call any external APIs — everything comes from the database.

## Database schema

**bars** — raw OHLCVT candles. Columns: `symbol` (TEXT), `timestamp` (TEXT, ISO-8601 UTC),
`open`, `high`, `low`, `close`, `volume` (REAL). Primary key: `(symbol, timestamp)`.

**indicators** — derived snapshot per bar. Columns: `symbol`, `timestamp`, `rsi`, `bb_mid`,
`bb_upper`, `bb_lower`, `bb_width`, `macd_line`, `macd_signal`, `macd_hist`, `ema_fast`,
`ema_slow`, `volume_avg`, `vol_spike` (INTEGER 0/1), `regime` (TEXT: "RANGING"/"TRENDING"),
`signal` (TEXT: "BUY"/"SELL"/"HOLD"). Primary key: `(symbol, timestamp)`.

## How to query

Use the Bash tool with Python — it handles edge cases better than the sqlite3 CLI for
complex queries. Run from the project root. Example:

```bash
python -c "
import sqlite3
con = sqlite3.connect('kerryghan_paper-trading/bars.db')
# ... your queries ...
con.close()
"
```

If the database file is missing or a table has no rows, report that clearly (e.g.,
"bars.db not found — bot may not have run yet") rather than raising an error.

## Report structure

Produce the report for **BTC/USD** first, then **ETH/USD**. Use `##` headings per symbol
and `###` headings per section. After both symbols, add a **Summary** paragraph.

For each symbol, include these six sections:

### 1. Data coverage
From `bars`: total bar count, first timestamp, last timestamp.

```sql
SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM bars WHERE symbol = ?
```

### 2. Regime distribution
From `indicators`: count and % for RANGING and TRENDING.

```sql
SELECT regime, COUNT(*) FROM indicators WHERE symbol = ? GROUP BY regime
```

Present as a markdown table (Regime | Count | %).

### 3. Signal breakdown
From `indicators`: BUY, SELL, HOLD counts.

```sql
SELECT signal, COUNT(*) FROM indicators WHERE symbol = ? GROUP BY signal
```

Present as a markdown table (Signal | Count).

### 4. Volume spike rate
From `indicators`:
- % of bars with `vol_spike = 1`
- Of those spike bars, what % were BUY or SELL (vs HOLD)

This shows whether the volume gate is too strict or too permissive.

### 5. Recent BUY/SELL signals
Last 5 BUY or SELL signals from `indicators`. Note: the `bars` and `indicators` tables
use different timestamps (`bars` stores bar open time; `indicators` stores the evaluation
time, which is slightly later), so a direct JOIN will silently return 0 rows. Query
`indicators` directly instead:

```sql
SELECT timestamp, signal, rsi, bb_width, regime
FROM indicators
WHERE symbol = ? AND signal IN ('BUY', 'SELL')
ORDER BY timestamp DESC LIMIT 5
```

Present as a markdown table (Timestamp | Signal | RSI | BB Width | Regime).
Round numbers to 2 decimal places. If no signals exist, say so explicitly.

### 6. Last 24 hours
Compute the cutoff in Python:

```python
from datetime import datetime, timedelta, timezone
cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
```

Then query bar count and signal breakdown filtered by `timestamp >= cutoff`.
If no bars exist in the last 24h, say so — it likely means the bot isn't running.

## After both symbols

Write a short **Summary** (2–4 sentences) noting the most notable patterns: dominant
regime, signal frequency, whether volume spikes are rare or frequent, anything unusual.
