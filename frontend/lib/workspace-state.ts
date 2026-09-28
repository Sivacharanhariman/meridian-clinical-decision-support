import type { SessionView, TriageResponse } from "./types";
import { advanceClinicalResponse } from "./version-gate";

export type WorkspaceState = {
  generation: number;
  session: SessionView | null;
  response: TriageResponse | null;
  integrityError: string | null;
};
export const emptyWorkspace = (generation = 0): WorkspaceState => ({ generation, session: null, response: null, integrityError: null });

export function receiveResponse(state: WorkspaceState, incoming: TriageResponse, generation: number): WorkspaceState {
  if (generation !== state.generation || !state.session || state.integrityError) return state;
  const result = advanceClinicalResponse(state.response, incoming, state.session.sessionId);
  if (result.kind === "conflict") return { ...state, integrityError: result.error };
  if (result.kind !== "advanced") return state;
  return { ...state, response: result.response };
}

export function receiveSession(state: WorkspaceState, incoming: SessionView, generation: number): WorkspaceState {
  if (generation !== state.generation || state.integrityError) return state;
  if (state.session && incoming.sessionId !== state.session.sessionId) return state;
  if (state.session && incoming.state.currentStateVersion < state.session.state.currentStateVersion) return state;
  if (incoming.state.sessionId !== incoming.sessionId) return { ...state, integrityError: "Session identity is inconsistent. Actions are paused." };
  if (!incoming.latestResponse) {
    if (state.response) return { ...state, integrityError: "The committed clinical response is missing from the session. Actions are paused." };
    return { ...state, session: incoming };
  }
  if (incoming.latestResponse.stateVersion > incoming.state.currentStateVersion) return { ...state, integrityError: "Clinical version is ahead of committed session state. Actions are paused." };
  const result = advanceClinicalResponse(state.response, incoming.latestResponse, incoming.sessionId);
  if (result.kind === "conflict") return { ...state, integrityError: result.error };
  if (result.kind === "stale") return state;
  return { ...state, session: incoming, response: result.response };
}

export function hasCurrentRecommendation(state: WorkspaceState): boolean {
  return !!(state.session && state.response && !state.integrityError && state.session.permissions.canView && state.session.latestResponse && state.session.latestResponse.responseId === state.response.responseId && state.session.state.currentStateVersion >= state.response.stateVersion);
}
