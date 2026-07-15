"""Demo dataset mirroring the design prototype.

When neither PostgreSQL nor Alpaca credentials are available the API
serves this data so the dashboard renders in full — identical in shape
to the real payloads.  Prices oscillate with wall-clock time so the UI
looks live, and every section varies by selected strategy, matching the
handoff mock.
"""

import math
import time

BASE_PRICE: dict[str, float] = {
    "BTC": 98420, "ETH": 4380, "NVDA": 182.4, "AAPL": 246.8,
    "TSLA": 388.5, "MSFT": 521.3, "AMZN": 214.6,
}
NAME: dict[str, str] = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "NVDA": "Nvidia",
    "AAPL": "Apple", "TSLA": "Tesla", "MSFT": "Microsoft",
    "AMZN": "Amazon",
}
DAY_CHG: dict[str, float] = {
    "BTC": 2.1, "ETH": 1.4, "NVDA": 3.2, "AAPL": -0.6,
    "TSLA": -1.8, "MSFT": 0.9, "AMZN": 1.1,
}
CRYPTO: set[str] = {"BTC", "ETH"}
TICKERS: list[str] = ["BTC", "ETH", "NVDA", "AAPL", "TSLA", "MSFT", "AMZN"]

STRATEGIES: list[dict] = [
    {"id": "momentum", "label": "Momentum Multi-Actifs",
     "description": "Suit les tendances fortes — actions + crypto",
     "universe": "all", "win": 68.4, "wins": 234, "losses": 108,
     "trades": 342, "dd": -8.3, "capital": 127480, "pnlTot": 27480,
     "pnlDay": 1240, "pnlDayPct": 0.98, "seed": 7},
    {"id": "meanrev", "label": "Mean-Reversion Crypto",
     "description": "Rachète les excès baissiers — BTC / ETH",
     "universe": "crypto", "win": 73.1, "wins": 156, "losses": 58,
     "trades": 214, "dd": -5.4, "capital": 118650, "pnlTot": 18650,
     "pnlDay": 820, "pnlDayPct": 0.70, "seed": 23},
    {"id": "breakout", "label": "Breakout Actions",
     "description": "Cassures de résistance — actions US",
     "universe": "action", "win": 58.7, "wins": 241, "losses": 170,
     "trades": 411, "dd": -13.6, "capital": 134120, "pnlTot": 34120,
     "pnlDay": -640, "pnlDayPct": -0.47, "seed": 47},
    {"id": "swing", "label": "Swing Global",
     "description": "Positions multi-jours, faible turnover — mixte",
     "universe": "all", "win": 64.2, "wins": 62, "losses": 35,
     "trades": 97, "dd": -6.1, "capital": 112980, "pnlTot": 12980,
     "pnlDay": 410, "pnlDayPct": 0.36, "seed": 88},
]


def _strat(strategy_id: str) -> dict:
    """Return the demo strategy dict for an id, defaulting to the first."""
    return next(
        (s for s in STRATEGIES if s["id"] == strategy_id), STRATEGIES[0]
    )


def _in_universe(sym: str, universe: str) -> bool:
    """Return True when a symbol belongs to a strategy's universe."""
    if universe == "all":
        return True
    return (sym in CRYPTO) if universe == "crypto" else (sym not in CRYPTO)


def _cat_match(cat: str, universe: str) -> bool:
    """Return True when a category matches a strategy's universe."""
    if universe == "all":
        return True
    return cat == ("Crypto" if universe == "crypto" else "Action")


def _mul(sym: str) -> float:
    """Return a small time-based price multiplier for liveliness."""
    phase = sum(ord(c) for c in sym)
    return 1 + 0.006 * math.sin(time.time() / 6 + phase)


def _price(sym: str) -> float:
    """Return the current jittered demo price for a symbol."""
    return BASE_PRICE[sym] * _mul(sym)


def strategies_payload() -> dict:
    """Return the demo strategy list and a default active id."""
    return {
        "active": STRATEGIES[0]["id"],
        "demo": True,
        "strategies": [
            {"id": s["id"], "label": s["label"],
             "description": s["description"], "universe": s["universe"],
             "config": {}}
            for s in STRATEGIES
        ],
    }


