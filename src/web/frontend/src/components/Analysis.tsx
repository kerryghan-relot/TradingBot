import { T } from "../theme";
import { Card, SectionLabel } from "../ui";
import { AllocDonut, AssetBars, WinLossDonut } from "./charts";
import type { HistoryPayload } from "../types";

// The three-up analysis row: win/loss donut, allocation donut, and
// per-asset performance bars. Shown under both tabs, like the mock.
export function Analysis({
  history,
  capital,
}: {
  history: HistoryPayload;
  capital: number;
}) {
  const { winLoss, alloc, assetBars } = history.analysis;
  return (
    <div>
      <SectionLabel>Répartition &amp; analyse</SectionLabel>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))",
          gap: 16,
        }}
      >
        <Card>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>Gains vs Pertes</div>
          <WinLossDonut wins={winLoss.wins} losses={winLoss.losses} />
        </Card>

        <Card>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>
            Répartition du portefeuille
          </div>
          {alloc.length ? (
            <AllocDonut alloc={alloc} total={capital} />
          ) : (
            <Empty>Aucune position à répartir.</Empty>
          )}
        </Card>

        <Card>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>
            Performance par actif
          </div>
          {assetBars.length ? (
            <AssetBars bars={assetBars} />
          ) : (
            <Empty>Pas encore de trades clôturés.</Empty>
          )}
        </Card>
      </div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div style={{ color: T.text3, fontSize: 13, padding: "8px 0" }}>{children}</div>;
}
