"""Demo dataset mirroring the design prototype.

When neither PostgreSQL nor Alpaca credentials are available the API
serves this data so the dashboard renders in full — identical in shape
to the real payloads.  Prices oscillate with wall-clock time so the UI
looks live, and every section varies by selected strategy, matching the
handoff mock.
"""

import math
import time
from datetime import UTC, datetime

from web.server.agents import PLANNED_AGENTS

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


# ── Agents pipeline (mirrors web/server/agents.py's real payload) ─────

AGENTS: list[dict] = [
    {
        "id": "marche", "name": "Agent Marché",
        "role": "Ingestion des barres de prix en temps réel",
        "glyph": "◎", "color": "#4d8dff", "status": "ok",
        "last": "il y a 12 s",
        "inputs": [
            "Flux WebSocket Alpaca (crypto + actions, barres 1 min)",
            "Backfill historique au démarrage (Alpaca REST)",
        ],
        "outputs": [
            "Barres OHLCV persistées (table bars)",
            "Fenêtres glissantes mises à jour par actif",
        ],
        "actions": [
            {"t": "14:32:07", "x": "Barre reçue BTC/USD @ 94 800",
             "s": "ok"},
            {"t": "14:32:00", "x": "Barre reçue NVDA @ 182.48", "s": "ok"},
            {"t": "14:31:53", "x": "Barre reçue AAPL @ 246.64", "s": "ok"},
        ],
    },
    {
        "id": "rotation", "name": "Agent Rotation",
        "role": "Sélection hebdomadaire du top-X (live/scorer.py)",
        "glyph": "⟳", "color": "#38bdf8", "status": "wait",
        "last": "il y a 3 j",
        "inputs": [
            "Backtest glissant par symbole (Sharpe annualisé)",
            "Univers candidat suivi (30 symboles)",
        ],
        "outputs": [
            "Top-5 des symboles à trader (config.json)",
            "Rotation live (abonnement / liquidation, sans redémarrage)",
        ],
        "actions": [
            {"t": "il y a 3j", "x": "Sélection top-5: BTC/USD, ETH/USD, "
             "NVDA, AAPL, TSLA", "s": "ok"},
            {"t": "il y a 3j", "x": "Retrait de MSFT (Sharpe insuffisant)",
             "s": "ok"},
        ],
    },
    {
        "id": "signaux", "name": "Agent Signaux",
        "role": "Calcule et agrège les votes des signaux actifs",
        "glyph": "Σ", "color": "#2fd07f", "status": "ok",
        "last": "il y a 12 s",
        "inputs": [
            "Fenêtres glissantes (closes / highs / lows / volumes)",
            "Signaux actifs : BB, OU, VWAP, VolSpike, KalmanZ",
            "Seuil de vote : 2 / 5",
        ],
        "outputs": [
            "Votes buy / sell par signal",
            "Décision agrégée BUY / SELL / HOLD",
        ],
        "actions": [
            {"t": "14:32:07", "x": "BTC/USD: Achat — 3▲/0▼ sur 5 signaux",
             "s": "ok"},
            {"t": "14:18:44", "x": "TSLA: Vente — 0▲/2▼ sur 5 signaux",
             "s": "ok"},
            {"t": "14:05:12", "x": "AAPL: Hold — 1▲/0▼ sur 5 signaux",
             "s": "wait"},
        ],
    },
    {
        "id": "risque", "name": "Agent Risque",
        "role": "Contrôle de stop-loss avant toute logique de vote",
        "glyph": "⛔", "color": "#ff5d6c", "status": "ok",
        "last": "il y a 40 min",
        "inputs": [
            "Prix d'entrée de la position ouverte",
            "Clôture courante de l'actif",
            "Seuil stop-loss : 2%",
        ],
        "outputs": [
            "Sortie immédiate si le seuil est franchi",
            "Vente au marché (raison : stop-loss)",
        ],
        "actions": [
            {"t": "11:59:31", "x": "STOP-LOSS ETH/USD @ 4 480 (-2.1%)",
             "s": "err"},
        ],
    },
    {
        "id": "sizing", "name": "Agent Sizing",
        "role": "Détermine la quantité selon la conviction du vote",
        "glyph": "%", "color": "#8b9dff", "status": "ok",
        "last": "il y a 2 min",
        "inputs": [
            "Conviction du vote (buy_votes / n_signals)",
            "Capital total : 100 000$",
            "Fourchette : 5%–20% du capital",
        ],
        "outputs": [
            "Quantité à acheter en unités d'actif",
            "Capital déployé mis à jour",
        ],
        "actions": [
            {"t": "14:32:05", "x": "BTC/USD: 0.35 unités (~33 180$, "
             "2.1% du capital)", "s": "ok"},
            {"t": "12:39:58", "x": "AAPL: 120 unités (~29 892$, "
             "5.8% du capital)", "s": "ok"},
        ],
    },
    {
        "id": "seuil", "name": "Agent Seuil",
        "role": "Règle de déclenchement : quand acheter / vendre",
        "glyph": "⇅", "color": "#22c1c3", "status": "ok",
        "last": "il y a 12 s",
        "inputs": [
            "Seuil de vote : 2 / 5",
            "Votes buy / sell agrégés (Agent Signaux)",
            "Seuil stop-loss : 2%",
        ],
        "outputs": [
            "ACHAT quand buy_votes ≥ 2",
            "VENTE quand sell_votes ≥ 2 ou stop-loss",
        ],
        "actions": [
            {"t": "14:32:07", "x": "BTC/USD: seuil franchi → Achat "
             "(3 ≥ 2)", "s": "ok"},
            {"t": "14:18:44", "x": "TSLA: seuil franchi → Vente "
             "(2 ≥ 2)", "s": "ok"},
        ],
    },
    {
        "id": "execution", "name": "Agent Exécution",
        "role": "Soumet l'ordre marché et persiste le trade",
        "glyph": "⚡", "color": "#e06a8b", "status": "ok",
        "last": "il y a 2 min",
        "inputs": [
            "Décision BUY / SELL (Agent Signaux ou Agent Risque)",
            "Quantité à exécuter (Agent Sizing)",
            "Client de trading Alpaca (ordre marché)",
        ],
        "outputs": [
            "Ordre soumis à Alpaca",
            "Trade persisté (table trades)",
            "P&L réalisé sur les ventes",
        ],
        "actions": [
            {"t": "14:32:07", "x": "ACHAT BTC/USD 0.35 @ 94 800 — vote",
             "s": "ok"},
            {"t": "14:18:44", "x": "VENTE TSLA 45 @ 402.00 (+3.1%) — vote",
             "s": "ok"},
            {"t": "11:59:31", "x": "VENTE ETH/USD 4.2 @ 4 480 (-2.1%) — "
             "stop-loss", "s": "err"},
        ],
    },
]


