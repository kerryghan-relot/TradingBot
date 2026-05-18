# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this folder.

## Running the bot

```bash
# Multi-asset regime-aware bot (current main version)
python crypto-trader-v1.py

# Original single-asset RSI-only bot
python btc_rsi_trader.py
```

Stop with `Ctrl+C` — this sends a proper WebSocket close frame. Closing the terminal window instead leaves an Alpaca connection slot open, causing `connection limit exceeded` on the next start.

Credentials go in `.env` (never commit this file):
```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
```

## Architecture (`crypto-trader-v1.py`)

The bot listens to Alpaca's WebSocket for 1-minute OHLCVT bars on **BTC/USD** and **ETH/USD** and runs a regime-aware signal engine on each bar.

**Data flow per bar** (`CryptoBot.on_bar`):
1. Hot-reload `config.json`
2. Persist raw OHLCVT bar to `bars.db` (before any signal logic)
3. Append close + volume to the asset's rolling `deque`
4. Call `_evaluate()` → compute indicators → check stop-loss → classify regime → generate signal → submit order → persist indicators

**Two classes:**
- `AssetState` — isolated rolling state (closes deque, volumes deque, position flag, entry price) for one symbol. The bot holds one per symbol in `CryptoBot.assets`.
- `CryptoBot` — orchestrator that owns the Alpaca clients, SQLite connection, and config. Routes each incoming bar to the correct `AssetState`.

**Regime logic in `_evaluate()`:**
- `bb_width < bb_width_threshold` → **RANGING**: requires RSI extreme + BB band touch + volume spike
- `bb_width ≥ bb_width_threshold` → **TRENDING**: requires EMA crossover + MACD confirmation + volume spike
- Stop-loss always runs first, bypassing regime logic entirely

**Startup warmup elimination:** on `__init__`, the bot queries the last `DEQUE_SIZE` (200) bars per symbol from `bars.db` and preloads them into the deques, so indicators compute on the very first live bar.

## Live config tuning

Edit `config.json` while the bot is running — changes are picked up on the next bar tick with no restart. The file is auto-created with defaults on first run. On a JSON parse error (e.g. mid-save), the bot silently retains the last valid config.

## Database (`bars.db`)

Two tables with composite primary key `(symbol, timestamp)`:
- `bars` — raw immutable OHLCVT, written before indicator computation
- `indicators` — derived snapshot (all indicator values + `regime` + `signal`), written after `_evaluate()`

All writes use `INSERT OR IGNORE` so duplicate bars on reconnect are silently skipped.

## Key constraints

- `in_position` is in-memory only — does not survive a restart. The bot always starts flat, regardless of real open positions.
- `PAPER = True` is hardcoded in the bot; switching to live trading requires a code change and a non-paper API key.
- All indicator functions are pure (no side effects) and operate on `list[float]` with oldest value first.
