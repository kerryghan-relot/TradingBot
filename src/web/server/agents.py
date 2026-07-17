"""Build the Agents-tab payload from the bot's real pipeline state.

Maps the processing stages the live bot actually runs (data
ingestion, weekly symbol rotation, signal vote, stop-loss check,
position sizing, buy/sell threshold rule, order execution — see
``live/bot.py`` and ``core/engine.py``) onto the pipeline
visualisation the frontend renders.  Every loader degrades gracefully
to an empty/"en attente" result when its data source is unavailable,
mirroring ``data.py``.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from core import db
from core.constants import LOG_FILE, ROOT_DIR
from web.server import data, strategies

SCORER_LOG: Path = ROOT_DIR / "scorer.log"

SIGNAL_LABEL: dict[str, str] = {
    "BUY": "Achat", "SELL": "Vente", "HOLD": "Hold",
}


# ── Small shared helpers ──────────────────────────────────────────────

def _parse(ts: str) -> datetime:
    """Parse an ISO timestamp, assuming UTC when no offset is present."""
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _ago(ts: datetime | None) -> str:
    """Human ``il y a Xs/Xmin/Xh/Xj`` string for a UTC timestamp."""
    if ts is None:
        return "jamais"
    secs = max(0, int((datetime.now(UTC) - ts).total_seconds()))
    if secs < 60:
        return f"il y a {secs} s"
    mins = secs // 60
    if mins < 60:
        return f"il y a {mins} min"
    hours = mins // 60
    if hours < 24:
        return f"il y a {hours} h"
    return f"il y a {hours // 24} j"


def _status_for_age(ts: datetime | None, fresh_within: timedelta) -> str:
    """Return ``"ok"`` when ``ts`` is recent enough, else ``"wait"``."""
    if ts is None:
        return "wait"
    return "ok" if datetime.now(UTC) - ts <= fresh_within else "wait"


def _log_tail_has(path: Path, needle: str, lines: int = 60) -> bool:
    """Return True when the tail of a log file contains ``needle``."""
    if not path.exists():
        return False
    try:
        tail = path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines()[-lines:]
    except OSError:
        return False
    return any(needle.lower() in ln.lower() for ln in tail)


# ── Agent Marché (data ingestion) ─────────────────────────────────────

def _marche() -> dict:
    inputs = [
        "Flux WebSocket Alpaca (crypto + actions, barres 1 min)",
        "Backfill historique au démarrage (Alpaca REST)",
    ]
    outputs = [
        "Barres OHLCV persistées (table bars)",
        "Fenêtres glissantes mises à jour par actif",
    ]
    actions: list[dict] = []
    last_ts: datetime | None = None
    if data.db_available():
        try:
            conn = db.connect(read_only=True)
            rows = conn.execute(
                "SELECT symbol, timestamp, close FROM bars "
                "ORDER BY timestamp DESC LIMIT 4"
            ).fetchall()
            conn.close()
        except psycopg.Error:
            rows = []
        for r in rows:
            ts = _parse(r["timestamp"])
            last_ts = last_ts or ts
            sym = data.base_symbol(r["symbol"])
            actions.append({
                "t": ts.strftime("%H:%M:%S"),
                "x": f"Barre reçue {sym} @ {r['close']:.2f}",
                "s": "ok",
            })
    return {
        "id": "marche", "name": "Agent Marché",
        "role": "Ingestion des barres de prix en temps réel",
        "glyph": "◎", "color": "#4d8dff",
        "status": _status_for_age(last_ts, timedelta(minutes=10)),
        "last": _ago(last_ts),
        "inputs": inputs, "outputs": outputs, "actions": actions,
    }


# ── Agent Rotation (weekly top-X scorer) ──────────────────────────────

def _rotation() -> dict:
    cfg = strategies.read_config()
    symbols = cfg.get("symbols", [])
    top_x = cfg.get("scorer_top_x", 5)
    inputs = [
        "Backtest glissant par symbole (Sharpe annualisé)",
        f"Univers candidat suivi ({len(symbols)} symboles)",
    ]
    outputs = [
        f"Top-{top_x} des symboles à trader (config.json)",
        "Rotation live (abonnement / liquidation, sans redémarrage)",
    ]
    actions: list[dict] = []
    last_ts: datetime | None = None
    if SCORER_LOG.exists():
        try:
            last_ts = datetime.fromtimestamp(
                SCORER_LOG.stat().st_mtime, UTC
            )
            tail = [
                ln for ln in SCORER_LOG.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
                if ln.strip()
            ][-6:]
        except OSError:
            tail = []
        for ln in reversed(tail):
            t = ln[:19] if len(ln) > 19 and ln[4] == "-" else "—"
            msg = ln[29:].strip() if len(ln) > 29 else ln.strip()
            actions.append({"t": t, "x": msg, "s": "ok"})
    return {
        "id": "rotation", "name": "Agent Rotation",
        "role": "Sélection hebdomadaire du top-X (live/scorer.py)",
        "glyph": "⟳", "color": "#38bdf8",
        "status": _status_for_age(last_ts, timedelta(days=8)),
        "last": _ago(last_ts),
        "inputs": inputs, "outputs": outputs, "actions": actions,
    }


# ── Agent Signaux (vote engine) ───────────────────────────────────────

def _signaux() -> dict:
    cfg = strategies.read_config()
    active = cfg.get("active_signals", [])
    threshold = cfg.get("vote_threshold", 2)
    inputs = [
        "Fenêtres glissantes (closes / highs / lows / volumes)",
        f"Signaux actifs : {', '.join(active) or '—'}",
        f"Seuil de vote : {threshold} / {len(active)}",
    ]
    outputs = [
        "Votes buy / sell par signal",
        "Décision agrégée BUY / SELL / HOLD",
    ]
    actions: list[dict] = []
    last_ts: datetime | None = None
    if data.db_available():
        try:
            conn = db.connect(read_only=True)
            rows = conn.execute(
                "SELECT symbol, timestamp, buy_votes, sell_votes, "
                "n_signals, signal FROM indicators "
                "ORDER BY timestamp DESC LIMIT 6"
            ).fetchall()
            conn.close()
        except psycopg.Error:
            rows = []
        for r in rows:
            ts = _parse(r["timestamp"])
            last_ts = last_ts or ts
            sym = data.base_symbol(r["symbol"])
            label = SIGNAL_LABEL.get(r["signal"], r["signal"] or "—")
            actions.append({
                "t": ts.strftime("%H:%M:%S"),
                "x": (
                    f"{sym}: {label} — {r['buy_votes']}▲/"
                    f"{r['sell_votes']}▼ sur {r['n_signals']} signaux"
                ),
                "s": "wait" if r["signal"] == "HOLD" else "ok",
            })
    return {
        "id": "signaux", "name": "Agent Signaux",
        "role": "Calcule et agrège les votes des signaux actifs",
        "glyph": "Σ", "color": "#2fd07f",
        "status": _status_for_age(last_ts, timedelta(minutes=10)),
        "last": _ago(last_ts),
        "inputs": inputs, "outputs": outputs, "actions": actions,
    }


# ── Agent Risque (stop-loss) ───────────────────────────────────────────

def _risque() -> dict:
    cfg = strategies.read_config()
    stop_pct = cfg.get("stop_loss_pct", 0.02)
    inputs = [
        "Prix d'entrée de la position ouverte",
        "Clôture courante de l'actif",
        f"Seuil stop-loss : {stop_pct * 100:.0f}%",
    ]
    outputs = [
        "Sortie immédiate si le seuil est franchi",
        "Vente au marché (raison : stop-loss)",
    ]
    actions: list[dict] = []
    last_ts: datetime | None = None
    if data.db_available():
        try:
            conn = db.connect(read_only=True)
            rows = conn.execute(
                "SELECT symbol, timestamp, price, pnl_pct FROM trades "
                "WHERE reason = 'stop-loss' "
                "ORDER BY timestamp DESC LIMIT 5"
            ).fetchall()
            conn.close()
        except psycopg.Error:
            rows = []
        for r in rows:
            ts = _parse(r["timestamp"])
            last_ts = last_ts or ts
            sym = data.base_symbol(r["symbol"])
            pnl = (r["pnl_pct"] or 0.0) * 100
            actions.append({
                "t": ts.strftime("%H:%M:%S"),
                "x": f"STOP-LOSS {sym} @ {r['price']:.2f} ({pnl:+.1f}%)",
                "s": "err",
            })
    if not actions:
        actions.append({
            "t": "—", "s": "ok",
            "x": "Aucun stop-loss déclenché récemment",
        })
    return {
        "id": "risque", "name": "Agent Risque",
        "role": "Contrôle de stop-loss avant toute logique de vote",
        "glyph": "⛔", "color": "#ff5d6c",
        "status": "ok" if data.db_available() else "wait",
        "last": _ago(last_ts),
        "inputs": inputs, "outputs": outputs, "actions": actions,
    }


# ── Agent Seuil (entry / exit trigger rule) ───────────────────────────

def _seuil() -> dict:
    cfg = strategies.read_config()
    threshold = cfg.get("vote_threshold", 2)
    active = cfg.get("active_signals", [])
    stop_pct = cfg.get("stop_loss_pct", 0.02)
    inputs = [
        f"Seuil de vote : {threshold} / {len(active)}",
        "Votes buy / sell agrégés (Agent Signaux)",
        f"Seuil stop-loss : {stop_pct * 100:.0f}%",
    ]
    outputs = [
        f"ACHAT quand buy_votes ≥ {threshold}",
        f"VENTE quand sell_votes ≥ {threshold} ou stop-loss",
    ]
    actions: list[dict] = []
    last_ts: datetime | None = None
    if data.db_available():
        try:
            conn = db.connect(read_only=True)
            rows = conn.execute(
                "SELECT symbol, timestamp, buy_votes, sell_votes, "
                "signal FROM indicators WHERE signal <> 'HOLD' "
                "ORDER BY timestamp DESC LIMIT 5"
            ).fetchall()
            conn.close()
        except psycopg.Error:
            rows = []
        for r in rows:
            ts = _parse(r["timestamp"])
            last_ts = last_ts or ts
            sym = data.base_symbol(r["symbol"])
            label = SIGNAL_LABEL.get(r["signal"], r["signal"] or "—")
            votes = (
                r["buy_votes"] if r["signal"] == "BUY"
                else r["sell_votes"]
            )
            actions.append({
                "t": ts.strftime("%H:%M:%S"),
                "x": (
                    f"{sym}: seuil franchi → {label} "
                    f"({votes} ≥ {threshold})"
                ),
                "s": "ok",
            })
    if not actions:
        actions.append({
            "t": "—", "s": "wait",
            "x": "Aucun seuil franchi récemment",
        })
    return {
        "id": "seuil", "name": "Agent Seuil",
        "role": "Règle de déclenchement : quand acheter / vendre",
        "glyph": "⇅", "color": "#22c1c3",
        "status": _status_for_age(last_ts, timedelta(hours=24)),
        "last": _ago(last_ts),
        "inputs": inputs, "outputs": outputs, "actions": actions,
    }


# ── Agent Sizing (position sizing) ────────────────────────────────────

def _sizing() -> dict:
    cfg = strategies.read_config()
    mode = cfg.get("sizing_mode", "confidence")
    min_pct = cfg.get("min_position_pct", 0.05)
    max_pct = cfg.get("max_position_pct", 0.20)
    capital = float(cfg.get("total_capital", 0.0))
    if mode == "confidence":
        inputs = [
            "Conviction du vote (buy_votes / n_signals)",
            f"Capital total : {capital:,.0f}$",
            f"Fourchette : {min_pct * 100:.0f}%–{max_pct * 100:.0f}% "
            "du capital",
        ]
    else:
        inputs = ["Mode fixe (order_qty / order_dollar_value)"]
    outputs = [
        "Quantité à acheter en unités d'actif",
        "Capital déployé mis à jour",
    ]
    actions: list[dict] = []
    last_ts: datetime | None = None
    if data.db_available():
        try:
            conn = db.connect(read_only=True)
            rows = conn.execute(
                "SELECT symbol, timestamp, qty, price FROM trades "
                "WHERE side = 'BUY' ORDER BY timestamp DESC LIMIT 5"
            ).fetchall()
            conn.close()
        except psycopg.Error:
            rows = []
        for r in rows:
            ts = _parse(r["timestamp"])
            last_ts = last_ts or ts
            sym = data.base_symbol(r["symbol"])
            notional = r["qty"] * r["price"]
            pct = notional / capital * 100 if capital else 0.0
            actions.append({
                "t": ts.strftime("%H:%M:%S"),
                "x": (
                    f"{sym}: {r['qty']:g} unités (~{notional:,.0f}$, "
                    f"{pct:.1f}% du capital)"
                ),
                "s": "ok",
            })
    return {
        "id": "sizing", "name": "Agent Sizing",
        "role": "Détermine la quantité selon la conviction du vote",
        "glyph": "%", "color": "#8b9dff",
        "status": _status_for_age(last_ts, timedelta(hours=24)),
        "last": _ago(last_ts),
        "inputs": inputs, "outputs": outputs, "actions": actions,
    }


# ── Agent Exécution (order placement) ─────────────────────────────────

def _execution() -> dict:
    inputs = [
        "Décision BUY / SELL (Agent Signaux ou Agent Risque)",
        "Quantité à exécuter (Agent Sizing)",
        "Client de trading Alpaca (ordre marché)",
    ]
    outputs = [
        "Ordre soumis à Alpaca",
        "Trade persisté (table trades)",
        "P&L réalisé sur les ventes",
    ]
    actions: list[dict] = []
    last_ts: datetime | None = None
    if data.db_available():
        try:
            conn = db.connect(read_only=True)
            rows = conn.execute(
                "SELECT symbol, timestamp, side, qty, price, reason, "
                "pnl_pct FROM trades ORDER BY timestamp DESC LIMIT 6"
            ).fetchall()
            conn.close()
        except psycopg.Error:
            rows = []
        for r in rows:
            ts = _parse(r["timestamp"])
            last_ts = last_ts or ts
            sym = data.base_symbol(r["symbol"])
            verb = "ACHAT" if r["side"] == "BUY" else "VENTE"
            pnl = (
                f" ({r['pnl_pct'] * 100:+.1f}%)"
                if r["pnl_pct"] is not None else ""
            )
            actions.append({
                "t": ts.strftime("%H:%M:%S"),
                "x": (
                    f"{verb} {sym} {r['qty']:g} @ {r['price']:.2f}"
                    f"{pnl} — {r['reason']}"
                ),
                "s": "ok",
            })
    status = (
        "err" if _log_tail_has(LOG_FILE, "order failed")
        else _status_for_age(last_ts, timedelta(hours=24))
    )
    return {
        "id": "execution", "name": "Agent Exécution",
        "role": "Soumet l'ordre marché et persiste le trade",
        "glyph": "⚡", "color": "#e06a8b",
        "status": status,
        "last": _ago(last_ts),
        "inputs": inputs, "outputs": outputs, "actions": actions,
    }


# ── Planned agents (not implemented yet — roadmap placeholders) ──────
#
# These have no wiring into the live bot: no signal, no config key, no
# DB table.  They exist only so the dashboard can show what's planned
# next to what's actually running.  ``strategies.py``/``data.py`` gain
# no new code until one of these is actually built.

_NOT_BUILT = "Fonctionnalité pas encore implémentée."

PLANNED_AGENTS: list[dict] = [
    {
        "id": "sentiment", "name": "Agent Sentiment",
        "role": "Score de sentiment news / réseaux par ticker (prévu)",
        "glyph": "▤", "color": "#8792ab", "status": "planned",
        "last": "—",
        "inputs": [
            "Flux news et réseaux sociaux par ticker",
            "Watchlist des symboles suivis",
        ],
        "outputs": [
            "Score de sentiment (nouveau signal pour Agent Signaux)",
        ],
        "actions": [{"t": "—", "s": "planned", "x": _NOT_BUILT}],
    },
    {
        "id": "decouverte", "name": "Agent Découverte",
        "role": (
            "Élargit l'univers scanné au-delà de la liste fixe (prévu)"
        ),
        "glyph": "⌕", "color": "#8792ab", "status": "planned",
        "last": "—",
        "inputs": ["Screener marché (volume, momentum, capitalisation)"],
        "outputs": ["Nouveaux candidats proposés à Agent Rotation"],
        "actions": [{"t": "—", "s": "planned", "x": _NOT_BUILT}],
    },
    {
        "id": "circuit_breaker", "name": "Agent Coupe-Circuit",
        "role": (
            "Stoppe le trading si le drawdown portefeuille dépasse "
            "un seuil (prévu)"
        ),
        "glyph": "⏻", "color": "#8792ab", "status": "planned",
        "last": "—",
        "inputs": [
            "Équité du portefeuille en temps réel",
            "Seuil de drawdown configurable",
        ],
        "outputs": [
            "Pause globale du trading",
            "Liquidation optionnelle des positions",
        ],
        "actions": [{"t": "—", "s": "planned", "x": _NOT_BUILT}],
    },
    {
        "id": "alertes", "name": "Agent Alertes",
        "role": (
            "Notifie Slack / Discord / e-mail sur trade ou "
            "erreur (prévu)"
        ),
        "glyph": "⚠", "color": "#8792ab", "status": "planned",
        "last": "—",
        "inputs": ["Trades exécutés, stop-loss déclenchés, erreurs bot"],
        "outputs": ["Notification externe (webhook / e-mail)"],
        "actions": [{"t": "—", "s": "planned", "x": _NOT_BUILT}],
    },
    {
        "id": "filtre_evenementiel", "name": "Agent Filtre Événementiel",
        "role": "Suspend le trading autour des earnings / macro (prévu)",
        "glyph": "⏱", "color": "#8792ab", "status": "planned",
        "last": "—",
        "inputs": ["Calendrier earnings / annonces macro"],
        "outputs": ["Blocage temporaire des votes autour des événements"],
        "actions": [{"t": "—", "s": "planned", "x": _NOT_BUILT}],
    },
]


# ── Public entry point ─────────────────────────────────────────────────

def agents_payload() -> dict:
    """Build the real Agents-tab payload from live sources.

    Returns:
        dict: ``{"demo": False, "agents": [...]}`` — the running
            pipeline stages (see module docstring) followed by the
            planned-but-not-built agents from ``PLANNED_AGENTS``.
    """
    return {
        "demo": False,
        "agents": [
            _marche(), _rotation(), _signaux(),
            _risque(), _sizing(), _seuil(), _execution(),
            *PLANNED_AGENTS,
        ],
    }
