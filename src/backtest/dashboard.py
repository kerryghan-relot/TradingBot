"""
Unified Research Dashboard — All testing methods in one place.
=============================================================
Launch (from src/): streamlit run backtest/dashboard.py

Pages:
  1. Stratégies Vote     — vote-based backtest + walk-forward comparison
  2. Random Forest       — ML strategy results
  3. Optimisation        — hyperparameter grid search results
  4. Top-X Portfolio     — dynamic symbol selection portfolio
  5. Comparaison         — side-by-side comparison of all methods
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────
# Resolved relative to this file (backtest/ → src/) so the
# dashboard works no matter where streamlit is launched from.
BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
DATA_DIR = BASE_DIR / "data"

CSV_VOTE = RESULTS_DIR / "resultats_backtest.csv"
CSV_VOTE_WF = RESULTS_DIR / "resultats_backtest_wf.csv"
CSV_ML = RESULTS_DIR / "resultats_backtest_ml.csv"
CSV_HYPERPARAMS = RESULTS_DIR / "hyperparams_resultats.csv"
CSV_SCORES = RESULTS_DIR / "scores_topx.csv"
CSV_WEIGHTS = RESULTS_DIR / "weights_topx.csv"
CSV_EQUITY = RESULTS_DIR / "equity_topx.csv"
CSV_OPTIMIZE_TOPX = RESULTS_DIR / "optimize_topx_resultats.csv"
CSV_V2_RESULTS = RESULTS_DIR / "v2_regime_mr_results.csv"
CSV_V2_EQUITY = RESULTS_DIR / "v2_regime_mr_equity.csv"
CSV_V2_TOPX_EQUITY = RESULTS_DIR / "v2_topx_equity.csv"
CSV_V2_TOPX_SELECTION = RESULTS_DIR / "v2_topx_selection.csv"

# ── Page config ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Research Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS / Theme ──────────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.metric-card { background:#0f0f0f; border:1px solid #222; border-radius:10px;
               padding:1rem 1.25rem; margin-bottom:.5rem; }
.metric-label { font-size:11px; letter-spacing:.1em; text-transform:uppercase;
                color:#666; font-family:'IBM Plex Mono',monospace; }
.metric-value { font-size:26px; font-weight:600; font-family:'IBM Plex Mono',monospace;
                margin-top:2px; }
.positive { color:#00e676; } .negative { color:#ff5252; } .neutral { color:#e0e0e0; }
.strat-row { display:flex; align-items:center; justify-content:space-between;
             padding:.6rem 1rem; border-radius:6px; background:#111;
             border:1px solid #1e1e1e; margin-bottom:.4rem;
             font-family:'IBM Plex Mono',monospace; font-size:13px; }
.tag { background:#1a1a1a; border:1px solid #2a2a2a; border-radius:4px;
       padding:2px 8px; font-size:11px; color:#888; }
.section-title { font-family:'IBM Plex Mono',monospace; font-size:11px;
                 letter-spacing:2px; text-transform:uppercase; color:#555;
                 margin:1.5rem 0 .75rem; }
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

SIG_COLORS = {
    "BB": "#448aff",
    "EMA_Cross": "#00e676",
    "MACD_Zero": "#ff7043",
    "Zscore": "#ffb300",
}


# ── Data helpers ─────────────────────────────────────────────────
@st.cache_data
def _load_flat(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    # Normalise French column names to English
    return df.rename(columns={
        "Symbole": "Symbol",
        "Stratégie": "Strategy",
        "Capital final": "Final Capital",
        "Nb trades": "Trades",
    })


@st.cache_data
def _load_dated(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors="coerce")
    return df.sort_index()


@st.cache_data
def _load_prices(symbol_list: tuple[str, ...]) -> pd.DataFrame:
    csv_files = sorted(DATA_DIR.glob("*_5min_3ans.csv"))
    if not csv_files:
        return pd.DataFrame()
    closes: dict[str, pd.Series] = {}
    common_index = None
    for csv_file in csv_files:
        sym = csv_file.stem.replace("_5min_3ans", "").replace("-", "/")
        if sym not in symbol_list:
            continue
        close = (
            pd.read_csv(csv_file, parse_dates=["datetime"])
            .set_index("datetime")
            .sort_index()["close"]
            .astype(float)
        )
        closes[sym] = close
        common_index = (
            close.index
            if common_index is None
            else common_index.intersection(close.index)
        )
    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(
        {s: closes[s].reindex(common_index) for s in closes}
    ).ffill()


def _symbol_contrib(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if weights.empty or prices.empty:
        return pd.DataFrame(), pd.DataFrame()
    idx = prices.index
    rpos = np.searchsorted(idx.values, weights.index.values, side="right") - 1
    mask = (rpos >= 0) & (rpos < len(idx) - 1)
    rpos = rpos[mask]
    rdates = idx[rpos]
    w_sub = weights.loc[rdates]
    contrib_rows: list[pd.Series] = []
    used_rows: list[pd.Series] = []
    for i in range(len(rpos) - 1):
        w = w_sub.iloc[i]
        if isinstance(w, pd.DataFrame):
            w = w.iloc[-1]
        p0 = prices.iloc[rpos[i]]
        p1 = prices.iloc[rpos[i + 1]]
        ret = (p1 / p0 - 1.0).astype(float)
        contrib_rows.append((w * ret).fillna(0.0))
        used_rows.append((w > 0).astype(int))
    if not contrib_rows:
        return pd.DataFrame(), pd.DataFrame()
    return (
        pd.DataFrame(contrib_rows, index=rdates[: len(contrib_rows)]),
        pd.DataFrame(used_rows, index=rdates[: len(used_rows)]),
    )


# ── UI helpers ───────────────────────────────────────────────────
def kpi(label: str, value: str, css: str = "neutral") -> None:
    st.markdown(
        f"<div class='metric-card'>"
        f"<div class='metric-label'>{label}</div>"
        f"<div class='metric-value {css}'>{value}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def section(title: str) -> None:
    st.markdown(
        f"<div class='section-title'>{title}</div>",
        unsafe_allow_html=True,
    )


def _alpha_bar(
    x: list | pd.Index,
    y: list | pd.Series,
    height: int = 380,
    **layout_kw,
) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=x,
            y=y,
            marker_color=["#00e676" if v >= 0 else "#ff5252" for v in y],
            text=[f"{v:+.1f}%" for v in y],
            textposition="outside",
            textfont=dict(size=10),
        )
    )
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.15)")
    fig.update_layout(
        **PLOTLY_THEME,
        height=height,
        yaxis=dict(ticksuffix="%", gridcolor="#1e1e1e"),
        xaxis=dict(tickangle=-35, tickfont=dict(size=11)),
        **layout_kw,
    )
    return fig


# ── Sidebar navigation ───────────────────────────────────────────
PAGES = {
    "📊 Stratégies Vote": "vote",
    "🤖 Random Forest (ML)": "ml",
    "🔬 Optimisation": "hyper",
    "🏆 Top-X Portfolio": "topx",
    "🧪 Optimize Top-X": "optimize_topx",
    "⚖️ Comparaison méthodes": "compare",
    "🧠 Stratégie V2 — Les choix": "v2_choices",
    "🔬 Stratégie V2 — Le test": "v2_test",
    "🎯 Sélection Top-X (V2)": "v2_topx",
}

with st.sidebar:
    st.markdown("## 📈 Research Dashboard")
    st.markdown("---")
    page_label = st.radio(
        "Page", list(PAGES.keys()), label_visibility="collapsed"
    )
    page = PAGES[page_label]
    st.markdown("---")
    st.markdown("**Fichiers disponibles**")
    for name, path in [
        ("Vote (in-sample)", CSV_VOTE),
        ("Vote (walk-fwd)", CSV_VOTE_WF),
        ("Random Forest", CSV_ML),
        ("Hyperparams", CSV_HYPERPARAMS),
        ("Top-X Portfolio", CSV_EQUITY),
        ("Optimize Top-X", CSV_OPTIMIZE_TOPX),
        ("V2 Régime MR", CSV_V2_RESULTS),
    ]:
        st.markdown(f"{'✅' if path.exists() else '⬜'} {name}")


# ══════════════════════════════════════════════════════════════════
# PAGE 1 : STRATÉGIES VOTE
# ══════════════════════════════════════════════════════════════════

def page_vote() -> None:
    has_is = CSV_VOTE.exists()
    has_wf = CSV_VOTE_WF.exists()

    if not has_is and not has_wf:
        st.error(
            "Aucun résultat vote trouvé.\n\n"
            "```\npython backtest_multi.py\n"
            "python backtest_multi.py --walk-forward\n```"
        )
        return

    options = (
        ["In-sample (complet)"] * has_is
        + ["Walk-forward (hors-échantillon)"] * has_wf
    )
    col_sel, _ = st.columns([2, 3])
    with col_sel:
        dataset = st.selectbox("Jeu de données", options)

    df = _load_flat(CSV_VOTE if "In-sample" in dataset else CSV_VOTE_WF)

    # ── Walk-forward gap analysis ─────────────────────────────────
    if has_is and has_wf:
        with st.expander("📉 Analyse du biais in-sample (overfitting gap)"):
            df_is = _load_flat(CSV_VOTE)
            df_wf = _load_flat(CSV_VOTE_WF)
            merged = df_is.merge(
                df_wf[["Symbol", "Strategy", "Alpha vs B&H"]],
                on=["Symbol", "Strategy"],
                suffixes=("_is", "_wf"),
            )
            merged["Gap"] = merged["Alpha vs B&H_is"] - merged["Alpha vs B&H_wf"]
            avg = (
                merged.groupby("Strategy")[
                    ["Alpha vs B&H_is", "Alpha vs B&H_wf", "Gap"]
                ]
                .mean()
                .sort_values("Gap", ascending=False)
            )

            section(
                "Gap = Alpha in-sample − Alpha walk-forward  "
                "· petit gap = stratégie robuste"
            )
            fig_gap = go.Figure()
            fig_gap.add_trace(
                go.Bar(
                    x=avg.index,
                    y=avg["Alpha vs B&H_is"],
                    name="In-sample",
                    marker_color="#448aff",
                )
            )
            fig_gap.add_trace(
                go.Bar(
                    x=avg.index,
                    y=avg["Alpha vs B&H_wf"],
                    name="Walk-forward",
                    marker_color="#00e676",
                )
            )
            fig_gap.update_layout(
                **PLOTLY_THEME,
                barmode="group",
                height=360,
                yaxis=dict(ticksuffix="%", gridcolor="#1e1e1e"),
                xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
            )
            st.plotly_chart(fig_gap, use_container_width=True)

            col_a, col_b = st.columns(2)
            with col_a:
                avg_gap = avg["Gap"].mean()
                kpi(
                    "Gap moyen",
                    f"{avg_gap:+.1f}%",
                    "negative" if avg_gap > 2 else "positive",
                )
            with col_b:
                robust = (avg["Gap"] < 2).sum()
                kpi("Strat. robustes (gap < 2%)", f"{robust} / {len(avg)}")

    # ── Sub-navigation ────────────────────────────────────────────
    sub = st.radio(
        "Vue", ["Par action", "Vue globale"],
        horizontal=True, label_visibility="collapsed",
    )
    st.markdown("---")

    symbols = sorted(df["Symbol"].unique())

    if sub == "Par action":
        symbol_sel = st.selectbox("Action", symbols)
        df_sym = df[df["Symbol"] == symbol_sel].copy()
        bh = df_sym["Buy&Hold %"].iloc[0]

        st.markdown(f"# {symbol_sel}")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            kpi("Buy & Hold", f"{bh:+.1f}%", "positive" if bh >= 0 else "negative")
        with c2:
            best = df_sym.nlargest(1, "Performance %").iloc[0]
            kpi(
                "Meilleure perf",
                f"{best['Performance %']:+.1f}%",
                "positive" if best["Performance %"] >= 0 else "negative",
            )
        with c3:
            bs = df_sym.nlargest(1, "Sharpe").iloc[0]
            kpi("Meilleur Sharpe", f"{bs['Sharpe']:.2f}")
        with c4:
            n_beat = (df_sym["Alpha vs B&H"] > 0).sum()
            kpi("Strat. > B&H", f"{n_beat} / {len(df_sym)}")

        # Sharpe vs Alpha scatter
        section("Sharpe vs Alpha — chaque point est une stratégie")
        sc_df = df_sym.copy()
        sc_df["_size"] = sc_df["Win Rate %"].fillna(0).clip(lower=1)
        fig_sc = px.scatter(
            sc_df,
            x="Alpha vs B&H",
            y="Sharpe",
            color="Max Drawdown %",
            size="_size",
            hover_name="Strategy",
            hover_data={"_size": False, "Win Rate %": True},
            color_continuous_scale="RdBu_r",
            labels={"Alpha vs B&H": "Alpha vs B&H (%)", "_size": "Win Rate %"},
        )
        fig_sc.add_vline(x=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
        fig_sc.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
        fig_sc.update_layout(**PLOTLY_THEME, height=380)
        st.plotly_chart(fig_sc, use_container_width=True)

        # Strategy detail list
        section("Détail par stratégie (trié par alpha)")
        for _, row in df_sym.sort_values("Alpha vs B&H", ascending=False).iterrows():
            alpha = row["Alpha vs B&H"]
            perf = row["Performance %"]
            ca = "#00e676" if alpha >= 0 else "#ff5252"
            cp = "#00e676" if perf >= 0 else "#ff5252"
            trades = int(row.get("Trades", row.get("Nb trades", 0)))
            st.markdown(
                f"<div class='strat-row'>"
                f"<span style='color:#ccc;font-weight:600;min-width:220px'>"
                f"{row['Strategy']}</span>"
                f"<span style='color:{cp}'>{perf:+.1f}%</span>"
                f"<span style='color:{ca}'>{'▲' if alpha >= 0 else '▼'} "
                f"{alpha:+.1f}% vs B&H</span>"
                f"<span class='tag'>Sharpe {row['Sharpe']:.2f}</span>"
                f"<span class='tag'>DD {row['Max Drawdown %']:.1f}%</span>"
                f"<span class='tag'>{trades} trades</span>"
                f"<span class='tag'>WR {row['Win Rate %']:.0f}%</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # VectorBT charts (generated with --html flag)
        section("Graphiques vectorbt (equity curves)")
        html_file = RESULTS_DIR / f"{symbol_sel.replace('/', '-')}_backtest.html"
        if html_file.exists():
            with open(html_file, encoding="utf-8") as f:
                st.components.v1.html(f.read(), height=4000, scrolling=True)
        else:
            st.info(
                "Génère les graphiques avec :\n"
                "```\npython backtest_multi.py --html\n```"
            )

    else:  # Vue globale
        st.markdown("# Vue globale")

        best_per_sym = (
            df.sort_values("Alpha vs B&H", ascending=False)
            .groupby("Symbol", sort=False)
            .first()
            .reset_index()
            .sort_values("Alpha vs B&H", ascending=False)
        )

        section("Meilleur alpha par action")
        st.plotly_chart(
            _alpha_bar(
                best_per_sym["Symbol"],
                best_per_sym["Alpha vs B&H"],
                height=400,
            ),
            use_container_width=True,
        )

        section("Distribution des alphas (toutes strats · tous symboles)")
        fig_hist = px.histogram(
            df,
            x="Alpha vs B&H",
            nbins=60,
            color_discrete_sequence=["#448aff"],
        )
        fig_hist.add_vline(x=0, line_dash="dash", line_color="#ff5252")
        fig_hist.update_layout(**PLOTLY_THEME, height=280, xaxis=dict(ticksuffix="%"))
        st.plotly_chart(fig_hist, use_container_width=True)

        section("Sharpe vs Alpha — meilleure stratégie par (symbole, strat)")
        fig_sc2 = px.scatter(
            df,
            x="Alpha vs B&H",
            y="Sharpe",
            color="Symbol",
            hover_data=["Strategy", "Max Drawdown %"],
            opacity=0.7,
        )
        fig_sc2.add_vline(x=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
        fig_sc2.update_layout(**PLOTLY_THEME, height=400)
        st.plotly_chart(fig_sc2, use_container_width=True)

        def pct_beats(s: pd.Series) -> float:
            return (s > 0).mean() * 100

        section("Récapitulatif par stratégie")
        strat_sum = (
            df.groupby("Strategy")
            .agg(
                Symboles=("Symbol", "nunique"),
                Alpha_moy=("Alpha vs B&H", "mean"),
                Sharpe_moy=("Sharpe", "mean"),
                DD_moy=("Max Drawdown %", "mean"),
                WR_moy=("Win Rate %", "mean"),
                Beat_BH=("Alpha vs B&H", pct_beats),
            )
            .reset_index()
            .sort_values("Alpha_moy", ascending=False)
        )
        st.dataframe(
            strat_sum.style.format(
                {
                    "Alpha_moy": "{:+.1f}%",
                    "Sharpe_moy": "{:.2f}",
                    "DD_moy": "{:.1f}%",
                    "WR_moy": "{:.0f}%",
                    "Beat_BH": "{:.0f}%",
                }
            ).background_gradient(subset=["Alpha_moy"], cmap="RdBu", vmin=-10, vmax=10),
            use_container_width=True,
            hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════
# PAGE 2 : RANDOM FOREST (ML)
# ══════════════════════════════════════════════════════════════════

def page_ml() -> None:
    st.markdown("# 🤖 Random Forest (ML)")

    df = _load_flat(CSV_ML)
    if df.empty:
        st.error(
            "Aucun résultat ML.\n\n"
            "```\npython backtest_multi.py --ml\n```"
        )
        return

    bh = df.groupby("Symbol")["Buy&Hold %"].first()
    rf = df.groupby("Symbol")["Performance %"].first()
    alpha = df.groupby("Symbol")["Alpha vs B&H"].first().sort_values(ascending=False)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi(
            "Alpha moyen",
            f"{alpha.mean():+.1f}%",
            "positive" if alpha.mean() >= 0 else "negative",
        )
    with c2:
        kpi("Battent le B&H", f"{(alpha > 0).sum()} / {len(alpha)}")
    with c3:
        kpi("Sharpe moyen", f"{df['Sharpe'].mean():.2f}")
    with c4:
        kpi("DD moyen", f"{df['Max Drawdown %'].mean():.1f}%")

    section("RandomForest vs Buy & Hold par symbole")
    comp = pd.DataFrame({"B&H": bh, "RandomForest": rf}).dropna()
    comp = comp.sort_values("B&H")
    fig_comp = go.Figure()
    fig_comp.add_trace(
        go.Bar(x=comp.index, y=comp["B&H"], name="B&H", marker_color="#555")
    )
    fig_comp.add_trace(
        go.Bar(
            x=comp.index,
            y=comp["RandomForest"],
            name="RandomForest",
            marker_color="#00e676",
        )
    )
    fig_comp.update_layout(
        **PLOTLY_THEME,
        barmode="group",
        height=380,
        yaxis=dict(ticksuffix="%", gridcolor="#1e1e1e"),
        xaxis=dict(tickangle=-35, tickfont=dict(size=11)),
    )
    st.plotly_chart(fig_comp, use_container_width=True)

    section("Alpha vs Buy & Hold par symbole")
    st.plotly_chart(
        _alpha_bar(alpha.index, alpha.values, height=360),
        use_container_width=True,
    )

    section("Détail par symbole")
    st.dataframe(
        df[
            [
                "Symbol", "Performance %", "Buy&Hold %",
                "Alpha vs B&H", "Sharpe", "Max Drawdown %",
            ]
        ]
        .sort_values("Alpha vs B&H", ascending=False)
        .style.format(
            {
                "Performance %": "{:+.1f}%",
                "Buy&Hold %": "{:+.1f}%",
                "Alpha vs B&H": "{:+.1f}%",
                "Sharpe": "{:.2f}",
                "Max Drawdown %": "{:.1f}%",
            }
        )
        .background_gradient(subset=["Alpha vs B&H"], cmap="RdBu", vmin=-20, vmax=20),
        use_container_width=True,
        hide_index=True,
    )

    st.info(
        "Le Random Forest est entraîné sur les **70 % premiers** de chaque "
        "série et évalué sur les **30 % finaux** (hors-échantillon interne). "
        "Ces résultats sont donc déjà out-of-sample, sans utiliser `--walk-forward`."
    )


# ══════════════════════════════════════════════════════════════════
# PAGE 3 : OPTIMISATION HYPERPARAMÈTRES
# ══════════════════════════════════════════════════════════════════

def page_hyperparams() -> None:
    st.markdown("# 🔬 Optimisation Hyperparamètres")

    df = _load_flat(CSV_HYPERPARAMS)
    if df.empty:
        st.error("Aucun résultat.\n\n```\npython optimize.py\n```")
        return

    sym_col = "Symbol" if "Symbol" in df.columns else "Symbole"
    signals = sorted(df["Signal"].unique())

    # Best params per signal (KPI row)
    section("Meilleur jeu de paramètres par signal (alpha moyen sur tous symboles)")
    cols = st.columns(len(signals))
    for i, sig in enumerate(signals):
        sub = df[df["Signal"] == sig].groupby("Params")["Alpha vs B&H"].mean()
        if sub.empty:
            continue
        best_v = sub.max()
        best_p = sub.idxmax()
        with cols[i]:
            kpi(sig, f"{best_v:+.1f}%", "positive" if best_v >= 0 else "negative")
            st.caption(f"`{best_p}`")

    # Alpha distribution per signal (box plot)
    section("Distribution des alphas par signal")
    fig_box = go.Figure()
    for sig in signals:
        fig_box.add_trace(
            go.Box(
                y=df[df["Signal"] == sig]["Alpha vs B&H"],
                name=sig,
                boxmean=True,
                marker_color=SIG_COLORS.get(sig, "#888"),
            )
        )
    fig_box.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
    fig_box.update_layout(
        **PLOTLY_THEME,
        height=360,
        yaxis=dict(ticksuffix="%", gridcolor="#1e1e1e"),
    )
    st.plotly_chart(fig_box, use_container_width=True)

    # Per-signal deep dive
    section("Analyse détaillée par signal")
    sig_sel = st.selectbox("Signal", signals)
    df_sig = df[df["Signal"] == sig_sel]

    # Avg alpha per param config (bar chart)
    avg_by_params = (
        df_sig.groupby("Params")["Alpha vs B&H"].mean().sort_values(ascending=False)
    )
    fig_params = go.Figure(
        go.Bar(
            x=avg_by_params.index,
            y=avg_by_params.values,
            marker_color=[
                "#00e676" if v >= 0 else "#ff5252" for v in avg_by_params.values
            ],
            text=[f"{v:+.1f}%" for v in avg_by_params.values],
            textposition="outside",
            textfont=dict(size=9),
        )
    )
    fig_params.add_hline(y=0, line_color="rgba(255,255,255,0.15)")
    fig_params.update_layout(
        **PLOTLY_THEME,
        height=360,
        yaxis=dict(ticksuffix="%", gridcolor="#1e1e1e"),
        xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
        title=f"{sig_sel} — alpha moyen par config de paramètres",
    )
    st.plotly_chart(fig_params, use_container_width=True)

    # Heatmap: params × symbol
    section(f"{sig_sel} — heatmap alpha moyen (params × symbole)")
    pivot = (
        df_sig.groupby(["Params", sym_col])["Alpha vs B&H"]
        .mean()
        .unstack(sym_col)
    )
    if not pivot.empty:
        fig_heat = px.imshow(
            pivot,
            aspect="auto",
            color_continuous_scale="RdBu",
            color_continuous_midpoint=0,
        )
        fig_heat.update_layout(
            **PLOTLY_THEME,
            height=max(300, len(pivot) * 28),
        )
        st.plotly_chart(fig_heat, use_container_width=True)

    # Full top-50 table
    section("Top 50 combinaisons")
    top = df_sig.nlargest(50, "Alpha vs B&H")
    st.dataframe(
        top[
            [
                "Params", sym_col, "Performance %", "Buy&Hold %",
                "Alpha vs B&H", "Sharpe", "Max Drawdown %",
            ]
        ]
        .style.format(
            {
                "Performance %": "{:+.1f}%",
                "Buy&Hold %": "{:+.1f}%",
                "Alpha vs B&H": "{:+.1f}%",
                "Sharpe": "{:.2f}",
                "Max Drawdown %": "{:.1f}%",
            }
        )
        .background_gradient(subset=["Alpha vs B&H"], cmap="RdBu", vmin=-10, vmax=10),
        use_container_width=True,
        hide_index=True,
    )


# ══════════════════════════════════════════════════════════════════
# PAGE 4 : TOP-X PORTFOLIO
# ══════════════════════════════════════════════════════════════════

def page_topx() -> None:
    st.markdown("# 🏆 Top-X Portfolio")

    scores_df = _load_dated(CSV_SCORES)
    weights_df = _load_dated(CSV_WEIGHTS)
    equity_df = _load_dated(CSV_EQUITY)

    if scores_df.empty or weights_df.empty or equity_df.empty:
        st.error(
            "Fichiers manquants.\n\n"
            "```\npython backtest_topx_portfolio.py\n```"
        )
        return

    if not weights_df.index.is_unique:
        weights_df = weights_df[~weights_df.index.duplicated(keep="last")]

    symbols = sorted(scores_df.columns.tolist())
    top_n = st.sidebar.slider("Top N symboles affichés", 3, 15, 5)
    view = st.radio(
        "Vue", ["Vue globale", "Par date"],
        horizontal=True, label_visibility="collapsed",
    )
    st.markdown("---")

    # KPIs
    eq = equity_df.iloc[:, 0]
    ret_pct = (eq.iloc[-1] / eq.iloc[0] - 1.0) * 100.0
    max_dd = (eq / eq.cummax() - 1.0).min() * -100.0
    n_rebal = len(equity_df)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi("Performance", f"{ret_pct:+.1f}%", "positive" if ret_pct >= 0 else "negative")
    with c2:
        kpi("Equity finale", f"{eq.iloc[-1]:,.0f} $")
    with c3:
        kpi("Max Drawdown", f"{max_dd:.1f}%")
    with c4:
        kpi("Rebalances", str(n_rebal))

    # Equity curve
    section("Equity")
    fig_eq = go.Figure(
        go.Scatter(
            x=equity_df.index,
            y=equity_df.iloc[:, 0],
            mode="lines",
            line=dict(color="#1b3a57", width=2),
            name="Portfolio",
            fill="tozeroy",
            fillcolor="rgba(27,58,87,0.15)",
        )
    )
    fig_eq.update_layout(**PLOTLY_THEME, height=300)
    st.plotly_chart(fig_eq, use_container_width=True)

    if view == "Vue globale":
        # Stacked area of weights
        section("Allocation dans le temps")
        w_plot = weights_df.copy()
        if top_n < len(symbols):
            totals = w_plot.sum(axis=0).sort_values(ascending=False)
            keep = totals.head(top_n).index
            other = w_plot.drop(columns=keep).sum(axis=1)
            w_plot = w_plot[keep].copy()
            w_plot["OTHER"] = other
        fig_stack = go.Figure()
        for col in w_plot.columns:
            fig_stack.add_trace(
                go.Scatter(
                    x=w_plot.index,
                    y=w_plot[col],
                    stackgroup="one",
                    mode="lines",
                    line=dict(width=0.5),
                    name=col,
                )
            )
        fig_stack.update_layout(
            **PLOTLY_THEME, height=360, yaxis=dict(tickformat=".0%")
        )
        st.plotly_chart(fig_stack, use_container_width=True)

        # Score heatmap
        section("Heatmap des scores (26 derniers rebalancements)")
        fig_heat = px.imshow(
            scores_df.tail(26).T,
            aspect="auto",
            color_continuous_scale="RdBu",
            origin="lower",
        )
        fig_heat.update_layout(**PLOTLY_THEME, height=420)
        st.plotly_chart(fig_heat, use_container_width=True)

        # Symbol usage & profitability
        section("Utilisation et rentabilité par symbole")
        prices = _load_prices(tuple(symbols))
        contrib_df, used_df = _symbol_contrib(weights_df, prices)

        if not contrib_df.empty:
            usage = used_df.sum().sort_values(ascending=False)
            profit = contrib_df.sum().sort_values(ascending=False)

            left, right = st.columns(2)
            with left:
                fig_use = go.Figure(
                    go.Bar(
                        x=usage.head(top_n).index,
                        y=usage.head(top_n).values,
                        marker_color="#448aff",
                    )
                )
                fig_use.update_layout(
                    **PLOTLY_THEME, height=320,
                    yaxis_title="Nb sélections", title="Plus utilisés",
                )
                st.plotly_chart(fig_use, use_container_width=True)

            with right:
                tp = profit.head(top_n)
                fig_prof = go.Figure(
                    go.Bar(
                        x=tp.index,
                        y=tp.values * 100.0,
                        marker_color=[
                            "#00e676" if v >= 0 else "#ff5252" for v in tp.values
                        ],
                    )
                )
                fig_prof.update_layout(
                    **PLOTLY_THEME, height=320,
                    yaxis_title="Contribution %", title="Plus rentables",
                )
                st.plotly_chart(fig_prof, use_container_width=True)

            # Monthly contribution heatmap
            section("Contribution mensuelle par symbole (top 8)")
            top_syms = profit.head(min(8, len(profit))).index
            contrib_month = (
                contrib_df[top_syms].resample("ME").sum().tail(24) * 100.0
            )
            fig_hm = px.imshow(
                contrib_month.T,
                aspect="auto",
                color_continuous_scale="RdBu",
                color_continuous_midpoint=0,
                origin="lower",
            )
            fig_hm.update_layout(**PLOTLY_THEME, height=360)
            st.plotly_chart(fig_hm, use_container_width=True)

            # Diagnostics
            section("Diagnostics du modèle")
            active = weights_df.clip(lower=0.0)
            concentration = active.pow(2).sum(axis=1)
            turnover = active.diff().abs().sum(axis=1)
            active_count = (active > 0).sum(axis=1)

            d1, d2 = st.columns(2)
            with d1:
                fig_to = go.Figure(
                    go.Scatter(
                        x=turnover.index, y=turnover.values, mode="lines",
                        line=dict(color="#ffb300", width=2), name="Turnover",
                    )
                )
                fig_to.update_layout(
                    **PLOTLY_THEME, height=280, yaxis_title="Turnover"
                )
                st.plotly_chart(fig_to, use_container_width=True)

            with d2:
                fig_hf = go.Figure(
                    go.Scatter(
                        x=concentration.index, y=concentration.values, mode="lines",
                        line=dict(color="#00e676", width=2), name="Herfindahl",
                    )
                )
                fig_hf.update_layout(
                    **PLOTLY_THEME, height=280, yaxis_title="Concentration (Herfindahl)"
                )
                st.plotly_chart(fig_hf, use_container_width=True)

            fig_act = go.Figure(
                go.Scatter(
                    x=active_count.index, y=active_count.values, mode="lines",
                    line=dict(color="#1b3a57", width=2),
                )
            )
            fig_act.update_layout(
                **PLOTLY_THEME, height=260, yaxis_title="Nb actifs retenus"
            )
            st.plotly_chart(fig_act, use_container_width=True)

    else:  # Par date
        dates = equity_df.index
        date_sel = st.sidebar.date_input(
            "Date",
            value=dates.max().date(),
            min_value=dates.min().date(),
            max_value=dates.max().date(),
        )
        dt = pd.to_datetime(date_sel)
        if dt not in weights_df.index:
            dt = weights_df.index[
                weights_df.index.get_indexer([dt], method="ffill")
            ][0]

        st.markdown(f"### Allocation au {dt.date()}")
        w = weights_df.loc[dt]
        if isinstance(w, pd.DataFrame):
            w = w.iloc[-1]
        w = w[w > 0].sort_values(ascending=False).head(top_n)

        left, right = st.columns(2)
        with left:
            fig_pie = go.Figure(
                go.Pie(
                    labels=w.index, values=w.values,
                    hole=0.35, textinfo="label+percent",
                )
            )
            fig_pie.update_layout(**PLOTLY_THEME, height=380)
            st.plotly_chart(fig_pie, use_container_width=True)

        with right:
            scores = scores_df.loc[dt].sort_values(ascending=False).head(top_n)
            fig_bar = go.Figure(
                go.Bar(
                    x=scores.index, y=scores.values,
                    marker_color=[
                        "#00e676" if v >= 0 else "#ff5252" for v in scores.values
                    ],
                )
            )
            fig_bar.update_layout(
                **PLOTLY_THEME, height=380, yaxis_title="Score composite"
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        cash = max(0.0, 1.0 - float(weights_df.loc[dt].sum()))
        df_tbl = pd.DataFrame({"Poids": w})
        if cash > 0:
            df_tbl.loc["CASH"] = cash
        st.dataframe(
            df_tbl.style.format({"Poids": "{:.2%}"}),
            use_container_width=True,
        )


# ══════════════════════════════════════════════════════════════════
# PAGE 5 : COMPARAISON MÉTHODES
# ══════════════════════════════════════════════════════════════════

def page_compare() -> None:
    st.markdown("# ⚖️ Comparaison des méthodes")

    # Collect available result sets
    sources: dict[str, dict] = {}

    for label, path, color in [
        ("Vote — in-sample", CSV_VOTE, "#448aff"),
        ("Vote — walk-forward", CSV_VOTE_WF, "#00b0ff"),
        ("Random Forest (ML)", CSV_ML, "#00e676"),
    ]:
        if not path.exists():
            continue
        df = _load_flat(path)
        sym_col = "Symbol"
        sources[label] = {
            "df": df,
            "color": color,
            "best_alpha": df.groupby(sym_col)["Alpha vs B&H"].max(),
            "mean_alpha": df["Alpha vs B&H"].mean(),
            "beat_bh": (df["Alpha vs B&H"] > 0).mean() * 100,
            "mean_sharpe": df["Sharpe"].mean(),
            "mean_dd": df["Max Drawdown %"].mean(),
        }

    if not sources:
        st.warning(
            "Aucun résultat disponible. Lance au moins un backtest.\n\n"
            "```\npython backtest_multi.py\n"
            "python backtest_multi.py --walk-forward\n"
            "python backtest_multi.py --ml\n```"
        )
        return

    # KPI summary row
    section("Résumé global par méthode")
    cols = st.columns(len(sources))
    for i, (name, data) in enumerate(sources.items()):
        with cols[i]:
            kpi(
                name,
                f"α moy : {data['mean_alpha']:+.1f}%",
                "positive" if data["mean_alpha"] >= 0 else "negative",
            )
            st.caption(
                f"Beat B&H : {data['beat_bh']:.0f}%  |  "
                f"Sharpe : {data['mean_sharpe']:.2f}  |  "
                f"DD moy : {data['mean_dd']:.1f}%"
            )

    # Summary table
    section("Tableau comparatif")
    rows = [
        {
            "Méthode": name,
            "Alpha moyen": data["mean_alpha"],
            "Beat B&H (%)": data["beat_bh"],
            "Sharpe moyen": data["mean_sharpe"],
            "DD moyen": data["mean_dd"],
            "Meilleur alpha": data["best_alpha"].max(),
            "Pire alpha": data["best_alpha"].min(),
        }
        for name, data in sources.items()
    ]
    summary = pd.DataFrame(rows).set_index("Méthode")
    st.dataframe(
        summary.style.format(
            {
                "Alpha moyen": "{:+.1f}%",
                "Beat B&H (%)": "{:.0f}%",
                "Sharpe moyen": "{:.2f}",
                "DD moyen": "{:.1f}%",
                "Meilleur alpha": "{:+.1f}%",
                "Pire alpha": "{:+.1f}%",
            }
        ).background_gradient(
            subset=["Alpha moyen", "Beat B&H (%)"], cmap="RdBu", vmin=-10, vmax=10
        ),
        use_container_width=True,
    )

    # Best alpha per symbol per method
    section("Meilleur alpha par symbole — toutes méthodes")
    all_syms = sorted(
        set().union(*[set(d["best_alpha"].index) for d in sources.values()])
    )
    fig_comp = go.Figure()
    for name, data in sources.items():
        fig_comp.add_trace(
            go.Bar(
                x=all_syms,
                y=[data["best_alpha"].get(s, float("nan")) for s in all_syms],
                name=name,
                marker_color=data["color"],
            )
        )
    fig_comp.add_hline(y=0, line_color="rgba(255,255,255,0.15)")
    fig_comp.update_layout(
        **PLOTLY_THEME,
        barmode="group",
        height=420,
        yaxis=dict(ticksuffix="%", gridcolor="#1e1e1e"),
        xaxis=dict(tickangle=-35, tickfont=dict(size=10)),
    )
    st.plotly_chart(fig_comp, use_container_width=True)

    # Overfitting analysis (only when both in-sample and walk-forward exist)
    if "Vote — in-sample" in sources and "Vote — walk-forward" in sources:
        section("Analyse du biais in-sample (overfitting gap)")
        st.markdown(
            "La différence **in-sample − walk-forward** mesure le biais de data snooping. "
            "Un gap faible indique une stratégie robuste dont l'alpha est réel."
        )

        best_is = sources["Vote — in-sample"]["best_alpha"]
        best_wf = sources["Vote — walk-forward"]["best_alpha"]
        gap_df = pd.DataFrame(
            {"In-sample": best_is, "Walk-forward": best_wf}
        ).dropna()
        gap_df["Gap (biais)"] = gap_df["In-sample"] - gap_df["Walk-forward"]
        gap_df = gap_df.sort_values("Gap (biais)", ascending=False)

        fig_gap = go.Figure()
        fig_gap.add_trace(
            go.Bar(
                x=gap_df.index, y=gap_df["In-sample"],
                name="In-sample", marker_color="#448aff",
            )
        )
        fig_gap.add_trace(
            go.Bar(
                x=gap_df.index, y=gap_df["Walk-forward"],
                name="Walk-forward", marker_color="#00e676",
            )
        )
        fig_gap.update_layout(
            **PLOTLY_THEME,
            barmode="group",
            height=380,
            yaxis=dict(ticksuffix="%", gridcolor="#1e1e1e"),
            xaxis=dict(tickangle=-35, tickfont=dict(size=11)),
        )
        st.plotly_chart(fig_gap, use_container_width=True)

        col_a, col_b = st.columns(2)
        with col_a:
            avg_gap = gap_df["Gap (biais)"].mean()
            kpi(
                "Gap moyen (biais)",
                f"{avg_gap:+.1f}%",
                "negative" if avg_gap > 3 else "positive",
            )
        with col_b:
            robust = (gap_df["Gap (biais)"].abs() < 2).sum()
            kpi("Symboles robustes (gap < 2%)", f"{robust} / {len(gap_df)}")

        st.dataframe(
            gap_df.style.format(
                {
                    "In-sample": "{:+.1f}%",
                    "Walk-forward": "{:+.1f}%",
                    "Gap (biais)": "{:+.1f}%",
                }
            ).background_gradient(
                subset=["Gap (biais)"], cmap="Reds", vmin=0, vmax=15
            ),
            use_container_width=True,
        )


# ══════════════════════════════════════════════════════════════════
# PAGE 5 : OPTIMIZE TOP-X
# ══════════════════════════════════════════════════════════════════

def page_optimize_topx() -> None:
    st.markdown("# 🧪 Optimize Top-X — Comparaison de toutes les stratégies")

    df = _load_flat(CSV_OPTIMIZE_TOPX)
    if df.empty:
        st.error(
            "Aucun résultat.\n\n"
            "```\npython optimize_topx.py\n```"
        )
        return

    # ── Sidebar filters ──────────────────────────────────────────
    with st.sidebar:
        st.markdown("### Filtres")
        min_sharpe = st.slider(
            "Sharpe minimum", -3.0, 5.0, -3.0, step=0.1
        )
        max_dd = st.slider(
            "Max Drawdown maximum (%)", 0.0, 100.0, 100.0, step=1.0
        )
        min_active = st.slider(
            "Symboles actifs minimum (moy)", 0.0, 10.0, 0.0, step=0.5
        )
        sort_col = st.selectbox(
            "Trier par",
            ["Sharpe", "Performance %", "Max Drawdown %", "Avg Symbols Active"],
            index=0,
        )
        sort_asc = st.checkbox("Ordre croissant", value=False)
        top_n_bar = st.slider("Top N dans les graphiques", 5, 50, 20)

    df_f = df[
        (df["Sharpe"] >= min_sharpe)
        & (df["Max Drawdown %"] <= max_dd)
        & (df["Avg Symbols Active"] >= min_active)
    ].sort_values(sort_col, ascending=sort_asc)

    # ── KPIs ─────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        kpi("Stratégies testées", str(len(df)))
    with c2:
        kpi("Après filtres", str(len(df_f)))
    with c3:
        best = df["Sharpe"].max()
        kpi("Meilleur Sharpe", f"{best:.3f}", "positive" if best > 0 else "negative")
    with c4:
        best_perf = df["Performance %"].max()
        kpi(
            "Meilleure Perf.",
            f"{best_perf:+.1f}%",
            "positive" if best_perf >= 0 else "negative",
        )
    with c5:
        pct_pos = (df["Performance %"] >= 0).mean() * 100
        kpi("Strat. profitables", f"{pct_pos:.0f}%")

    st.markdown("---")

    # ── Scatter : Sharpe vs Performance ──────────────────────────
    section("Sharpe vs Performance — chaque point est une stratégie")
    st.caption(
        "Taille = symboles actifs en moyenne · Couleur = Max Drawdown"
    )
    fig_sc = px.scatter(
        df_f,
        x="Performance %",
        y="Sharpe",
        color="Max Drawdown %",
        size=df_f["Avg Symbols Active"].clip(lower=0.5),
        hover_name="Strategy",
        hover_data={
            "Performance %": ":.2f",
            "Sharpe": ":.3f",
            "Max Drawdown %": ":.2f",
            "Avg Symbols Active": ":.1f",
            "Rebalances In Cash": True,
        },
        color_continuous_scale="RdBu_r",
        labels={
            "Performance %": "Performance %",
            "Sharpe": "Sharpe annuel",
        },
    )
    fig_sc.add_vline(x=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
    fig_sc.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
    fig_sc.update_layout(**PLOTLY_THEME, height=450)
    st.plotly_chart(fig_sc, use_container_width=True)

    # ── Top N bar charts ─────────────────────────────────────────
    left, right = st.columns(2)

    with left:
        section(f"Top {top_n_bar} — Sharpe")
        top_sharpe = df_f.nlargest(top_n_bar, "Sharpe")
        fig_sh = go.Figure(
            go.Bar(
                x=top_sharpe["Strategy"],
                y=top_sharpe["Sharpe"],
                marker_color=[
                    "#00e676" if v >= 0 else "#ff5252"
                    for v in top_sharpe["Sharpe"]
                ],
                text=[f"{v:.3f}" for v in top_sharpe["Sharpe"]],
                textposition="outside",
                textfont=dict(size=9),
            )
        )
        fig_sh.add_hline(y=0, line_color="rgba(255,255,255,0.15)")
        fig_sh.update_layout(
            **PLOTLY_THEME,
            height=400,
            xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
        )
        st.plotly_chart(fig_sh, use_container_width=True)

    with right:
        section(f"Top {top_n_bar} — Performance %")
        top_perf = df_f.nlargest(top_n_bar, "Performance %")
        fig_pf = go.Figure(
            go.Bar(
                x=top_perf["Strategy"],
                y=top_perf["Performance %"],
                marker_color=[
                    "#00e676" if v >= 0 else "#ff5252"
                    for v in top_perf["Performance %"]
                ],
                text=[f"{v:+.1f}%" for v in top_perf["Performance %"]],
                textposition="outside",
                textfont=dict(size=9),
            )
        )
        fig_pf.add_hline(y=0, line_color="rgba(255,255,255,0.15)")
        fig_pf.update_layout(
            **PLOTLY_THEME,
            height=400,
            xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
        )
        st.plotly_chart(fig_pf, use_container_width=True)

    # ── Signal frequency in top strategies ───────────────────────
    section(
        f"Signaux les plus présents dans le top {top_n_bar} (par Sharpe)"
    )
    st.caption(
        "Montre quels signaux reviennent le plus dans les meilleures stratégies."
    )
    top_strats = df.nlargest(top_n_bar, "Sharpe")["Strategy"]
    signal_counts: dict[str, int] = {}
    for name in top_strats:
        base = name.replace("_2v3", "").replace("_3v3", "").replace("_3v4", "").replace("_3v5", "")
        for sig in base.split("+"):
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

    if signal_counts:
        sc_sorted = sorted(signal_counts.items(), key=lambda x: x[1], reverse=True)
        sc_df = pd.DataFrame(sc_sorted, columns=["Signal", "Occurrences"])
        fig_freq = go.Figure(
            go.Bar(
                x=sc_df["Signal"],
                y=sc_df["Occurrences"],
                marker_color="#448aff",
                text=sc_df["Occurrences"],
                textposition="outside",
            )
        )
        fig_freq.update_layout(
            **PLOTLY_THEME,
            height=320,
            yaxis_title="Nb d'apparitions dans le top",
            xaxis=dict(tickangle=-35),
        )
        st.plotly_chart(fig_freq, use_container_width=True)

    # ── Distributions ─────────────────────────────────────────────
    section("Distributions (toutes stratégies)")
    d1, d2 = st.columns(2)

    with d1:
        fig_hist_sh = px.histogram(
            df,
            x="Sharpe",
            nbins=50,
            color_discrete_sequence=["#448aff"],
            title="Distribution des Sharpe",
        )
        fig_hist_sh.add_vline(x=0, line_dash="dash", line_color="#ff5252")
        fig_hist_sh.update_layout(**PLOTLY_THEME, height=300)
        st.plotly_chart(fig_hist_sh, use_container_width=True)

    with d2:
        fig_hist_pf = px.histogram(
            df,
            x="Performance %",
            nbins=50,
            color_discrete_sequence=["#00e676"],
            title="Distribution des Performances",
        )
        fig_hist_pf.add_vline(x=0, line_dash="dash", line_color="#ff5252")
        fig_hist_pf.update_layout(**PLOTLY_THEME, height=300)
        st.plotly_chart(fig_hist_pf, use_container_width=True)

    # ── Full table ───────────────────────────────────────────────
    section(f"Tableau complet ({len(df_f)} stratégies)")
    st.dataframe(
        df_f[
            [
                "Strategy",
                "Performance %",
                "Sharpe",
                "Max Drawdown %",
                "Avg Symbols Active",
                "Rebalances In Cash",
            ]
        ]
        .reset_index(drop=True)
        .style.format(
            {
                "Performance %": "{:+.2f}%",
                "Sharpe": "{:.3f}",
                "Max Drawdown %": "{:.2f}%",
                "Avg Symbols Active": "{:.1f}",
                "Rebalances In Cash": "{:.0f}",
            }
        )
        .background_gradient(subset=["Sharpe"], cmap="RdBu", vmin=-2, vmax=2)
        .background_gradient(
            subset=["Performance %"], cmap="RdBu", vmin=-50, vmax=50
        ),
        use_container_width=True,
        height=500,
    )


# ══════════════════════════════════════════════════════════════════
# PAGE 7 : STRATÉGIE V2 — LES CHOIX
# ══════════════════════════════════════════════════════════════════

def page_v2_choices() -> None:
    st.markdown("# 🧠 Stratégie V2 — chaque choix expliqué")
    st.caption(
        "Mean-reversion filtré par régime, barres 15 min, long-only. "
        "Code : `research/backtest_v2_regime_mr.py`"
    )

    # ── Contexte ─────────────────────────────────────────────────
    section("Pourquoi une V2 — le diagnostic de la V1")
    st.markdown(
        """
