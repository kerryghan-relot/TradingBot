"""
Fake data generator to test the dashboard.
===========================================
Inserts realistic OHLCV bars + indicators into PostgreSQL
for all 30 symbols, without needing the bot to run.

Usage (from src/):
    python -m tools.seed_fake_data           # 500 bars per symbol
    python -m tools.seed_fake_data --bars 1000
    python -m tools.seed_fake_data --reset   # wipe the existing data
"""

import argparse
import math
import random
from datetime import datetime, timedelta, UTC

import psycopg

from core import db
from core.constants import CRYPTO_SYMBOLS

# ── Config ────────────────────────────────────────────────────────────────────

random.seed(42)  # reproducible

# Realistic reference prices (2025-2026 order of magnitude)
BASE_PRICES: dict[str, float] = {
    "AAPL":    213.0,
    "ABBV":    187.0,
    "AMD":     155.0,
    "AMZN":    198.0,
    "BAC":      44.0,
    "BTC/USD": 94_500.0,
    "COP":     108.0,
    "CVX":     153.0,
    "DIS":      97.0,
    "ETH/USD":  3_400.0,
    "GOOGL":   172.0,
    "GS":      528.0,
    "JPM":     236.0,
    "META":    582.0,
    "MRK":      94.0,
    "MS":      122.0,
    "MSFT":    440.0,
    "NFLX":    718.0,
    "NVDA":    137.0,
    "PLTR":     29.5,
    "PYPL":     76.0,
    "QQQ":     487.0,
    "ROKU":     66.0,
    "SNAP":     12.4,
    "SPY":     574.0,
    "SQ":       67.0,
    "TSLA":    316.0,
    "UBER":     76.0,
    "UNH":     309.0,
    "XOM":     112.0,
}

# 1-min volatility (as the std dev of the log-return)
VOLATILITY: dict[str, float] = {
    "BTC/USD":  0.0030,
    "ETH/USD":  0.0035,
    "TSLA":     0.0025,
    "NVDA":     0.0022,
    "PLTR":     0.0028,
    "SNAP":     0.0030,
    "ROKU":     0.0025,
    "AMD":      0.0020,
    "META":     0.0018,
    "NFLX":     0.0018,
    "SPY":      0.0008,
    "QQQ":      0.0010,
}
DEFAULT_VOL = 0.0014

CRYPTO: set[str] = CRYPTO_SYMBOLS

# Friday 2026-05-22 — last market day before the weekend
FRIDAY_CLOSE = datetime(2026, 5, 22, 20, 0, 0, tzinfo=UTC)   # 16:00 ET
FRIDAY_OPEN  = datetime(2026, 5, 22, 13, 30, 0, tzinfo=UTC)  # 09:30 ET
NOW          = datetime(2026, 5, 23, 10, 0, 0, tzinfo=UTC)   # Saturday morning


# ══════════════════════════════════════════════════════════════════════════════
#  Bar generation
# ══════════════════════════════════════════════════════════════════════════════

def _market_timestamps(n_bars: int) -> list[datetime]:
    """Generate n_bars 1-min timestamps during US market hours.

    Walks back into the past from FRIDAY_CLOSE, skipping nights
    and weekends.
    """
    result: list[datetime] = []
    # Generate starting from Friday evening and walking back
    t   = FRIDAY_CLOSE - timedelta(minutes=1)
    day = t.date()

    while len(result) < n_bars:
        market_open  = datetime(
            day.year, day.month, day.day, 13, 30, tzinfo=UTC
        )
        market_close = datetime(
            day.year, day.month, day.day, 20,  0, tzinfo=UTC
        )
        # Weekend skip (5=Sat, 6=Sun)
        if day.weekday() >= 5:
            day -= timedelta(days=1)
            continue

        bar_t = market_close - timedelta(minutes=1)
        while bar_t >= market_open and len(result) < n_bars:
            result.append(bar_t)
            bar_t -= timedelta(minutes=1)

        day -= timedelta(days=1)

    result.reverse()
    return result


def _crypto_timestamps(n_bars: int) -> list[datetime]:
    """Generate n_bars continuous 1-min timestamps up to NOW."""
    return [
        NOW - timedelta(minutes=(n_bars - 1 - i))
        for i in range(n_bars)
    ]


def generate_bars(symbol: str, n_bars: int) -> list[tuple]:
    """Generate n_bars of realistic OHLCV data via a random walk.

    Args:
        symbol: Symbol identifier (e.g. ``"AAPL"`` or ``"BTC/USD"``).
        n_bars: Number of bars to generate.

    Returns:
        list[tuple]: Rows ready for INSERT into ``bars``.
    """
    is_crypto = symbol in CRYPTO
    vol       = VOLATILITY.get(symbol, DEFAULT_VOL)
    price     = BASE_PRICES.get(symbol, 100.0)

    timestamps = (
        _crypto_timestamps(n_bars)
        if is_crypto else
        _market_timestamps(n_bars)
    )

    rows = []
    for ts in timestamps:
        log_ret = random.gauss(0, vol)
        open_p  = price
        close_p = open_p * math.exp(log_ret)
        intra   = abs(random.gauss(0, vol * 0.6))
        high_p  = max(open_p, close_p) * (1 + intra)
        low_p   = min(open_p, close_p) * (1 - intra)

        # Volume: higher on bars with a large move
        base_vol = (
            price * 0.5          if is_crypto
            else price * 2_000
        )
        volume = base_vol * (0.5 + abs(log_ret) / vol + random.expovariate(2))

        rows.append((
            symbol,
            ts.isoformat(),
            round(open_p,  4),
            round(high_p,  4),
            round(low_p,   4),
            round(close_p, 4),
            round(volume,  2),
        ))
        price = close_p

    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  Indicator generation
