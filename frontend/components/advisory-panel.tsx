"use client";

import { useState } from "react";
import { ArrowUpRight, BookOpen, Check, CheckCheck, ChevronDown, CircleHelp, ClipboardCheck, Clock3, FileCheck2, Fingerprint, Info, ListFilter, LockKeyhole, ShieldCheck, Sparkles, TriangleAlert } from "lucide-react";
import type { SessionView, TriageResponse } from "@/lib/types";
import { dispositionLabel, formatToken, shortId } from "@/lib/display";

export function AdvisoryPanel({ response, session, busy, integrityError }: { response: TriageResponse | null; session: SessionView | null; busy: boolean; integrityError: string | null }) {
  const [tab, setTab] = useState<"overview" | "evidence" | "facts">("overview");
  if (integrityError) return <section className="panel advisory-panel"><div className="panel-heading"><ShieldCheck size={18} /><h2>Clinical advisory</h2></div><div className="integrity-state" role="alert"><LockKeyhole size={34} /><h3>Clinical display paused</h3><p>{integrityError}</p><p>Start a fresh encounter to continue. No conflicting response was rendered.</p></div></section>;
  if (busy) return <section className="panel advisory-panel"><div className="panel-heading"><Sparkles size={18} /><h2>Clinical advisory</h2><span className="badge neutral">Processing</span></div><div className="pending-state" role="status"><div className="orb pending-orb"><ShieldCheck size={35} /></div><span className="eyebrow">VALIDATION IN PROGRESS</span><h3>Bringing the picture together</h3><p>Patient context, guidance, and policy checks are being processed. The advisory appears after validation and a committed result.</p><div className="pending-checks"><span><span className="pending-dot" />Safety & context checks</span><span><span className="pending-dot" />Eligible guidance & source integrity</span><span><span className="pending-dot" />Grounding, policy & state validation</span></div><small>Checks shown are the request scope, not a live stage stream.</small></div></section>;
  if (!response) return <section className="panel advisory-panel"><div className="panel-heading"><Sparkles size={18} /><h2>Clinical advisory</h2><span className="badge neutral">Awaiting analysis</span></div><div className="empty-advisory"><div className="orb"><ShieldCheck size={38} /></div><span className="eyebrow">A CLEARER NEXT STEP</span><h3>Context first.<br />Confidence through evidence.</h3><p>Review the synthetic patient transcript, then analyze the encounter for a validated, evidence-linked advisory.</p><div className="empty-features"><div><FileCheck2 size={18} /><strong>Grounded in the encounter</strong><span>Explicit facts, unknowns kept visible</span></div><div><BookOpen size={18} /><strong>Guidance you can inspect</strong><span>Verified, turn-scoped evidence</span></div><div><ShieldCheck size={18} /><strong>Your judgment leads</strong><span>Human decisions recorded separately</span></div></div><div className="subtle-info"><Info size={15} /><span>No clinical recommendation is available before validation.</span></div></div></section>;
  const locked = response.safety.safetyLocked;
  const manual = response.recommendation.recommendedDisposition === "MANUAL_ESCALATION";
  const tone = locked ? "danger" : response.readinessState === "READY" ? "success" : "warning";
  const currentStatus = session?.latestResponse?.responseId === response.responseId;
  const declined = currentStatus && session.recommendationStatus === "DECLINED_BY_PATIENT";
  return <section className="panel advisory-panel" aria-label="Validated clinical advisory">
    <div className="panel-heading"><Sparkles size={18} /><h2>Clinical advisory</h2><span className="commit-label"><CheckCheck size={14} />Committed v{response.stateVersion}</span></div>
    <div className={`recommendation-card ${tone}`}>
      <div className="recommendation-top"><span className="eyebrow">SYSTEM RECOMMENDATION · ADVISORY</span><span className={`badge ${tone}`}>{locked ? <LockKeyhole size={12} /> : <ShieldCheck size={12} />}{formatToken(response.readinessState)}</span></div>
      <div className="recommendation-title">{locked ? <TriangleAlert size={29} strokeWidth={1.8} /> : manual ? <ClipboardCheck size={29} strokeWidth={1.8} /> : <Clock3 size={29} strokeWidth={1.8} />}<h3 data-testid="system-recommendation">{dispositionLabel[response.recommendation.recommendedDisposition]}</h3></div>
      <p>{locked ? "A deterministic safety rule is active. Lower-acuity automation is blocked." : manual ? "Human review is required. No low-acuity automated recommendation is available." : response.readinessState === "INCOMPLETE" ? "Review the missing information below before deciding the next step." : "All required deterministic gates passed for this synthetic encounter."}</p>
      <div className="recommendation-foot"><span><ShieldCheck size={13} />{locked ? "Safety protection active" : "Validated against current policy"}</span><span>{response.mode === "DETERMINISTIC" ? "Deterministic demo" : formatToken(response.mode)}</span></div>
    </div>
    {declined && <div className="refusal-notice" role="status"><TriangleAlert size={18} /><div><strong>Recommended care declined by patient</strong><p>Patient outcome: remains home. The system recommendation above is preserved.</p></div></div>}
    
    {response.systemAlerts.length > 0 && <div className="system-alerts">{response.systemAlerts.map((alert, i) => <p key={i}><TriangleAlert size={14} />{alert}</p>)}</div>}
    <div className="advisory-tabs" role="tablist" aria-label="Advisory details">
      <button role="tab" aria-selected={tab === "overview"} className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>Overview</button>
      <button role="tab" aria-selected={tab === "evidence"} className={tab === "evidence" ? "active" : ""} onClick={() => setTab("evidence")}>Evidence <span>{response.evidence.length}</span></button>
      <button role="tab" aria-selected={tab === "facts"} className={tab === "facts" ? "active" : ""} onClick={() => setTab("facts")}>Patient facts <span>{response.factGraph.facts.length}</span></button>
    </div>
    <div className="advisory-content" role="tabpanel">
      {tab === "overview" && <>
        <div className="section-title"><span><FileCheck2 size={16} />Why this recommendation</span><span className="mini-label">VALIDATED RATIONALE</span></div>
        {response.rationale.length === 0 ? <div className="no-rationale"><Info size={18} /><p>No model rationale was eligible for publication. Use the verified evidence and human review workflow.</p></div> : <ol className="rationale-list">{response.rationale.map((claim, index) => <li key={claim.claimId}><span className="rationale-number">{String(index + 1).padStart(2, "0")}</span><div><p>{claim.claim}</p><div className="rationale-refs">{claim.evidenceRefs.map(ref => <button key={ref} onClick={() => setTab("evidence")}><BookOpen size={11} />{ref}<ArrowUpRight size={10} /></button>)}<button onClick={() => setTab("facts")} title={claim.factRefs.join(", ")}>{claim.factRefs.length} linked fact{claim.factRefs.length === 1 ? "" : "s"}</button></div></div></li>)}</ol>}
        {response.missingInformation.length > 0 && <div className="missing-block"><div className="section-title"><span><CircleHelp size={17} />Clarify with the patient</span><span className="count-badge">{response.missingInformation.length}</span></div><p className="section-description">Not stated does not mean absent.</p><ul>{response.missingInformation.map((item, index) => <li key={index}><span className="empty-checkbox" />{item}</li>)}</ul></div>}
        <div className="evidence-preview"><div><BookOpen size={17} /><span><strong>{response.evidence.length} verified guidance excerpt{response.evidence.length === 1 ? "" : "s"}</strong><small>Source identity, eligibility & content hash checked</small></span></div><button onClick={() => setTab("evidence")} aria-label="Inspect evidence"><ArrowUpRight size={19} /></button></div>
        {response.validationCodes.length > 0 && <details className="technical-detail"><summary><ShieldCheck size={14} />Validation details<ChevronDown size={13} /></summary><div className="code-list">{response.validationCodes.map(code => <span key={code}>{code}</span>)}</div>{response.safety.matchedRuleIds.length > 0 && <p>Matched rules: {response.safety.matchedRuleIds.join(", ")}</p>}</details>}
      </>}
      {tab === "evidence" && <>
        <div className="section-title"><span><BookOpen size={16} />Verified guidance</span><span className="mini-label">SYNTHETIC SOURCES</span></div>
        <p className="section-description">Evidence is bound to this encounter and committed turn. These demonstration excerpts are not real clinical protocols.</p>
        {response.evidence.length === 0 && <div className="no-rationale"><TriangleAlert size={18} /><p>No eligible evidence was retrieved. Automated low-acuity advice is blocked.</p></div>}
        {response.evidence.map(item => <article className="evidence-card" key={item.alias}><div className="evidence-card-top"><span className="reference-badge">{item.alias}</span><span><Check size={12} />Verified source</span></div><h4>{formatToken(item.chunk.guidelineId.replaceAll("-", " "))}</h4><p>{item.chunk.text}</p><div className="evidence-meta"><span>Version {item.chunk.guidelineVersion}</span><span>Chunk {item.chunk.chunkIndex}</span><span title="Retrieval similarity, not clinical confidence">Match {item.chunk.retrievalScore.toFixed(3)}</span></div><details className="hash-detail"><summary><Fingerprint size={12} />Source provenance</summary><dl><dt>Chunk ID</dt><dd>{item.chunk.chunkId}</dd><dt>SHA-256</dt><dd>{item.chunk.sourceHash}</dd><dt>Manifest</dt><dd>{response.retrievalManifest.manifestId}</dd></dl></details></article>)}
      </>}
      {tab === "facts" && <>
        <div className="section-title"><span><ListFilter size={16} />Structured patient facts</span></div><p className="section-description">Unknown facts cannot support a positive or negative clinical assertion.</p>
        <div className="fact-list">{response.factGraph.facts.map(fact => <article className="fact-item" key={fact.factId}><div><strong>{formatToken(fact.factType)}</strong><span className={`fact-status ${fact.assertionStatus === "UNKNOWN_NOT_STATED" ? "unknown" : fact.assertionStatus === "ABSENT" ? "absent" : "present"}`}>{fact.assertionStatus === "UNKNOWN_NOT_STATED" ? "Not stated" : formatToken(fact.assertionStatus)}</span></div><p>{fact.normalizedValue}</p><small>{fact.source} · {shortId(fact.factId)}</small></article>)}</div>
        {response.safety.events.length > 0 && <details className="technical-detail"><summary><ShieldCheck size={14} />Deterministic context events<ChevronDown size={13} /></summary>{response.safety.events.map(event => <div className="context-event" key={event.eventId}><strong>{formatToken(event.category)}</strong><span>{event.assertion} · {event.temporality} · {event.subject}</span><p>“{event.sourceText}”</p></div>)}</details>}
      </>}
    </div>
    <div className="advisory-footer"><ShieldCheck size={13} /><span>Decision support only. The care decision remains with the clinical team.</span></div>
  </section>;
}
