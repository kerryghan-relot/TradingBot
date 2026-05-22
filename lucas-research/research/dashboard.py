"""
Dashboard Streamlit — Résultats de backtest multi-stratégies
Lancement : streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent.parent
RESULTATS = BASE_DIR / "resultats" / "resultats_backtest.csv"
HTML_DIR  = BASE_DIR / "resultats"

st.set_page_config(page_title="Backtest Dashboard", page_icon="📈", layout="wide")

# ── CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.metric-card { background:#0f0f0f; border:1px solid #222; border-radius:8px; padding:1rem 1.25rem; margin-bottom:.5rem; }
.metric-label { font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:#666; font-family:'IBM Plex Mono',monospace; }
.metric-value { font-size:26px; font-weight:600; font-family:'IBM Plex Mono',monospace; margin-top:2px; }
.positive { color:#00e676; } .negative { color:#ff5252; } .neutral { color:#e0e0e0; }
.strat-row { display:flex; align-items:center; justify-content:space-between; padding:.6rem 1rem; border-radius:6px; background:#111; border:1px solid #1e1e1e; margin-bottom:.4rem; font-family:'IBM Plex Mono',monospace; font-size:13px; }
.tag { background:#1a1a1a; border:1px solid #2a2a2a; border-radius:4px; padding:2px 8px; font-size:11px; color:#888; }
.section-title { font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:2px; text-transform:uppercase; color:#555; margin:1.5rem 0 .75rem; }
</style>
""", unsafe_allow_html=True)

PLOTLY_THEME = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="IBM Plex Mono, monospace", color="#aaa"),
    margin=dict(t=30, b=30, l=30, r=30),
)
STRAT_COLORS = {"RSI": "#448aff", "SMA": "#e040fb", "Bollinger": "#ffab40"}

# ── Données ────────────────────────────────────────────────────
@st.cache_data
def charger():
    if not RESULTATS.exists():
        return None
    return pd.read_csv(RESULTATS)

df = charger()
if df is None:
    st.error("Fichier `resultats_backtest.csv` introuvable. Lance d'abord le backtest.")
    st.stop()

symboles   = sorted(df["Symbole"].unique())
strategies = sorted(df["Stratégie"].unique())

