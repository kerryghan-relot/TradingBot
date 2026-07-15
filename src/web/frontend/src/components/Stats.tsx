import { CSSProperties } from "react";
import { T } from "../theme";
import { signed, pct, usd } from "../format";
import { SectionLabel, arrow, gainLoss } from "../ui";
import type { Stats } from "../types";

interface Card {
  label: string;
  value: string;
  valColor: string;
  arrow: string;
  delta: string;
  deltaColor: string;
  sub: string;
}

// Seven overview cards derived from the live stats payload.
export function StatsOverview({ stats }: { stats: Stats }) {
  const cards: Card[] = [
    {
      label: "P&L total",
      value: signed(stats.pnlTotal),
      valColor: gainLoss(stats.pnlTotal),
      arrow: arrow(stats.pnlTotal),
      delta: pct(stats.pnlTotalPct),
      deltaColor: gainLoss(stats.pnlTotal),
      sub: "depuis le début",
    },
    {
      label: "P&L du jour",
      value: signed(stats.pnlDay),
      valColor: gainLoss(stats.pnlDay),
      arrow: arrow(stats.pnlDay),
      delta: pct(stats.pnlDayPct),
      deltaColor: gainLoss(stats.pnlDay),
      sub: "aujourd'hui",
    },
    {
      label: "Taux de réussite",
      value: stats.winRate.toFixed(1) + "%",
      valColor: T.text,
      arrow: "▲",
      delta: stats.wins + " G",
      deltaColor: T.gain,
      sub: stats.losses + " pertes",
    },
    {
      label: "Trades",
      value: String(stats.trades),
      valColor: T.text,
      arrow: "",
      delta: "",
      deltaColor: T.text2,
      sub: "clôturés",
    },
    {
      label: "Drawdown max",
      value: stats.drawdown.toFixed(1) + "%",
      valColor: T.loss,
      arrow: "▼",
      delta: "seuil −15%",
      deltaColor: T.text2,
      sub: "",
    },
    {
      label: "Capital actuel",
      value: usd(stats.capital),
      valColor: T.text,
      arrow: arrow(stats.pnlDay),
      delta: signed(stats.pnlDay),
      deltaColor: gainLoss(stats.pnlDay),
      sub: "init. $100k",
    },
    {
      label: "Exposition",
      value: usd(stats.exposure),
      valColor: T.text,
      arrow: "",
      delta: stats.exposurePct.toFixed(0) + "%",
      deltaColor: T.text2,
      sub: "du capital",
    },
  ];

  return (
    <>
      <SectionLabel>Vue d'ensemble</SectionLabel>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit,minmax(168px,1fr))",
          gap: 12,
          marginBottom: 24,
        }}
      >
        {cards.map((c) => (
          <div key={c.label} style={cardStyle}>
            <div style={{ fontSize: 12, color: T.text2, letterSpacing: ".02em" }}>
              {c.label}
            </div>
            <div
              style={{
                fontFamily: T.mono,
                fontSize: 23,
                fontWeight: 600,
                letterSpacing: "-.01em",
                color: c.valColor,
              }}
            >
              {c.value}
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                fontSize: 12,
                fontFamily: T.mono,
              }}
            >
              <span style={{ color: c.deltaColor, fontWeight: 600 }}>
                {c.arrow} {c.delta}
              </span>
              <span style={{ color: T.text3 }}>{c.sub}</span>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

const cardStyle: CSSProperties = {
  background: T.panel,
  border: `1px solid ${T.border}`,
  borderRadius: 12,
  padding: "15px 16px",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};