def live(strategy_id: str) -> dict:
    """Return the demo live payload for a strategy (bot, tickers, ...)."""
    st = _strat(strategy_id)
    uni = st["universe"]
    universe_label = {
        "crypto": "BTC · ETH", "action": "Actions US",
    }.get(uni, "Actions · BTC · ETH")

    tickers = [
        {"sym": s, "name": NAME[s], "price": _price(s),
         "chgPct": DAY_CHG[s], "isCrypto": s in CRYPTO}
        for s in TICKERS if _in_universe(s, uni)
    ]

    raw_pos = [
        {"sym": "BTC", "cat": "Crypto", "side": "long", "entry": 94800,
         "size": 0.35, "sizeStr": "0.35 BTC", "ago": 6 * 3600e3},
        {"sym": "ETH", "cat": "Crypto", "side": "short", "entry": 4520,
         "size": 4.2, "sizeStr": "4.20 ETH", "ago": 3 * 3600e3},
        {"sym": "NVDA", "cat": "Action", "side": "long", "entry": 176.2,
         "size": 60, "sizeStr": "60 sh", "ago": 28 * 3600e3},
        {"sym": "AAPL", "cat": "Action", "side": "long", "entry": 249.1,
         "size": 120, "sizeStr": "120 sh", "ago": 8 * 3600e3},
        {"sym": "TSLA", "cat": "Action", "side": "short", "entry": 402.0,
         "size": 45, "sizeStr": "45 sh", "ago": 2 * 3600e3},
    ]
    now_ms = time.time() * 1000
    positions, exposure = [], 0.0
    for p in raw_pos:
        if not _cat_match(p["cat"], uni):
            continue
        cur = _price(p["sym"])
        exposure += cur * p["size"]
        positions.append({
            "sym": p["sym"], "name": NAME[p["sym"]], "cat": p["cat"],
            "side": p["side"], "entry": p["entry"], "cur": cur,
            "size": p["size"], "sizeStr": p["sizeStr"],
            "openedMs": now_ms - p["ago"],
        })

    stats = {
        "pnlTotal": st["pnlTot"],
        "pnlTotalPct": st["pnlTot"] / (st["capital"] - st["pnlTot"]) * 100,
        "pnlDay": st["pnlDay"], "pnlDayPct": st["pnlDayPct"],
        "winRate": st["win"], "wins": st["wins"], "losses": st["losses"],
        "trades": st["trades"], "drawdown": st["dd"],
        "capital": st["capital"], "exposure": exposure,
        "exposurePct": exposure / st["capital"] * 100 if st["capital"] else 0,
    }

    raw_j = [
        ("14:32:07", "BTC", "Crypto", "Achat",
         "RSI < 30 + croisement MACD", 94800, "0.35 BTC", "Ouvert"),
        ("14:18:44", "TSLA", "Action", "Vente",
         "Résistance + volume faiblissant", 402.00, "45 sh", "Ouvert"),
        ("13:57:12", "ETH", "Crypto", "Vente",
         "Divergence baissière RSI", 4520, "4.2 ETH", "Ouvert"),
        ("12:40:03", "AAPL", "Action", "Achat",
         "Breakout moyenne mobile 50", 249.10, "120 sh", "Ouvert"),
        ("11:22:51", "MSFT", "Action", "Achat",
         "Momentum + earnings beat", 510.00, "40 sh", "Fermé"),
        ("10:05:19", "AMZN", "Action", "Vente",
         "Rejet zone d'offre", 220.00, "90 sh", "Fermé"),
        ("09:47:33", "NVDA", "Action", "Achat",
         "Tendance haussière confirmée", 176.20, "60 sh", "Ouvert"),
        ("09:12:08", "BTC", "Crypto", "Hold",
         "Consolidation, pas de signal net", 0, "—", "Annulé"),
        ("08:33:55", "ETH", "Crypto", "Achat",
         "Support testé 3×", 3980, "5.0 ETH", "Fermé"),
        ("07:58:40", "TSLA", "Action", "Hold",
         "Volatilité élevée, attente", 0, "—", "Annulé"),
        ("07:20:14", "BTC", "Crypto", "Achat",
         "Cassure triangle ascendant", 97000, "0.20 BTC", "Fermé"),
        ("06:41:29", "MSFT", "Action", "Vente",
         "Prise de profit — objectif atteint", 524.00, "40 sh", "Fermé"),
    ]
    journal = [
        {"time": t, "sym": sym, "cat": cat, "signal": sig,
         "reason": reason, "entry": entry, "size": size, "status": status}
        for (t, sym, cat, sig, reason, entry, size, status) in raw_j
        if _cat_match(cat, uni)
    ]

    return {
        "demo": True,
        "bot": {"state": "active", "label": "Bot actif (démo)"},
        "universeLabel": universe_label,
        "activeStrategy": st["id"],
        "strategy": {"id": st["id"], "label": st["label"],
                     "desc": st["description"], "universe": uni},
        "stats": stats, "tickers": tickers,
        "positions": positions, "journal": journal,
    }


def _gen_equity(seed: int, end: float) -> list[int]:
    """Reproduce the prototype's 90-point equity generator."""
    s = seed
    def rnd() -> float:
        nonlocal s
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        return s / 0x7FFFFFFF
    out, v = [], 100000.0
    drift = (end - 100000) / 90
    for i in range(90):
        dd = -abs(drift) * 3.5 if 46 < i < 54 else 0
        v += drift + (rnd() - 0.45) * max(650, abs(drift) * 2.5) + dd
        out.append(round(v))
    out[89] = round(end)
    return out


