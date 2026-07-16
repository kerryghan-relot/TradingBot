import { useState } from "react";
import { T } from "../theme";
import { chipStyle, hexA } from "../ui";
import type { Agent, AgentsPayload, AgentStatus } from "../types";

const STATUS_META: Record<AgentStatus, { label: string; color: string }> = {
  ok: { label: "Succès", color: T.gain },
  run: { label: "En cours", color: T.accent },
  wait: { label: "En attente", color: T.bench },
  err: { label: "Erreur", color: T.loss },
  planned: { label: "Prévu", color: T.text2 },
};

const CARD_W = 214;
const CARD_H = 126;
const CANVAS_W = 1420;
const CANVAS_H = 660;

interface NodePos {
  id: string;
  left: number;
  top: number;
}

// Fixed pipeline layout mirroring the target model: the sourcing
// column (market feed, symbol research, discovery, sentiment) merges
// into the buy decision, which flows through sizing then the buy/sell
// threshold rule to execution — with the stop-loss risk gate feeding
// execution in parallel.  Stages line up with STAGES below.
const LAYOUT: NodePos[] = [
  { id: "marche", left: 20, top: 34 },
  { id: "rotation", left: 20, top: 190 },
  { id: "decouverte", left: 20, top: 346 },
  { id: "sentiment", left: 20, top: 502 },
  { id: "signaux", left: 320, top: 268 },
  { id: "sizing", left: 610, top: 268 },
  { id: "seuil", left: 900, top: 268 },
  { id: "risque", left: 900, top: 484 },
  { id: "execution", left: 1190, top: 376 },
];

// Column headers, positioned by the centre x of each stage's column.
const STAGES: { label: string; cx: number }[] = [
  { label: "1 · Sourcing", cx: 127 },
  { label: "2 · Achat", cx: 427 },
  { label: "3 · Quantité", cx: 717 },
  { label: "4 · Seuil", cx: 1007 },
  { label: "5 · Exécution", cx: 1297 },
];

const EDGES: { from: string; to: string; color: string }[] = [
  { from: "marche", to: "signaux", color: "#4d8dff" },
  { from: "rotation", to: "signaux", color: "#38bdf8" },
  { from: "decouverte", to: "signaux", color: "#8792ab" },
  { from: "sentiment", to: "signaux", color: "#8792ab" },
  { from: "signaux", to: "sizing", color: "#2fd07f" },
  { from: "sizing", to: "seuil", color: "#8b9dff" },
  { from: "seuil", to: "execution", color: "#22c1c3" },
  { from: "risque", to: "execution", color: "#ff5d6c" },
];

const PIPELINE_IDS = new Set(LAYOUT.map((p) => p.id));

function pos(id: string): NodePos {
  return LAYOUT.find((p) => p.id === id) ?? LAYOUT[0];
}

function edgePath(from: NodePos, to: NodePos): string {
  const x1 = from.left + CARD_W;
  const y1 = from.top + CARD_H / 2;
  const x2 = to.left;
  const y2 = to.top + CARD_H / 2;
  const midX = (x1 + x2) / 2;
  return `M${x1},${y1} C${midX},${y1} ${midX},${y2} ${x2},${y2}`;
}

