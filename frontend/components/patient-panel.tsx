"use client";
import { Activity, ChevronDown, CircleUserRound, ClipboardList, FileText, HeartPulse, MessageSquareText, Pill, ShieldPlus, Sparkles, Stethoscope } from "lucide-react";
import type { SessionView } from "@/lib/types";
import { formatToken, shortId } from "@/lib/display";

export function PatientPanel({ session, transcript, notes, onTranscript, onNotes, onAnalyze, busy, loading, dirty }: { session: SessionView | null; transcript: string; notes: string; onTranscript: (value: string) => void; onNotes: (value: string) => void; onAnalyze: () => void; busy: boolean; loading: boolean; dirty: boolean }) {
  if (!session) return <section className="panel patient-panel"><div className="panel-heading"><CircleUserRound size={18} /><h2>Patient context</h2></div><div className="patient-skeleton"><div /><div /><div /><p>{loading ? "Loading verified synthetic context…" : "Select a demo encounter to begin."}</p></div></section>;
  const patient = session.patient;
  const age = Math.floor(patient.demographics.ageInMonths / 12);
  return <section className="panel patient-panel" aria-label="Synthetic patient context">
    <div className="panel-heading"><CircleUserRound size={18} /><h2>Patient context</h2><span className="live-dot" /></div>
    <div className="patient-identity"><div className="patient-avatar">{patient.displayName.split(" ").map(name => name[0]).join("").slice(0, 2)}</div><div><h3>{patient.displayName}</h3><p>{age} years <span>·</span> {formatToken(patient.demographics.biologicalSex)}</p><span className="record-tag">SYNTHETIC PATIENT</span></div></div>
    <div className="patient-details"><div><span>Patient ID</span><strong title={patient.patientId}>{shortId(patient.patientId)}</strong></div><div><span>Pregnancy status</span><strong>{patient.demographics.isPregnant === null ? "Unknown" : patient.demographics.isPregnant ? "Pregnant" : "Not pregnant"}</strong></div></div>
    <div className="patient-section"><div className="section-title"><span><HeartPulse size={15} />Relevant history</span></div><ul className="context-list">{patient.history.map((item, i) => <li key={i}>{item.replace(" (synthetic record)", "")}</li>)}</ul></div>
    <div className="patient-section"><div className="section-title"><span><Pill size={15} />Medications</span></div><ul className="context-list">{patient.medications.map((item, i) => <li key={i}>{item.replace(" (synthetic)", "")}</li>)}</ul></div>
    <div className="allergy-note"><ShieldPlus size={15} /><span>{patient.allergies.join(" · ").replace(" in synthetic record", "")}</span></div>
    <div className="transcript-section"><div className="section-title"><label htmlFor="transcript"><MessageSquareText size={16} />Patient transcript</label><span className="editable-tag">EDITABLE</span></div><div className="transcript-topline"><span className="call-dot" /><span>Synthetic call transcript</span><Activity size={32} strokeWidth={1.2} /></div><textarea id="transcript" value={transcript} onChange={event => onTranscript(event.target.value)} maxLength={12000} disabled={busy || loading} placeholder="Describe the patient's symptoms…" spellCheck={false} /><div className="textarea-meta"><span><FileText size={11} />Original wording retained for analysis</span><span>{transcript.length.toLocaleString()}</span></div></div>
    <details className="nurse-notes" open><summary><span><ClipboardList size={15} />Nurse notes</span><ChevronDown size={13} /></summary><textarea aria-label="Nurse notes" value={notes} onChange={event => onNotes(event.target.value)} maxLength={6000} disabled={busy || loading} placeholder="Add relevant observations…" /></details>
    <div className="analyze-area"><button className="button primary analyze-button" onClick={onAnalyze} disabled={busy || loading || !transcript.trim()}><Sparkles size={16} />{busy ? "Validating encounter…" : "Analyze advisory"}</button><p>{dirty ? "Edits are ready for a new validated turn." : "Guidance is validated before it reaches this workspace."}</p></div>
    <div className="context-source"><Stethoscope size={13} /><span>Meridian synthetic care record</span></div>
  </section>;
}