La V1 (vote BB + OU + VWAP + VolSpike + KalmanZ, seuil 2, stop 2 %)
perdait **~ −40 % sur 3 ans** après coûts, et sa sélection top-5 par
Sharpe glissant ne battait que 31 % des sélections aléatoires. Quatre
causes identifiées, chacune corrigée par un choix précis de la V2 :

| Problème V1 | Correction V2 |
|---|---|
| 4 signaux qui mesurent tous « le prix est sous sa moyenne » (redondants) | Un seul déclencheur (z-score) + deux filtres **orthogonaux** (régime, volatilité) |
| Aucune vraie sortie : on attend le signal opposé, stop fixe 2 % | 3 sorties dédiées : take-profit à la moyenne, stop temporel, stop-loss en σ |
| ~460 combinaisons × 30 symboles = 14 000 backtests, gagnants choisis a posteriori | Grille de **12** combinaisons, calibrée sur le train uniquement |
| Barres corrompues (close ETH à 6.7e-06) dans les classements | Filtre de glitchs par médiane mobile avant tout calcul |
"""
    )

    st.markdown("---")

    # ── Choix 1 : barres 15 min ──────────────────────────────────
    section("Choix 1 — Barres 15 minutes (au lieu de 5)")
    st.markdown(
        """
Chaque aller-retour coûte **0,20 %** (0,10 % par côté : frais +
slippage), quel que soit le résultat du trade. Sur des barres de
5 min, les mouvements exploitables sont souvent plus petits que ce
péage : on multiplie les trades dont le gain brut ne couvre pas les
frais. En agrégeant en 15 min, le mouvement moyen par signal grossit,
le bruit diminue, et le nombre de trades chute — on paie le péage
moins souvent, pour des trajets plus longs.
"""
    )
    with st.expander("Dans le code"):
        st.code(
            'df.resample("15min").agg({"open": "first", "high": "max",'
            ' "low": "min", "close": "last", "volume": "sum"})',
            language="python",
        )

    # ── Choix 2 : z-score ────────────────────────────────────────
    section("Choix 2 — Le déclencheur : z-score en croisement")
    st.markdown(
        """
