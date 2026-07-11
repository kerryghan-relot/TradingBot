import { CSSProperties, useEffect, useState } from "react";
import { T } from "../theme";
import { Card, SectionLabel, hexA } from "../ui";
import { fetchConfig, saveConfig } from "../api";
import type { ConfigPayload } from "../types";

// Fields shown as percentages in the UI but stored as fractions on disk.
const PCT_KEYS = new Set(["stop_loss_pct", "min_position_pct", "max_position_pct"]);

interface NumField {
  key: string;
  label: string;
  step?: number;
}

const GROUPS: { title: string; fields: NumField[] }[] = [
  {
    title: "Risque & sizing",
    fields: [
      { key: "vote_threshold", label: "Seuil de votes", step: 1 },
      { key: "max_open_positions", label: "Positions max", step: 1 },
      { key: "stop_loss_pct", label: "Stop-loss %", step: 0.1 },
      { key: "total_capital", label: "Capital total ($)", step: 1000 },
      { key: "min_position_pct", label: "Position min %", step: 0.5 },
      { key: "max_position_pct", label: "Position max %", step: 0.5 },
      { key: "backfill_days", label: "Backfill (jours)", step: 1 },
    ],
  },
  {
    title: "Paramètres des signaux",
    fields: [
      { key: "bb_period", label: "BB période", step: 1 },
      { key: "bb_std", label: "BB écart-type", step: 0.1 },
      { key: "rsi_period", label: "RSI période", step: 1 },
      { key: "rsi_buy", label: "RSI achat", step: 1 },
      { key: "rsi_sell", label: "RSI vente", step: 1 },
      { key: "ema_fast", label: "EMA rapide", step: 1 },
      { key: "ema_slow", label: "EMA lente", step: 1 },
      { key: "ou_window", label: "OU fenêtre", step: 1 },
      { key: "ou_threshold", label: "OU seuil", step: 0.1 },
      { key: "vol_window", label: "Volume fenêtre", step: 1 },
      { key: "vol_factor", label: "Volume facteur", step: 0.1 },
      { key: "kalman_threshold", label: "Kalman seuil", step: 0.1 },
      { key: "vwap_threshold", label: "VWAP seuil", step: 0.001 },
      { key: "zscore_window", label: "Z-score fenêtre", step: 1 },
      { key: "zscore_threshold", label: "Z-score seuil", step: 0.1 },
    ],
  },
];

type SaveState = "idle" | "saving" | "saved" | "error";

