import { useMemo, useState } from "react";
import { T } from "../theme";
import { usd, pct } from "../format";
import { chipStyle, gainLoss, hexA } from "../ui";
import type {
  OpportunitiesPayload,
  Opportunity,
  OppSource,
} from "../types";

const SOURCE_META: Record<OppSource, { label: string; color: string }> = {
  mover: { label: "Top hausse", color: T.gain },
  active: { label: "Très actif", color: T.accent },
  watchlist: { label: "Watchlist", color: T.bench },
};

const VOL_PRESETS: { label: string; value: number }[] = [
  { label: "≥ 1 M$", value: 1_000_000 },
  { label: "≥ 5 M$", value: 5_000_000 },
  { label: "≥ 20 M$", value: 20_000_000 },
  { label: "Tous", value: 0 },
];

// Ranking blend: the appetite slider decides how much the risk score
// counts *for* a candidate. At 1 the top-right (risky + promising) wins;
// at 0 risk is penalised (safer momentum surfaces). Reward and risk are
// always shown separately so the trade-off stays explicit.
function composite(o: Opportunity, appetite: number): number {
  return o.reward + (appetite - 0.5) * 0.8 * o.risk;
}

function compactUsd(n: number): string {
  if (n >= 1e9) return "$" + (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return "$" + (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return "$" + (n / 1e3).toFixed(0) + "K";
  return "$" + n.toFixed(0);
}

export function HunterView({
  payload,
  onRefresh,
}: {
  payload: OpportunitiesPayload;
  onRefresh: () => void;
}) {
  const [appetite, setAppetite] = useState(0.65);
  const [minPrice, setMinPrice] = useState(payload.guardrails.minPrice);
  const [minVol, setMinVol] = useState(payload.guardrails.minDollarVol);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string | null>(null);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return payload.items
      .filter(
        (o) =>
          o.price >= minPrice &&
          o.factors.dollarVol >= minVol &&
          (!needle ||
            o.sym.toLowerCase().includes(needle) ||
            o.name.toLowerCase().includes(needle)),
      )
      .map((o) => ({ o, score: composite(o, appetite) }))
      .sort((a, b) => b.score - a.score);
  }, [payload.items, appetite, minPrice, minVol, q]);

  const selected = rows.find((r) => r.o.sym === sel)?.o ?? null;
  const genTime = payload.generatedAt
    ? new Date(payload.generatedAt).toLocaleTimeString("fr-FR", {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

  return (
    <div>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
          marginBottom: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>
            Chasseur d'opportunités
          </div>
          <div style={{ fontSize: 12.5, color: T.text2, marginTop: 3, maxWidth: 620 }}>
            Titres US risqués mais à fort potentiel, notés sur deux axes
            indépendants : potentiel de hausse et risque. Outil de recherche —
            pas un conseil d'investissement, à backtester avant tout trade.
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {payload.demo && (
            <span style={chipStyle(hexA(T.bench, 0.16), T.bench)}>Démo</span>
          )}
          <span style={{ fontSize: 12, color: T.text3, fontFamily: T.mono }}>
            {rows.length} titres · {genTime}
          </span>
          <button
            onClick={onRefresh}
            style={{
              background: T.panel,
              border: `1px solid ${T.border}`,
              color: T.text2,
              borderRadius: 8,
              padding: "7px 12px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            ↻ Rafraîchir
          </button>
        </div>
      </div>

      {/* Controls */}
      <div
        style={{
          background: T.panel,
          border: `1px solid ${T.border}`,
          borderRadius: 14,
          padding: "14px 18px",
          marginBottom: 16,
          display: "flex",
          gap: 26,
          flexWrap: "wrap",
          alignItems: "flex-end",
        }}
      >
        <div style={{ flex: "1 1 280px", minWidth: 240 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 11,
              textTransform: "uppercase",
              letterSpacing: ".06em",
              color: T.text2,
              marginBottom: 6,
            }}
          >
            <span>Appétit au risque</span>
            <span style={{ color: T.text, fontWeight: 600 }}>
              {appetite < 0.4
                ? "Prudent"
                : appetite > 0.6
                  ? "Agressif"
                  : "Équilibré"}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={appetite * 100}
            onChange={(e) => setAppetite(Number(e.target.value) / 100)}
            style={{ width: "100%", accentColor: T.accent }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 11,
              color: T.text3,
              marginTop: 2,
            }}
          >
            <span>Sûr &amp; prometteur</span>
            <span>Risqué &amp; prometteur</span>
          </div>
        </div>

        <Field label="Prix min">
          <input
            type="number"
            min={0}
            step={1}
            value={minPrice}
            onChange={(e) => setMinPrice(Number(e.target.value) || 0)}
            style={inputStyle}
          />
        </Field>

        <Field label="Liquidité min">
          <select
            value={minVol}
            onChange={(e) => setMinVol(Number(e.target.value))}
            style={inputStyle}
          >
            {VOL_PRESETS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Recherche">
          <input
            type="text"
            placeholder="ticker / nom"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ ...inputStyle, width: 150 }}
          />
        </Field>
      </div>

      {/* Scatter */}
      <div
        style={{
          background: "#0d1220",
          border: `1px solid ${T.border}`,
          borderRadius: 14,
          padding: 18,
          marginBottom: 16,
        }}
      >
        <Scatter rows={rows.map((r) => r.o)} sel={sel} onSel={setSel} />
      </div>

      {selected && <DetailCard o={selected} onClose={() => setSel(null)} />}

      {/* Table */}
      <div
        style={{
          background: T.panel,
          border: `1px solid ${T.border}`,
          borderRadius: 14,
          padding: 18,
        }}
      >
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              minWidth: 820,
              fontSize: 13,
            }}
          >
            <thead>
              <tr style={{ borderBottom: `1px solid ${T.border}`, color: T.text2 }}>
                <Th w={34}>#</Th>
                <Th>Titre</Th>
                <Th align="right">Prix</Th>
                <Th w={150}>Potentiel</Th>
                <Th w={150}>Risque</Th>
                <Th>Pourquoi</Th>
                <Th align="right" w={90}>
                  20 j
                </Th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ o }, i) => {
                const isSel = o.sym === sel;
                const sm = SOURCE_META[o.source];
                return (
                  <tr
                    key={o.sym}
                    onClick={() => setSel(isSel ? null : o.sym)}
                    style={{
                      borderBottom: `1px solid ${T.rowSep}`,
                      cursor: "pointer",
                      background: isSel ? hexA(T.accent, 0.08) : "transparent",
                    }}
                  >
                    <td style={{ padding: "10px 8px", color: T.text3, fontFamily: T.mono }}>
                      {i + 1}
                    </td>
                    <td style={{ padding: "10px 8px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontWeight: 700 }}>{o.sym}</span>
                        <span
                          style={{
                            ...chipStyle(hexA(sm.color, 0.14), sm.color),
                            fontSize: 10,
                            padding: "1px 7px",
                          }}
                        >
                          {sm.label}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: T.text3 }}>{o.name}</div>
                    </td>
                    <td style={{ padding: "10px 8px", textAlign: "right", fontFamily: T.mono }}>
                      <div>{usd(o.price, 2)}</div>
                      <div style={{ fontSize: 11.5, color: gainLoss(o.dayChangePct) }}>
                        {pct(o.dayChangePct)}
                      </div>
                    </td>
                    <td style={{ padding: "10px 8px" }}>
                      <ScoreBar value={o.reward} color={T.gain} />
                    </td>
                    <td style={{ padding: "10px 8px" }}>
                      <ScoreBar value={o.risk} color={T.loss} />
                    </td>
                    <td style={{ padding: "10px 8px" }}>
                      <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                        {o.why.slice(0, 3).map((w, k) => (
                          <span
                            key={k}
                            style={{
                              ...chipStyle(hexA(T.text2, 0.12), T.text2),
                              fontSize: 10.5,
                              padding: "1px 7px",
                            }}
                          >
                            {w}
                          </span>
                        ))}
                        {o.why.length === 0 && (
                          <span style={{ color: T.text3, fontSize: 11 }}>—</span>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: "10px 8px", textAlign: "right" }}>
                      <Spark data={o.spark} up={o.spark[o.spark.length - 1] >= o.spark[0]} />
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ padding: "24px 8px", color: T.text3 }}>
                    Aucun titre ne passe les filtres actuels.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Scatter: risk (x) vs reward (y) ───────────────────────────────────

