"""Assemble real dashboard payloads from live sources.

Combines the ``data`` loaders (PostgreSQL + Alpaca) and the active
strategy config into the exact JSON shapes the frontend consumes —
mirroring ``demo.live`` / ``demo.history`` so the client is source
agnostic.  Sections with no data collapse to empty/zero rather than
faking values; the demo module covers the fully-empty case upstream.
"""

from datetime import UTC, datetime

from web.server import data, strategies

INITIAL_CAPITAL: float = 100000.0


def _max_drawdown(series: list[float]) -> float:
    """Return the worst peak-to-trough drawdown of a series, in percent."""
    if not series:
        return 0.0
    peak, worst = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        if peak:
            worst = min(worst, (v - peak) / peak * 100)
    return worst


def live() -> dict:
    """Build the real live payload (bot, tickers, stats, positions).

    Returns:
        dict: Same shape as ``demo.live``.
    """
    cfg = strategies.read_config()
    symbols = cfg.get("symbols", [])
    account, positions = data.account_and_positions()
    trade_stats = data.trade_stats()
    open_syms = {p["sym"] for p in positions}

    equity = account.get("equity") or 0.0
    exposure = sum(p.get("marketValue", 0.0) for p in positions)
    last_equity = account.get("lastEquity") or 0.0
    pnl_total = equity - INITIAL_CAPITAL if equity else 0.0
    pnl_day = (equity - last_equity) if (equity and last_equity) else 0.0
    dd = _max_drawdown(data.portfolio_history("all") or [])

    active = strategies.active_strategy_id()
    strat = next(
        (s for s in strategies.discover() if s.name == active), None
    )
    label = active.replace("_", " ").title() if active else "—"
    universe = _universe_label(symbols)

    stats = {
        "pnlTotal": pnl_total,
        "pnlTotalPct": pnl_total / INITIAL_CAPITAL * 100 if pnl_total else 0,
        "pnlDay": pnl_day,
        "pnlDayPct": pnl_day / last_equity * 100 if last_equity else 0,
        "winRate": trade_stats["winRate"],
        "wins": trade_stats["wins"],
        "losses": trade_stats["losses"],
        "trades": trade_stats["trades"],
        "drawdown": dd,
        "capital": equity,
        "exposure": exposure,
        "exposurePct": exposure / equity * 100 if equity else 0,
    }

    return {
        "demo": False,
        "bot": data.bot_status(),
        "clockUtc": datetime.now(UTC).strftime("%H:%M:%S"),
        "universeLabel": universe,
        "activeStrategy": active,
        "strategy": {
            "id": active, "label": label,
            "desc": strat.description if strat else "",
            "universe": _universe_key(symbols),
        },
        "stats": stats,
        "tickers": data.tickers(symbols),
        "positions": positions,
        "journal": data.journal(open_syms),
        "error": account.get("_error"),
    }


def history(period: str) -> dict:
    """Build the real history payload (equity, closed trades, analysis).

    Args:
        period (str): ``"day"``, ``"week"``, ``"month"`` or ``"all"``.

    Returns:
        dict: Same shape as ``demo.history`` (benchmark always ``None``
            — no market-index source is wired in live mode).
    """
    account, positions = data.account_and_positions()
    equity_series = data.portfolio_history(period)
    if not equity_series:
        equity = account.get("equity") or INITIAL_CAPITAL
        equity_series = [INITIAL_CAPITAL, equity]

    trade_stats = data.trade_stats()
    cash = account.get("cash") or 0.0

    alloc = [
        {"sym": p["sym"], "value": round(p.get("marketValue", 0.0)),
         "pct": 0.0}
        for p in positions
    ]
    if cash > 0:
        alloc.append({"sym": "Liquidités", "value": round(cash), "pct": 0.0})
    total = sum(a["value"] for a in alloc) or 1
    for a in alloc:
        a["pct"] = a["value"] / total * 100

    asset_bars = [
        {"sym": sym, "value": round(v)}
        for sym, v in sorted(
            trade_stats["bySymbol"].items(),
            key=lambda kv: kv[1], reverse=True,
        )
    ]

    return {
        "demo": False,
        "capitalInitial": INITIAL_CAPITAL,
        "equity": [float(v) for v in equity_series],
        "bench": None,
        "benchLabel": None,
        "closed": data.closed_trades(),
        "analysis": {
            "winLoss": {"wins": trade_stats["wins"],
                        "losses": trade_stats["losses"]},
            "alloc": alloc,
            "assetBars": asset_bars,
        },
    }


def _universe_key(symbols: list[str]) -> str:
    """Classify a symbol list as crypto/action/all."""
    has_crypto = any(data.is_crypto(s) for s in symbols)
    has_stock = any(not data.is_crypto(s) for s in symbols)
    if has_crypto and not has_stock:
        return "crypto"
    if has_stock and not has_crypto:
        return "action"
    return "all"


def _universe_label(symbols: list[str]) -> str:
    """Human label for a symbol universe."""
    return {
        "crypto": "BTC · ETH", "action": "Actions US",
    }.get(_universe_key(symbols), "Actions · Crypto")