def agents() -> dict:
    """Return the demo Agents-tab payload (fixed pipeline snapshot)."""
    return {"demo": True, "agents": [*AGENTS, *PLANNED_AGENTS]}


# ── Opportunities (risky / high-upside scan) demo ─────────────────────

# Fabricated candidates spanning the risk/reward plane, so the Chasseur
# page is fully populated with no Alpaca data.  Fields mirror the real
# ``opportunities`` payload; scores gently oscillate with wall time.
_OPP_SEED: list[dict] = [
    {"sym": "SMCI", "name": "Super Micro", "src": "mover", "price": 38.2,
     "day": 6.4, "reward": 92, "risk": 82, "mom": 34, "vol": 4.1,
     "brk": -1.2, "atr": 9.1, "gap": 5.8, "dv": 9_400_000, "news": 4},
    {"sym": "IONQ", "name": "IonQ", "src": "mover", "price": 12.7,
     "day": 8.9, "reward": 88, "risk": 90, "mom": 41, "vol": 5.2,
     "brk": 0.4, "atr": 11.3, "gap": 7.1, "dv": 3_100_000, "news": 3},
    {"sym": "MARA", "name": "Marathon Digital", "src": "active",
     "price": 18.4, "day": 4.2, "reward": 79, "risk": 86, "mom": 22,
     "vol": 3.3, "brk": -3.5, "atr": 10.2, "gap": 2.4, "dv": 6_800_000,
     "news": 2},
    {"sym": "CVNA", "name": "Carvana", "src": "watchlist", "price": 214.5,
     "day": 2.7, "reward": 74, "risk": 63, "mom": 28, "vol": 2.1,
     "brk": -0.8, "atr": 6.4, "gap": 1.2, "dv": 24_000_000, "news": 1},
    {"sym": "SOUN", "name": "SoundHound AI", "src": "mover", "price": 6.1,
     "day": 11.3, "reward": 85, "risk": 94, "mom": 52, "vol": 6.8,
     "brk": 1.1, "atr": 13.7, "gap": 9.4, "dv": 2_200_000, "news": 5},
    {"sym": "PLTR", "name": "Palantir", "src": "active", "price": 71.8,
     "day": 1.9, "reward": 68, "risk": 55, "mom": 19, "vol": 1.8,
     "brk": -1.9, "atr": 5.2, "gap": 0.6, "dv": 41_000_000, "news": 2},
    {"sym": "RGTI", "name": "Rigetti", "src": "mover", "price": 3.4,
     "day": 14.2, "reward": 83, "risk": 97, "mom": 61, "vol": 7.9,
     "brk": 2.3, "atr": 16.1, "gap": 11.8, "dv": 1_600_000, "news": 3},
    {"sym": "AFRM", "name": "Affirm", "src": "watchlist", "price": 44.9,
     "day": 3.1, "reward": 71, "risk": 68, "mom": 24, "vol": 2.6,
     "brk": -2.1, "atr": 7.3, "gap": 2.9, "dv": 12_000_000, "news": 1},
    {"sym": "HOOD", "name": "Robinhood", "src": "active", "price": 28.6,
     "day": 2.2, "reward": 66, "risk": 59, "mom": 17, "vol": 2.0,
     "brk": -1.4, "atr": 5.9, "gap": 1.0, "dv": 18_000_000, "news": 1},
    {"sym": "BBAI", "name": "BigBear.ai", "src": "mover", "price": 2.9,
     "day": 9.6, "reward": 77, "risk": 95, "mom": 44, "vol": 5.7,
     "brk": 0.2, "atr": 14.9, "gap": 8.2, "dv": 1_300_000, "news": 2},
    {"sym": "DKNG", "name": "DraftKings", "src": "watchlist", "price": 39.7,
     "day": 1.4, "reward": 58, "risk": 52, "mom": 12, "vol": 1.5,
     "brk": -3.2, "atr": 4.8, "gap": 0.4, "dv": 15_000_000, "news": 0},
    {"sym": "RIVN", "name": "Rivian", "src": "watchlist", "price": 13.2,
     "day": -2.1, "reward": 49, "risk": 71, "mom": -8, "vol": 2.4,
     "brk": -8.6, "atr": 8.1, "gap": -1.9, "dv": 9_900_000, "news": 1},
    {"sym": "COIN", "name": "Coinbase", "src": "active", "price": 248.3,
     "day": 3.8, "reward": 72, "risk": 64, "mom": 26, "vol": 2.3,
     "brk": -0.5, "atr": 6.7, "gap": 2.1, "dv": 33_000_000, "news": 2},
    {"sym": "LCID", "name": "Lucid", "src": "watchlist", "price": 2.3,
     "day": -3.4, "reward": 41, "risk": 88, "mom": -14, "vol": 3.1,
     "brk": -12.3, "atr": 9.8, "gap": -2.7, "dv": 4_500_000, "news": 0},
    {"sym": "UPST", "name": "Upstart", "src": "mover", "price": 58.4,
     "day": 5.6, "reward": 76, "risk": 74, "mom": 31, "vol": 3.0,
     "brk": -0.9, "atr": 8.6, "gap": 4.3, "dv": 7_200_000, "news": 2},
    {"sym": "CHPT", "name": "ChargePoint", "src": "watchlist", "price": 1.2,
     "day": 1.1, "reward": 38, "risk": 92, "mom": -3, "vol": 2.7,
     "brk": -18.4, "atr": 12.4, "gap": 0.8, "dv": 1_100_000, "news": 0},
]