# ── Sidebar ────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 Backtest")
    st.markdown("---")
    page = st.radio("Navigation", ["Par action", "Vue globale"], label_visibility="collapsed")
    st.markdown("---")

    if page == "Par action":
        symbol_sel = st.selectbox("Action", symboles)

    total   = len(df)
    battent = (df["Alpha vs B&H"] > 0).sum()
    st.markdown(f"**{battent} / {total}** combinaisons battent le B&H")
    st.markdown("---")
    st.markdown("**Top 5 Alpha**")
    for _, row in df.nlargest(5, "Alpha vs B&H").iterrows():
        col = "#00e676" if row["Alpha vs B&H"] >= 0 else "#ff5252"
        st.markdown(
            f"<div style='font-family:monospace;font-size:12px;padding:3px 0'>"
            f"<span style='color:#888'>{row['Symbole']}</span> · {row['Stratégie']} "
            f"<span style='color:{col};float:right'>{row['Alpha vs B&H']:+.1f}%</span></div>",
            unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# PAGE : PAR ACTION
# ════════════════════════════════════════════════════════════════
if page == "Par action":
    df_sym  = df[df["Symbole"] == symbol_sel].copy()
    bh_perf = df_sym["Buy&Hold %"].iloc[0]

    st.markdown(f"# {symbol_sel}")

    # KPI cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        c = "positive" if bh_perf >= 0 else "negative"
        st.markdown(f'<div class="metric-card"><div class="metric-label">Buy & Hold</div><div class="metric-value {c}">{bh_perf:+.1f}%</div></div>', unsafe_allow_html=True)
    with c2:
        best = df_sym.nlargest(1, "Performance %").iloc[0]
        c = "positive" if best["Performance %"] >= 0 else "negative"
        st.markdown(f'<div class="metric-card"><div class="metric-label">Meilleure stratégie</div><div class="metric-value {c}">{best["Performance %"]:+.1f}%</div><div class="metric-label" style="margin-top:4px">{best["Stratégie"]}</div></div>', unsafe_allow_html=True)
    with c3:
        bs = df_sym.nlargest(1, "Sharpe").iloc[0]
        st.markdown(f'<div class="metric-card"><div class="metric-label">Meilleur Sharpe</div><div class="metric-value neutral">{bs["Sharpe"]:.2f}</div><div class="metric-label" style="margin-top:4px">{bs["Stratégie"]}</div></div>', unsafe_allow_html=True)
    with c4:
        n = (df_sym["Alpha vs B&H"] > 0).sum()
        st.markdown(f'<div class="metric-card"><div class="metric-label">Strat. > B&H</div><div class="metric-value neutral">{n} / {len(df_sym)}</div></div>', unsafe_allow_html=True)

    # ── Comparaison visuelle des 3 stratégies ─────────────────
    st.markdown('<div class="section-title">Comparaison des stratégies</div>', unsafe_allow_html=True)

    fig_bar = go.Figure()
    metrics = ["Performance %", "Sharpe", "Max Drawdown %", "Win Rate %"]
    labels  = ["Performance %", "Sharpe Ratio", "Max Drawdown %", "Win Rate %"]

    for _, row in df_sym.iterrows():
        strat = row["Stratégie"]
        fig_bar.add_trace(go.Bar(
            name=strat,
            x=labels,
            y=[row["Performance %"], row["Sharpe"] * 10, -row["Max Drawdown %"], row["Win Rate %"]],
            marker_color=STRAT_COLORS.get(strat, "#888"),
            marker_line_width=0,
            text=[f"{row['Performance %']:+.1f}%", f"{row['Sharpe']:.2f}", f"{row['Max Drawdown %']:.1f}%", f"{row['Win Rate %']:.0f}%"],
            textposition="outside",
            textfont=dict(size=11),
        ))

    # Ligne B&H
    fig_bar.add_hline(y=bh_perf, line_dash="dot", line_color="rgba(255,255,255,0.2)",
                      annotation_text=f"B&H {bh_perf:+.1f}%", annotation_font_color="#666",
                      annotation_position="top right")

    fig_bar.update_layout(**PLOTLY_THEME, barmode="group", height=340, showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0),
        yaxis=dict(gridcolor="#1e1e1e", zerolinecolor="#333"),
        xaxis=dict(tickfont=dict(size=12)),
        annotations=[dict(text="* Sharpe affiché ×10 pour la lisibilité", x=1, y=-0.12,
                          xref="paper", yref="paper", showarrow=False,
                          font=dict(size=10, color="#444"))]
    )
    st.plotly_chart(fig_bar, width='stretch')

    # ── Tableau détaillé ──────────────────────────────────────
    st.markdown('<div class="section-title">Détail par stratégie</div>', unsafe_allow_html=True)
    for _, row in df_sym.sort_values("Alpha vs B&H", ascending=False).iterrows():
        alpha = row["Alpha vs B&H"]; perf = row["Performance %"]
        ca = "#00e676" if alpha >= 0 else "#ff5252"
        cp = "#00e676" if perf >= 0 else "#ff5252"
        st.markdown(f"""
        <div class="strat-row">
            <span style="color:#ccc;font-weight:600;width:100px">{row['Stratégie']}</span>
            <span style="color:{cp}">{perf:+.1f}%</span>
            <span style="color:{ca}">{'▲' if alpha>=0 else '▼'} {alpha:+.1f}% vs B&H</span>
            <span class="tag">Sharpe {row['Sharpe']:.2f}</span>
            <span class="tag">DD {row['Max Drawdown %']:.1f}%</span>
            <span class="tag">{int(row['Nb trades'])} trades</span>
            <span class="tag">WR {row['Win Rate %']:.0f}%</span>
        </div>""", unsafe_allow_html=True)

    # ── Graphiques vectorbt ───────────────────────────────────
    st.markdown('<div class="section-title">Graphiques vectorbt</div>', unsafe_allow_html=True)
    html_file = HTML_DIR / f"{symbol_sel.replace('/', '-')}_backtest.html"
    if html_file.exists():
        with open(html_file, "r", encoding="utf-8") as f:
            st.components.v1.html(f.read(), height=4000)
    else:
        st.warning(f"Graphique HTML introuvable pour {symbol_sel}")


