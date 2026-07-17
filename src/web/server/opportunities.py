"""Opportunity scanner: rank risky-but-high-upside US stocks.

Powers the dashboard's "Chasseur d'opportunités" page.  Sources
candidate tickers from Alpaca's screener (most-actives + top gainers)
unioned with a curated high-volatility watchlist, enriches each with
daily-bar factors (momentum, volume surge, breakout, volatility, gap),
then assigns two independent 0-100 scores — potential upside and risk —
via percentile ranking within the day's candidate pool.

This is a research/discovery tool: it ranks and explains, it never
places orders.  Every network call degrades gracefully (empty result on
failure), and the module never imports ``core.broker`` so the dashboard
still runs with no Alpaca keys (demo mode handles that case upstream).
All Alpaca access goes through plain ``requests`` against the market
data host, mirroring ``data.py``.
"""

import os
import time
from datetime import UTC, datetime, timedelta

import requests

from web.server import data

DATA_URL: str = "https://data.alpaca.markets"

# Curated high-volatility / high-beta US names, used to enrich the
# dynamic screener candidates so the scan never depends solely on
# Alpaca's screener entitlements.
WATCHLIST: list[str] = [
    "TSLA", "NVDA", "AMD", "PLTR", "COIN", "MARA", "RIOT", "MSTR",
    "GME", "AMC", "SOFI", "RIVN", "LCID", "NIO", "AFRM", "UPST",
    "ROKU", "DKNG", "HOOD", "CVNA", "SMCI", "ARM", "IONQ", "RGTI",
    "BBAI", "SOUN", "CHPT", "PLUG", "FUBO", "DNA",
]

# Guardrails — drop anything untradeable or manipulation-prone.  Kept
# permissive (this page is *about* risk); tighten on the frontend.
MIN_PRICE: float = 1.0
MIN_DOLLAR_VOL: float = 1_000_000.0

# Scoring weights (must each sum to 1.0).
REWARD_WEIGHTS: dict[str, float] = {
    "momentum": 0.35, "volSurge": 0.25, "breakout": 0.25, "catalyst": 0.15,
}
RISK_WEIGHTS: dict[str, float] = {
    "atr": 0.45, "liquidity": 0.25, "penny": 0.15, "gap": 0.15,
}

# The scan fans out to several Alpaca calls; cache the whole payload so
# repeated page loads / polls don't re-scan every time.
_CACHE_TTL_S: float = 120.0
_cache: tuple[float, dict] | None = None


# ── HTTP helpers ──────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    """Return Alpaca auth headers from the environment."""
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }


def _get(path: str, params: dict | None = None) -> dict:
    """GET a market-data endpoint, returning ``{}`` on any error."""
    try:
        resp = requests.get(
            f"{DATA_URL}{path}", headers=_headers(),
            params=params or {}, timeout=8,
        )
        if resp.status_code != 200:
            return {}
        body = resp.json()
        return body if isinstance(body, dict) else {}
    except requests.RequestException:
        return {}


# ── Candidate sourcing ────────────────────────────────────────────────

def _screener_candidates(top: int = 40) -> dict[str, str]:
    """Return ``{symbol: source}`` from Alpaca's screener.

    Combines the most-active names with the day's top gainers.  Each
    symbol maps to the source that surfaced it (``"active"`` or
    ``"mover"``), for display.  Empty when the screener is unavailable.

    Args:
        top (int, optional): Max entries to request per list.

    Returns:
        dict[str, str]: Candidate symbols mapped to their source.
    """
    found: dict[str, str] = {}
    actives = _get(
        "/v1beta1/screener/stocks/most-actives", {"top": top}
    ).get("most_actives", [])
    for row in actives:
        sym = row.get("symbol")
        if sym:
            found.setdefault(sym, "active")
    movers = _get("/v1beta1/screener/stocks/movers", {"top": top})
    for row in movers.get("gainers", []):
        sym = row.get("symbol")
        if sym:
            found.setdefault(sym, "mover")
    return found


