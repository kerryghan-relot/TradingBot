import { CSSProperties, ReactNode, useMemo, useState } from "react";
import { T } from "./theme";

// ── Chip / badge ──────────────────────────────────────────────────────
export function chipStyle(bg: string, fg: string): CSSProperties {
  return {
    display: "inline-block",
    padding: "3px 9px",
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
    background: bg,
    color: fg,
  };
}

export function Chip({ bg, fg, children }: { bg: string; fg: string; children: ReactNode }) {
  return <span style={chipStyle(bg, fg)}>{children}</span>;
}

// ── Panel card ────────────────────────────────────────────────────────
export function Card({
  children,
  style,
}: {
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 14,
        padding: 18,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
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
      {children}
    </div>
  );
}

// ── Semantic colour helpers ───────────────────────────────────────────
export const gainLoss = (n: number): string => (n >= 0 ? T.gain : T.loss);
export const arrow = (n: number): string => (n >= 0 ? "▲" : "▼");

export const SIGNAL_COLOR: Record<string, string> = {
  Achat: T.gain,
  Vente: T.loss,
  Hold: T.text2,
};
export const STATUS_COLOR: Record<string, string> = {
  Ouvert: T.accent,
  Fermé: T.text2,
  Annulé: T.text3,
};

// ── Segmented / pill buttons ──────────────────────────────────────────
// Filter pill (period, journal category). `accent` lets the equity
// benchmark row reuse the same shape in orange.
export function segButtonStyle(
  active: boolean,
  accent: string = T.accent,
  opts: { padding?: string; fontSize?: number } = {},
): CSSProperties {
  return {
    padding: opts.padding ?? "7px 13px",
    borderRadius: 8,
    fontSize: opts.fontSize ?? 13,
    fontWeight: 600,
    cursor: "pointer",
    border: `1px solid ${active ? accent : T.border}`,
    background: active ? hexA(accent, 0.14) : "transparent",
    color: active ? accent : T.text2,
  };
}

// Strategy switcher button: active text stays bright (not accent).
export function stratButtonStyle(active: boolean): CSSProperties {
  return {
    padding: "8px 14px",
    borderRadius: 9,
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    border: `1px solid ${active ? T.accent : T.border}`,
    background: active ? hexA(T.accent, 0.14) : "transparent",
    color: active ? T.text : T.text2,
  };
}

export function tabButtonStyle(active: boolean): CSSProperties {
  return {
    padding: "11px 18px",
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer",
    background: "transparent",
    border: "none",
    borderBottom: `2px solid ${active ? T.accent : "transparent"}`,
    color: active ? T.text : T.text2,
    marginBottom: -1,
  };
}

// Turn a #rrggbb into an rgba() string at the given alpha.
export function hexA(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── Sortable table hook ───────────────────────────────────────────────
type Dir = "asc" | "desc";

export function useSort<T extends Record<string, unknown>>(rows: T[]) {
  const [key, setKey] = useState<keyof T | null>(null);
  const [dir, setDir] = useState<Dir>("desc");

  const sorted = useMemo(() => {
    if (!key) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      const x = a[key];
      const y = b[key];
      if (typeof x === "string" && typeof y === "string") {
        return x.localeCompare(y);
      }
      return (x as number) - (y as number);
    });
    return dir === "asc" ? copy : copy.reverse();
  }, [rows, key, dir]);

  function onSort(k: keyof T) {
    if (key === k && dir === "desc") setDir("asc");
    else {
      setKey(k);
      setDir("desc");
    }
  }

  function arrowFor(k: keyof T): string {
    if (key !== k) return "";
    return dir === "desc" ? "↓" : "↑";
  }

  return { sorted, onSort, arrowFor };
}

// ── Table header cell ─────────────────────────────────────────────────
export function Th({
  children,
  align = "left",
  onClick,
  arrow: ar,
}: {
  children: ReactNode;
  align?: "left" | "right" | "center";
  onClick?: () => void;
  arrow?: string;
}) {
  return (
    <th
      onClick={onClick}
      style={{
        textAlign: align,
        padding: "9px 12px",
        fontSize: 11,
        letterSpacing: ".05em",
        textTransform: "uppercase",
        color: T.text2,
        cursor: onClick ? "pointer" : "default",
        userSelect: "none",
        whiteSpace: "nowrap",
      }}
    >
      {children}
      {onClick && <span style={{ color: T.accent }}> {ar}</span>}
    </th>
  );
}