const SW = 1000;
const SH = 440;
const SP = 46;

function Scatter({
  rows,
  sel,
  onSel,
}: {
  rows: Opportunity[];
  sel: string | null;
  onSel: (s: string) => void;
}) {
  const px = (risk: number) => SP + (risk / 100) * (SW - 2 * SP);
  const py = (reward: number) => SP + (1 - reward / 100) * (SH - 2 * SP);
  const midX = px(50);
  const midY = py(50);

  const dotColor = (o: Opportunity) =>
    o.reward >= 66 ? T.gain : o.reward >= 40 ? T.accent : T.text3;

  return (
    <svg viewBox={`0 0 ${SW} ${SH}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {/* sweet-spot quadrant (high reward + high risk) */}
      <rect
        x={midX}
        y={SP}
        width={SW - SP - midX}
        height={midY - SP}
        fill={hexA(T.gain, 0.06)}
      />
      <text x={SW - SP - 6} y={SP + 18} textAnchor="end" fill={hexA(T.gain, 0.7)} fontSize={12}>
        Risqué &amp; prometteur
      </text>

      {/* axes / quadrant guides */}
      <line x1={SP} y1={midY} x2={SW - SP} y2={midY} stroke={T.gridline} strokeWidth={1} strokeDasharray="4 5" />
      <line x1={midX} y1={SP} x2={midX} y2={SH - SP} stroke={T.gridline} strokeWidth={1} strokeDasharray="4 5" />
      <line x1={SP} y1={SP} x2={SP} y2={SH - SP} stroke={T.border} strokeWidth={1} />
      <line x1={SP} y1={SH - SP} x2={SW - SP} y2={SH - SP} stroke={T.border} strokeWidth={1} />

      <text x={SW / 2} y={SH - 10} textAnchor="middle" fill={T.text3} fontSize={12}>
        Risque →
      </text>
      <text
        x={16}
        y={SH / 2}
        textAnchor="middle"
        fill={T.text3}
        fontSize={12}
        transform={`rotate(-90 16 ${SH / 2})`}
      >
        Potentiel ↑
      </text>

      {rows.map((o) => {
        const isSel = o.sym === sel;
        const cx = px(o.risk);
        const cy = py(o.reward);
        return (
          <g key={o.sym} onClick={() => onSel(o.sym)} style={{ cursor: "pointer" }}>
            <circle
              cx={cx}
              cy={cy}
              r={isSel ? 9 : 6}
              fill={dotColor(o)}
              fillOpacity={isSel ? 1 : 0.82}
              stroke={isSel ? T.text : "#0d1220"}
              strokeWidth={isSel ? 2 : 1}
            >
              <title>{`${o.sym} — potentiel ${o.reward}, risque ${o.risk}`}</title>
            </circle>
            {isSel && (
              <text x={cx} y={cy - 13} textAnchor="middle" fill={T.text} fontSize={12} fontWeight={700}>
                {o.sym}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── Detail card for the selected candidate ────────────────────────────

function DetailCard({ o, onClose }: { o: Opportunity; onClose: () => void }) {
  const f = o.factors;
  const facts: { label: string; value: string }[] = [
    { label: "Momentum 20j", value: pct(f.momentum) },
    { label: "Surge volume", value: "×" + f.volSurge.toFixed(1) },
    { label: "Vs plus-haut 60j", value: pct(f.breakout) },
    { label: "Volatilité (ATR)", value: f.atrPct.toFixed(1) + "%" },
    { label: "Gap du jour", value: pct(f.gapPct) },
    { label: "Volume $/j", value: compactUsd(f.dollarVol) },
    { label: "News 48h", value: String(f.news) },
  ];
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderLeft: `3px solid ${T.accent}`,
        borderRadius: 14,
        padding: "16px 18px",
        marginBottom: 16,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>
            {o.sym} <span style={{ color: T.text2, fontWeight: 500, fontSize: 13 }}>{o.name}</span>
          </div>
          <div style={{ fontSize: 13, fontFamily: T.mono, marginTop: 2 }}>
            {usd(o.price, 2)}{" "}
            <span style={{ color: gainLoss(o.dayChangePct) }}>{pct(o.dayChangePct)}</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <ScorePill label="Potentiel" value={o.reward} color={T.gain} />
          <ScorePill label="Risque" value={o.risk} color={T.loss} />
          <button
            onClick={onClose}
            style={{
              background: "#1a2233",
              border: `1px solid ${T.border}`,
              color: T.text2,
              width: 28,
              height: 28,
              borderRadius: 8,
              cursor: "pointer",
            }}
          >
            ✕
          </button>
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: 12,
          marginTop: 14,
        }}
      >
        {facts.map((ft) => (
          <div key={ft.label}>
            <div style={{ fontSize: 11, color: T.text3 }}>{ft.label}</div>
            <div style={{ fontSize: 14, fontFamily: T.mono, marginTop: 2 }}>{ft.value}</div>
          </div>
        ))}
      </div>
      {o.why.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 14 }}>
          {o.why.map((w, k) => (
            <span key={k} style={chipStyle(hexA(T.accent, 0.12), T.accent)}>
              {w}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Small pieces ──────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: ".06em",
          color: T.text2,
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: "#0d1220",
  border: `1px solid ${T.border}`,
  color: T.text,
  borderRadius: 8,
  padding: "7px 10px",
  fontSize: 13,
  width: 96,
  fontFamily: "inherit",
};

function ScoreBar({ value, color }: { value: number; color: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          flex: 1,
          height: 6,
          background: T.gridline,
          borderRadius: 3,
          overflow: "hidden",
          minWidth: 52,
        }}
      >
        <div style={{ height: "100%", width: `${value}%`, background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontFamily: T.mono, fontSize: 12, width: 26, textAlign: "right" }}>
        {value.toFixed(0)}
      </span>
    </div>
  );
}

function ScorePill({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: 10.5, color: T.text3, textTransform: "uppercase", letterSpacing: ".06em" }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, fontFamily: T.mono, color }}>
        {value.toFixed(0)}
      </div>
    </div>
  );
}

function Spark({ data, up }: { data: number[]; up: boolean }) {
  if (!data || data.length < 2) return null;
  const w = 80;
  const h = 24;
  const mn = Math.min(...data);
  const mx = Math.max(...data);
  const rng = mx - mn || 1;
  const pts = data
    .map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - mn) / rng) * h}`)
    .join(" ");
  return (
    <svg width={w} height={h} style={{ display: "inline-block", verticalAlign: "middle" }}>
      <polyline points={pts} fill="none" stroke={up ? T.gain : T.loss} strokeWidth={1.5} />
    </svg>
  );
}

function Th({
  children,
  align,
  w,
}: {
  children?: React.ReactNode;
  align?: "right";
  w?: number;
}) {
  return (
    <th
      style={{
        textAlign: align ?? "left",
        fontWeight: 600,
        fontSize: 11,
        textTransform: "uppercase",
        letterSpacing: ".05em",
        padding: "0 8px 10px",
        width: w,
      }}
    >
      {children}
    </th>
  );
}