Le z-score mesure l'écart du prix à sa moyenne mobile, **exprimé en
écarts-types** :
"""
    )
    st.latex(r"z_t = \frac{close_t - SMA_{100}}{\sigma_{100}}")
    st.markdown(
        """
Un z de −1,5 signifie : le prix est 1,5 écart-type sous sa moyenne
des ~2-4 derniers jours — un niveau statistiquement inhabituel, qui
tend à se résorber (retour à la moyenne).

Deux décisions importantes ici :

- **Croisement, pas niveau.** On entre quand z *franchit* −1,5
  (`z(t−1) ≥ −1,5` et `z(t) < −1,5`), pas quand il *est* sous −1,5.
  Un signal de niveau se re-déclenche à chaque barre pendant que le
  prix s'enfonce — c'est ce qui faisait racheter la V1 en pleine
  chute. Le croisement donne une seule entrée par excursion.
- **Un seul estimateur de moyenne.** BB, OU, KalmanZ et VWAP sont
  quatre variantes du même calcul, corrélées entre elles. Un vote
  entre clones n'ajoute aucune information, seulement des paramètres
  à sur-ajuster. La V2 garde un déclencheur unique et place
  l'intelligence dans les *filtres* (choix 3 et 4).
"""
    )

    # ── Choix 3 : Efficiency Ratio ───────────────────────────────
    section("Choix 3 — Le filtre de régime : Efficiency Ratio < 0,35")
    st.markdown(
        """
