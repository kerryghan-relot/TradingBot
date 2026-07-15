// Design tokens from the Claude Design handoff (variant 1a). Every
// colour/spacing decision lives here so a future restyle only touches
// this file — matching the handoff's "only tokens change" note.

export const T = {
  // Backgrounds
  bg: "#0a0e17",
  panel: "#111726",
  hover: "#172033",
  gridline: "#1a2233",
  // Borders
  border: "#222c40",
  rowSep: "#171f30",
  // Text
  text: "#e7ecf6",
  text2: "#8792ab",
  text3: "#5a6478",
  textBright: "#b9c2d6",
  // Semantics
  gain: "#2fd07f",
  loss: "#ff5d6c",
  accent: "#4d8dff",
  accentHover: "#7aa9ff",
  bench: "#f0a441",
  // Instruments
  btc: "#f7931a",
  eth: "#8b9dff",
  // Fonts
  sans: "'IBM Plex Sans', system-ui, sans-serif",
  mono: "'IBM Plex Mono', monospace",
} as const;

// Allocation-slice palette (donut), matching the prototype.
export const ALLOC_COLORS: Record<string, string> = {
  BTC: "#f7931a",
  ETH: "#8b9dff",
  NVDA: "#3fb950",
  AAPL: "#4d8dff",
  MSFT: "#38bdf8",
  TSLA: "#e06a8b",
  AMZN: "#f0a441",
  GOOGL: "#c084fc",
  META: "#22d3ee",
  AMD: "#f43f5e",
  Liquidités: "#4a5570",
};

// Deterministic fallback colour for symbols outside the fixed palette.
const FALLBACK = ["#3fb950", "#38bdf8", "#e06a8b", "#f0a441", "#c084fc", "#22d3ee"];

export function allocColor(sym: string, index: number): string {
  return ALLOC_COLORS[sym] ?? FALLBACK[index % FALLBACK.length];
}
