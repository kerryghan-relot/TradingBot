---
paths:
  - "kerryghan_paper-trading/**"
---

# Signal Engine Rules

Invariants for `_evaluate()` and the trading signal pipeline in `crypto-trader-v1.py`.

---

## Execution order inside `_evaluate()` is fixed

The evaluation steps must always run in this order:

1. Warmup check — skip if insufficient bars
2. Compute all indicators
3. **Stop-loss check** — runs unconditionally before any regime or signal logic
4. Regime classification
5. Signal logic (RANGING or TRENDING)
6. Order submission
7. Indicator persistence

Never move the stop-loss check below step 3. It must bypass all signal logic and
exit immediately when triggered.

## All thresholds come from `self.cfg` — never hardcode them

Every hyperparameter (`rsi_oversold`, `bb_width_threshold`, `volume_factor`, etc.)
must be read from `self.cfg` at evaluation time. `config.json` is hot-reloaded on
every bar — hardcoding a value means it can't be tuned without a restart.

## Regime is determined solely by `bb_width`

```python
ranging = bb_width < cfg["bb_width_threshold"]
```

No other indicator contributes to regime classification. Do not add secondary
conditions to the regime gate.

## Volume spike is always the final confirmation gate

Both RANGING and TRENDING strategies require `vol_spike_detected` as their last
condition. A qualifying RSI + BB touch (or EMA cross + MACD) without a volume
spike must produce HOLD, not a trade.

## All conditions within a regime are required simultaneously

RANGING BUY requires **all three** at once: `rsi < rsi_oversold` AND `close ≤ bb_lower`
AND `vol_spike`. TRENDING BUY requires **all three**: `ema_crossed_up` AND `macd_bull`
AND `vol_spike`. There is no partial-match or scoring — if any condition is unmet,
the signal is HOLD.

## `in_position` is in-memory only — never persist it

The flag does not survive a restart. On restart the bot always starts flat regardless
of any real open positions on Alpaca. Do not attempt to persist `in_position` to
`bars.db` or `config.json` — the bot is intentionally stateless across sessions.

## Each `AssetState` instance is fully isolated

BTC and ETH state must never cross-contaminate. Do not share `closes`, `volumes`,
`in_position`, or `entry_price` between two `AssetState` instances. `CryptoBot.assets`
is the authoritative routing table — always look up the asset by `bar.symbol`.