export function AgentsView({ payload }: { payload: AgentsPayload }) {
  const [selId, setSelId] = useState<string | null>(null);
  const sel = payload.agents.find((a) => a.id === selId) ?? null;
  const pipeline = payload.agents.filter((a) => PIPELINE_IDS.has(a.id));
  const planned = payload.agents.filter((a) => !PIPELINE_IDS.has(a.id));

  return (
    <div>
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
          <div style={{ fontSize: 15, fontWeight: 600 }}>
            Architecture du bot — pipeline de traitement
          </div>
          <div style={{ fontSize: 12, color: T.text2, marginTop: 3 }}>
            Flux de données entre les étapes du moteur. Cliquez sur une
            étape pour voir son détail.
          </div>
        </div>
        <div
          style={{
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
            fontSize: 12,
            color: T.text2,
          }}
        >
          {(Object.keys(STATUS_META) as AgentStatus[]).map((k) => (
            <span
              key={k}
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              <span
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: "50%",
                  background: STATUS_META[k].color,
                }}
              />
              {STATUS_META[k].label}
            </span>
          ))}
        </div>
      </div>

      <div
        style={{
          background: "#0d1220",
          border: `1px solid ${T.border}`,
          borderRadius: 14,
          padding: 18,
          overflowX: "auto",
          marginBottom: 8,
        }}
      >
        <div style={{ position: "relative", width: CANVAS_W, height: CANVAS_H, margin: "0 auto" }}>
          {STAGES.map((s) => (
            <div
              key={s.label}
              style={{
                position: "absolute",
                left: s.cx,
                top: 2,
                transform: "translateX(-50%)",
                fontSize: 11,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: ".08em",
                color: T.text2,
                whiteSpace: "nowrap",
                zIndex: 3,
              }}
            >
              {s.label}
            </div>
          ))}
          <svg
            viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
            style={{
              position: "absolute",
              inset: 0,
              width: CANVAS_W,
              height: CANVAS_H,
              pointerEvents: "none",
              zIndex: 1,
              overflow: "visible",
            }}
          >
            <defs>
              {EDGES.map((e, i) => (
                <marker
                  key={i}
                  id={`agent_ah_${i}`}
                  markerWidth="10"
                  markerHeight="10"
                  refX="7"
                  refY="4"
                  orient="auto"
                  markerUnits="userSpaceOnUse"
                >
                  <path d="M0,0 L8,4 L0,8 Z" fill={e.color} />
                </marker>
              ))}
            </defs>
            {EDGES.map((e, i) => {
              const d = edgePath(pos(e.from), pos(e.to));
              return (
                <g key={i}>
                  <path
                    d={d}
                    fill="none"
                    stroke={e.color}
                    strokeWidth={2}
                    opacity={0.45}
                    markerEnd={`url(#agent_ah_${i})`}
                  />
                  <path
                    d={d}
                    fill="none"
                    stroke={e.color}
                    strokeWidth={2.4}
                    strokeDasharray="2 10"
                    strokeLinecap="round"
                    opacity={0.9}
                    style={{ animation: "dashflow 1.1s linear infinite" }}
                  />
                </g>
              );
            })}
          </svg>

          {pipeline.map((a) => {
            const p = pos(a.id);
            const meta = STATUS_META[a.status];
            return (
              <div
                key={a.id}
                onClick={() => setSelId(a.id)}
                style={{
                  position: "absolute",
                  left: p.left,
                  top: p.top,
                  width: CARD_W,
                  height: CARD_H,
                  background: T.panel,
                  border: `1px ${
                    a.status === "planned" ? "dashed" : "solid"
                  } ${T.border}`,
                  borderLeft: `3px solid ${a.color}`,
                  borderRadius: 14,
                  padding: 14,
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                  cursor: "pointer",
                  zIndex: 2,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 10,
                      background: a.color,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#0a0e17",
                      fontSize: 18,
                      fontWeight: 700,
                      flexShrink: 0,
                    }}
                  >
                    {a.glyph}
                  </div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div
                      style={{
                        fontSize: 14,
                        fontWeight: 700,
                        lineHeight: 1.15,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {a.name}
                    </div>
                    <div
                      style={{
                        fontSize: 11,
                        color: T.text2,
                        lineHeight: 1.25,
                        marginTop: 2,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {a.role}
                    </div>
                  </div>
                </div>
                <div
                  style={{
                    marginTop: "auto",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                  }}
                >
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      fontSize: 11,
                      fontWeight: 600,
                      color: meta.color,
                    }}
                  >
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: meta.color,
                      }}
                    />
                    {meta.label}
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text2 }}>
                    ⟳ {a.last}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {planned.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: ".08em",
              color: T.text2,
              margin: "0 2px 12px",
            }}
          >
            Prochainement
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: 12,
            }}
          >
            {planned.map((a) => (
              <div
                key={a.id}
                onClick={() => setSelId(a.id)}
                style={{
                  background: T.panel,
                  border: `1px dashed ${T.border}`,
                  borderRadius: 14,
                  padding: 14,
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                  cursor: "pointer",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 10,
                      background: hexA(a.color, 0.16),
                      border: `1px solid ${a.color}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: a.color,
                      fontSize: 16,
                      fontWeight: 700,
                      flexShrink: 0,
                    }}
                  >
                    {a.glyph}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.2 }}>
                    {a.name}
                  </div>
                </div>
                <div style={{ fontSize: 11.5, color: T.text2, lineHeight: 1.35 }}>
                  {a.role}
                </div>
                <span
                  style={{
                    ...chipStyle(hexA(T.text2, 0.14), T.text2),
                    alignSelf: "flex-start",
                  }}
                >
                  Prévu
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {sel && <AgentDetailPanel agent={sel} onClose={() => setSelId(null)} />}
    </div>
  );
}

function AgentDetailPanel({
  agent,
  onClose,
}: {
  agent: Agent;
  onClose: () => void;
}) {
  const meta = STATUS_META[agent.status];
  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(6,9,15,.6)",
          backdropFilter: "blur(2px)",
          zIndex: 60,
        }}
      />
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: "min(460px, 94vw)",
          background: "#0d1220",
          borderLeft: `1px solid ${T.border}`,
          boxShadow: "-18px 0 50px rgba(0,0,0,.55)",
          zIndex: 61,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            padding: "20px 22px",
            borderBottom: `1px solid ${T.border}`,
            display: "flex",
            alignItems: "flex-start",
            gap: 14,
          }}
        >
          <div
            style={{
              width: 46,
              height: 46,
              borderRadius: 12,
              background: agent.color,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#0a0e17",
              fontSize: 22,
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            {agent.glyph}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 17, fontWeight: 700, lineHeight: 1.2 }}>
              {agent.name}
            </div>
            <div style={{ fontSize: 12.5, color: T.text2, marginTop: 3, lineHeight: 1.35 }}>
              {agent.role}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "#1a2233",
              border: `1px solid ${T.border}`,
              color: T.text2,
              width: 30,
              height: 30,
              borderRadius: 8,
              cursor: "pointer",
              fontSize: 14,
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            ✕
          </button>
        </div>
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "20px 22px",
            display: "flex",
            flexDirection: "column",
            gap: 22,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span style={chipStyle(hexA(meta.color, 0.14), meta.color)}>
              {meta.label}
            </span>
            <span style={{ fontFamily: T.mono, fontSize: 12, color: T.text2 }}>
              Dernière exécution : {agent.last}
            </span>
          </div>

          <div>
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: ".08em",
                color: T.text2,
                marginBottom: 11,
              }}
            >
              Données
            </div>
            <div
              style={{
                background: T.panel,
                border: `1px solid ${T.border}`,
                borderRadius: 12,
                padding: "14px 16px",
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600, color: T.accent, marginBottom: 8 }}>
                ↓ Entrées
              </div>
              {agent.inputs.map((i, idx) => (
                <div
                  key={idx}
                  style={{ display: "flex", gap: 9, alignItems: "flex-start", fontSize: 13, color: T.textBright, padding: "4px 0" }}
                >
                  <span style={{ color: T.accent, flexShrink: 0 }}>•</span>
                  <span>{i}</span>
                </div>
              ))}
              <div style={{ height: 1, background: T.border, margin: "13px 0" }} />
              <div style={{ fontSize: 12, fontWeight: 600, color: T.gain, marginBottom: 8 }}>
                ↑ Sorties
              </div>
              {agent.outputs.map((o, idx) => (
                <div
                  key={idx}
                  style={{ display: "flex", gap: 9, alignItems: "flex-start", fontSize: 13, color: T.textBright, padding: "4px 0" }}
                >
                  <span style={{ color: T.gain, flexShrink: 0 }}>•</span>
                  <span>{o}</span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: ".08em",
                color: T.text2,
                marginBottom: 6,
              }}
            >
              Dernières actions / décisions
            </div>
            {agent.actions.length === 0 ? (
              <div style={{ color: T.text3, fontSize: 13, padding: "12px 0" }}>
                Aucune donnée récente.
              </div>
            ) : (
              agent.actions.map((a, idx) => (
                <div
                  key={idx}
                  style={{ display: "flex", gap: 13, padding: "12px 0", borderBottom: `1px solid ${T.rowSep}` }}
                >
                  <div
                    style={{
                      fontFamily: T.mono,
                      fontSize: 11,
                      color: T.text3,
                      width: 58,
                      flexShrink: 0,
                      textAlign: "right",
                      paddingTop: 1,
                    }}
                  >
                    {a.t}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, color: T.text, lineHeight: 1.4 }}>{a.x}</div>
                    <div style={{ marginTop: 6 }}>
                      <span style={chipStyle(hexA(STATUS_META[a.s].color, 0.14), STATUS_META[a.s].color)}>
                        {STATUS_META[a.s].label}
                      </span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </>
  );
}
