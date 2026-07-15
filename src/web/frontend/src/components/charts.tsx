import { T, allocColor } from "../theme";
import { usd, signed } from "../format";
import { gainLoss } from "../ui";
import type { AllocSlice, AssetBar } from "../types";

const W = 1000;
const H = 280;
const PAD = 14;

function pathFor(series: number[], mn: number, rng: number): string {
  const xs = (i: number) => (series.length > 1 ? (i / (series.length - 1)) * W : 0);
  const ys = (v: number) => PAD + (1 - (v - mn) / rng) * (H - 2 * PAD);
  return series
    .map((v, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)} ${ys(v).toFixed(1)}`)
    .join(" ");
}

// Equity area/line chart with optional benchmark overlay and a dashed
// initial-capital reference line — the SVG maths from the prototype.
export function EquityChart({
  equity,
  bench,
  benchLabel,
  capitalInitial,
}: {
  equity: number[];
  bench: number[] | null;
  benchLabel: string | null;
  capitalInitial: number;
}) {
  if (equity.length === 0) return null;
  const all = bench ? equity.concat(bench) : equity;
  const mn = Math.min(...all);
  const mx = Math.max(...all);
  const rng = mx - mn || 1;
  const ys = (v: number) => PAD + (1 - (v - mn) / rng) * (H - 2 * PAD);

  const eqLine = pathFor(equity, mn, rng);
  const benchLine = bench ? pathFor(bench, mn, rng) : "";
  const first = equity[0];
  const last = equity[equity.length - 1];
  const delta = last - first;
  const deltaPct = first ? (delta / first) * 100 : 0;
  const refY =
    capitalInitial >= mn && capitalInitial <= mx ? ys(capitalInitial) : -20;

  const benchDeltaPct =
    bench && bench.length ? ((bench[bench.length - 1] - bench[0]) / bench[0]) * 100 : 0;
  const outperf = deltaPct - benchDeltaPct;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
        <span style={{ fontFamily: T.mono, fontSize: 26, fontWeight: 600 }}>
          {usd(last)}
        </span>
        <span
          style={{ fontFamily: T.mono, fontSize: 14, fontWeight: 600, color: gainLoss(delta) }}
        >
          {signed(delta)} ({fmtPct(deltaPct)})
        </span>
      </div>
      <div style={{ position: "relative" }}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          style={{ width: "100%", height: 280, display: "block", overflow: "hidden" }}
        >
          {[70, 140, 210].map((y) => (
            <line key={y} x1={0} y1={y} x2={W} y2={y} stroke={T.gridline} strokeWidth={1} />
          ))}
          <line
            x1={0}
            y1={refY}
            x2={W}
            y2={refY}
            stroke={T.text3}
            strokeWidth={1}
            strokeDasharray="6 6"
            vectorEffect="non-scaling-stroke"
          />
          {benchLine && (
            <path
              d={benchLine}
              fill="none"
              stroke={T.bench}
              strokeWidth={1.5}
              strokeDasharray="5 5"
              vectorEffect="non-scaling-stroke"
            />
          )}
          <path
            d={eqLine}
            fill="none"
            stroke={T.gain}
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        <div style={{ position: "absolute", top: 0, left: 0, fontFamily: T.mono, fontSize: 11, color: T.text3 }}>
          {usd(mx)}
        </div>
        <div style={{ position: "absolute", bottom: 0, left: 0, fontFamily: T.mono, fontSize: 11, color: T.text3 }}>
          {usd(mn)}
        </div>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 18,
          marginTop: 12,
          fontSize: 12,
          color: T.text2,
          flexWrap: "wrap",
        }}
      >
        <Legend color={T.gain}>
          Stratégie{" "}
          <span style={{ fontFamily: T.mono, color: T.gain, fontWeight: 600 }}>
            {fmtPct(deltaPct)}
          </span>
        </Legend>
        {bench && (
          <Legend color={T.bench} dashed>
            {benchLabel}{" "}
            <span style={{ fontFamily: T.mono, color: T.bench, fontWeight: 600 }}>
              {fmtPct(benchDeltaPct)}
            </span>
          </Legend>
        )}
        {bench && (
          <div>
            Sur/sous-perf. :{" "}
            <span style={{ fontFamily: T.mono, fontWeight: 600, color: gainLoss(outperf) }}>
              {fmtPct(outperf)} pts
            </span>
          </div>
        )}
        <Legend color={T.text3} thin dashed>
          Capital initial · {usd(capitalInitial)}
        </Legend>
      </div>
    </div>
  );
}

function Legend({
  color,
  dashed,
  thin,
  children,
}: {
  color: string;
  dashed?: boolean;
  thin?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
      <span
        style={{
          display: "inline-block",
          width: 16,
          height: 0,
          borderTop: `${thin ? 1 : 2}px ${dashed ? "dashed" : "solid"} ${color}`,
        }}
      />
      {children}
    </div>
  );
}

function fmtPct(n: number): string {
  return (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(1) + "%";
}

// ── Win/Loss donut ────────────────────────────────────────────────────
const R = 70;
const C = 2 * Math.PI * R;

export function WinLossDonut({ wins, losses }: { wins: number; losses: number }) {
  const total = wins + losses;
  const wr = total ? wins / total : 0;
  const gLen = C * wr;
  const rLen = C * (1 - wr);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
      <svg viewBox="0 0 200 200" style={{ width: 150, height: 150, flexShrink: 0 }}>
        <circle cx={100} cy={100} r={R} fill="none" stroke={T.gridline} strokeWidth={26} />
        <circle
          cx={100}
          cy={100}
          r={R}
          fill="none"
          stroke={T.gain}
          strokeWidth={26}
          strokeDasharray={`${gLen.toFixed(1)} ${(C - gLen).toFixed(1)}`}
          strokeDashoffset={0}
          transform="rotate(-90 100 100)"
        />
        <circle
          cx={100}
          cy={100}
          r={R}
          fill="none"
          stroke={T.loss}
          strokeWidth={26}
          strokeDasharray={`${rLen.toFixed(1)} ${(C - rLen).toFixed(1)}`}
          strokeDashoffset={-gLen.toFixed(1)}
          transform="rotate(-90 100 100)"
        />
        <text x={100} y={96} textAnchor="middle" fill={T.text} fontSize={30} fontWeight={700} fontFamily="IBM Plex Mono">
          {(wr * 100).toFixed(1)}%
        </text>
        <text x={100} y={118} textAnchor="middle" fill={T.text2} fontSize={12} fontFamily="IBM Plex Sans">
          win rate
        </text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, fontSize: 13 }}>
        <LegendDot color={T.gain} label="Gains" value={wins} />
        <LegendDot color={T.loss} label="Pertes" value={losses} />
        <LegendDot color={T.gridline} label="Total" value={total} />
      </div>
    </div>
  );
}

function LegendDot({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ width: 10, height: 10, borderRadius: 3, background: color }} />
      {label}{" "}
      <span style={{ color: T.text2, fontFamily: T.mono }}>{value}</span>
    </div>
  );
}

// ── Portfolio allocation donut ────────────────────────────────────────
export function AllocDonut({ alloc, total }: { alloc: AllocSlice[]; total: number }) {
  let offset = 0;
  const segs = alloc.map((a, i) => {
    const len = C * (a.pct / 100);
    const seg = {
      ...a,
      color: allocColor(a.sym, i),
      dash: `${len.toFixed(2)} ${(C - len).toFixed(2)}`,
      off: (-offset).toFixed(2),
    };
    offset += len;
    return seg;
  });
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "center", marginBottom: 18 }}>
        <svg viewBox="0 0 200 200" style={{ width: 150, height: 150 }}>
          <circle cx={100} cy={100} r={R} fill="none" stroke={T.gridline} strokeWidth={26} />
          {segs.map((s) => (
            <circle
              key={s.sym}
              cx={100}
              cy={100}
              r={R}
              fill="none"
              stroke={s.color}
              strokeWidth={26}
              strokeDasharray={s.dash}
              strokeDashoffset={s.off}
              transform="rotate(-90 100 100)"
            />
          ))}
          <text x={100} y={96} textAnchor="middle" fill={T.text} fontSize={15} fontWeight={700} fontFamily="IBM Plex Mono">
            {usd(total)}
          </text>
          <text x={100} y={116} textAnchor="middle" fill={T.text2} fontSize={11} fontFamily="IBM Plex Sans">
            portefeuille
          </text>
        </svg>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 18px", fontSize: 13 }}>
        {segs.map((s) => (
          <div key={s.sym} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color, flexShrink: 0 }} />
            <span style={{ fontWeight: 500 }}>{s.sym}</span>
            <span style={{ marginLeft: "auto", fontFamily: T.mono, fontWeight: 600 }}>
              {s.pct.toFixed(1)}%
            </span>
            <span style={{ fontFamily: T.mono, color: T.text3, width: 64, textAlign: "right" }}>
              {usd(s.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Per-asset performance bars ────────────────────────────────────────
export function AssetBars({ bars }: { bars: AssetBar[] }) {
  const maxV = Math.max(...bars.map((b) => Math.abs(b.value)), 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {bars.map((b) => (
        <div key={b.sym} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 44, fontWeight: 600, fontSize: 13 }}>{b.sym}</div>
          <div style={{ flex: 1, height: 14, background: T.gridline, borderRadius: 4, overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${(Math.abs(b.value) / maxV) * 100}%`,
                background: gainLoss(b.value),
                borderRadius: 4,
              }}
            />
          </div>
          <div
            style={{
              width: 78,
              textAlign: "right",
              fontFamily: T.mono,
              fontSize: 13,
              color: gainLoss(b.value),
            }}
          >
            {signed(b.value)}
          </div>
        </div>
      ))}
    </div>
  );
}
