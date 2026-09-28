"use client";
import { useEffect, useRef } from "react";
import { CheckCheck, ChevronDown, Fingerprint, History, LockKeyhole, RefreshCw, X } from "lucide-react";
import type { AuditResponse } from "@/lib/types";
import { formatToken, shortId, timeLabel } from "@/lib/display";
export function AuditDrawer({ audit, loading, error, onClose, onRefresh }: { audit: AuditResponse | null; loading: boolean; error: string | null; onClose: () => void; onRefresh: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    dialog?.querySelector<HTMLButtonElement>("button")?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab" && dialog) {
        const items = Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), summary, [tabindex="0"]'));
        if (!items.length) return;
        if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items[items.length - 1].focus(); }
        else if (!event.shiftKey && document.activeElement === items[items.length - 1]) { event.preventDefault(); items[0].focus(); }
      }
    };
    document.addEventListener("keydown", handle);
    return () => { document.removeEventListener("keydown", handle); previous?.focus(); };
  }, [onClose]);
  return <div className="drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><div className="audit-drawer" role="dialog" aria-modal="true" aria-labelledby="audit-title" ref={dialogRef}><header><div><span className="eyebrow">ENCOUNTER PROVENANCE</span><h2 id="audit-title"><History size={23} />Audit trail</h2></div><button className="icon-button" onClick={onClose} aria-label="Close audit trail"><X size={20} /></button></header><div className="audit-explanation"><LockKeyhole size={16} /><p>Operational provenance records identities, decisions, and validation references. Raw transcripts and model prompts are excluded.</p></div><div className="audit-toolbar"><span>{audit ? `${audit.events.length} recorded events` : "Encounter events"}</span><button onClick={onRefresh} disabled={loading}><RefreshCw size={13} />Refresh</button></div>{error && <div className="global-error" role="alert">{error}</div>}{loading && <p className="audit-loading" role="status">Loading audit provenance…</p>}<div className="audit-events">{audit?.events.slice().reverse().map(event => <article className="audit-event" key={event.eventId}><div className={`audit-event-icon ${event.outcome.toUpperCase().includes("DEN") || event.outcome.toUpperCase().includes("REJECT") ? "denied" : ""}`}><CheckCheck size={16} /></div><div className="audit-event-content"><div className="audit-event-title"><h3>{formatToken(event.eventType)}</h3><time>{timeLabel(event.timestamp)}</time></div><p>{formatToken(event.action)} <span>·</span> {formatToken(event.outcome)}</p><div className="audit-event-meta"><span>{event.actorId}</span><span>Session v{event.stateVersion}</span></div><details><summary>Inspect provenance <ChevronDown size={12} /></summary><dl><dt>Correlation</dt><dd>{event.correlationId}</dd><dt>Authority source</dt><dd>{event.authoritySource}</dd><dt>Policy / rule</dt><dd>{event.policyVersion} / {event.rule}</dd><dt>Turn</dt><dd>{event.turnId ?? "—"}</dd><dt>Model</dt><dd>{event.modelIdentifier ?? "—"}</dd><dt>Prompt hash</dt><dd>{event.promptHash ?? "—"}</dd><dt>Manifest</dt><dd>{event.manifestId ?? "—"}</dd><dt>Fact references</dt><dd>{event.factIds.join(", ") || "—"}</dd><dt>Source hashes</dt><dd>{event.sourceHashes.join(", ") || "—"}</dd><dt>Validation codes</dt><dd>{event.validationCodes.join(", ") || "—"}</dd><dt>Recommendation</dt><dd>{event.recommendationId ?? "—"}</dd><dt>Nurse action</dt><dd>{event.nurseActionId ?? "—"}</dd><dt>Patient response</dt><dd>{event.patientResponseId ?? "—"}</dd></dl></details></div></article>)}{!loading && audit?.events.length === 0 && <p className="audit-loading">No events recorded for this encounter yet.</p>}</div><footer><Fingerprint size={14} /><span>{audit ? `Session ${shortId(audit.sessionId)}` : "Append-only encounter history"}</span></footer></div></div>;
}
