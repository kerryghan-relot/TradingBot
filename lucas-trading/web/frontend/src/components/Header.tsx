import { T } from "../theme";
import type { BotState } from "../types";

const STATE_COLOR: Record<BotState, string> = {
  active: T.gain,
  paused: T.bench,
  error: T.loss,
};

// Top bar: brand + universe on the left, bot status pill + clock right.
export function Header({
  universeLabel,
  bot,
  clock,
  route,
  onRoute,
}: {
  universeLabel: string;
  bot: { state: BotState; label: string };
  clock: string;
  route: "dashboard" | "config";
  onRoute: (r: "dashboard" | "config") => void;
}) {
  const color = STATE_COLOR[bot.state];
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        flexWrap: "wrap",
        marginBottom: 14,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div
          style={{
            width: 38,
            height: 38,
            borderRadius: 10,
            background: `linear-gradient(135deg,${T.accent},${T.gain})`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 18,
            color: T.bg,
          }}
        >
          ⌁
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: ".01em" }}>
            AlgoDesk
            <span style={{ color: T.accent }}> / </span>
            <span style={{ color: T.text2, fontWeight: 500 }}>Auto-Trader</span>
          </div>
          <div style={{ fontSize: 12, color: T.text2 }}>{universeLabel}</div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <nav style={{ display: "flex", gap: 4 }}>
          {(["dashboard", "config"] as const).map((r) => (
            <button
              key={r}
              onClick={() => onRoute(r)}
              style={{
                padding: "7px 13px",
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                border: `1px solid ${route === r ? T.accent : T.border}`,
                background: route === r ? "rgba(77,141,255,.14)" : "transparent",
                color: route === r ? T.text : T.text2,
              }}
            >
              {r === "dashboard" ? "Tableau de bord" : "Configuration"}
            </button>
          ))}
        </nav>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 9,
            background: T.panel,
            border: `1px solid ${T.border}`,
            borderRadius: 999,
            padding: "7px 14px",
          }}
        >
          <span
            style={{
              width: 9,
              height: 9,
              borderRadius: "50%",
              background: color,
              animation: bot.state === "active" ? "pulse 1.8s infinite" : "none",
            }}
          />
          <span style={{ fontWeight: 600, color, fontSize: 13 }}>{bot.label}</span>
        </div>
        <div style={{ textAlign: "right" }}>
          <div
            style={{
              fontSize: 11,
              color: T.text2,
              textTransform: "uppercase",
              letterSpacing: ".06em",
            }}
          >
            Dernière MàJ
          </div>
          <div style={{ fontFamily: T.mono, fontWeight: 600 }}>{clock}</div>
        </div>
      </div>
    </div>
  );
}
