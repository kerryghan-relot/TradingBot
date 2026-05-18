---
name: bot-status
description: >
  Quick health-check for the paper-trading bot. Use this skill whenever the user
  asks if the bot is running, wants to check for errors, wants to see recent logs,
  or asks "is my bot okay?", "check the bot", "is there a problem?", "what's the
  bot doing?", "is the stream still active?", "check bot health", "any errors in
  the logs?". Always prefer this skill over manual log reading for bot health questions.
  Read-only — no writes, no API calls.
---

# bot-status

Perform a read-only health-check of the paper-trading bot and produce a compact,
scannable report. Goal: give the user a clear picture in under 30 seconds.

All paths are relative to the project root:
- Log: `kerryghan_paper-trading/bot.log`
- Database: `kerryghan_paper-trading/bars.db`
- Config: `kerryghan_paper-trading/config.json`

Do not write any files, modify the database, or make any external API calls.

---

## Check 1 — Log (`bot.log`)

Read the last 60 lines of `kerryghan_paper-trading/bot.log` using the Bash tool:

```bash
tail -n 60 kerryghan_paper-trading/bot.log
```

On Windows, use PowerShell if `tail` is unavailable:
```powershell
Get-Content kerryghan_paper-trading/bot.log -Tail 60
```

From those 60 lines, extract:
- **Every ERROR or WARN line** — show in full. These are the most urgent.
- **The single most recent bar-tick INFO line** — look for lines mentioning a symbol
  (BTC, ETH), a close price, or regime/signal keywords. This confirms the bot is
  still processing live data.

If the file doesn't exist: "bot.log not found — bot may never have been run."
If no errors/warnings: "No errors or warnings in the last 60 lines."
If no bar-tick line found: "No bar-tick line found — bot may not be receiving data."

---

## Check 2 — Data freshness (`bars.db`)

Use Python to query the most recent bar per symbol and compute how many minutes ago it arrived:

```python
import sqlite3, datetime, sys

db = "kerryghan_paper-trading/bars.db"
symbols = ["BTC/USD", "ETH/USD"]

try:
    con = sqlite3.connect(db)
    now = datetime.datetime.utcnow()
    for sym in symbols:
        row = con.execute(
            "SELECT timestamp, close FROM bars WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (sym,)
        ).fetchone()
        if not row:
            print(f"{sym}: no data in database")
        else:
            ts_str, close = row
            try:
                ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
                age = (now - ts).total_seconds() / 60
                stale = " *** STALE — stream may have dropped ***" if age > 5 else ""
                print(f"{sym}: last bar {age:.1f} min ago  close={close:.2f}{stale}")
            except Exception as e:
                print(f"{sym}: could not parse timestamp ({ts_str}): {e}")
    con.close()
except FileNotFoundError:
    print("bars.db not found — bot has not run yet")
except Exception as e:
    print(f"DB error: {e}")
```

A bar older than 5 minutes during market hours almost certainly means the WebSocket
stream dropped. Flag it clearly — the user needs to restart the bot.

---

## Check 3 — Active config (`config.json`)

Read `kerryghan_paper-trading/config.json`. The file may only contain a subset of
parameters — display whatever keys are present and omit groups that have no matching
keys. For any missing key that the bot uses, note the hardcoded default from
`DEFAULT_CONFIG` in `crypto-trader-v1.py` (e.g., `macd_fast=12`, `ema_fast=9`,
`volume_factor=1.5`). Group present keys as:

- **Position sizes**: `order_qty` / `order_qty_btc` / `order_qty_eth`, `stop_loss_pct`
- **RSI**: `rsi_period`, `rsi_oversold`, `rsi_overbought`
- **Bollinger Bands**: `bb_period`, `bb_std`, `bb_width_threshold`
- **MACD**: `macd_fast`, `macd_slow`, `macd_signal`
- **EMA cross**: `ema_fast`, `ema_slow`
- **Volume**: `volume_factor`, `volume_period`

If the file doesn't exist: "config.json not found — bot will use hardcoded defaults."

---

## Output format

```
## Log
Errors/Warnings: [lines, or "None"]
Last bar-tick:   [line, or "None found"]

## Data freshness
  BTC/USD: last bar N.N min ago  close=XXXXX.XX  [*** STALE ***]
  ETH/USD: last bar N.N min ago  close=XXXX.XX

## Active config
  Position sizes : BTC=0.001  ETH=0.01  stop-loss=2.0%
  RSI            : period=14  oversold=30  overbought=70
  Bollinger Bands: period=20  std=2.0  width_threshold=0.65%
  MACD           : fast=12  slow=26  signal=9
  EMA cross      : fast=9  slow=21
  Volume         : factor=1.5×  period=20
```

Keep it tight — this is a glance, not a deep audit.