def _opp_spark(base: float, seed: int) -> list[float]:
    """Build a 20-point pseudo-random daily-close sparkline near ``base``."""
    pts: list[float] = []
    v = base * 0.82
    for i in range(20):
        v *= 1 + math.sin(seed * 1.7 + i * 0.9) * 0.03
        pts.append(round(v, 2))
    pts[-1] = base
    return pts


def _opp_why(o: dict) -> list[str]:
    """Mirror the real scanner's explanatory tags for a demo row."""
    tags: list[str] = []
    if o["vol"] >= 2:
        tags.append(f"Volume ×{o['vol']:.1f}")
    if o["brk"] >= -2:
        tags.append("Proche du plus-haut 60j")
    if o["mom"] >= 15:
        tags.append(f"Momentum +{o['mom']:.0f}% (20j)")
    if abs(o["gap"]) >= 4:
        tags.append(f"Gap {o['gap']:+.0f}%")
    if o["news"] >= 2:
        tags.append(f"{o['news']} news 48h")
    if o["atr"] >= 6:
        tags.append(f"Très volatil (ATR {o['atr']:.0f}%)")
    return tags


def opportunities() -> dict:
    """Return the demo Chasseur-d'opportunités payload."""
    now = time.time()
    items: list[dict] = []
    for i, o in enumerate(_OPP_SEED):
        reward = max(1.0, min(100.0, o["reward"] + math.sin(now / 30 + i) * 2))
        risk = max(1.0, min(100.0, o["risk"] + math.cos(now / 30 + i) * 2))
        items.append({
            "sym": o["sym"], "name": o["name"], "source": o["src"],
            "price": o["price"], "dayChangePct": o["day"],
            "reward": round(reward, 1), "risk": round(risk, 1),
            "factors": {
                "momentum": o["mom"], "volSurge": o["vol"],
                "breakout": o["brk"], "atrPct": o["atr"],
                "dollarVol": o["dv"], "gapPct": o["gap"], "news": o["news"],
            },
            "why": _opp_why(o),
            "spark": _opp_spark(o["price"], i + 1),
        })
    items.sort(key=lambda x: x["reward"], reverse=True)
    return {
        "demo": True,
        "generatedAt": datetime.now(UTC).isoformat(),
        "count": len(items),
        "guardrails": {"minPrice": 1.0, "minDollarVol": 1_000_000.0},
        "items": items,
    }