Le retour à la moyenne ne fonctionne que si le marché **oscille**.
Pendant une tendance, acheter « parce que c'est bas » revient à se
placer face au mouvement. L'Efficiency Ratio de Kaufman distingue
les deux régimes en comparant le déplacement *net* du prix à la
distance *totale* parcourue :
"""
    )
    st.latex(
        r"ER = \frac{|close_t - close_{t-48}|}"
        r"{\sum_{i=t-47}^{t} |close_i - close_{i-1}|}"
    )
    st.markdown(
        """
- **ER proche de 1** : le prix va tout droit → tendance → on ne
  trade pas.
- **ER proche de 0** : le prix fait beaucoup de chemin pour finir
  près de son point de départ → range → le retour à la moyenne a
  ses chances.

L'entrée n'est autorisée que si **ER < 0,35** sur les 48 dernières
barres (~12 h). Ce filtre existait déjà dans `strategies.py`
(`Regime_Range`) mais était désactivé — c'est le signal orthogonal
qui manquait au vote de la V1.
"""
    )

    # ── Choix 4 : filtre de volatilité ───────────────────────────
    section("Choix 4 — Le filtre économique : volatilité ≥ 0,3 %")
    st.markdown(
        """
Le gain espéré d'un trade de retour à la moyenne est à peu près la
distance à la moyenne au moment de l'entrée, soit
`|z| × σ ≈ 1,5 σ`. Si σ est trop petit, même un retour parfait ne
rembourse pas les 0,20 % de coûts. On exige donc :
"""
    )
    st.latex(
        r"\frac{\sigma_{100}}{close} \geq 0{,}003"
        r"\quad\Rightarrow\quad"
        r"\text{gain espéré} \approx 1{,}5 \times 0{,}3\,\% = 0{,}45\,\%"
        r" \gg 0{,}20\,\% \text{ de coûts}"
    )
    st.markdown(
        """
