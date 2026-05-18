---
name: tune-config
description: >
  Analyze bars.db and config.json to surface calibration data that helps the user
  decide whether the bot's hyperparameter thresholds are well-tuned. Use this skill
  whenever the user asks about tuning, calibrating, or reviewing their bot's config —
  even informally ("are my thresholds right?", "should I change my RSI levels?",
  "is my bb_width_threshold set correctly?", "help me calibrate the bot",
  "review my config settings"). Always prefer this skill over ad-hoc analysis for
  config calibration questions. Never modifies any files — read-only.
---

# tune-config

Surface statistical data from `bars.db` to help the user judge whether their
hyperparameter thresholds are well-calibrated. Present data and observations —
do not prescribe specific values. The user decides what to change.

Files used (relative to project root):
- Config: `kerryghan_paper-trading/config.json`
- Database: `kerryghan_paper-trading/bars.db`

No external API calls. No file modifications.

## Step 1 — Read config.json

Use the Read tool on `kerryghan_paper-trading/config.json`. Display whatever keys are
present — do not assume a fixed set. The file may contain only a subset of parameters
(e.g., only RSI + bb_width_threshold), with the rest handled as hardcoded defaults in
the bot. Note any missing keys and state what the bot's default value would be (from
`DEFAULT_CONFIG` in `crypto-trader-v1.py`) so the user has the full picture.

Common keys to look for (show only those present):
- `bb_width_threshold`, `bb_period`, `bb_std`
- `rsi_period`, `rsi_oversold`, `rsi_overbought`
- `volume_factor`, `volume_period`
- `stop_loss_pct`, `order_qty_btc`, `order_qty_eth`, `order_qty`
- `macd_fast`, `macd_slow`, `macd_signal`
- `ema_fast`, `ema_slow`

## Step 2 — Run analysis queries

Use the Bash tool to run a single Python script that queries `bars.db` for both
symbols (BTC/USD and ETH/USD). Running everything in one script avoids repeated
subprocess overhead. Handle missing DB or empty tables gracefully — report "no data"
rather than crashing.

For each symbol, compute:

### A. Bollinger Band width distribution
Validates whether `bb_width_threshold` sits in a meaningful zone.

```python
cur.execute("""
    SELECT bb_width FROM indicators
    WHERE symbol=? AND bb_width IS NOT NULL
    ORDER BY bb_width
""", (sym,))
vals = [r[0] for r in cur.fetchall()]
# Compute: min, p25, median, p75, p90, max
# Also: what % of bars have bb_width < bb_width_threshold (= % time in RANGING)
```

### B. RSI at actual signals (RANGING regime only)
Shows whether RSI actually reaches the configured thresholds before a signal fires.
If BUY signals average RSI of 28 when the threshold is 30, that's fine. If they
average 29.9, the threshold may be so tight it almost never triggers.

```python
# BUY signals in RANGING: avg and min RSI
# SELL signals in RANGING: avg and max RSI
```

### C. Volume spike rate
If spikes are very rare (<5%), `volume_factor` may be too strict — signals are
being filtered out. If spikes are very common (>40%), the gate isn't selective enough.

```python
# Total indicator bars, spike count, spike %
# flag if < 5% or > 40%
```

### D. BUY signal frequency
Average, min, and max time between consecutive BUY signals (in hours). Very low
frequency (many days apart) might indicate filters are too strict; very high
(multiple per hour) might indicate too loose.

```python
# Fetch all BUY timestamps ordered ASC, compute gaps between consecutive ones
```

### E. SELL counts by regime
Helps estimate rough ratio of normal sells vs stop-loss sells (both stored as SELL).

```python
cur.execute("""
    SELECT regime, COUNT(*) FROM indicators
    WHERE symbol=? AND signal='SELL'
    GROUP BY regime
""", (sym,))
```

Note in the output that stop-loss SELLs and normal SELLs are both stored as 'SELL',
so the regime breakdown is an approximation.

## Step 3 — Format the report

Structure:

```
# Config Tune Analysis

## Current Config Values
(all parameters from config.json, grouped logically)

---

## BTC/USD

### A. BB Width Distribution
(min / p25 / median / p75 / p90 / max, current threshold, % time in RANGING)

### B. RSI at Signals (RANGING only)
(avg & min RSI for BUY signals; avg & max RSI for SELL signals; current thresholds)

### C. Volume Spike Rate
(total bars, spike count, spike %, current factor & period, flag if out of range)

### D. BUY Signal Frequency
(total BUY count, avg/min/max gap in hours)

### E. SELL Counts by Regime
(RANGING and TRENDING SELL counts; reminder about stop-loss approximation)

---

## ETH/USD

(same five sections)

---

## Observations

3–6 bullet points noting anything that stands out. Use language like
"may warrant review", "worth examining", "could indicate". Do not recommend
specific numeric values — the user makes that call.
```

## Important constraints

- Never call any external API or network endpoint
- Never write to config.json or bars.db
- If the database has no data for a symbol, say so clearly per section
- Do not prescribe values ("set bb_width_threshold to 0.008") — present data only