def _gen_day(seed: int, end: float) -> list[int]:
    """Reproduce the prototype's 24-point intraday generator."""
    s = seed
    def rnd() -> float:
        nonlocal s
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        return s / 0x7FFFFFFF
    out, v = [], end * 0.994
    for _ in range(24):
        v += (rnd() - 0.4) * (end * 0.0016)
        out.append(round(v))
    out[23] = round(end)
    return out


def _bench(series: list[float], key: str) -> list[float] | None:
    """Reproduce the prototype's benchmark series for a period slice."""
    if key == "none":
        return None
    ret_all = {"sp500": 0.12, "nasdaq": 0.18, "msci": 0.09}.get(key)
    if ret_all is None:
        return None
    n = len(series)
    ret = ret_all * (n / 90)
    b0 = series[0]
    end = b0 * (1 + ret)
    s = {"sp500": 5, "nasdaq": 9, "msci": 13}[key]
    def rnd() -> float:
        nonlocal s
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        return s / 0x7FFFFFFF
    out = []
    for i in range(n):
        f = i / (n - 1) if n > 1 else 0
        out.append((b0 + (end - b0) * f) + (rnd() - 0.5) * b0 * 0.005)
    out[0] = b0
    out[-1] = end
    return out


def history(strategy_id: str, period: str, bench: str) -> dict:
    """Return the demo history payload (equity, closed, analysis)."""
    st = _strat(strategy_id)
    uni = st["universe"]
    all_eq = _gen_equity(st["seed"], st["capital"])
    day_eq = _gen_day(st["seed"] + 3, st["capital"])
    series = {
        "day": day_eq, "week": all_eq[-7:], "month": all_eq[-30:],
    }.get(period, all_eq)
    bench_series = _bench([float(v) for v in series], bench)

    raw_c = [
        {"sym": "BTC", "cat": "Crypto", "side": "long", "entry": 89200,
         "exit": 96100, "size": 0.4},
        {"sym": "ETH", "cat": "Crypto", "side": "long", "entry": 3980,
         "exit": 4310, "size": 5},
        {"sym": "NVDA", "cat": "Action", "side": "long", "entry": 168.0,
         "exit": 179.5, "size": 80},
        {"sym": "TSLA", "cat": "Action", "side": "short", "entry": 415.0,
         "exit": 398.0, "size": 50},
        {"sym": "AAPL", "cat": "Action", "side": "long", "entry": 251.0,
         "exit": 247.5, "size": 100},
        {"sym": "MSFT", "cat": "Action", "side": "long", "entry": 510.0,
         "exit": 524.0, "size": 40},
        {"sym": "AMZN", "cat": "Action", "side": "short", "entry": 220.0,
         "exit": 224.0, "size": 90},
    ]
    closed = []
    for t in raw_c:
        if not _cat_match(t["cat"], uni):
            continue
        pnl = ((t["exit"] - t["entry"]) if t["side"] == "long"
               else (t["entry"] - t["exit"])) * t["size"]
        closed.append({**t, "pnl": pnl})

    alloc_table = {
        "all": [("BTC", 24), ("ETH", 13), ("NVDA", 12), ("AAPL", 11),
                ("MSFT", 10), ("TSLA", 8), ("AMZN", 7), ("Liquidités", 15)],
        "crypto": [("BTC", 44), ("ETH", 34), ("Liquidités", 22)],
        "action": [("NVDA", 18), ("AAPL", 16), ("MSFT", 15), ("TSLA", 13),
                   ("AMZN", 11), ("Liquidités", 27)],
    }
    alloc = [
        {"sym": sym, "pct": pct, "value": round(pct / 100 * st["capital"])}
        for sym, pct in alloc_table[uni]
    ]
    raw_bars = [("BTC", 12400), ("ETH", 6800), ("NVDA", 4200),
                ("TSLA", 2100), ("MSFT", 1600), ("AMZN", -740),
                ("AAPL", -900)]
    asset_bars = [
        {"sym": sym, "value": v}
        for sym, v in raw_bars if _in_universe(sym, uni)
    ]

    return {
        "demo": True,
        "capitalInitial": 100000,
        "equity": [float(v) for v in series],
        "bench": bench_series,
        "benchLabel": {"sp500": "S&P 500", "nasdaq": "Nasdaq",
                       "msci": "MSCI World"}.get(bench),
        "closed": closed,
        "analysis": {
            "winLoss": {"wins": st["wins"], "losses": st["losses"]},
            "alloc": alloc, "assetBars": asset_bars,
        },
    }
