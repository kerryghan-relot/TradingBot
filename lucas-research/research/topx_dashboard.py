"""
Dashboard Streamlit — Top X portfolio scoring/backtest
Lancement : streamlit run research/topx_dashboard.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

# ------------------------------
# Config
# ------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "resultats"
DATA_DIR = BASE_DIR / "data"

SCORES_CSV = RESULTS_DIR / "scores_topx.csv"
WEIGHTS_CSV = RESULTS_DIR / "weights_topx.csv"
EQUITY_CSV = RESULTS_DIR / "equity_topx.csv"

st.set_page_config(page_title="Top X Portfolio", page_icon=":chart_with_upwards_trend:", layout="wide")

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.metric-card { background:#0f0f0f; border:1px solid #222; border-radius:10px; padding:1rem 1.25rem; }
.metric-label { font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:#666; font-family:'IBM Plex Mono',monospace; }
.metric-value { font-size:26px; font-weight:600; font-family:'IBM Plex Mono',monospace; margin-top:2px; }
.positive { color:#00e676; } .negative { color:#ff5252; } .neutral { color:#e0e0e0; }
.section-title { font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:2px; text-transform:uppercase; color:#555; margin:1.5rem 0 .75rem; }
</style>
""",
    unsafe_allow_html=True,
)

PLOTLY_THEME = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="IBM Plex Mono, monospace", color="#aaa"),
    margin=dict(t=30, b=30, l=30, r=30),
)

# ------------------------------
# Load data
# ------------------------------

def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, index_col=0, parse_dates=True)


def _ensure_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors="coerce")
    return df.sort_index()


scores_df = _ensure_index(_load_csv(SCORES_CSV))
weights_df = _ensure_index(_load_csv(WEIGHTS_CSV))
equity_df = _ensure_index(_load_csv(EQUITY_CSV))

if not weights_df.index.is_unique:
    weights_df = weights_df[~weights_df.index.duplicated(keep="last")]

if scores_df.empty or weights_df.empty or equity_df.empty:
    st.error("Fichiers de resultats manquants. Lance d'abord backtest_topx_portfolio.py")
    st.stop()

symbols = sorted(scores_df.columns.tolist())


def _load_prices(symbol_list: list[str]) -> pd.DataFrame:
    csv_files = sorted(DATA_DIR.glob("*_5min_3ans.csv"))
    if not csv_files:
        return pd.DataFrame()

    closes = {}
    common_index = None
    for csv_file in csv_files:
        symbol = csv_file.stem.replace("_5min_3ans", "").replace("-", "/")
        if symbol not in symbol_list:
            continue
        df = pd.read_csv(csv_file, parse_dates=["datetime"]).set_index("datetime").sort_index()
        df["close"] = df["close"].astype(float)
        close = df["close"]
        closes[symbol] = close
        common_index = close.index if common_index is None else common_index.intersection(close.index)

    if not closes:
        return pd.DataFrame()

    return pd.DataFrame({s: closes[s].reindex(common_index) for s in closes}).ffill()


