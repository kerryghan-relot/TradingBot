// Thin fetch wrappers around the Flask JSON API.

import type {
  AgentsPayload,
  Bench,
  ConfigPayload,
  HistoryPayload,
  LivePayload,
  OpportunitiesPayload,
  Period,
  StrategiesPayload,
} from "./types";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return (await res.json()) as T;
}

export function fetchLive(strategy: string): Promise<LivePayload> {
  return getJson(`/api/live?strategy=${encodeURIComponent(strategy)}`);
}

export function fetchHistory(
  strategy: string,
  period: Period,
  bench: Bench,
): Promise<HistoryPayload> {
  const q = new URLSearchParams({ strategy, period, bench });
  return getJson(`/api/history?${q.toString()}`);
}

export function fetchStrategies(): Promise<StrategiesPayload> {
  return getJson("/api/strategies");
}

export async function selectStrategy(id: string): Promise<void> {
  await fetch("/api/strategy/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
}

export function fetchAgents(): Promise<AgentsPayload> {
  return getJson("/api/agents");
}

export function fetchOpportunities(): Promise<OpportunitiesPayload> {
  return getJson("/api/opportunities");
}

export function fetchConfig(): Promise<ConfigPayload> {
  return getJson("/api/config");
}

export async function saveConfig(
  patch: Record<string, unknown>,
): Promise<{ ok: boolean; error?: string; config?: Record<string, unknown> }> {
  const res = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return res.json();
}
