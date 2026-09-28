import type { Disposition, ActionType } from "./types";
export const dispositionLabel: Record<Disposition, string> = {
  EMERGENCY_911: "Emergency services · 911",
  EMERGENCY_DEPARTMENT: "Emergency department",
  CLINICIAN_WITHIN_24H: "Clinician within 24 hours",
  HOME_MONITORING: "Home monitoring",
  MANUAL_ESCALATION: "Manual clinical review",
};
export const actionLabel: Record<ActionType, string> = {
  ACCEPT_RECOMMENDATION: "Recommendation accepted",
  CLINICIAN_OVERRIDE: "Clinician override recorded",
  DOCUMENT_PATIENT_REFUSAL: "Patient refusal documented",
  ESCALATE_TO_CLINICIAN: "Escalated to clinician",
};
export const formatToken = (value: string) => value.toLowerCase().replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
export const shortId = (value: string) => value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
export const timeLabel = (value: string) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const newId = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;