def _daily_bars(symbols: list[str]) -> dict[str, list[dict]]:
    """Fetch ~90 days of daily bars for many symbols, in chunks.

    Args:
        symbols (list[str]): Stock tickers to fetch.

    Returns:
        dict[str, list[dict]]: Symbol → chronological list of bar dicts
            (keys ``o/h/l/c/v``).  Missing symbols are simply absent.
    """
    start = (datetime.now(UTC) - timedelta(days=90)).date().isoformat()
    out: dict[str, list[dict]] = {}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i + 50]
        body = _get("/v2/stocks/bars", {
            "symbols": ",".join(chunk),
            "timeframe": "1Day",
            "start": start,
            "limit": 10000,
            "feed": "iex",
            "adjustment": "split",
        })
        for sym, bars in (body.get("bars") or {}).items():
            out[sym] = bars
    return out


def _news_counts(symbols: list[str]) -> dict[str, int]:
    """Return a best-effort count of recent (48h) news per symbol.

    Args:
        symbols (list[str]): Tickers to look up.

    Returns:
        dict[str, int]: Symbol → article count.  Empty when the news
            endpoint is unavailable.
    """
    if not symbols:
        return {}
    start = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    counts: dict[str, int] = {}
    for i in range(0, len(symbols), 40):
        chunk = symbols[i:i + 40]
        body = _get("/v1beta1/news", {
            "symbols": ",".join(chunk), "start": start, "limit": 50,
        })
        for article in body.get("news", []):
            for sym in article.get("symbols", []):
                counts[sym] = counts.get(sym, 0) + 1
    return counts


# ── Factor computation ────────────────────────────────────────────────

def _factors(bars: list[dict], news: int) -> dict | None:
    """Compute raw factor values for one symbol from its daily bars.

    Args:
        bars (list[dict]): Chronological daily bars (``o/h/l/c/v``).
        news (int): Recent news-article count for the symbol.

    Returns:
        dict | None: Raw factors, or ``None`` when there is too little
            history or the symbol fails the liquidity guardrails.
    """
    if len(bars) < 21:
        return None
    closes = [float(b["c"]) for b in bars]
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    vols = [float(b["v"]) for b in bars]
    opens = [float(b["o"]) for b in bars]

    price = closes[-1]
    prev_close = closes[-2]
    if price <= 0 or prev_close <= 0:
        return None

    vol_avg20 = sum(vols[-21:-1]) / 20
    dollar_vol = price * vol_avg20
    if price < MIN_PRICE or dollar_vol < MIN_DOLLAR_VOL:
        return None

    ret5 = price / closes[-6] - 1 if closes[-6] > 0 else 0.0
    ret20 = price / closes[-21] - 1 if closes[-21] > 0 else 0.0
    vol_surge = vols[-1] / vol_avg20 if vol_avg20 > 0 else 1.0

    window_high = max(highs[-60:]) if highs else price
    pct_from_high = (price / window_high - 1) * 100 if window_high else 0.0

    trs = [
        max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        for i in range(len(bars) - 14, len(bars))
    ]
    atr = sum(trs) / len(trs) if trs else 0.0
    atr_pct = atr / price * 100 if price else 0.0

    gap_pct = (opens[-1] / prev_close - 1) * 100 if prev_close else 0.0
    day_change_pct = (price / prev_close - 1) * 100 if prev_close else 0.0

    return {
        "price": price,
        "dayChangePct": day_change_pct,
        "momentum": 0.5 * ret5 + 0.5 * ret20,
        "ret20": ret20,
        "volSurge": vol_surge,
        "breakout": pct_from_high,
        "atrPct": atr_pct,
        "dollarVol": dollar_vol,
        "gapPct": gap_pct,
        "catalyst": news + abs(day_change_pct) * 0.05,
        "news": news,
        "spark": [round(c, 2) for c in closes[-20:]],
    }


def _pct_ranks(values: list[float]) -> list[float]:
    """Rank each value to a 0-100 percentile (higher value → higher)."""
    n = len(values)
    if n == 1:
        return [50.0]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    for pos, i in enumerate(order):
        ranks[i] = pos / (n - 1) * 100
    return ranks