C'est la traduction directe du diagnostic V1 : les signaux ne
perdaient pas tant que ça *avant* frais — ce sont les coûts qui
mangeaient un gain brut trop petit. Sur le train, ce filtre à 0,003
bat sa variante à 0,002 pour **toutes** les combinaisons testées :
moins de trades, meilleurs trades.
"""
    )

    # ── Choix 5 : les sorties ────────────────────────────────────
    section("Choix 5 — Trois sorties, chacune avec un rôle")
    st.markdown(
        """
La V1 achetait « trop bas » et revendait « trop haut », sans rien
entre les deux : une position pouvait glisser des semaines sans
déclencher ni la revente ni le stop. La V2 donne à chaque trade un
objectif, une date limite et un plan d'évacuation :

| Sortie | Condition | Rôle |
|---|---|---|
| **Take-profit** | z ≥ 0 | Le prix a retouché sa moyenne : l'espérance conditionnelle du trade est consommée. Attendre le seuil opposé (+2σ) transformerait la seconde moitié du trade en pari directionnel sans edge. |
| **Stop temporel** | 96 barres (~4 jours de bourse) | Si la moyenne n'est pas retouchée dans le délai, le contexte a changé : l'edge estimé à l'entrée n'existe plus. Élimine les « positions zombies ». |
| **Stop-loss** | prix ≤ entrée − 3σ | Dimensionné en volatilité, pas en % fixe : 2 % est trop serré pour TSLA, trop lâche pour SPY. À 3σ, il ne se déclenche que si l'hypothèse « étirement » est statistiquement réfutée — c'est devenu une tendance. |
"""
    )

    # ── Choix 6 : protocole ──────────────────────────────────────
    section("Choix 6 — La discipline de validation")
    st.markdown(
        """
