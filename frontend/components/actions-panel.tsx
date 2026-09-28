"use client";
import { useEffect, useState } from "react";
import { ArrowUpRight, Check, CheckCheck, ChevronRight, ClipboardCheck, ClipboardPenLine, CornerUpRight, History, Info, LockKeyhole, ShieldCheck, ShieldX, TriangleAlert, UserRoundCheck, X } from "lucide-react";
import type { ActionType, Disposition, NurseActionRequest, SessionView, TriageResponse } from "@/lib/types";
import { actionLabel, dispositionLabel, formatToken, timeLabel } from "@/lib/display";

type ActionDetails = Pick<NurseActionRequest, "actionType" | "rationale" | "statedPreference" | "overrideDisposition">;
export function ActionsPanel({ session, response, enabled, busy, onAction, onAudit }: { session: SessionView | null; response: TriageResponse | null; enabled: boolean; busy: boolean; onAction: (details: ActionDetails) => Promise<boolean>; onAudit: () => void }) {
  const [form, setForm] = useState<ActionType | null>(null);
  const [rationale, setRationale] = useState("");
  const [preference, setPreference] = useState("");
  const [override, setOverride] = useState<Disposition>("CLINICIAN_WITHIN_24H");
  useEffect(() => { setForm(null); setRationale(""); setPreference(""); }, [session?.sessionId, response?.responseId]);
  const permissions = session?.permissions;
  const selectable = enabled && !busy;
  const begin = (type: ActionType) => { setForm(type); setRationale(""); setPreference(""); if (response) setOverride(response.recommendation.recommendedDisposition); };
  const submit = async () => {
    if (!form) return;
    const success = await onAction({ actionType: form, rationale: rationale.trim(), statedPreference: form === "DOCUMENT_PATIENT_REFUSAL" ? preference.trim() : null, overrideDisposition: form === "CLINICIAN_OVERRIDE" ? override : null });
    if (success) setForm(null);
  };
  const latestAction = session && session.actions.length > 0 ? session.actions[session.actions.length - 1] : null;
  const declined = session?.recommendationStatus === "DECLINED_BY_PATIENT";
  return <aside className="actions-column">
    <section className="panel actions-panel"><div className="panel-heading"><UserRoundCheck size={18} /><h2>Your next step</h2></div><div className="actions-intro"><span className="eyebrow">HUMAN DECISION</span><p>Review the advisory.<br /><strong>You remain in control.</strong></p></div>
      {response?.safety.safetyLocked && <div className="action-safety"><LockKeyhole size={16} /><div><strong>Safety lock active</strong><span>Lower-acuity automation is blocked.</span></div></div>}
      <div className="action-buttons">
        <button className="action-button accept" disabled={!selectable || !permissions?.canAccept || response?.mode === "MANUAL"} onClick={() => begin("ACCEPT_RECOMMENDATION")}><span className="action-icon"><CheckCheck size={18} /></span><span><strong>Accept recommendation</strong><small>Record your reviewed decision</small></span><ChevronRight size={15} /></button>
        <button className="action-button" disabled={!selectable || !permissions?.canEscalate} onClick={() => begin("ESCALATE_TO_CLINICIAN")}><span className="action-icon"><CornerUpRight size={18} /></span><span><strong>Escalate to clinician</strong><small>Request human clinical review</small></span><ChevronRight size={15} /></button>
        <button className="action-button refusal" disabled={!selectable || !permissions?.canDocumentRefusal} onClick={() => begin("DOCUMENT_PATIENT_REFUSAL")}><span className="action-icon"><ClipboardPenLine size={18} /></span><span><strong>Document patient refusal</strong><small>Preserve recommended care</small></span><ChevronRight size={15} /></button>
        {permissions?.canOverride && <button className="action-button override" disabled={!selectable} onClick={() => begin("CLINICIAN_OVERRIDE")}><span className="action-icon"><ShieldCheck size={18} /></span><span><strong>Clinician override</strong><small>Authorized, separately recorded</small></span><ChevronRight size={15} /></button>}
      </div>
      {!permissions?.canOverride && <div className="permission-note"><LockKeyhole size={12} /><span>Clinician override requires current server-authorized privilege.</span></div>}
      {permissions && !permissions.authorizationServiceAvailable && <div className="manual-notice"><ShieldX size={15} /><span>Authority service unavailable. Sensitive override is denied.</span></div>}
      {!enabled && !busy && <div className="action-hint"><Info size={13} /><span>Actions become available after a current validated response and fresh session permissions.</span></div>}
      {form && <div className={`action-form ${form === "DOCUMENT_PATIENT_REFUSAL" ? "refusal-form" : ""}`}><div className="action-form-title"><strong>{form === "DOCUMENT_PATIENT_REFUSAL" ? "Document patient refusal" : form === "ACCEPT_RECOMMENDATION" ? "Confirm reviewed care" : form === "CLINICIAN_OVERRIDE" ? "Clinician override" : "Request clinician review"}</strong><button aria-label="Close action form" onClick={() => setForm(null)} disabled={busy}><X size={15} /></button></div>
        {form === "DOCUMENT_PATIENT_REFUSAL" && <><div className="preserved-recommendation"><LockKeyhole size={14} /><span>Recommended care stays <strong>{response ? dispositionLabel[response.recommendation.recommendedDisposition] : "unchanged"}</strong>.</span></div><label htmlFor="stated-preference">Patient&apos;s stated preference <span>Required</span></label><textarea id="stated-preference" value={preference} onChange={event => setPreference(event.target.value)} placeholder="Document the patient's own stated preference…" maxLength={2000} disabled={busy} /></>}
        {form === "CLINICIAN_OVERRIDE" && <><label htmlFor="override-disposition">Requested disposition</label><select id="override-disposition" value={override} onChange={event => setOverride(event.target.value as Disposition)} disabled={busy}>{(Object.keys(dispositionLabel) as Disposition[]).map(value => <option key={value} value={value}>{dispositionLabel[value]}</option>)}</select><p className="form-explainer">The server rechecks current authority at execution. The original advisory and safety state remain preserved.</p></>}
        <label htmlFor="action-rationale">Clinical documentation <span>Required</span></label><textarea id="action-rationale" value={rationale} onChange={event => setRationale(event.target.value)} placeholder={form === "DOCUMENT_PATIENT_REFUSAL" ? "Record the discussion, recommendation, and follow-up or escalation…" : "Record why you are taking this action…"} maxLength={3000} disabled={busy} />
        <button className={`button ${form === "DOCUMENT_PATIENT_REFUSAL" ? "amber-button" : "primary"}`} onClick={submit} disabled={!selectable || rationale.trim().length < 3 || (form === "DOCUMENT_PATIENT_REFUSAL" && preference.trim().length === 0)}><ClipboardCheck size={15} />{busy ? "Saving decision…" : "Save documented action"}</button>
      </div>}
    </section>
    <section className={`panel decision-panel ${declined ? "declined" : ""}`}><div className="panel-heading"><ClipboardCheck size={17} /><h2>Encounter decision</h2></div><div className="decision-body"><span className="eyebrow">RECOMMENDATION STATUS</span><div className={`decision-status ${declined ? "warning-text" : ""}`}>{declined ? <TriangleAlert size={17} /> : latestAction ? <Check size={17} /> : <span className="status-dot" />}{session ? formatToken(session.recommendationStatus) : "Awaiting encounter"}</div><div className="outcome-row"><span>Patient outcome</span><strong>{session ? formatToken(session.patientOutcome) : "Unrecorded"}</strong></div>{latestAction && <div className="last-action"><strong>{actionLabel[latestAction.actionType]}</strong><p>{latestAction.rationale}</p>{latestAction.overrideDisposition && <div className="human-disposition">Human disposition: <strong>{dispositionLabel[latestAction.overrideDisposition]}</strong></div>}<span>{timeLabel(latestAction.timestamp)}</span></div>}{declined && <p className="decision-note">Patient refusal is recorded separately. It does not replace the system recommendation.</p>}</div></section>
    <button className="audit-shortcut" onClick={onAudit} disabled={!session || busy}><span className="audit-icon"><History size={19} /></span><span><strong>Every decision, traceable</strong><small>Open encounter audit trail</small></span><ArrowUpRight size={16} /></button>
    <div className="workspace-promise"><ShieldCheck size={23} /><p><strong>Designed for clinical oversight</strong><span>Advisories support judgment. They never replace it.</span></p></div>
  </aside>;
}
