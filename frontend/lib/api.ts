import type { operations } from "@/generated/api";
import type { DemoCatalog, DemoLoginResponse, SessionView, TriageRequest, TriageResponse, NurseActionRequest, AuditResponse, MetricsResponse, SessionSummary } from "./types";

export class RequestError extends Error {
  constructor(public status: number, public code: string, message: string, public correlationId: string | null) {
    super(message); this.name = "RequestError";
  }
}

async function request<T>(path: string, token?: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    cache: "no-store",
  });
  const data: unknown = await response.json();
  if (!response.ok) {
    const error = data && typeof data === "object" ? data as Record<string, unknown> : {};
    throw new RequestError(response.status, typeof error.code === "string" ? error.code : "REQUEST_FAILED", typeof error.message === "string" ? error.message : "The request could not be completed. Refresh the session before continuing.", typeof error.correlationId === "string" ? error.correlationId : null);
  }
  return data as T;
}

type RenderBody = operations["recordSafeRender"]["requestBody"]["content"]["application/json"];
export const api = {
  catalog: () => request<DemoCatalog>("/demo"),
  login: (actorId: string) => request<DemoLoginResponse>("/auth/demo", undefined, { actorId }),
  sessions: (token: string) => request<SessionSummary[]>("/sessions", token),
  create: (token: string, caseId: string) => request<SessionView>("/sessions", token, { caseId }),
  session: (token: string, sessionId: string) => request<SessionView>(`/sessions/${encodeURIComponent(sessionId)}`, token),
  triage: (token: string, body: TriageRequest) => request<TriageResponse>("/triage", token, body),
  action: (token: string, sessionId: string, body: NurseActionRequest) => request<SessionView>(`/sessions/${encodeURIComponent(sessionId)}/actions`, token, body),
  audit: (token: string, sessionId: string) => request<AuditResponse>(`/sessions/${encodeURIComponent(sessionId)}/audit`, token),
  metrics: (token: string) => request<MetricsResponse>("/metrics", token),
  renderMetric: (token: string, body: RenderBody) => request("/metrics/render", token, body),
};