# ════════════════════════════════════════════════════════════════
# PAGE : VUE GLOBALE
# ════════════════════════════════════════════════════════════════
else:
    st.markdown("# Vue globale")

    # ── Classement global ─────────────────────────────────────
    st.markdown('<div class="section-title">Classement — Meilleur alpha vs Buy & Hold par action</div>', unsafe_allow_html=True)

    # Meilleure stratégie par action
    best_per_symbol = (
        df.sort_values("Alpha vs B&H", ascending=False)
          .groupby("Symbole", sort=False)
          .first()
          .reset_index()
          .sort_values("Alpha vs B&H", ascending=False)
    )

    fig_rank = go.Figure()
    colors = [("#00e676" if v >= 0 else "#ff5252") for v in best_per_symbol["Alpha vs B&H"]]

    fig_rank.add_trace(go.Bar(
        x=best_per_symbol["Symbole"],
        y=best_per_symbol["Alpha vs B&H"],
        marker_color=colors,
        marker_line_width=0,
        text=[f"{v:+.1f}%" for v in best_per_symbol["Alpha vs B&H"]],
        textposition="outside",
        textfont=dict(size=10),
        customdata=best_per_symbol[["Stratégie", "Performance %", "Buy&Hold %"]].values,
        hovertemplate="<b>%{x}</b><br>Alpha: %{y:+.1f}%<br>Stratégie: %{customdata[0]}<br>Perf: %{customdata[1]:+.1f}%<br>B&H: %{customdata[2]:+.1f}%<extra></extra>",
    ))
    fig_rank.add_hline(y=0, line_color="rgba(255,255,255,0.15)", line_width=1)
    fig_rank.update_layout(**PLOTLY_THEME, height=400,
        yaxis=dict(gridcolor="#1e1e1e", zerolinecolor="#333", ticksuffix="%"),
        xaxis=dict(tickangle=-35, tickfont=dict(size=11)),
        showlegend=False,
    )
    st.plotly_chart(fig_rank, width='stretch')

    # Tableau classement
    st.markdown('<div class="section-title">Tableau classement</div>', unsafe_allow_html=True)
    rank_df = best_per_symbol[["Symbole", "Stratégie", "Performance %", "Buy&Hold %", "Alpha vs B&H", "Sharpe", "Max Drawdown %", "Nb trades", "Win Rate %"]].copy()
    rank_df.insert(0, "#", range(1, len(rank_df) + 1))

    def style_alpha(val):
        color = "#00e676" if val >= 0 else "#ff5252"
        return f"color: {color}; font-weight: 600"

    def style_perf(val):
        return f"color: {'#00e676' if val >= 0 else '#ff5252'}"

    styled = (
        rank_df.style
        .map(style_alpha, subset=["Alpha vs B&H"])
        .map(style_perf, subset=["Performance %", "Buy&Hold %"])
        .format({
            "Performance %": "{:+.1f}%",
            "Buy&Hold %": "{:+.1f}%",
            "Alpha vs B&H": "{:+.1f}%",
            "Sharpe": "{:.2f}",
            "Max Drawdown %": "{:.1f}%",
            "Win Rate %": "{:.0f}%",
        })
        .set_properties(**{"background-color": "#0f0f0f", "color": "#ccc",
                           "font-family": "IBM Plex Mono, monospace", "font-size": "12px"})
        .set_table_styles([
            {"selector": "th", "props": [("background-color", "#161616"), ("color", "#555"),
                                          ("font-size", "10px"), ("letter-spacing", "1px"),
                                          ("text-transform", "uppercase"), ("padding", "8px 12px")]},
            {"selector": "td", "props": [("padding", "7px 12px"), ("border-bottom", "1px solid #1a1a1a")]},
        ])
    )
    st.dataframe(styled, width='stretch', hide_index=True)

    # ── Récap par stratégie ──────────────────────────────────
    st.markdown('<div class="section-title">Récapitulatif par stratégie</div>', unsafe_allow_html=True)

    def pct_beats_bh(series):
        return (series > 0).mean() * 100

    strat_summary = (
        df.groupby("Stratégie")
          .agg(
              Symboles=("Symbole", "nunique"),
              Perf_moy=("Performance %", "mean"),
              Alpha_moy=("Alpha vs B&H", "mean"),
              Sharpe_moy=("Sharpe", "mean"),
              DD_moy=("Max Drawdown %", "mean"),
              WR_moy=("Win Rate %", "mean"),
              Trades_moy=("Nb trades", "mean"),
              Beat_BH=("Alpha vs B&H", pct_beats_bh),
          )
          .reset_index()
          .sort_values("Alpha_moy", ascending=False)
    )

    strat_styled = (
        strat_summary.style
        .format({
            "Perf_moy": "{:+.1f}%",
            "Alpha_moy": "{:+.1f}%",
            "Sharpe_moy": "{:.2f}",
            "DD_moy": "{:.1f}%",
            "WR_moy": "{:.0f}%",
            "Trades_moy": "{:.0f}",
            "Beat_BH": "{:.0f}%",
        })
        .set_properties(**{"background-color": "#0f0f0f", "color": "#ccc",
                           "font-family": "IBM Plex Mono, monospace", "font-size": "12px"})
        .set_table_styles([
            {"selector": "th", "props": [("background-color", "#161616"), ("color", "#555"),
                                          ("font-size", "10px"), ("letter-spacing", "1px"),
                                          ("text-transform", "uppercase"), ("padding", "8px 12px")]},
            {"selector": "td", "props": [("padding", "7px 12px"), ("border-bottom", "1px solid #1a1a1a")]},
        ])
    )

    st.dataframe(strat_styled, width='stretch', hide_index=True)

