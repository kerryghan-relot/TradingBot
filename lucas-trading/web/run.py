"""Entry point for the web dashboard server.

Run from ``lucas-trading/``::

    python -m web.run                 # http://127.0.0.1:8501
    python -m web.run --port 9000     # custom port
    python -m web.run --host 0.0.0.0  # expose on the LAN

In production the app sits behind Nginx (see ``deploy/``); bind to
127.0.0.1 there and let Nginx terminate.
"""

import argparse

from web.server.app import create_app


def main() -> None:
    """Parse CLI flags and start the Flask development server."""
    parser = argparse.ArgumentParser(description="Dashboard web lucas-trading")
    parser.add_argument("--host", default="127.0.0.1", help="Adresse d'écoute")
    parser.add_argument("--port", type=int, default=8501, help="Port")
    parser.add_argument("--debug", action="store_true", help="Mode debug")
    args = parser.parse_args()

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
