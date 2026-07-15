import { T } from "../theme";
import { priceStr, pct } from "../format";
import { gainLoss } from "../ui";
import type { Ticker } from "../types";

// Live price strip: one cell per instrument, 1px-gap grid on a border.
export function TickerStrip({ tickers }: { tickers: Ticker[] }) {
  if (tickers.length === 0) return null;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))",
        gap: 1,
        background: T.border,
        border: `1px solid ${T.border}`,
        borderRadius: 12,
        overflow: "hidden",
        marginBottom: 20,
      }}
    >
      {tickers.map((t) => (
        <div
          key={t.sym}
          style={{
            background: T.panel,
            padding: "12px 14px",
            display: "flex",
            flexDirection: "column",
            gap: 3,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: t.isCrypto ? T.btc : T.accent,
              }}
            />
            <span style={{ fontWeight: 600, fontSize: 13 }}>{t.sym}</span>
            <span style={{ fontSize: 11, color: T.text3 }}>{t.name}</span>
          </div>
          <div style={{ fontFamily: T.mono, fontSize: 15, fontWeight: 600 }}>
            {priceStr(t.sym, t.price, t.isCrypto)}
          </div>
          <div
            style={{
              fontFamily: T.mono,
              fontSize: 12,
              fontWeight: 600,
              color: gainLoss(t.chgPct),
            }}
          >
            {pct(t.chgPct)}
          </div>
        </div>
      ))}
    </div>
  );
}