# ══════════════════════════════════════════════════════════════════════════════

def generate_indicators(
    bars: list[tuple],
    n_signals: int  = 5,
    threshold: int  = 2,
) -> list[tuple]:
    """Generate indicator rows with votes and BUY/SELL/HOLD signals.

    Args:
        bars      : Bars generated by ``generate_bars()``.
        n_signals : Total number of active signals.
        threshold : Vote threshold to trigger an order.

    Returns:
        list[tuple]: Rows ready for INSERT into ``indicators``.
    """
    rows        = []
    in_position = False

    for i, (symbol, ts_bar, _, _, _, close, volume) in enumerate(bars):
        # Evaluation timestamp = bar timestamp + 2 seconds (realistic)
        ts_eval = (
            datetime.fromisoformat(ts_bar) + timedelta(seconds=2)
        ).isoformat()

        vol_avg   = volume * random.uniform(0.5, 1.5)
        vol_spike = 1 if random.random() < 0.06 else 0

        # Warmup: no signal on the first 50 bars
        if i < 50:
            rows.append((
                symbol, ts_eval, round(close, 4),
                round(vol_avg, 2), 0, 0, 0, n_signals, "HOLD",
            ))
            continue

        rnd = random.random()

        if not in_position and rnd < 0.025:
            # Entry: enough BUY votes
            buy_v, sell_v = threshold, random.randint(0, threshold - 1)
            signal        = "BUY"
            in_position   = True

        elif in_position and rnd < 0.022:
            # Exit: enough SELL votes
            buy_v, sell_v = random.randint(0, threshold - 1), threshold
            signal        = "SELL"
            in_position   = False

        else:
            # HOLD: not enough votes
            buy_v  = random.randint(0, threshold - 1)
            sell_v = random.randint(0, threshold - 1)
            signal = "HOLD"

        rows.append((
            symbol, ts_eval, round(close, 4),
            round(vol_avg, 2), vol_spike,
            buy_v, sell_v, n_signals, signal,
        ))

    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  Writing to the database
# ══════════════════════════════════════════════════════════════════════════════

def reset_db(conn: psycopg.Connection) -> None:
    """Delete all existing data."""
    # indicators references bars → cascading TRUNCATE on both.
    conn.execute("TRUNCATE indicators, bars RESTART IDENTITY CASCADE")
    conn.commit()
    print("🗑️  Données existantes effacées.")


def seed(n_bars: int, reset: bool) -> None:
    """Main entry point: generate and insert the fake data."""
    conn = db.connect()
    db.init_schema(conn)

    if reset:
        reset_db(conn)

    symbols = list(BASE_PRICES.keys())
    total   = len(symbols)

    print(f"\n🌱 Génération de données fictives pour {total} symboles "
          f"({n_bars} barres chacun)…\n")

    for idx, symbol in enumerate(symbols, 1):
        print(f"  [{idx:2d}/{total}] {symbol:10s} ", end="", flush=True)

        bars = generate_bars(symbol, n_bars)
        inds = generate_indicators(bars)

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO bars "
                "(symbol, timestamp, open, high, low, close, volume) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (symbol, timestamp) DO NOTHING",
                bars,
            )
            cur.executemany(
                "INSERT INTO indicators "
                "(symbol, timestamp, close, vol_avg, vol_spike, "
                " buy_votes, sell_votes, n_signals, signal) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (symbol, timestamp) DO NOTHING",
                inds,
            )
        conn.commit()

        n_signals = sum(1 for r in inds if r[-1] in ("BUY", "SELL"))
        last_close = bars[-1][5]
        print(
            f"✅  {len(bars)} barres  |  "
            f"{n_signals:2d} signaux  |  "
            f"dernier prix : {last_close:>10.2f}"
        )

    # Summary
    n_bars_total = conn.execute(
        "SELECT COUNT(*) AS n FROM bars"
    ).fetchone()["n"]
    n_ind_total = conn.execute(
        "SELECT COUNT(*) AS n FROM indicators"
    ).fetchone()["n"]
    n_trades_total = conn.execute(
        "SELECT COUNT(*) AS n FROM indicators "
        "WHERE signal IN ('BUY','SELL')"
    ).fetchone()["n"]
    conn.close()

    print(
        f"\n✅  Terminé !\n"
        f"   Barres    : {n_bars_total:,}\n"
        f"   Indicateurs : {n_ind_total:,}\n"
        f"   Signaux BUY/SELL : {n_trades_total}\n"
        f"   DB : {db.safe_dsn()}\n"
    )
    print("Lance maintenant le dashboard web :\n"
          "   python -m web.run   (ou via docker compose)\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Génère des données fictives pour tester le dashboard."
    )
    parser.add_argument(
        "--bars", type=int, default=500,
        help="Nombre de barres par symbole (défaut : 500)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Efface les données existantes avant d'insérer",
    )
    args = parser.parse_args()
    seed(args.bars, args.reset)
