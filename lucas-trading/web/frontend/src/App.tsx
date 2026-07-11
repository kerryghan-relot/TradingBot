import { useCallback, useEffect, useRef, useState } from "react";
import { T } from "./theme";
import { tabButtonStyle } from "./ui";
import {
  fetchHistory,
  fetchLive,
  fetchStrategies,
  selectStrategy,
} from "./api";
import type {
  Bench,
  HistoryPayload,
  JournalCat,
  LivePayload,
  Period,
  StrategiesPayload,
} from "./types";
import { Header } from "./components/Header";
import { StrategySwitcher } from "./components/StrategySwitcher";
import { TickerStrip } from "./components/Ticker";
import { StatsOverview } from "./components/Stats";
import { LiveView } from "./components/LiveView";
import { HistoryView } from "./components/HistoryView";
import { Analysis } from "./components/Analysis";
import { ConfigPage } from "./components/ConfigPage";

const LIVE_POLL_MS = 2500;

export function App() {
  const [route, setRoute] = useState<"dashboard" | "config">("dashboard");
  const [strategies, setStrategies] = useState<StrategiesPayload | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [live, setLive] = useState<LivePayload | null>(null);
  const [history, setHistory] = useState<HistoryPayload | null>(null);

  const [tab, setTab] = useState<"live" | "hist">("live");
  const [period, setPeriod] = useState<Period>("all");
  const [bench, setBench] = useState<Bench>("none");
  const [jcat, setJcat] = useState<JournalCat>("Tous");

  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  // Load strategy list once, seed the selected strategy from the active.
  useEffect(() => {
    fetchStrategies()
      .then((s) => {
        setStrategies(s);
        setSelected(s.active);
      })
      .catch(() => setStrategies({ active: "", demo: false, strategies: [] }));
  }, []);

  // Poll live data on an interval, always with the current selection.
  useEffect(() => {
    if (!selected) return;
    let alive = true;
    const tick = () =>
      fetchLive(selectedRef.current)
        .then((p) => alive && setLive(p))
        .catch(() => {});
    tick();
    const id = setInterval(tick, LIVE_POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [selected]);

  // Refetch history when the query (strategy / period / benchmark) changes.
  useEffect(() => {
    if (!selected) return;
    fetchHistory(selected, period, bench)
      .then(setHistory)
      .catch(() => {});
  }, [selected, period, bench]);

  const onSelect = useCallback(async (id: string) => {
    setSelected(id);
    await selectStrategy(id).catch(() => {});
    fetchStrategies().then(setStrategies).catch(() => {});
  }, []);

  if (!live || !strategies) {
    return <Splash />;
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: T.bg,
        color: T.text,
        fontFamily: T.sans,
        padding: "20px 24px 48px",
        fontSize: 14,
        lineHeight: 1.4,
      }}
    >
      <Header
        universeLabel={live.universeLabel}
        bot={live.bot}
        clock={live.clock}
        route={route}
        onRoute={setRoute}
      />

      {live.error && <ErrorBanner message={live.error} />}
      {live.demo && route === "dashboard" && <DemoBanner />}

      {route === "config" ? (
        <ConfigPage />
      ) : (
        <>
          <StrategySwitcher
            strategies={strategies.strategies}
            active={selected}
            activeLabel={live.strategy.label}
            activeDesc={live.strategy.desc}
            onSelect={onSelect}
          />
          <TickerStrip tickers={live.tickers} />
          <StatsOverview stats={live.stats} />

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              borderBottom: `1px solid ${T.border}`,
              marginBottom: 22,
            }}
          >
            <button onClick={() => setTab("live")} style={tabButtonStyle(tab === "live")}>
              ● Live
            </button>
            <button onClick={() => setTab("hist")} style={tabButtonStyle(tab === "hist")}>
              ◫ Historique
            </button>
          </div>

          {tab === "live" ? (
            <LiveView
              positions={live.positions}
              journal={live.journal}
              jcat={jcat}
              onJcat={setJcat}
            />
          ) : history ? (
            <HistoryView
              history={history}
              period={period}
              bench={bench}
              onPeriod={setPeriod}
              onBench={setBench}
            />
          ) : (
            <Splash inline />
          )}

          {history && (
            <Analysis history={history} capital={live.stats.capital} />
          )}
        </>
      )}
    </div>
  );
}

function Splash({ inline }: { inline?: boolean }) {
  return (
    <div
      style={{
        minHeight: inline ? 200 : "100vh",
        background: T.bg,
        color: T.text3,
        fontFamily: T.sans,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 14,
      }}
    >
      Chargement du tableau de bord…
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      style={{
        background: "rgba(255,93,108,.10)",
        border: `1px solid ${T.loss}`,
        color: T.loss,
        borderRadius: 12,
        padding: "10px 14px",
        marginBottom: 16,
        fontSize: 13,
      }}
    >
      Erreur source de données : {message}
    </div>
  );
}

function DemoBanner() {
  return (
    <div
      style={{
        background: "rgba(240,164,65,.10)",
        border: `1px solid ${T.bench}`,
        color: T.bench,
        borderRadius: 12,
        padding: "10px 14px",
        marginBottom: 16,
        fontSize: 13,
      }}
    >
      Mode démonstration — aucune base <code>bars.db</code> ni clé Alpaca
      détectée. Les données affichées sont fictives.
    </div>
  );
}
