// Shape of the JSON payloads returned by the Flask API. Kept in sync
// with web/server/{demo,assemble}.py.

export type BotState = "active" | "paused" | "error";
export type Universe = "all" | "crypto" | "action";
export type Period = "day" | "week" | "month" | "all";
export type Bench = "none" | "sp500" | "nasdaq" | "msci";
export type JournalCat = "Tous" | "Action" | "Crypto";

export interface Stats {
  pnlTotal: number;
  pnlTotalPct: number;
  pnlDay: number;
  pnlDayPct: number;
  winRate: number;
  wins: number;
  losses: number;
  trades: number;
  drawdown: number;
  capital: number;
  exposure: number;
  exposurePct: number;
}

export interface Ticker {
  sym: string;
  name: string;
  price: number;
  chgPct: number;
  isCrypto: boolean;
}

export interface Position {
  sym: string;
  name: string;
  cat: "Crypto" | "Action";
  side: "long" | "short";
  entry: number;
  cur: number;
  size: number;
  sizeStr: string;
  openedMs: number;
}

export interface JournalRow {
  time: string;
  sym: string;
  cat: "Crypto" | "Action";
  signal: "Achat" | "Vente" | "Hold";
  reason: string;
  entry: number;
  size: string;
  status: "Ouvert" | "Fermé" | "Annulé";
}

export interface ClosedTrade {
  sym: string;
  cat: "Crypto" | "Action";
  side: "long" | "short";
  entry: number;
  exit: number;
  size: number;
  pnl: number;
}

export interface LivePayload {
  demo: boolean;
  bot: { state: BotState; label: string };
  clock: string;
  universeLabel: string;
  activeStrategy: string;
  strategy: { id: string; label: string; desc: string; universe: Universe };
  stats: Stats;
  tickers: Ticker[];
  positions: Position[];
  journal: JournalRow[];
  error?: string | null;
}

export interface AllocSlice {
  sym: string;
  pct: number;
  value: number;
}

export interface AssetBar {
  sym: string;
  value: number;
}

export interface HistoryPayload {
  demo: boolean;
  capitalInitial: number;
  equity: number[];
  bench: number[] | null;
  benchLabel: string | null;
  closed: ClosedTrade[];
  analysis: {
    winLoss: { wins: number; losses: number };
    alloc: AllocSlice[];
    assetBars: AssetBar[];
  };
}

export interface StrategyMeta {
  id: string;
  label: string;
  description: string;
  universe: Universe;
  config: Record<string, unknown>;
}

export interface StrategiesPayload {
  active: string;
  demo: boolean;
  strategies: StrategyMeta[];
}

export interface ConfigPayload {
  config: Record<string, unknown>;
  allSignals: string[];
  editable: string[];
  demo: boolean;
}