Le choix le plus important n'est pas dans la stratégie mais dans la
méthode :

1. **Coupe 70 / 30 dans le temps** : calibration sur mars 2023 →
   juin 2025 (train), évaluation sur juin 2025 → mai 2026 (test),
   regardée **une seule fois** à la fin.
2. **Grille minuscule** : 12 combinaisons (3 seuils z × 2 seuils ER
   × 2 seuils σ). Avec 14 000 backtests comme la V1, trouver des
   gagnants in-sample est une certitude statistique, pas une
   découverte. Avec 12, le meilleur du train a encore un sens.
3. **Benchmark anti-chance** : sur le test, on rejoue 200 fois le
   même nombre de trades, avec les mêmes durées, mais à des dates
   aléatoires. Une stratégie dont les signaux valent quelque chose
   doit battre ce benchmark — voir la page « Le test ».
"""
    )

    st.info(
        "Paramètres retenus (sélection sur le train) : "
        "**z_entry = 1,5 · ER < 0,35 · σ/prix ≥ 0,003 · "
        "max_hold = 96 barres · stop = 3σ · coût = 0,10 %/côté**"
    )


# ══════════════════════════════════════════════════════════════════
# PAGE 8 : STRATÉGIE V2 — LE TEST
# ══════════════════════════════════════════════════════════════════

# Valeurs issues du run du 2026-07-05 qui ne sont pas recalculables
# depuis les CSV (benchmark aléatoire, split train/test, actions
# seules). Relancer backtest_v2_regime_mr.py pour les régénérer.
V2_RUN_INFO: dict = {
    "run_date": "2026-07-05",
    "train_range": "2023-03-01 → 2025-06-12",
    "test_range": "2025-06-12 → 2026-05-15",
    "grid_best": "z=1.5, ER<0.35, σ_rel≥0.003 (Sharpe train −0.671)",
    "pct_random_beaten": 87,
    "random_median_pct": -4.89,
    "stocks_only_test_ret": +1.97,
    "stocks_only_test_sharpe": +0.371,
    "stocks_only_train_ret": -9.04,
    "train_sharpes": [
        ("z=1.5 ER<0.25 σ≥0.002", -0.959),
        ("z=1.5 ER<0.25 σ≥0.003", -0.793),
        ("z=1.5 ER<0.35 σ≥0.002", -0.819),
        ("z=1.5 ER<0.35 σ≥0.003", -0.671),
        ("z=2.0 ER<0.25 σ≥0.002", -1.128),
        ("z=2.0 ER<0.25 σ≥0.003", -0.925),
        ("z=2.0 ER<0.35 σ≥0.002", -1.141),
        ("z=2.0 ER<0.35 σ≥0.003", -0.981),
        ("z=2.5 ER<0.25 σ≥0.002", -1.225),
        ("z=2.5 ER<0.25 σ≥0.003", -1.022),
        ("z=2.5 ER<0.35 σ≥0.002", -1.444),
        ("z=2.5 ER<0.35 σ≥0.003", -1.311),
    ],
}


def page_v2_test() -> None:
    st.markdown("# 🔬 Stratégie V2 — protocole et résultats du test")

    df = _load_flat(CSV_V2_RESULTS)
    eq = _load_dated(CSV_V2_EQUITY)
    if df.empty or eq.empty:
        st.error(
            "Aucun résultat V2 trouvé.\n\n"
            "```\npython backtest_v2_regime_mr.py\n```"
        )
        return

    info = V2_RUN_INFO

    # ── Protocole ────────────────────────────────────────────────
    section("Le protocole")
    st.markdown(
        f"""
