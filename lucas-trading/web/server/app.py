"""Flask application: JSON API + built React front.

Replaces the Streamlit dashboard.  Serves the compiled Vite bundle
(``web/frontend/dist``) and a small JSON API that returns real data
from PostgreSQL + Alpaca when available, and demo data otherwise so
the interface is always fully populated.
"""

from datetime import UTC, datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from web.server import assemble, data, demo, strategies

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
except ModuleNotFoundError:
    # python-dotenv is optional: env vars may already be exported.
    pass

DIST_DIR: Path = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def use_real_data() -> bool:
    """Return True when at least one live source is configured."""
    return data.db_available() or data.alpaca_available()


def create_app() -> Flask:
    """Build and configure the Flask application.

    Returns:
        Flask: The configured app with API routes and static serving.
    """
    app = Flask(__name__, static_folder=None)

    # ── API ────────────────────────────────────────────────────────────
    @app.get("/api/live")
    def api_live() -> object:
        """Return the live payload (real or demo) with a fresh clock."""
        strategy = request.args.get("strategy", "")
        if use_real_data():
            payload = assemble.live()
        else:
            payload = demo.live(strategy)
        payload["clock"] = datetime.now(UTC).strftime("%H:%M:%S")
        return jsonify(payload)

    @app.get("/api/history")
    def api_history() -> object:
        """Return the history payload for a period and benchmark."""
        strategy = request.args.get("strategy", "")
        period = request.args.get("period", "all")
        bench = request.args.get("bench", "none")
        if use_real_data():
            return jsonify(assemble.history(period))
        return jsonify(demo.history(strategy, period, bench))

    @app.get("/api/strategies")
    def api_strategies() -> object:
        """Return the strategy list and the active id."""
        if use_real_data():
            payload = strategies.strategies_payload()
            payload["demo"] = False
            return jsonify(payload)
        return jsonify(demo.strategies_payload())

    @app.post("/api/strategy/select")
    def api_strategy_select() -> object:
        """Activate a strategy by writing its config to disk."""
        body = request.get_json(silent=True) or {}
        strategy_id = body.get("id", "")
        if not use_real_data():
            return jsonify({"ok": True, "demo": True, "active": strategy_id})
        try:
            strategies.select_strategy(strategy_id)
        except KeyError:
            return jsonify({"ok": False, "error": "unknown strategy"}), 404
        return jsonify({"ok": True, "active": strategy_id})

    @app.get("/api/config")
    def api_config_get() -> object:
        """Return the effective config plus editor metadata."""
        return jsonify({
            "config": strategies.read_config(),
            "allSignals": strategies.ALL_SIGNALS,
            "editable": list(strategies.EDITABLE),
            "demo": not use_real_data(),
        })

    @app.post("/api/config")
    def api_config_post() -> object:
        """Apply a validated config patch to ``config.json``."""
        patch = request.get_json(silent=True) or {}
        try:
            cfg = strategies.update_config(patch)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "config": cfg})

    @app.get("/api/health")
    def api_health() -> object:
        """Return a small status summary for diagnostics."""
        return jsonify({
            "db": data.db_available(),
            "alpaca": data.alpaca_available(),
            "mode": "real" if use_real_data() else "demo",
        })

    # ── Static front (built Vite bundle) ───────────────────────────────
    @app.get("/")
    @app.get("/<path:path>")
    def serve_front(path: str = "") -> object:
        """Serve the built SPA, falling back to index.html for routes."""
        if not DIST_DIR.exists():
            return (
                "<h1>Front non compilé</h1><p>Lance "
                "<code>npm install &amp;&amp; npm run build</code> dans "
                "<code>web/frontend/</code>, ou <code>npm run dev</code> "
                "pour le mode développement.</p>",
                200,
            )
        target = DIST_DIR / path
        if path and target.is_file():
            return send_from_directory(DIST_DIR, path)
        return send_from_directory(DIST_DIR, "index.html")

    return app
