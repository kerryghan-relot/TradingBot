import websocket
import json
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY    = os.getenv("ALPACA_API_KEY")
API_SECRET = os.getenv("ALPACA_SECRET_KEY")
# Stocks to watch
SYMBOLS = ["AAPL", "GOOGL", "TSLA", "ABNB", "NVDA", "UBER", "SPOT", "META", "AMZN", "MSFT", "SHOP", "DIS", "NFLX", "COIN", "SNAP", "PYPL", "ROKU"]

# ── 1. Called once when the connection is established ──────────────────────
def on_open(ws):
    print("✅ Connected to Alpaca")

    # Authenticate
    auth = {
        "action": "auth",
        "key":    API_KEY,
        "secret": API_SECRET
    }
    ws.send(json.dumps(auth))

    # Subscribe to trades and quotes for our symbols
    subscribe = {
        "action":  "subscribe",
        # "trades":  SYMBOLS,
        # "quotes":  SYMBOLS,
        "bars":  SYMBOLS,  # uncomment for 1-min OHLCV bars
    }
    ws.send(json.dumps(subscribe))


# ── 2. Called every time a message arrives ────────────────────────────────
def on_message(ws, message):
    data = json.loads(message)

    for event in data:
        msg_type = event.get("T")

        if msg_type == "t":   # Trade
            print(f"[TRADE] {event['S']:6}  "
                  f"price={event['p']:.2f}  "
                  f"size={event['s']}  "
                  f"time={event['t']}")

        elif msg_type == "q":  # Quote (bid/ask)
            print(f"[QUOTE] {event['S']:6}  "
                  f"bid={event['bp']:.2f} x {event['bs']}  "
                  f"ask={event['ap']:.2f} x {event['as']}")

        elif msg_type == "b":  # Bar (OHLCV)
            print(f"[BAR]   {event['S']:6}  "
                  f"O={event['o']} H={event['h']} "
                  f"L={event['l']} C={event['c']}  "
                  f"vol={event['v']}")

        elif msg_type == "success":
            print(f"ℹ️  {event.get('msg')}")   # "connected" / "authenticated"

        elif msg_type == "subscription":
            print(f"📡 Subscribed → "
                  f"trades: {event.get('trades')}  "
                  f"quotes: {event.get('quotes')}  "
                  f"bars: {event.get('bars')}")

        elif msg_type == "error":
            print(f"❌ Error: {event.get('msg')} (code {event.get('code')})")


# ── 3. Called on error ────────────────────────────────────────────────────
def on_error(ws, error):
    print(f"⚠️  WebSocket error: {error}")


# ── 4. Called when the connection closes ──────────────────────────────────
def on_close(ws, close_status_code, close_msg):
    print(f"🔌 Connection closed ({close_status_code}: {close_msg})")


# ── 5. Start the connection ───────────────────────────────────────────────
if __name__ == "__main__":
    ws = websocket.WebSocketApp(
        "wss://stream.data.alpaca.markets/v2/iex",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    ws.run_forever()  # Blocks here, listening until interrupted (Ctrl+C)