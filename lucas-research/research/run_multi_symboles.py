"""
Batch download of 5-min bars from Twelve Data for a list of symbols.

Requires twelve_data_5min_3ans.py in the same directory and the
TWELVE_DATA_API_KEY environment variable to be set.
"""

import logging
from datetime import datetime

from twelve_data_5min_3ans import fetch_history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Symbols to download ──────────────────────────────────────────
SYMBOLS: list[str] = [
    # Cryptocurrencies
    "BTC/USD",
    "ETH/USD",
]

# ── Main loop ────────────────────────────────────────────────────
succeeded: list[str] = []
failed: list[str] = []
t_start = datetime.now()

logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info("%d symbols to download", len(SYMBOLS))
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

for idx, symbol in enumerate(SYMBOLS, 1):
    logger.info("[%d/%d] Starting %s...", idx, len(SYMBOLS), symbol)
    try:
        fetch_history(symbol)
        succeeded.append(symbol)
    except Exception as exc:
        logger.error("  ✗ %s failed: %s", symbol, exc)
        failed.append(symbol)

duration = datetime.now() - t_start
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info("Done in %s", str(duration).split(".")[0])
logger.info("✓ Success: %d — %s", len(succeeded), ", ".join(succeeded))
if failed:
    logger.warning("✗ Failed:  %d — %s", len(failed), ", ".join(failed))
logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