def _compute_symbol_contrib(weights: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if weights.empty or prices.empty:
        return pd.DataFrame(), pd.DataFrame()

    idx = prices.index
    rebalance_pos = np.searchsorted(idx.values, weights.index.values, side="right") - 1
    valid_mask = (rebalance_pos >= 0) & (rebalance_pos < len(idx) - 1)
    rebalance_pos = rebalance_pos[valid_mask]
    rebal_dates = idx[rebalance_pos]

    weights = weights.loc[rebal_dates]

    contrib_rows = []
    used_rows = []
    for i in range(len(rebalance_pos) - 1):
        pos0 = rebalance_pos[i]
        pos1 = rebalance_pos[i + 1]
        dt0 = rebal_dates[i]

        w = weights.loc[dt0]
        if isinstance(w, pd.DataFrame):
            w = w.iloc[-1]

        prices0 = prices.iloc[pos0]
        prices1 = prices.iloc[pos1]
        symbol_rets = (prices1 / prices0 - 1.0).astype(float)

        contrib = (w * symbol_rets).fillna(0.0)
        used = (w > 0).astype(int)
        contrib_rows.append(contrib)
        used_rows.append(used)

    if not contrib_rows:
        return pd.DataFrame(), pd.DataFrame()

    contrib_df = pd.DataFrame(contrib_rows, index=rebal_dates[: len(contrib_rows)])
    used_df = pd.DataFrame(used_rows, index=rebal_dates[: len(used_rows)])
    return contrib_df, used_df

# ------------------------------
# Sidebar
# ------------------------------
with st.sidebar:
    st.markdown("## Top X Portfolio")
    st.markdown("---")
    view = st.radio("Vue", ["Vue globale", "Par date"], index=0)
    st.markdown("---")

    dates = equity_df.index
    date_min = dates.min().date()
    date_max = dates.max().date()
    date_sel = st.date_input("Date", value=date_max, min_value=date_min, max_value=date_max)

    top_n = st.slider("Top actions", min_value=3, max_value=15, value=5, step=1)

# ------------------------------
# KPIs
# ------------------------------

latest = equity_df.iloc[-1, 0]
first = equity_df.iloc[0, 0]
ret_pct = (latest / first - 1.0) * 100.0

c1, c2, c3 = st.columns(3)
with c1:
    c = "positive" if ret_pct >= 0 else "negative"
    st.markdown(
        f"<div class='metric-card'><div class='metric-label'>Performance</div>"
        f"<div class='metric-value {c}'>{ret_pct:+.1f}%</div></div>",
        unsafe_allow_html=True,
    )
with c2:
    st.markdown(
        f"<div class='metric-card'><div class='metric-label'>Equity finale</div>"
        f"<div class='metric-value neutral'>{latest:,.0f} $</div></div>",
        unsafe_allow_html=True,
    )
with c3:
    max_dd = (equity_df.iloc[:, 0] / equity_df.iloc[:, 0].cummax() - 1.0).min() * -100.0
    st.markdown(
        f"<div class='metric-card'><div class='metric-label'>Max drawdown</div>"
        f"<div class='metric-value neutral'>{max_dd:.1f}%</div></div>",
        unsafe_allow_html=True,
    )

# ------------------------------
# Equity curve
# ------------------------------

st.markdown('<div class="section-title">Equity</div>', unsafe_allow_html=True)
fig_eq = go.Figure()
fig_eq.add_trace(
    go.Scatter(
        x=equity_df.index,
        y=equity_df.iloc[:, 0],
        mode="lines",
        line=dict(color="#1b3a57", width=2),
        name="Equity",
    )
)
fig_eq.update_layout(**PLOTLY_THEME, height=300)
st.plotly_chart(fig_eq, use_container_width=True)

# ------------------------------
# View: global
# ------------------------------

if view == "Vue globale":
    st.markdown('<div class="section-title">Choix d\'investissement</div>', unsafe_allow_html=True)

    # Stacked area of weights
    weights_top = weights_df.copy()
    if top_n < len(symbols):
        totals = weights_top.sum(axis=0).sort_values(ascending=False)
        keep = totals.head(top_n).index
        other = weights_top.drop(columns=keep).sum(axis=1)
        weights_top = weights_top[keep]
        weights_top["OTHER"] = other

    fig_stack = go.Figure()
    for col in weights_top.columns:
        fig_stack.add_trace(
            go.Scatter(
                x=weights_top.index,
                y=weights_top[col],
                stackgroup="one",
                mode="lines",
                line=dict(width=0.5),
                name=col,
            )
        )
    fig_stack.update_layout(**PLOTLY_THEME, height=360, yaxis=dict(tickformat=".0%"))
    st.plotly_chart(fig_stack, use_container_width=True)

    st.markdown('<div class="section-title">Heatmap des scores</div>', unsafe_allow_html=True)
    score_sample = scores_df.tail(26)
    fig_heat = px.imshow(
        score_sample.T,
        aspect="auto",
        color_continuous_scale="RdBu",
        origin="lower",
    )
    fig_heat.update_layout(**PLOTLY_THEME, height=420)
    st.plotly_chart(fig_heat, use_container_width=True)

    st.markdown('<div class="section-title">Actions les plus utilisees et rentables</div>', unsafe_allow_html=True)
    prices_df = _load_prices(symbols)
    contrib_df, used_df = _compute_symbol_contrib(weights_df, prices_df)

    if contrib_df.empty or used_df.empty:
        st.warning("Impossible de calculer l'utilisation et la rentabilite par action.")
    else:
        usage = used_df.sum().sort_values(ascending=False)
        profit = contrib_df.sum().sort_values(ascending=False)

        left, right = st.columns(2)
        with left:
            fig_use = go.Figure(
                data=[
                    go.Bar(
                        x=usage.head(top_n).index,
                        y=usage.head(top_n).values,
                        marker_color="#448aff",
                    )
                ]
            )
            fig_use.update_layout(**PLOTLY_THEME, height=320, yaxis_title="Nb selections")
            st.plotly_chart(fig_use, use_container_width=True)

        with right:
            top_profit = profit.head(top_n)
            fig_prof = go.Figure(
                data=[
                    go.Bar(
                        x=top_profit.index,
                        y=top_profit.values * 100.0,
                        marker_color=["#00e676" if v >= 0 else "#ff5252" for v in top_profit.values],
                    )
                ]
            )
            fig_prof.update_layout(**PLOTLY_THEME, height=320, yaxis_title="Contribution %")
            st.plotly_chart(fig_prof, use_container_width=True)

        st.markdown("<div class='section-title'>Periodes d'utilisation et performance</div>", unsafe_allow_html=True)
        top_syms = profit.head(min(8, len(profit))).index
        contrib_month = contrib_df[top_syms].resample("ME").sum()
        used_month = used_df[top_syms].resample("ME").sum()

        contrib_month = contrib_month.tail(24)
        used_month = used_month.tail(24)

        fig_hm = px.imshow(
            contrib_month.T * 100.0,
            aspect="auto",
            color_continuous_scale="RdBu",
            origin="lower",
        )
        fig_hm.update_layout(**PLOTLY_THEME, height=360)
        st.plotly_chart(fig_hm, use_container_width=True)

        fig_used = go.Figure()
        for sym in used_month.columns:
            fig_used.add_trace(
                go.Scatter(
                    x=used_month.index,
                    y=used_month[sym],
                    mode="lines",
                    name=sym,
                )
            )
        fig_used.update_layout(**PLOTLY_THEME, height=320, yaxis_title="Nb selections / mois")
        st.plotly_chart(fig_used, use_container_width=True)

# ------------------------------
# View: per date
# ------------------------------

else:
    dt = pd.to_datetime(date_sel)
    if dt not in weights_df.index:
        dt = weights_df.index[weights_df.index.get_indexer([dt], method="ffill")][0]

    st.markdown(f"### Allocation au {dt.date()}")
    weights = weights_df.loc[dt].copy()
    weights = weights[weights > 0].sort_values(ascending=False).head(top_n)

    fig_pie = go.Figure(
        data=[
            go.Pie(
                labels=weights.index,
                values=weights.values,
                hole=0.35,
                textinfo="label+percent",
            )
        ]
    )
    fig_pie.update_layout(**PLOTLY_THEME, height=360)
    st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown('<div class="section-title">Scores du meme jour</div>', unsafe_allow_html=True)
    scores = scores_df.loc[dt].sort_values(ascending=False).head(top_n)
    fig_bar = go.Figure(
        data=[
            go.Bar(
                x=scores.index,
                y=scores.values,
                marker_color=["#00e676" if v >= 0 else "#ff5252" for v in scores.values],
            )
        ]
    )
    fig_bar.update_layout(**PLOTLY_THEME, height=320)
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown('<div class="section-title">Poids et cash</div>', unsafe_allow_html=True)
    cash = max(0.0, 1.0 - float(weights_df.loc[dt].sum()))
    df_tbl = pd.DataFrame({"Poids": weights}).copy()
    if cash > 0:
        df_tbl.loc["CASH"] = cash
    st.dataframe(df_tbl.style.format({"Poids": "{:.2%}"}), use_container_width=True)