def _why(f: dict) -> list[str]:
    """Build short human tags explaining why a candidate stands out."""
    tags: list[str] = []
    if f["volSurge"] >= 2:
        tags.append(f"Volume ×{f['volSurge']:.1f}")
    if f["breakout"] >= -2:
        tags.append("Proche du plus-haut 60j")
    if f["ret20"] >= 0.15:
        tags.append(f"Momentum +{f['ret20'] * 100:.0f}% (20j)")
    if abs(f["gapPct"]) >= 4:
        tags.append(f"Gap {f['gapPct']:+.0f}%")
    if f["news"] >= 2:
        tags.append(f"{f['news']} news 48h")
    if f["atrPct"] >= 6:
        tags.append(f"Très volatil (ATR {f['atrPct']:.0f}%)")
    return tags


# ── Payload assembly ──────────────────────────────────────────────────

def _build() -> dict:
    """Run one full scan and return the ranked opportunity payload."""
    sources = _screener_candidates()
    for sym in WATCHLIST:
        sources.setdefault(sym, "watchlist")
    symbols = list(sources)
    if not symbols:
        return {"demo": False, "generatedAt": _now_iso(), "items": []}

    bars_by_sym = _daily_bars(symbols)
    news_by_sym = _news_counts(list(bars_by_sym))

    raw: list[dict] = []
    for sym in symbols:
        bars = bars_by_sym.get(sym)
        if not bars:
            continue
        f = _factors(bars, news_by_sym.get(sym, 0))
        if f is None:
            continue
        f["sym"] = sym
        f["name"] = data.display_name(sym)
        f["source"] = sources[sym]
        raw.append(f)

    if not raw:
        return {"demo": False, "generatedAt": _now_iso(), "items": []}

    reward_ranks = {
        "momentum": _pct_ranks([r["momentum"] for r in raw]),
        "volSurge": _pct_ranks([r["volSurge"] for r in raw]),
        "breakout": _pct_ranks([r["breakout"] for r in raw]),
        "catalyst": _pct_ranks([r["catalyst"] for r in raw]),
    }
    risk_ranks = {
        "atr": _pct_ranks([r["atrPct"] for r in raw]),
        "liquidity": _pct_ranks([-r["dollarVol"] for r in raw]),
        "penny": _pct_ranks([-r["price"] for r in raw]),
        "gap": _pct_ranks([abs(r["gapPct"]) for r in raw]),
    }

    items: list[dict] = []
    for idx, r in enumerate(raw):
        reward = sum(
            REWARD_WEIGHTS[k] * reward_ranks[k][idx] for k in REWARD_WEIGHTS
        )
        risk = sum(
            RISK_WEIGHTS[k] * risk_ranks[k][idx] for k in RISK_WEIGHTS
        )
        items.append({
            "sym": r["sym"],
            "name": r["name"],
            "source": r["source"],
            "price": round(r["price"], 2),
            "dayChangePct": round(r["dayChangePct"], 2),
            "reward": round(reward, 1),
            "risk": round(risk, 1),
            "factors": {
                "momentum": round(r["ret20"] * 100, 1),
                "volSurge": round(r["volSurge"], 2),
                "breakout": round(r["breakout"], 1),
                "atrPct": round(r["atrPct"], 1),
                "dollarVol": round(r["dollarVol"]),
                "gapPct": round(r["gapPct"], 1),
                "news": r["news"],
            },
            "why": _why(r),
            "spark": r["spark"],
        })

    items.sort(key=lambda x: x["reward"], reverse=True)
    return {
        "demo": False,
        "generatedAt": _now_iso(),
        "count": len(items),
        "guardrails": {"minPrice": MIN_PRICE, "minDollarVol": MIN_DOLLAR_VOL},
        "items": items,
    }


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def opportunities_payload() -> dict:
    """Return the ranked opportunity payload (cached ~2 min).

    Returns:
        dict: ``{"demo": False, "generatedAt", "count", "guardrails",
            "items": [...]}``.  ``items`` is empty when no live market
            data is reachable.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_S:
        return _cache[1]
    payload = _build()
    _cache = (now, payload)
    return payload
