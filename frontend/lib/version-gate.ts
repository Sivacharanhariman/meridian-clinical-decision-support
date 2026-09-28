import type { TriageResponse } from "./types";

/** Canonicalizes all response content, not only an ID or selected clinical fields. */
export function canonicalize(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonicalize(item)}`).join(",")}}`;
}

export type GateResult = {
  kind: "advanced" | "replay" | "stale" | "conflict";
  response: TriageResponse | null;
  error: string | null;
};

/** Clinical version is immutable; a human action's session version is separate. */
export function advanceClinicalResponse(current: TriageResponse | null, incoming: TriageResponse, sessionId: string): GateResult {
  const conflict = (error: string): GateResult => ({ kind: "conflict", response: current, error });
  if (incoming.sessionId !== sessionId) return conflict("Response belongs to a different session.");
  if (!Number.isInteger(incoming.stateVersion) || incoming.stateVersion < 1 || incoming.recommendation.computedStateVersion !== incoming.stateVersion || incoming.retrievalManifest.stateVersion !== incoming.stateVersion || incoming.retrievalManifest.sessionId !== incoming.sessionId || incoming.retrievalManifest.turnId !== incoming.turnId || incoming.readinessState !== incoming.recommendation.readinessState) {
    return conflict("Committed response identity or clinical version is inconsistent.");
  }
  if (!current || incoming.stateVersion > current.stateVersion) return { kind: "advanced", response: incoming, error: null };
  if (incoming.stateVersion < current.stateVersion) return { kind: "stale", response: current, error: null };
  if (incoming.turnId === current.turnId && canonicalize(incoming) === canonicalize(current)) return { kind: "replay", response: current, error: null };
  return conflict("Integrity error: the same committed version returned different clinical content. Actions are paused; refresh this encounter.");
}

/** Promises from a previous session/identity cannot write the current workspace. */
export class SessionGeneration {
  private value = 0;
  next(): number { return ++this.value; }
  current(): number { return this.value; }
  isCurrent(generation: number): boolean { return generation === this.value; }
}
