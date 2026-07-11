import { T } from "../theme";
import { stratButtonStyle } from "../ui";
import type { StrategyMeta } from "../types";

// Active-strategy banner + switch buttons. Selecting one activates it
// (writes config.json in real mode; swaps the demo dataset otherwise).
export function StrategySwitcher({
  strategies,
  active,
  activeLabel,
  activeDesc,
  onSelect,
}: {
  strategies: StrategyMeta[];
  active: string;
  activeLabel: string;
  activeDesc: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 14,
        padding: "14px 16px",
        marginBottom: 20,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div>
        <div
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: ".08em",
            color: T.text2,
            marginBottom: 3,
          }}
        >
          Stratégie active
        </div>
        <div style={{ fontSize: 17, fontWeight: 700 }}>{activeLabel}</div>
        <div style={{ fontSize: 12, color: T.text2, marginTop: 2 }}>{activeDesc}</div>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {strategies.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            style={stratButtonStyle(s.id === active)}
            title={s.description}
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
