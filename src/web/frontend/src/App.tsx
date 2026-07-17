import { useCallback, useEffect, useRef, useState } from "react";
import { T } from "./theme";
import { tabButtonStyle } from "./ui";
import {
  fetchAgents,
  fetchHistory,
  fetchLive,
  fetchOpportunities,
  fetchStrategies,
  selectStrategy,
} from "./api";
import type {
  AgentsPayload,
  Bench,
  HistoryPayload,
  JournalCat,
  LivePayload,
  OpportunitiesPayload,
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
import { AgentsView } from "./components/AgentsView";
import { HunterView } from "./components/HunterView";

const LIVE_POLL_MS = 2500;
const AGENTS_POLL_MS = 5000;

export function App() {
  const [route, setRoute] = useState<"dashboard" | "hunter" | "config">(
    "dashboard",
  );
  const [strategies, setStrategies] = useState<StrategiesPayload | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [live, setLive] = useState<LivePayload | null>(null);
  const [history, setHistory] = useState<HistoryPayload | null>(null);
  const [agents, setAgents] = useState<AgentsPayload | null>(null);
  const [opps, setOpps] = useState<OpportunitiesPayload | null>(null);

  const [tab, setTab] = useState<"live" | "hist" | "agents">("live");
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

  // Poll the pipeline status only while the Agents tab is on screen: the
  // tab stays selected when the user leaves the dashboard, so the route
  // has to be checked too.
  useEffect(() => {
    if (route !== "dashboard" || tab !== "agents") return;
    let alive = true;
    const tick = () => fetchAgents().then((p) => alive && setAgents(p)).catch(() => {});
    tick();
    const id = setInterval(tick, AGENTS_POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [route, tab]);

  // Load the opportunity scan when the Hunter page opens (the server
  // caches the heavy scan, so re-entering the page is cheap).
  const refreshOpps = useCallback(() => {
    fetchOpportunities().then(setOpps).catch(() => {});
  }, []);
  useEffect(() => {
    if (route === "hunter") refreshOpps();
  }, [route, refreshOpps]);

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
      ) : route === "hunter" ? (
        opps ? (
          <HunterView payload={opps} onRefresh={refreshOpps} />
        ) : (
          <Splash inline />
        )
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
            <button onClick={() => setTab("agents")} style={tabButtonStyle(tab === "agents")}>
              ◇ Agents
            </button>
          </div>

          {tab === "live" ? (
            <LiveView
              positions={live.positions}
              journal={live.journal}
              jcat={jcat}
              onJcat={setJcat}
            />
          ) : tab === "hist" ? (
            history ? (
              <HistoryView
                history={history}
                period={period}
                bench={bench}
                onPeriod={setPeriod}
                onBench={setBench}
              />
            ) : (
              <Splash inline />
            )
          ) : agents ? (
            <AgentsView payload={agents} />
          ) : (
            <Splash inline />
          )}

          {tab !== "agents" && history && (
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
