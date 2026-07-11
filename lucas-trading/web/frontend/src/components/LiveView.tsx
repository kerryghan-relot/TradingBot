import { useMemo } from "react";
import { T } from "../theme";
import { priceStr, signed, pct, usd, duration } from "../format";
import {
  Chip,
  Th,
  chipStyle,
  gainLoss,
  hexA,
  segButtonStyle,
  SIGNAL_COLOR,
  STATUS_COLOR,
  useSort,
} from "../ui";
import type { JournalCat, JournalRow, Position } from "../types";

interface PosRow extends Record<string, unknown> {
  sym: string;
  name: string;
  sideLabel: string;
  side: "long" | "short";
  entry: number;
  entryStr: string;
  cur: number;
  curStr: string;
  pnlNum: number;
  pnlStr: string;
  pnlPctStr: string;
  sizeStr: string;
  durMs: number;
  durStr: string;
  isCrypto: boolean;
}

export function LiveView({
  positions,
  journal,
  jcat,
  onJcat,
}: {
  positions: Position[];
  journal: JournalRow[];
  jcat: JournalCat;
  onJcat: (c: JournalCat) => void;
}) {
  const now = Date.now();
  const rows: PosRow[] = useMemo(
    () =>
      positions.map((p) => {
        const pnl =
          p.side === "long"
            ? (p.cur - p.entry) * p.size
            : (p.entry - p.cur) * p.size;
        const pnlPct = p.entry * p.size ? (pnl / (p.entry * p.size)) * 100 : 0;
        const durMs = p.openedMs > 0 ? now - p.openedMs : 0;
        return {
          sym: p.sym,
          name: p.name,
          side: p.side,
          sideLabel: p.side === "long" ? "Long" : "Short",
          entry: p.entry,
          entryStr: priceStr(p.sym, p.entry, p.cat === "Crypto"),
          cur: p.cur,
          curStr: priceStr(p.sym, p.cur, p.cat === "Crypto"),
          pnlNum: pnl,
          pnlStr: signed(pnl),
          pnlPctStr: pct(pnlPct),
          sizeStr: p.sizeStr,
          durMs,
          durStr: durMs > 0 ? duration(durMs) : "—",
          isCrypto: p.cat === "Crypto",
        };
      }),
    [positions, now],
  );

  const openPnl = rows.reduce((s, r) => s + r.pnlNum, 0);
  const exposure = positions.reduce((s, p) => s + p.cur * p.size, 0);
  const pos = useSort<PosRow>(rows);

  const filteredJournal = journal.filter(
    (r) => jcat === "Tous" || r.cat === jcat,
  );
  const jour = useSort<JournalRow & Record<string, unknown>>(
    filteredJournal as (JournalRow & Record<string, unknown>)[],
  );

  return (
    <div>
      {/* Open positions */}
      <div style={panel}>
        <div style={header}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>
            Positions ouvertes{" "}
            <span style={{ color: T.text3, fontWeight: 500 }}>({rows.length})</span>
          </div>
          <div style={{ display: "flex", gap: 20, fontFamily: T.mono, fontSize: 13 }}>
            <div>
              P&amp;L latent :{" "}
              <span style={{ fontWeight: 600, color: gainLoss(openPnl) }}>
                {signed(openPnl)}
              </span>
            </div>
            <div style={{ color: T.text2 }}>
              Exposition :{" "}
              <span style={{ color: T.text, fontWeight: 600 }}>{usd(exposure)}</span>
            </div>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          {rows.length === 0 ? (
            <Empty>Aucune position ouverte.</Empty>
          ) : (
            <table style={{ ...table, minWidth: 760 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                  <Th onClick={() => pos.onSort("sym")} arrow={pos.arrowFor("sym")}>
                    Actif
                  </Th>
                  <Th
                    onClick={() => pos.onSort("sideLabel")}
                    arrow={pos.arrowFor("sideLabel")}
                  >
                    Sens
                  </Th>
                  <Th align="right" onClick={() => pos.onSort("entry")} arrow={pos.arrowFor("entry")}>
                    Entrée
                  </Th>
                  <Th align="right" onClick={() => pos.onSort("cur")} arrow={pos.arrowFor("cur")}>
                    Actuel
                  </Th>
                  <Th align="right" onClick={() => pos.onSort("pnlNum")} arrow={pos.arrowFor("pnlNum")}>
                    P&amp;L latent
                  </Th>
                  <Th align="right">Taille</Th>
                  <Th align="right" onClick={() => pos.onSort("durMs")} arrow={pos.arrowFor("durMs")}>
                    Durée
                  </Th>
                </tr>
              </thead>
              <tbody>
                {pos.sorted.map((r, i) => (
                  <tr key={r.sym + i} style={{ borderBottom: `1px solid ${T.rowSep}` }}>
                    <td style={{ ...td, fontWeight: 600 }}>
                      {r.sym}{" "}
                      <span style={{ fontSize: 11, color: T.text3, fontWeight: 400 }}>
                        {r.name}
                      </span>
                    </td>
                    <td style={td}>
                      <span
                        style={chipStyle(
                          hexA(r.side === "long" ? T.gain : T.loss, 0.12),
                          r.side === "long" ? T.gain : T.loss,
                        )}
                      >
                        {r.sideLabel}
                      </span>
                    </td>
                    <td style={tdNum}>{r.entryStr}</td>
                    <td style={tdNum}>{r.curStr}</td>
                    <td style={tdNum}>
                      <div style={{ color: gainLoss(r.pnlNum), fontWeight: 600 }}>
                        {r.pnlStr}
                      </div>
                      <div style={{ fontSize: 12, color: gainLoss(r.pnlNum) }}>
                        {r.pnlPctStr}
                      </div>
                    </td>
                    <td style={{ ...tdNum, color: T.textBright }}>{r.sizeStr}</td>
                    <td style={{ ...tdNum, color: T.text2 }}>{r.durStr}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Decision journal */}
      <div style={{ ...panel, marginBottom: 8 }}>
        <div style={header}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>
            Journal des décisions du bot
          </div>
          <div style={{ display: "flex", gap: 7 }}>
            {(["Tous", "Action", "Crypto"] as JournalCat[]).map((c) => (
              <button
                key={c}
                onClick={() => onJcat(c)}
                style={segButtonStyle(jcat === c, T.accent, { padding: "6px 13px" })}
              >
                {c === "Action" ? "Actions" : c}
              </button>
            ))}
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          {filteredJournal.length === 0 ? (
            <Empty>Aucune décision enregistrée.</Empty>
          ) : (
            <table style={{ ...table, minWidth: 860 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                  <Th onClick={() => jour.onSort("time")} arrow={jour.arrowFor("time")}>
                    Horodatage
                  </Th>
                  <Th onClick={() => jour.onSort("sym")} arrow={jour.arrowFor("sym")}>
                    Actif
                  </Th>
                  <Th onClick={() => jour.onSort("cat")} arrow={jour.arrowFor("cat")}>
                    Catégorie
                  </Th>
                  <Th onClick={() => jour.onSort("signal")} arrow={jour.arrowFor("signal")}>
                    Signal
                  </Th>
                  <Th>Déclencheur</Th>
                  <Th align="right">Entrée</Th>
                  <Th align="right">Taille</Th>
                  <Th align="center" onClick={() => jour.onSort("status")} arrow={jour.arrowFor("status")}>
                    Statut
                  </Th>
                </tr>
              </thead>
              <tbody>
                {jour.sorted.map((r, i) => (
                  <tr
                    key={r.time + r.sym + i}
                    style={{
                      borderBottom: `1px solid ${T.rowSep}`,
                      borderLeft: `3px solid ${SIGNAL_COLOR[r.signal]}`,
                    }}
                  >
                    <td style={{ ...tdTight, fontFamily: T.mono, color: T.textBright }}>
                      {r.time}
                    </td>
                    <td style={{ ...tdTight, fontWeight: 600 }}>{r.sym}</td>
                    <td style={tdTight}>
                      <Chip bg={T.gridline} fg={r.cat === "Crypto" ? T.btc : T.accent}>
                        {r.cat}
                      </Chip>
                    </td>
                    <td style={tdTight}>
                      <span
                        style={chipStyle(
                          r.signal === "Achat"
                            ? hexA(T.gain, 0.12)
                            : r.signal === "Vente"
                              ? hexA(T.loss, 0.12)
                              : T.gridline,
                          SIGNAL_COLOR[r.signal],
                        )}
                      >
                        {r.signal}
                      </span>
                    </td>
                    <td style={{ ...tdTight, color: T.textBright, fontSize: 13 }}>
                      {r.reason}
                    </td>
                    <td style={{ ...tdTight, textAlign: "right", fontFamily: T.mono }}>
                      {r.entry ? priceStr(r.sym, r.entry, r.cat === "Crypto") : "—"}
                    </td>
                    <td
                      style={{
                        ...tdTight,
                        textAlign: "right",
                        fontFamily: T.mono,
                        color: T.textBright,
                      }}
                    >
                      {r.size}
                    </td>
                    <td style={{ ...tdTight, textAlign: "center" }}>
                      <Chip bg={T.gridline} fg={STATUS_COLOR[r.status]}>
                        {r.status}
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

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: "24px 12px", color: T.text3, fontSize: 13 }}>{children}</div>
  );
}

const panel = {
  background: T.panel,
  border: `1px solid ${T.border}`,
  borderRadius: 14,
  padding: "18px 18px 6px",
  marginBottom: 20,
} as const;

const header = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
  flexWrap: "wrap",
  marginBottom: 14,
} as const;

const table = { width: "100%", borderCollapse: "collapse" } as const;
const td = { padding: 12 } as const;
const tdNum = { padding: 12, textAlign: "right", fontFamily: T.mono } as const;
const tdTight = { padding: "11px 12px" } as const;
