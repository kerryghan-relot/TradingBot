"""
Dashboard de monitoring — lucas-trading/live
============================================
Visualise en temps quasi-réel :
  - Portefeuille Alpaca (positions, P&L, solde)
  - Prix et graphiques OHLCV par symbole
  - Votes de signaux en cours
  - Historique des ordres BUY/SELL
  - Configuration active (lecture + édition)

Lancement (depuis lucas-trading/) :
    streamlit run live/dashboard.py

Nécessite le même .env que bot.py (ALPACA_API_KEY / ALPACA_SECRET_KEY).
"""

import json
import os
import sqlite3
import time
from datetime import datetime, UTC
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from plotly.subplots import make_subplots

# ── Setup ─────────────────────────────────────────────────────────────────────

load_dotenv()

# Paths resolved relative to this file so the dashboard works no
# matter where streamlit is launched from (kept self-contained: no
# core import — streamlit runs this file with its own sys.path).
TRADING_DIR: Path       = Path(__file__).resolve().parent.parent
DB_FILE:     Path       = TRADING_DIR / "bars.db"
CONFIG_FILE: Path       = TRADING_DIR / "config" / "config.json"
API_KEY:     str | None = os.getenv("ALPACA_API_KEY")
API_SECRET:  str | None = os.getenv("ALPACA_SECRET_KEY")
PAPER:       bool       = True

st.set_page_config(
    page_title = "Bot Dashboard",
    page_icon  = "🤖",
    layout     = "wide",
)