- **Données** : 30 symboles, 3 ans de barres 5 min nettoyées
  (filtre de glitchs) puis rééchantillonnées en 15 min.
- **Train** ({info["train_range"]}) : les 12 combinaisons de la
  grille sont scorées sur le Sharpe du portefeuille équipondéré.
- **Test** ({info["test_range"]}) : la combinaison gagnante du train
  est évaluée **une seule fois** sur cette période jamais vue.
- **Coûts** : 0,10 % par côté (frais + slippage), entrée/sortie au
  close de la barre du signal.
- **Benchmark anti-chance** : 200 rejeux à entrées aléatoires, même
  nombre de trades et mêmes durées de détention.
"""
    )

    with st.expander("Grille complète — Sharpe train des 12 combinaisons"):
        grid_df = pd.DataFrame(
            info["train_sharpes"], columns=["Combinaison", "Sharpe train"]
        ).sort_values("Sharpe train", ascending=False)
        st.dataframe(
            grid_df.reset_index(drop=True).style.format(
                {"Sharpe train": "{:+.3f}"}
            ),
            use_container_width=True,
        )
        st.caption(
            "Toutes négatives sur le train : la sélection retient la "
            "moins mauvaise, le verdict se joue sur le test. "
            f"Retenue : {info['grid_best']}."
        )

    st.markdown("---")

    # ── KPIs portefeuille (recalculés depuis les CSV) ────────────
    section("Résultats — portefeuille test (30 symboles)")
    rets = eq["test_equity"].pct_change().dropna()
    years = max(
        (eq.index[-1] - eq.index[0]).days / 365.25, 1e-9
    )
    ann_sharpe = (
        0.0 if rets.std() == 0
        else float(rets.mean() / rets.std() * np.sqrt(len(rets) / years))
    )
    total_ret = float(eq["test_equity"].iloc[-1] / eq["test_equity"].iloc[0] - 1) * 100
    peak = eq["test_equity"].cummax()
    max_dd = float(((peak - eq["test_equity"]) / peak).max()) * 100
    n_trades = int(df["test_trades"].sum())
    win_rate = float(
        (df["test_trades"] * df["test_win_rate_%"]).sum()
        / max(df["test_trades"].sum(), 1)
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        kpi(
            "Rendement test", f"{total_ret:+.2f}%",
            "positive" if total_ret >= 0 else "negative",
        )
    with c2:
        kpi(
            "Sharpe annualisé", f"{ann_sharpe:+.3f}",
            "positive" if ann_sharpe >= 0 else "negative",
        )
    with c3:
        kpi("Max Drawdown", f"{max_dd:.2f}%", "negative")
    with c4:
        kpi("Trades (test)", f"{n_trades}")
    with c5:
        kpi("Win rate moyen", f"{win_rate:.1f}%")

    st.markdown(
        f"""
| Portefeuille | Rendement test | Sharpe |
|---|---|---|
| 30 symboles (avec crypto) | {total_ret:+.2f} % | {ann_sharpe:+.3f} |
| Actions seules (28) | **{info["stocks_only_test_ret"]:+.2f} %** | **{info["stocks_only_test_sharpe"]:+.3f}** |
| Hasard (médiane des 200 rejeux) | {info["random_median_pct"]:+.2f} % | — |

