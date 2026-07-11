import { useMemo } from "react";
import { T } from "../theme";
import { priceStr, signed, pct } from "../format";
import {
  Chip,
  Th,
  chipStyle,
  gainLoss,
  hexA,
  segButtonStyle,
  useSort,
} from "../ui";
import { EquityChart } from "./charts";
import type { Bench, ClosedTrade, HistoryPayload, Period } from "../types";

const PERIODS: { key: Period; label: string }[] = [
  { key: "day", label: "Jour" },
  { key: "week", label: "Semaine" },
  { key: "month", label: "Mois" },
  { key: "all", label: "Tout" },
];
const BENCHES: { key: Bench; label: string }[] = [
  { key: "none", label: "Aucun" },
  { key: "sp500", label: "S&P 500" },
  { key: "nasdaq", label: "Nasdaq" },
  { key: "msci", label: "MSCI World" },
];

interface ClosedRow extends Record<string, unknown> {
  sym: string;
  cat: string;
  sideLabel: string;
  side: "long" | "short";
  entry: number;
  entryStr: string;
  exit: number;
  exitStr: string;
  pnlNum: number;
  pnlStr: string;
  pnlPctStr: string;
  result: string;
  isCrypto: boolean;
}

export function HistoryView({
  history,
  period,
  bench,
  onPeriod,
  onBench,
}: {
  history: HistoryPayload;
  period: Period;
  bench: Bench;
  onPeriod: (p: Period) => void;
  onBench: (b: Bench) => void;
}) {
  const rows: ClosedRow[] = useMemo(
    () =>
      history.closed.map((t: ClosedTrade) => {
        const pnlPct = t.entry * t.size ? (t.pnl / (t.entry * t.size)) * 100 : 0;
        return {
          sym: t.sym,
          cat: t.cat,
          side: t.side,
          sideLabel: t.side === "long" ? "Long" : "Short",
          entry: t.entry,
          entryStr: priceStr(t.sym, t.entry, t.cat === "Crypto"),
          exit: t.exit,
          exitStr: priceStr(t.sym, t.exit, t.cat === "Crypto"),
          pnlNum: t.pnl,
          pnlStr: signed(t.pnl),
          pnlPctStr: pct(pnlPct),
          result: t.pnl >= 0 ? "Gain" : "Perte",
          isCrypto: t.cat === "Crypto",
        };
      }),
    [history.closed],
  );
  const cl = useSort<ClosedRow>(rows);

  return (
    <div>
      {/* Equity curve */}
      <div style={{ ...panel, padding: 18 }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
            marginBottom: 16,
          }}
        >
          <div style={{ fontSize: 15, fontWeight: 600 }}>Courbe de performance</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9, alignItems: "flex-end" }}>
            <div style={{ display: "flex", gap: 7 }}>
              {PERIODS.map((p) => (
                <button key={p.key} onClick={() => onPeriod(p.key)} style={segButtonStyle(period === p.key)}>
                  {p.label}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 7, alignItems: "center" }}>
              <span
                style={{
                  fontSize: 11,
                  color: T.text3,
                  textTransform: "uppercase",
                  letterSpacing: ".06em",
                  marginRight: 2,
                }}
              >
                Comparer
              </span>
              {BENCHES.map((b) => (
                <button
                  key={b.key}
                  onClick={() => onBench(b.key)}
                  style={segButtonStyle(bench === b.key, T.bench, {
                    padding: "6px 11px",
                    fontSize: 12,
                  })}
                >
                  {b.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        <EquityChart
          equity={history.equity}
          bench={history.bench}
          benchLabel={history.benchLabel}
          capitalInitial={history.capitalInitial}
        />
        {history.bench === null && bench !== "none" && (
          <div style={{ marginTop: 8, fontSize: 12, color: T.text3 }}>
            Comparaison d'indice indisponible en mode réel (aucune source de
            données de marché connectée).
          </div>
        )}
      </div>

      {/* Closed trades */}
      <div style={panel}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 14 }}>
          Trades fermés <span style={{ color: T.text3, fontWeight: 500 }}>({rows.length})</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          {rows.length === 0 ? (
            <div style={{ padding: "24px 12px", color: T.text3, fontSize: 13 }}>
              Aucun trade fermé pour l'instant.
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 800 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                  <Th onClick={() => cl.onSort("sym")} arrow={cl.arrowFor("sym")}>Actif</Th>
                  <Th>Sens</Th>
                  <Th align="right" onClick={() => cl.onSort("entry")} arrow={cl.arrowFor("entry")}>Entrée</Th>
                  <Th align="right" onClick={() => cl.onSort("exit")} arrow={cl.arrowFor("exit")}>Sortie</Th>
                  <Th align="right" onClick={() => cl.onSort("pnlNum")} arrow={cl.arrowFor("pnlNum")}>P&amp;L</Th>
                  <Th align="center" onClick={() => cl.onSort("result")} arrow={cl.arrowFor("result")}>Résultat</Th>
                </tr>
              </thead>
              <tbody>
                {cl.sorted.map((r, i) => (
                  <tr key={r.sym + i} style={{ borderBottom: `1px solid ${T.rowSep}` }}>
                    <td style={{ padding: 12, fontWeight: 600 }}>
                      {r.sym}{" "}
                      <span style={{ fontSize: 11, color: T.text3, fontWeight: 400 }}>{r.cat}</span>
                    </td>
                    <td style={{ padding: 12 }}>
                      <span
                        style={chipStyle(
                          hexA(r.side === "long" ? T.gain : T.loss, 0.12),
                          r.side === "long" ? T.gain : T.loss,
                        )}
                      >
                        {r.sideLabel}
                      </span>
                    </td>
                    <td style={num}>{r.entryStr}</td>
                    <td style={num}>{r.exitStr}</td>
                    <td style={num}>
                      <div style={{ color: gainLoss(r.pnlNum), fontWeight: 600 }}>{r.pnlStr}</div>
                      <div style={{ fontSize: 12, color: gainLoss(r.pnlNum) }}>{r.pnlPctStr}</div>
                    </td>
                    <td style={{ padding: 12, textAlign: "center" }}>
                      <Chip bg={hexA(gainLoss(r.pnlNum), 0.12)} fg={gainLoss(r.pnlNum)}>
                        {r.result}
                      </Chip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

const panel = {
  background: T.panel,
  border: `1px solid ${T.border}`,
  borderRadius: 14,
  padding: "18px 18px 6px",
  marginBottom: 20,
} as const;

const num = { padding: 12, textAlign: "right", fontFamily: T.mono } as const;