# Inject minimal CSS for KPI cards
st.markdown("""
<style>
div[data-testid="metric-container"] {
    background: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 8px;
    padding: 12px 16px;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Data loaders
# ══════════════════════════════════════════════════════════════════════════════

def _db_available() -> bool:
    """Return True if bars.db exists and has at least one table."""
    return DB_FILE.exists()


@st.cache_data(ttl=15)
def get_bars(symbol: str, limit: int = 500) -> pd.DataFrame:
    """Load recent OHLCV bars for one symbol from bars.db."""
    if not _db_available():
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql(
            "SELECT * FROM bars WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            conn, params=(symbol, limit),
        )
        conn.close()
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=15)
def get_indicators(symbol: str, limit: int = 300) -> pd.DataFrame:
    """Load recent indicator snapshots for one symbol from bars.db."""
    if not _db_available():
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql(
            "SELECT * FROM indicators WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            conn, params=(symbol, limit),
        )
        conn.close()
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=15)
def get_latest_indicators() -> pd.DataFrame:
    """Load the most recent indicator row per symbol."""
    if not _db_available():
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql(
            """
            SELECT i.* FROM indicators i
            INNER JOIN (
                SELECT symbol, MAX(timestamp) AS max_ts
                FROM   indicators
                GROUP  BY symbol
            ) latest ON i.symbol = latest.symbol
                    AND i.timestamp = latest.max_ts
            """,
            conn,
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=15)
def get_recent_signals(limit: int = 100) -> pd.DataFrame:
    """Load the most recent BUY/SELL signals across all symbols."""
    if not _db_available():
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql(
            "SELECT * FROM indicators WHERE signal IN ('BUY','SELL') "
            "ORDER BY timestamp DESC LIMIT ?",
            conn, params=(limit,),
        )
        conn.close()
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=15)
def get_trades(limit: int = 500) -> pd.DataFrame:
    """Load recent executed orders from the trades table.

    Returns an empty DataFrame when the table doesn't exist yet
    (bars.db created by an older bot version).
    """
    if not _db_available():
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
            conn, params=(limit,),
        )
        conn.close()
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return (
            df.sort_values("timestamp", ascending=False)
            .reset_index(drop=True)
        )
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def get_account_and_positions() -> tuple[dict, list[dict]]:
    """Fetch account balance and open positions from Alpaca.

    Returns:
        tuple: (account_dict, positions_list).  Both empty on error.
    """
    if not API_KEY or not API_SECRET:
        return {}, []
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(API_KEY, API_SECRET, paper=PAPER)
        acct   = client.get_account()
        pos    = client.get_all_positions()
        def _f(obj: object, attr: str, default: float = 0.0) -> float:
            """Read a float attribute safely, returning default if absent."""
            val = getattr(obj, attr, None)
            return float(val) if val is not None else default

        # unrealized_pl was removed from TradeAccount in newer alpaca-py
        # versions; fall back to summing positions when unavailable.
        acct_unr = getattr(acct, "unrealized_pl", None)
        acct_d = {
            "equity":          _f(acct, "equity"),
            "cash":            _f(acct, "cash"),
            "buying_power":    _f(acct, "buying_power"),
            "portfolio_value": _f(acct, "portfolio_value"),
            "unrealized_pl":   float(acct_unr) if acct_unr is not None else 0.0,
        }
        pos_list = [
            {
                "symbol":      p.symbol,
                "qty":         _f(p, "qty"),
                "entry_price": _f(p, "avg_entry_price"),
                "current":     _f(p, "current_price"),
                "pl_$":        _f(p, "unrealized_pl"),
                "pl_%":        _f(p, "unrealized_plpc") * 100,
                "mkt_value":   _f(p, "market_value"),
                "side":        p.side.value if hasattr(p.side, "value") else str(p.side),
            }
            for p in pos
        ]
        # If account didn't expose unrealized_pl, derive it from positions.
        if acct_unr is None:
            acct_d["unrealized_pl"] = sum(p["pl_$"] for p in pos_list)
        return acct_d, pos_list
    except Exception as e:
        return {"_error": str(e)}, []


def load_config() -> dict:
    """Read config.json; return empty dict on error."""
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
#  Chart builders
# ══════════════════════════════════════════════════════════════════════════════

def _rolling_bb(
    series: pd.Series, period: int = 20, std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute rolling Bollinger Bands (mid, upper, lower)."""
    mid   = series.rolling(period, min_periods=1).mean()
    sigma = series.rolling(period, min_periods=1).std()
    return mid, mid + std * sigma, mid - std * sigma


def build_price_chart(
    bars_df: pd.DataFrame,
    ind_df:  pd.DataFrame,
    symbol:  str,
    show_bb: bool = True,
) -> go.Figure:
    """Build a candlestick + volume chart with buy/sell signal markers.

    Args:
        bars_df : OHLCV DataFrame from ``get_bars()``.
        ind_df  : Indicators DataFrame from ``get_indicators()``.
        symbol  : Display title.
        show_bb : Whether to overlay Bollinger Bands.

    Returns:
        go.Figure: Plotly figure ready for ``st.plotly_chart()``.
    """
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.03,
        subplot_titles=(f"{symbol} — Prix", "Volume", "Votes (B / S)"),
    )

    # ── Candlestick ────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x     = bars_df["timestamp"],
        open  = bars_df["open"],
        high  = bars_df["high"],
        low   = bars_df["low"],
        close = bars_df["close"],
        name  = symbol,
        increasing_line_color = "#26a641",
        decreasing_line_color = "#e05252",
    ), row=1, col=1)

    # ── Bollinger Bands ────────────────────────────────────────────────────
    if show_bb and len(bars_df) >= 20:
        mid, upper, lower = _rolling_bb(bars_df["close"])
        for band, name, dash in [
            (upper, "BB Upper", "dot"),
            (mid,   "BB Mid",   "dash"),
            (lower, "BB Lower", "dot"),
        ]:
            fig.add_trace(go.Scatter(
                x=bars_df["timestamp"], y=band,
                name=name, line=dict(color="#7c9cbf", dash=dash, width=1),
                opacity=0.6,
            ), row=1, col=1)

    # ── Buy / Sell markers ─────────────────────────────────────────────────
    if not ind_df.empty:
        buys  = ind_df[ind_df["signal"] == "BUY"]
        sells = ind_df[ind_df["signal"] == "SELL"]
        if not buys.empty:
            fig.add_trace(go.Scatter(
                x=buys["timestamp"], y=buys["close"],
                mode="markers", name="BUY",
                marker=dict(symbol="triangle-up", size=12, color="#26a641"),
            ), row=1, col=1)
        if not sells.empty:
            fig.add_trace(go.Scatter(
                x=sells["timestamp"], y=sells["close"],
                mode="markers", name="SELL",
                marker=dict(symbol="triangle-down", size=12, color="#e05252"),
            ), row=1, col=1)

    # ── Volume ─────────────────────────────────────────────────────────────
    colors = [
        "#26a641" if c >= o else "#e05252"
        for c, o in zip(bars_df["close"], bars_df["open"])
    ]
    fig.add_trace(go.Bar(
        x=bars_df["timestamp"], y=bars_df["volume"],
        name="Volume", marker_color=colors, opacity=0.7,
    ), row=2, col=1)

    # ── Vote ratio ─────────────────────────────────────────────────────────
    if not ind_df.empty and "n_signals" in ind_df.columns:
        valid = ind_df[ind_df["n_signals"] > 0].copy()
        valid["buy_ratio"]  = valid["buy_votes"]  / valid["n_signals"]
        valid["sell_ratio"] = valid["sell_votes"] / valid["n_signals"]
        fig.add_trace(go.Scatter(
            x=valid["timestamp"], y=valid["buy_ratio"],
            name="Buy ratio", line=dict(color="#26a641", width=1.5),
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=valid["timestamp"], y=valid["sell_ratio"],
            name="Sell ratio", line=dict(color="#e05252", width=1.5),
        ), row=3, col=1)

    fig.update_layout(
        template       = "plotly_dark",
        height         = 650,
        showlegend     = True,
        xaxis_rangeslider_visible = False,
        margin         = dict(l=0, r=0, t=30, b=0),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  Tab pages
# ══════════════════════════════════════════════════════════════════════════════

def page_portfolio(acct: dict, positions: list[dict]) -> None:
    """Display account balance and open positions."""
    if "_error" in acct:
        st.error(f"Erreur Alpaca : {acct['_error']}")
        return
    if not acct:
        st.warning("Clés API Alpaca non trouvées dans .env")
        return

    # ── Account KPIs ───────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Equity totale",    f"${acct['equity']:,.2f}")
    c2.metric("💵 Cash disponible",  f"${acct['cash']:,.2f}")
    c3.metric("⚡ Buying power",     f"${acct['buying_power']:,.2f}")
    delta_color = "normal" if acct["unrealized_pl"] >= 0 else "inverse"
    c4.metric(
        "📊 P&L non réalisé",
        f"${acct['unrealized_pl']:+,.2f}",
        delta_color=delta_color,
    )

    st.divider()

    # ── Positions ──────────────────────────────────────────────────────────
    st.subheader("📋 Positions ouvertes")
    if not positions:
        st.info("Aucune position ouverte actuellement.")
        return

    df = pd.DataFrame(positions)
    df["pl_%"]    = df["pl_%"].map("{:+.2f}%".format)
    df["pl_$"]    = df["pl_$"].map("${:+.2f}".format)
    df["entry_price"] = df["entry_price"].map("${:.4f}".format)
    df["current"]     = df["current"].map("${:.4f}".format)
    df["mkt_value"]   = df["mkt_value"].map("${:.2f}".format)
    df.columns = ["Symbole", "Qté", "Prix entrée", "Prix actuel",
                  "P&L $", "P&L %", "Valeur marché", "Sens"]
    st.dataframe(df, width="stretch", hide_index=True)

    # ── Allocation pie ─────────────────────────────────────────────────────
    raw = pd.DataFrame(positions)
    if not raw.empty:
        fig = go.Figure(go.Pie(
            labels  = raw["symbol"],
            values  = raw["mkt_value"],
            hole    = 0.45,
            textinfo = "label+percent",
        ))
        fig.update_layout(
            template = "plotly_dark",
            height   = 320,
            margin   = dict(l=0, r=0, t=20, b=0),
            showlegend = False,
        )
        st.plotly_chart(fig, width="stretch")


def page_charts(symbols: list[str], cfg: dict) -> None:
    """Show OHLCV chart + signals for a selected symbol."""
    col1, col2, col3 = st.columns([2, 1, 1])
    symbol  = col1.selectbox("Symbole", symbols)
    limit   = col2.selectbox("Barres", [100, 200, 500, 1000], index=1)
    show_bb = col3.checkbox("Bollinger Bands", value=True)

    bars_df = get_bars(symbol, limit)
    ind_df  = get_indicators(symbol, limit)

    if bars_df.empty:
        st.warning(
            f"Aucune donnée pour {symbol}. "
            "Le bot doit avoir tourné au moins une fois."
        )
        return

    fig = build_price_chart(bars_df, ind_df, symbol, show_bb)
    st.plotly_chart(fig, width="stretch")

    # ── Latest bar stats ───────────────────────────────────────────────────
    last = bars_df.iloc[-1]
    change = (last["close"] - bars_df.iloc[-2]["close"]) / bars_df.iloc[-2]["close"] * 100 \
        if len(bars_df) > 1 else 0.0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Clôture",  f"${last['close']:,.4f}", f"{change:+.2f}%")
    c2.metric("Open",     f"${last['open']:,.4f}")
    c3.metric("High",     f"${last['high']:,.4f}")
    c4.metric("Low",      f"${last['low']:,.4f}")
    c5.metric("Volume",   f"{last['volume']:,.0f}")


def page_votes(symbols: list[str], positions: list[dict]) -> None:
    """Rank symbols by how close each is to a buy/sell trigger.

    The bot acts when the vote count reaches ``vote_threshold``: a BUY
    when flat, a SELL when holding.  For each symbol this computes the
    number of votes still missing for its *relevant* action (buy if
    flat, sell if held) and sorts so the symbols about to trade appear
    first.  A per-symbol card view remains available below for detail.

    Args:
        symbols   (list[str]): Symbols currently selected for display.
        positions (list[dict]): Open Alpaca positions (for the 📦 flag).
    """
    latest = get_latest_indicators()
    in_pos = {p["symbol"] for p in positions}

    if latest.empty:
        st.info("Aucun indicateur en base — le bot n'a pas encore tourné.")
        return

    cfg       = load_config()
    threshold = int(cfg.get("vote_threshold", 2))

    # ── Build the proximity ranking ───────────────────────────────────────
    records: list[dict] = []
    for symbol in symbols:
        row = latest[latest["symbol"] == symbol]
        if row.empty:
            continue
        r       = row.iloc[0]
        buy_v   = int(r.get("buy_votes",  0))
        sell_v  = int(r.get("sell_votes", 0))
        n_sigs  = int(r.get("n_signals",  1)) or 1
        close   = float(r.get("close", 0))
        holding = symbol in in_pos

        # Only the action allowed by the current position state matters:
        # you can only BUY when flat, only SELL when holding.
        action = "VENTE" if holding else "ACHAT"
        votes  = sell_v if holding else buy_v
        gap    = max(0, threshold - votes)

        if gap == 0:
            etat = (
                "🔴 VENTE imminente" if holding
                else "🟢 ACHAT imminent"
            )
        elif gap == 1:
            etat = f"🟡 proche ({action})"
        else:
            etat = "⚪ loin"

        proche = (
            f"{action} déclenché" if gap == 0
            else f"{action} — {gap} vote(s) manquant(s)"
        )
        records.append({
            "_gap":      gap,
            "_conv":     votes / n_sigs,
            "Symbole":   f"{symbol}{' 📦' if holding else ''}",
            "État":      etat,
            "Prix":      f"${close:,.2f}",
            "Achat":     f"{buy_v}/{n_sigs}",
            "Vente":     f"{sell_v}/{n_sigs}",
            "Conviction": f"{votes / n_sigs * 100:.0f}%",
            "Proche de": proche,
        })

    if not records:
        st.info("Aucune donnée pour les symboles sélectionnés.")
        return

    df = pd.DataFrame(records).sort_values(
        ["_gap", "_conv"], ascending=[True, False]
    ).reset_index(drop=True)

    # ── Summary KPIs ──────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    c1.metric("🎯 Déclenchements imminents", int((df["_gap"] == 0).sum()))
    c2.metric("🟡 Proches (1 vote)", int((df["_gap"] == 1).sum()))
    c3.metric("Seuil de vote", f"{threshold} signaux")

    display = df.drop(columns=["_gap", "_conv"])

    def _color_row(r: pd.Series) -> list[str]:
        etat = r["État"]
        if "imminent" in etat:
            bg = ("rgba(38,166,65,0.28)" if "ACHAT" in etat
                  else "rgba(224,82,82,0.28)")
        elif "proche" in etat:
            bg = "rgba(240,200,80,0.16)"
        else:
            bg = ""
        return [f"background-color: {bg}"] * len(r)

    st.dataframe(
        display.style.apply(_color_row, axis=1),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Trié du plus proche d'un ordre au plus loin. "
        "« Achat »/« Vente » = votes actuels sur le nombre de signaux ; "
        "l'action se déclenche à partir du seuil."
    )

    # ── Per-symbol card detail (collapsed) ────────────────────────────────
    with st.expander("🔍 Détail par symbole"):
        cols = st.columns(min(len(symbols), 5))
        for i, symbol in enumerate(symbols):
            row = latest[latest["symbol"] == symbol]
            col = cols[i % len(cols)]
            with col:
                if row.empty:
                    st.metric(symbol, "—", "pas de données")
                    continue

                r          = row.iloc[0]
                signal     = r.get("signal", "HOLD")
                buy_v      = int(r.get("buy_votes",  0))
                sell_v     = int(r.get("sell_votes", 0))
                n_sigs     = int(r.get("n_signals",  1)) or 1
                close      = float(r.get("close", 0))
                holding    = symbol in in_pos

                color = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(
                    signal, "⚪"
                )
                pos_badge = " 📦" if holding else ""

                st.markdown(
                    f"**{symbol}**{pos_badge}  "
                    f"{color} **{signal}**  \n"
                    f"`B {buy_v}/{n_sigs}`  `S {sell_v}/{n_sigs}`  \n"
                    f"${close:,.4f}"
                )
                buy_pct = buy_v / n_sigs
                st.progress(buy_pct, text=f"Buy {buy_pct*100:.0f}%")


def page_history() -> None:
    """Show executed trades (realised P&L) and recent BUY/SELL signals."""
    # ── Trades réels (table trades, alimentée par place_order) ────────────
    st.subheader("💹 Trades exécutés (P&L réalisé)")
    trades = get_trades(500)

    if trades.empty:
        st.info(
            "Aucun trade en base — la table `trades` se remplit à "
            "chaque ordre accepté par Alpaca."
        )
    else:
        exits = trades.dropna(subset=["pnl_pct"]).copy()
        if not exits.empty:
            exits["pnl_$"] = (
                exits["qty"] * (exits["price"] - exits["entry_price"])
            )
            wins     = (exits["pnl_pct"] > 0).sum()
            win_rate = wins / len(exits) * 100
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Trades clôturés", len(exits))
            c2.metric("P&L réalisé", f"${exits['pnl_$'].sum():+,.2f}")
            c3.metric("Win rate", f"{win_rate:.0f}%")
            c4.metric(
                "P&L moyen / trade",
                f"{exits['pnl_pct'].mean() * 100:+.2f}%",
            )

            # ── P&L par symbole ────────────────────────────────────────────
            by_sym = (
                exits.groupby("symbol")["pnl_$"].sum().sort_values()
            )
            fig = go.Figure(go.Bar(
                x=by_sym.values, y=by_sym.index, orientation="h",
                marker_color=[
                    "#26a641" if v >= 0 else "#e05252"
                    for v in by_sym.values
                ],
            ))
            fig.update_layout(
                template="plotly_dark",
                height=max(200, 30 * len(by_sym)),
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis_title="P&L réalisé ($)",
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption(
                "Aucune position clôturée pour l'instant — "
                "le P&L apparaît après le premier SELL."
            )

        # ── Table des derniers ordres ──────────────────────────────────────
        show = trades.head(100)[[
            "timestamp", "symbol", "side", "qty",
            "price", "reason", "pnl_pct",
        ]].copy()
        show["timestamp"] = show["timestamp"].dt.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        show["pnl_pct"] = show["pnl_pct"].map(
            lambda v: f"{v * 100:+.2f}%" if pd.notna(v) else "—"
        )
        show.columns = ["Horodatage", "Symbole", "Sens", "Qté",
                        "Prix", "Raison", "P&L"]
        st.dataframe(show, width="stretch", hide_index=True)

    st.divider()

    # ── Signaux (table indicators) ─────────────────────────────────────────
    df = get_recent_signals(100)

    if df.empty:
        st.info("Aucun signal BUY/SELL en base pour le moment.")
        return

    # ── Stats ──────────────────────────────────────────────────────────────
    n_buy  = (df["signal"] == "BUY").sum()
    n_sell = (df["signal"] == "SELL").sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Signaux BUY",  n_buy)
    c2.metric("Signaux SELL", n_sell)
    c3.metric("Total signaux", n_buy + n_sell)

    st.divider()

    # ── Table ──────────────────────────────────────────────────────────────
    st.subheader("📜 Historique des signaux")
    display = df[["timestamp", "symbol", "signal",
                  "close", "buy_votes", "sell_votes", "n_signals"]].copy()
    display["timestamp"] = display["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    display.columns      = ["Horodatage", "Symbole", "Signal",
                             "Prix", "Votes B", "Votes S", "Total"]

    def _color_signal(val: str) -> str:
        if val == "BUY":
            return "color: #26a641; font-weight: bold"
        if val == "SELL":
            return "color: #e05252; font-weight: bold"
        return ""

    st.dataframe(
        display.style.map(_color_signal, subset=["Signal"]),
        width="stretch",
        hide_index=True,
    )


def page_config(cfg: dict) -> None:
    """Show and edit the active configuration."""
    if not cfg:
        st.warning(f"`config.json` introuvable à `{CONFIG_FILE}`.")
        st.info("Lance bot.py une fois — il crée le fichier automatiquement.")
        return

    # ── Quick-edit panel ───────────────────────────────────────────────────
    st.subheader("⚙️ Paramètres actifs")

    all_signals = [
        "BB", "EMA_Cross", "MACD_Zero", "Zscore", "RSI",
        "VolSpike", "OU", "KalmanZ", "VWAP", "ORB", "TimeFilter",
    ]
    current_active = cfg.get("active_signals", [])
    new_active = st.multiselect(
        "Signaux actifs", all_signals, default=current_active
    )

    col1, col2, col3 = st.columns(3)
    new_threshold = col1.number_input(
        "Vote threshold", min_value=1, max_value=len(new_active) or 1,
        value=int(cfg.get("vote_threshold", 2)),
    )
    new_sl = col2.slider(
        "Stop-loss %", 0.5, 10.0,
        value=float(cfg.get("stop_loss_pct", 0.02)) * 100,
        step=0.1,
    )
    new_bb_period = col3.number_input(
        "BB period", min_value=10, max_value=500,
        value=int(cfg.get("bb_period", 200)),
    )

    if st.button("💾 Sauvegarder dans config.json", type="primary"):
        cfg["active_signals"] = new_active
        cfg["vote_threshold"] = new_threshold
        cfg["stop_loss_pct"]  = round(new_sl / 100, 4)
        cfg["bb_period"]      = new_bb_period
        try:
            CONFIG_FILE.write_text(json.dumps(cfg, indent=4))
            st.success("✅ config.json mis à jour — le bot appliquera les changements au prochain bar.")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Erreur d'écriture : {e}")

    st.divider()

    # ── Raw JSON viewer ────────────────────────────────────────────────────
    st.subheader("📄 config.json complet")
    st.json(cfg)


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Render the full dashboard."""
    # ── Header ─────────────────────────────────────────────────────────────
    col_title, col_refresh = st.columns([5, 1])
    col_title.title("🤖 Bot Dashboard — lucas-live-trading")
    now_str = datetime.now(UTC).strftime("%H:%M:%S UTC")

    if col_refresh.button("🔄 Rafraîchir", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    # ── Sidebar ─────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Contrôles")

        cfg         = load_config()
        all_symbols = cfg.get("symbols", ["BTC/USD", "ETH/USD"])

        selected_symbols = st.multiselect(
            "Symboles affichés", all_symbols,
            default=all_symbols,
        )

        st.divider()
        auto_refresh = st.checkbox("Auto-refresh", value=False)
        refresh_sec  = st.slider(
            "Intervalle (s)", 15, 300, 60,
            disabled=not auto_refresh,
        )

        st.divider()
        st.caption(f"Dernière MAJ : {now_str}")
        st.caption(f"DB : `{'✅ OK' if _db_available() else '❌ absente'}`")
        st.caption(f"Config : `{'✅ OK' if cfg else '❌ absente'}`")

    symbols = selected_symbols or all_symbols

    # ── Global KPIs ─────────────────────────────────────────────────────────
    acct, positions = get_account_and_positions()
    latest          = get_latest_indicators()
    sigs_today      = get_recent_signals(200)

    k1, k2, k3, k4 = st.columns(4)
    equity = acct.get("equity", 0)
    k1.metric("💰 Equity", f"${equity:,.2f}" if equity else "—")
    k2.metric("📦 Positions", len(positions))
    k3.metric(
        "🗳️ Symboles actifs",
        f"{len(latest)}/{len(symbols)}" if not latest.empty else "0",
    )
    n_trades = len(sigs_today) if not sigs_today.empty else 0
    k4.metric("📈 Signaux aujourd'hui", n_trades)

    st.divider()

    # ── Tabs ────────────────────────────────────────────────────────────────
    tab_portfolio, tab_charts, tab_votes, tab_history, tab_config = st.tabs([
        "💼 Portefeuille",
        "📈 Graphiques",
        "🗳️ Votes",
        "📜 Historique",
        "⚙️ Configuration",
    ])

    with tab_portfolio:
        page_portfolio(acct, positions)

    with tab_charts:
        page_charts(symbols, cfg)

    with tab_votes:
        page_votes(symbols, positions)

    with tab_history:
        page_history()

    with tab_config:
        page_config(cfg)

    # ── Auto-refresh (non-blocking) ─────────────────────────────────────────
    # Sleep at most 1 s per rerun so the UI stays responsive (clicks,
    # tab switches) instead of blocking the thread for `refresh_sec` s.
    if auto_refresh:
        if "last_refresh_ts" not in st.session_state:
            st.session_state.last_refresh_ts = time.time()
        elapsed   = time.time() - st.session_state.last_refresh_ts
        remaining = max(0.0, refresh_sec - elapsed)
        with st.sidebar:
            st.progress(
                min(elapsed / refresh_sec, 1.0),
                text=f"Refresh dans {remaining:.0f}s",
            )
        if remaining <= 0:
            st.session_state.last_refresh_ts = time.time()
            st.cache_data.clear()
            st.rerun()
        else:
            time.sleep(min(1.0, remaining))
            st.rerun()


if __name__ == "__main__":
    main()