La stratégie bat **{info["pct_random_beaten"]} % des 200 rejeux
aléatoires** (la sélection top-X de la V1 n'en battait que 31 %).
"""
    )

    # ── Courbe d'équité ──────────────────────────────────────────
    section("Courbe d'équité — période de test")
    fig_eq = go.Figure(
        go.Scatter(
            x=eq.index, y=eq["test_equity"],
            line=dict(color="#448aff", width=2), name="V2 (30 symboles)",
        )
    )
    fig_eq.add_hline(y=1.0, line_dash="dot", line_color="rgba(255,255,255,0.25)")
    fig_eq.update_layout(
        **PLOTLY_THEME, height=380,
        yaxis=dict(gridcolor="#1e1e1e", title="Équité (base 1.0)"),
    )
    st.plotly_chart(fig_eq, use_container_width=True)

    # ── Par symbole ──────────────────────────────────────────────
    section("Rendement net par symbole (test)")
    df_sorted = df.sort_values("test_total_net_%", ascending=False)
    st.plotly_chart(
        _alpha_bar(
            df_sorted["symbol"], df_sorted["test_total_net_%"], height=420
        ),
        use_container_width=True,
    )
    st.caption(
        "BTC et ETH perdent lourdement — comme sur le train (−55 % / "
        "−49 %), ce qui justifie de les exclure sans tricher sur le "
        "test : en 15 min, ils tendent plus qu'ils ne « rangent »."
    )

    section("Détail par symbole")
    st.dataframe(
        df_sorted.reset_index(drop=True).style.format({
            "test_win_rate_%": "{:.1f}%",
            "test_avg_net_per_trade_%": "{:+.3f}%",
            "test_total_net_%": "{:+.2f}%",
        }).background_gradient(
            subset=["test_total_net_%"], cmap="RdBu", vmin=-35, vmax=35
        ),
        use_container_width=True,
        height=500,
    )

    # ── Verdict ──────────────────────────────────────────────────
    st.markdown("---")
    section("Verdict honnête")
    st.markdown(
        f"""
- ✅ **Énorme progrès vs V1** : de −40 % sur 3 ans à ~l'équilibre
  après coûts sur l'année de test, en battant
  {info["pct_random_beaten"]} % du hasard.
- ⚠️ **Pas encore un edge démontré** : le train actions seules est à
  {info["stocks_only_train_ret"]:+.2f} % — une année de test positive
  ne suffit pas.
- 🎯 **La frontière actuelle est le coût d'exécution** : gain net
  moyen par trade ≈ 0 alors que le win rate est de
  {win_rate:.0f} %. Pistes : ordres limit au niveau −1,5σ (supprime
  l'essentiel du slippage), coûts réels Alpaca (~0,05 %/côté ?),
  actions uniquement.

*Run du {info["run_date"]} — relancer
`python backtest_v2_regime_mr.py` pour régénérer les CSV.*
"""
    )


# ══════════════════════════════════════════════════════════════════
# PAGE 9 : SÉLECTION TOP-X (V2)
# ══════════════════════════════════════════════════════════════════

def page_v2_topx() -> None:
    st.markdown("# 🎯 Sélection Top-X — investir sur les 5 meilleures, pas toutes")
    st.caption(
        "Toutes les actions restent suivies en base ; seules les "
        "TOP_X les plus prometteuses reçoivent du capital chaque "
        "semaine. Code : `research/backtest_v2_topx.py`"
    )

    eq = _load_dated(CSV_V2_TOPX_EQUITY)
    sel = _load_flat(CSV_V2_TOPX_SELECTION)
    if eq.empty:
        st.error(
            "Aucun résultat trouvé.\n\n"
            "```\npython backtest_v2_topx.py\n```"
        )
        return

    # ── Principe ─────────────────────────────────────────────────
    section("Le principe : deux garde-fous contre la chute libre")
    st.markdown(
        """
Une stratégie de retour à la moyenne achète *par nature* ce qui vient
de baisser. Le risque « acheter un couteau qui tombe » est donc réel,
et il est traité à deux niveaux distincts :

1. **Au niveau de la barre** (déjà dans la stratégie V2) — le filtre
   de régime (Efficiency Ratio) bloque toute entrée tant que le
   marché est en tendance, y compris une tendance baissière.
2. **Au niveau de la sélection hebdomadaire** (nouveau, ce module) —
   une action est retirée de l'univers investissable pour la semaine
   si son rendement sur les 20 derniers jours est **inférieur à
   −15 %** : un déclin prolongé, même s'il contient des rebonds
   locaux qui passeraient le filtre du point 1.

Parmi les actions restantes (« éligibles »), on classe par Sharpe
glissant de **leur propre** stratégie V2 (comme `scorer.py` en live)
et on retient les 5 mieux classées, en poids égaux.
"""
    )

    st.markdown("---")

    # ── Comparaison des 4 portefeuilles ───────────────────────────
    section("Quatre portefeuilles comparés sur la période de test")
    cols = st.columns(3)
    labels = {
        "topx_equity": ("Top-5 (filtre + classement)", "primary"),
        "all_equity": ("Équipondéré — TOUTES les actions", "neutral"),
        "eligible_equity": ("Équipondéré — éligibles seuls", "neutral"),
    }
    for i, (col_name, (label, _)) in enumerate(labels.items()):
        if col_name not in eq.columns:
            continue
        ret = float(eq[col_name].iloc[-1] / eq[col_name].iloc[0] - 1) * 100
        with cols[i % 3]:
            kpi(label, f"{ret:+.2f}%", "positive" if ret >= 0 else "negative")

    fig = go.Figure()
    colors = {"topx_equity": "#00e676", "all_equity": "#448aff",
              "eligible_equity": "#ffb300"}
    names = {"topx_equity": f"Top-X sélection",
             "all_equity": "Équipondéré (tous)",
             "eligible_equity": "Équipondéré (éligibles)"}
    for col_name in ["topx_equity", "all_equity", "eligible_equity"]:
        if col_name in eq.columns:
            fig.add_scatter(
                x=eq.index, y=eq[col_name], name=names[col_name],
                line=dict(width=2, color=colors[col_name]),
            )
    fig.add_hline(y=1.0, line_dash="dot", line_color="rgba(255,255,255,0.25)")
    fig.update_layout(
        **PLOTLY_THEME, height=420,
        yaxis=dict(gridcolor="#1e1e1e", title="Équité (base 1.0)"),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Remarque contre-intuitive : « éligibles seuls » (le filtre "
        "anti-chute libre sans classement) est parfois *pire* que "
        "« toutes les actions ». Le filtre 20 jours exclut aussi des "
        "actions très volatiles (ex. TSLA) pendant leurs creux — "
        "précisément le moment où une stratégie de retour à la "
        "moyenne est la plus rentable. Le filtre protège contre le "
        "risque structurel, mais n'est pas gratuit."
    )

    st.markdown("---")

    # ── Effet du lookback de classement ───────────────────────────
    section("Le classement hebdomadaire à courte vue ne marche pas")
    st.markdown(
        """
Premier essai avec un Sharpe glissant sur 20 jours (comme
`scorer.py` en live) : la sélection ne battait que **27 % des tirages
aléatoires** — le même symptôme que la V1. Des actions perdantes sur
l'ensemble de la période (SNAP, PYPL, PLTR) étaient sélectionnées 8 à
9 fois sur 45 semaines : le Sharpe à 20 jours est trop bruité pour
prédire la semaine suivante.

En allongeant la fenêtre de classement, sur la **même période
d'évaluation** (pour isoler l'effet du lookback de tout artefact de
fenêtre) :
"""
    )
    lookback_df = pd.DataFrame({
        "Lookback classement": ["20 jours", "40 jours", "60 jours", "90 jours"],
        "Rendement (fenêtre fixe)": ["−2,15 %", "−1,32 %", "−1,77 %", "+2,36 %"],
        "Sharpe": ["−0,307", "−0,169", "−0,236", "+0,438"],
    })
    st.dataframe(lookback_df, use_container_width=True, hide_index=True)
    st.markdown(
        """
Seul le lookback à **90 jours** (un trimestre) fait passer la
sélection en territoire positif — c'est la valeur retenue par défaut
dans `backtest_v2_topx.py`. Un Sharpe estimé sur un trimestre lisse
le bruit hebdomadaire ; en dessous, le classement revient à choisir
au hasard parmi les actions qui viennent d'avoir une bonne ou
mauvaise semaine, sans rapport avec la semaine suivante.
"""
    )

    # ── Résultat final ────────────────────────────────────────────
    section("Résultat retenu — lookback 90 jours")
    if "topx_equity" in eq.columns:
        total_ret = float(
            eq["topx_equity"].iloc[-1] / eq["topx_equity"].iloc[0] - 1
        ) * 100
        rets = eq["topx_equity"].pct_change().dropna()
        years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
        ann_sharpe = (
            0.0 if rets.std() == 0
            else float(rets.mean() / rets.std() * np.sqrt(len(rets) / years))
        )
        peak = eq["topx_equity"].cummax()
        max_dd = float(
            ((peak - eq["topx_equity"]) / peak).max()
        ) * 100
        c1, c2, c3 = st.columns(3)
        with c1:
            kpi("Rendement", f"{total_ret:+.2f}%",
                "positive" if total_ret >= 0 else "negative")
        with c2:
            kpi("Sharpe annualisé", f"{ann_sharpe:+.3f}",
                "positive" if ann_sharpe >= 0 else "negative")
        with c3:
            kpi("Max Drawdown", f"{max_dd:.2f}%", "negative")

    if not sel.empty:
        with st.expander("Historique des sélections hebdomadaires"):
            st.dataframe(
                sel[["rebalance", "n_eligible", "selected"]]
                .reset_index(drop=True),
                use_container_width=True, height=400,
            )

    # ── Verdict ──────────────────────────────────────────────────
    st.markdown("---")
    section("Verdict honnête")
    st.markdown(
        """
- ✅ Le principe **DB complète + sélection top-X** fonctionne
  correctement une fois le classement calibré sur une fenêtre assez
  longue (90 jours) pour ne pas être du bruit.
- ⚠️ L'échantillon reste petit (~0,66 an, une trentaine de
  rebalancements) : un seul lookback gagnant sur quatre testés est un
  indice encourageant, pas une preuve définitive — à reconfirmer sur
  plus de données une fois davantage d'historique accumulé.
- 🛡️ Le filtre anti-chute libre (20 jours, −15 %) protège le
  principal risque redouté, mais son coût (exclusion d'actions
  volatiles pendant leurs meilleurs points d'entrée) doit être
  accepté consciemment, pas subi.
"""
    )


# ── Dispatch ─────────────────────────────────────────────────────
if page == "vote":
    page_vote()
elif page == "ml":
    page_ml()
elif page == "hyper":
    page_hyperparams()
elif page == "topx":
    page_topx()
elif page == "optimize_topx":
    page_optimize_topx()
elif page == "v2_choices":
    page_v2_choices()
elif page == "v2_test":
    page_v2_test()
elif page == "v2_topx":
    page_v2_topx()
elif page == "compare":
    page_compare()