export function ConfigPage() {
  const [meta, setMeta] = useState<ConfigPayload | null>(null);
  const [values, setValues] = useState<Record<string, number>>({});
  const [signals, setSignals] = useState<string[]>([]);
  const [symbols, setSymbols] = useState<string>("");
  const [sizingMode, setSizingMode] = useState<string>("confidence");
  const [state, setState] = useState<SaveState>("idle");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    fetchConfig().then((c) => {
      setMeta(c);
      const cfg = c.config;
      const nums: Record<string, number> = {};
      for (const g of GROUPS) {
        for (const f of g.fields) {
          const raw = Number(cfg[f.key] ?? 0);
          nums[f.key] = PCT_KEYS.has(f.key) ? +(raw * 100).toFixed(4) : raw;
        }
      }
      setValues(nums);
      setSignals((cfg.active_signals as string[]) ?? []);
      setSymbols(((cfg.symbols as string[]) ?? []).join(", "));
      setSizingMode((cfg.sizing_mode as string) ?? "confidence");
    });
  }, []);

  if (!meta) return <div style={{ color: T.text3 }}>Chargement…</div>;

  function toggleSignal(sig: string) {
    setSignals((prev) =>
      prev.includes(sig) ? prev.filter((s) => s !== sig) : [...prev, sig],
    );
    setState("idle");
  }

  function setNum(key: string, v: string) {
    setValues((prev) => ({ ...prev, [key]: v === "" ? 0 : Number(v) }));
    setState("idle");
  }

  async function onSave() {
    setState("saving");
    setError("");
    const patch: Record<string, unknown> = {
      active_signals: signals,
      sizing_mode: sizingMode,
      symbols: symbols
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter(Boolean),
    };
    for (const [key, val] of Object.entries(values)) {
      patch[key] = PCT_KEYS.has(key) ? +(val / 100).toFixed(6) : val;
    }
    const res = await saveConfig(patch);
    if (res.ok) {
      setState("saved");
      setTimeout(() => setState("idle"), 2500);
    } else {
      setState("error");
      setError(res.error ?? "échec");
    }
  }

  return (
    <div>
      <SectionLabel>Configuration — config.json</SectionLabel>
      <div style={{ fontSize: 13, color: T.text2, margin: "0 2px 18px", maxWidth: 720 }}>
        Ces réglages sont écrits dans <code>config/config.json</code>, que le bot
        recharge à chaud. Change de stratégie via le sélecteur du tableau de bord,
        puis affine ses paramètres ici.
      </div>

      {/* Active signals */}
      <Card style={{ marginBottom: 16 }}>
        <div style={cardTitle}>Signaux actifs</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {meta.allSignals.map((sig) => {
            const on = signals.includes(sig);
            return (
              <button
                key={sig}
                onClick={() => toggleSignal(sig)}
                style={{
                  padding: "7px 13px",
                  borderRadius: 8,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  border: `1px solid ${on ? T.accent : T.border}`,
                  background: on ? hexA(T.accent, 0.14) : "transparent",
                  color: on ? T.accent : T.text2,
                }}
              >
                {on ? "✓ " : ""}
                {sig}
              </button>
            );
          })}
        </div>
      </Card>

      {/* Numeric groups */}
      {GROUPS.map((g) => (
        <Card key={g.title} style={{ marginBottom: 16 }}>
          <div style={cardTitle}>{g.title}</div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))",
              gap: 14,
            }}
          >
            {g.title === "Risque & sizing" && (
              <label style={fieldWrap}>
                <span style={fieldLabel}>Mode de sizing</span>
                <select
                  value={sizingMode}
                  onChange={(e) => {
                    setSizingMode(e.target.value);
                    setState("idle");
                  }}
                  style={input}
                >
                  <option value="confidence">confidence</option>
                  <option value="fixed">fixed</option>
                </select>
              </label>
            )}
            {g.fields.map((f) => (
              <label key={f.key} style={fieldWrap}>
                <span style={fieldLabel}>{f.label}</span>
                <input
                  type="number"
                  step={f.step ?? 1}
                  value={values[f.key] ?? 0}
                  onChange={(e) => setNum(f.key, e.target.value)}
                  style={input}
                />
              </label>
            ))}
          </div>
        </Card>
      ))}

      {/* Symbols */}
      <Card style={{ marginBottom: 16 }}>
        <div style={cardTitle}>Symboles tradés</div>
        <textarea
          value={symbols}
          onChange={(e) => {
            setSymbols(e.target.value);
            setState("idle");
          }}
          rows={4}
          spellCheck={false}
          style={{ ...input, width: "100%", resize: "vertical", fontFamily: T.mono }}
        />
        <div style={{ fontSize: 12, color: T.text3, marginTop: 6 }}>
          Séparés par des virgules ou des espaces. Le scorer hebdomadaire peut
          réécrire cette liste.
        </div>
      </Card>

      {/* Save bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 4 }}>
        <button
          onClick={onSave}
          disabled={state === "saving"}
          style={{
            padding: "10px 20px",
            borderRadius: 9,
            fontSize: 14,
            fontWeight: 700,
            cursor: state === "saving" ? "default" : "pointer",
            border: "none",
            background: T.accent,
            color: T.bg,
            opacity: state === "saving" ? 0.6 : 1,
          }}
        >
          {state === "saving" ? "Enregistrement…" : "Enregistrer"}
        </button>
        {state === "saved" && (
          <span style={{ color: T.gain, fontSize: 13, fontWeight: 600 }}>
            ✓ config.json mis à jour
          </span>
        )}
        {state === "error" && (
          <span style={{ color: T.loss, fontSize: 13, fontWeight: 600 }}>
            Erreur : {error}
          </span>
        )}
      </div>
    </div>
  );
}

const cardTitle: CSSProperties = { fontSize: 14, fontWeight: 600, marginBottom: 16 };
const fieldWrap: CSSProperties = { display: "flex", flexDirection: "column", gap: 6 };
const fieldLabel: CSSProperties = { fontSize: 12, color: T.text2 };
const input: CSSProperties = {
  background: T.bg,
  border: `1px solid ${T.border}`,
  borderRadius: 8,
  padding: "9px 11px",
  color: T.text,
  fontSize: 14,
  fontFamily: T.sans,
  outline: "none",
};
