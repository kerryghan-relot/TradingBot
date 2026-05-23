"""
Fetch 3 years of 5-min OHLCV data from the Twelve Data API.
============================================================

Strategy: download in chunks of ~5 000 bars, resume if interrupted,
then concatenate into a single sorted CSV.

Requires the environment variable TWELVE_DATA_API_KEY.
"""

import csv
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

API_KEY: str | None = os.getenv("TWELVE_DATA_API_KEY")
INTERVAL: str = "5min"
BARS_PER_CHUNK: int = 5_000
MINUTES_PER_BAR: int = 5
PAUSE_BETWEEN_CALLS: int = 15  # seconds (Twelve Data rate limit)


def symbol_to_filename(symbol: str) -> str:
    """
    Convert a ticker symbol to a safe filename stem.

    Args:
        symbol (str): Ticker, e.g. ``"BTC/USD"``.

    Returns:
        str: Filename-safe string, e.g. ``"BTC-USD"``.
    """
    return symbol.replace("/", "-")


def fetch_history(symbol: str) -> None:
    """
    Download 3 years of 5-min bars for *symbol* and save to CSV.

    Resumes from the last downloaded chunk when interrupted.
    Chunk files are deleted after the final CSV is written.

    Args:
        symbol (str): Ticker accepted by the Twelve Data API,
            e.g. ``"AAPL"`` or ``"BTC/USD"``.

    Raises:
        RuntimeError: On API error responses.
    """
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    safe_symbol = symbol_to_filename(symbol)
    chunk_dir = data_dir / f"chunks_{safe_symbol}"
    final_file = data_dir / f"{safe_symbol}_5min_3ans.csv"

    end_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=3 * 365)
    is_crypto = "/" in symbol

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info(
        "%s — %s — %s → %s  (%s)",
        symbol, INTERVAL, start_date.date(), end_date.date(),
        "crypto 24/7" if is_crypto else "equity",
    )
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    chunk_dir.mkdir(exist_ok=True)

    chunk_files: list[Path] = []
    cursor = end_date
    i = 1

    while cursor > start_date:
        chunk_path = chunk_dir / f"chunk_{i:03d}.csv"

        if chunk_path.exists():
            df_chunk = pd.read_csv(chunk_path, parse_dates=["datetime"])
            oldest = df_chunk["datetime"].min()
            cursor = oldest - timedelta(minutes=MINUTES_PER_BAR)
            logger.info(
                "[%d] chunk already present — cursor → %s",
                i, cursor.strftime("%Y-%m-%d %H:%M:%S"),
            )
            chunk_files.append(chunk_path)
            i += 1
            continue

        logger.info(
            "[%d] fetching up to %s ...",
            i, cursor.strftime("%Y-%m-%d %H:%M:%S"),
        )

        response = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol":     symbol,
                "interval":   INTERVAL,
                "end_date":   cursor.strftime("%Y-%m-%d %H:%M:%S"),
                "apikey":     API_KEY,
                "outputsize": BARS_PER_CHUNK,
                "format":     "JSON",
            },
            timeout=30,
        )
        data = response.json()

        if data.get("status") == "error":
            raise RuntimeError(data.get("message"))

        values = data.get("values", [])
        if not values:
            logger.warning("[%d] no data returned, skipping", i)
            cursor -= timedelta(minutes=MINUTES_PER_BAR)
            i += 1
            continue

        with open(chunk_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["datetime", "open", "high", "low", "close", "volume"],
            )
            writer.writeheader()
            writer.writerows(reversed(values))

        chunk_files.append(chunk_path)
        logger.info("[%d] ✓ %d bars", i, len(values))

        oldest = datetime.strptime(values[-1]["datetime"], "%Y-%m-%d %H:%M:%S")
        cursor = oldest - timedelta(minutes=MINUTES_PER_BAR)
        i += 1

        time.sleep(PAUSE_BETWEEN_CALLS)

    # ── Concatenate chunks ───────────────────────────────────────
    logger.info("Concatenating %d chunks...", len(chunk_files))

    dfs = [pd.read_csv(f, parse_dates=["datetime"]) for f in chunk_files]
    df_final = pd.concat(dfs, ignore_index=True)
    df_final = df_final.drop_duplicates(subset="datetime")
    df_final = df_final.sort_values("datetime").reset_index(drop=True)
    df_final.to_csv(final_file, index=False)

    logger.info("✓ %d bars total", len(df_final))
    logger.info(
        "  Period: %s → %s",
        df_final["datetime"].iloc[0],
        df_final["datetime"].iloc[-1],
    )
    logger.info("  File: %s", final_file)

    for f in chunk_files:
        f.unlink()
    chunk_dir.rmdir()
    logger.info("✓ Done.")


# Keep the old name as an alias for backwards compatibility
recuperer_historique = fetch_history


if __name__ == "__main__":
    fetch_history("AAPL")
