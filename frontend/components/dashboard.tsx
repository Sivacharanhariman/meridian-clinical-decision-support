"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, ArrowRight, Bell, Building2, Check, ChevronDown, CircleHelp, CircleUserRound, Clock3, Headphones, HeartPulse, History, LayoutDashboard, LockKeyhole, MoreHorizontal, Play, Plus, RefreshCw, ShieldCheck, Sparkles, Stethoscope, TriangleAlert, X } from "lucide-react";
import { api, RequestError } from "@/lib/api";
import type { AuditResponse, DemoCatalog, DemoLoginResponse, MetricsResponse, NurseActionRequest, SessionView } from "@/lib/types";
import { newId, shortId } from "@/lib/display";
import { emptyWorkspace, hasCurrentRecommendation, receiveResponse, receiveSession, type WorkspaceState } from "@/lib/workspace-state";
import { SessionGeneration } from "@/lib/version-gate";
import { PatientPanel } from "./patient-panel";
import { AdvisoryPanel } from "./advisory-panel";
import { ActionsPanel } from "./actions-panel";
import { AuditDrawer } from "./audit-drawer";

const errorMessage = (error: unknown) => error instanceof RequestError ? `${error.message}${error.correlationId ? ` · Reference ${shortId(error.correlationId)}` : ""}` : "Connection unavailable. Check that the local backend is running, then refresh the encounter.";

export function Dashboard() {
  const [catalog, setCatalog] = useState<DemoCatalog | null>(null);
  const [auth, setAuth] = useState<DemoLoginResponse | null>(null);
  const authRef = useRef<DemoLoginResponse | null>(null);
  const generation = useRef(new SessionGeneration());
  const [workspace, setWorkspace] = useState<WorkspaceState>(emptyWorkspace());
  const workspaceRef = useRef(workspace);
  const [transcript, setTranscript] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmedInput, setConfirmedInput] = useState({ transcript: "", notes: "" });
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [metricsIssue, setMetricsIssue] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditResponse | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [metricsOpen, setMetricsOpen] = useState(false);
  const renderPending = useRef<{ generation: number; sessionId: string; responseId: string; start: number } | null>(null);
  const renderedResponses = useRef(new Set<string>());
  const updateWorkspace = useCallback((next: WorkspaceState) => { workspaceRef.current = next; setWorkspace(next); }, []);
  const applySession = useCallback((view: SessionView, gen: number) => { updateWorkspace(receiveSession(workspaceRef.current, view, gen)); }, [updateWorkspace]);
  const loadMetrics = useCallback(async (token: string, gen: number) => {
    try { const data = await api.metrics(token); if (generation.current.isCurrent(gen)) { setMetrics(data); setMetricsIssue(false); } }
    catch { if (generation.current.isCurrent(gen)) setMetricsIssue(true); }
  }, []);

  useEffect(() => {
    let disposed = false;
    const gen = generation.current.next();
    updateWorkspace(emptyWorkspace(gen));
    async function initialize() {
      try {
        const [demo, identity] = await Promise.all([api.catalog(), api.login("nurse-avery")]);
        if (disposed || !generation.current.isCurrent(gen)) return;
        setCatalog(demo); setAuth(identity); authRef.current = identity;
        const view = await api.create(identity.accessToken, demo.defaultCaseId);
        if (disposed || !generation.current.isCurrent(gen)) return;
        applySession(view, gen); setTranscript(view.originalTranscript); setNotes(view.nurseNotes); setConfirmedInput({ transcript: view.originalTranscript, notes: view.nurseNotes });
        void loadMetrics(identity.accessToken, gen);
      } catch (err) { if (!disposed && generation.current.isCurrent(gen)) setError(errorMessage(err)); }
      finally { if (!disposed && generation.current.isCurrent(gen)) setLoading(false); }
    }
    void initialize();
    return () => { disposed = true; };
  }, [applySession, loadMetrics, updateWorkspace]);

  useEffect(() => {
    const pending = renderPending.current;
    const identity = authRef.current;
    if (!pending || !identity || analyzing || loading || !workspace.response || workspace.integrityError || workspace.response.responseId !== pending.responseId || !generation.current.isCurrent(pending.generation) || renderedResponses.current.has(pending.responseId)) return;
    let secondFrame = 0;
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        if (!generation.current.isCurrent(pending.generation) || workspaceRef.current.integrityError || workspaceRef.current.response?.responseId !== pending.responseId) return;
        renderedResponses.current.add(pending.responseId);
        void api.renderMetric(identity.accessToken, { sessionId: pending.sessionId, responseId: pending.responseId, durationMs: performance.now() - pending.start }).then(() => loadMetrics(identity.accessToken, pending.generation)).catch(() => { if (generation.current.isCurrent(pending.generation)) setMetricsIssue(true); });
      });
    });
    return () => { cancelAnimationFrame(firstFrame); cancelAnimationFrame(secondFrame); };
  }, [workspace.response, workspace.integrityError, analyzing, loading, loadMetrics]);
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(null), 5000); return () => clearTimeout(timer); }, [toast]);

  const openCase = async (caseId: string) => {
    const identity = authRef.current;
    if (!identity) return;
    const gen = generation.current.next();
    updateWorkspace(emptyWorkspace(gen)); setLoading(true); setAnalyzing(false); setSaving(false); setError(null); setToast(null); setAuditOpen(false); setAudit(null); setTranscript(""); setNotes(""); renderPending.current = null;
    try {
      const view = await api.create(identity.accessToken, caseId);
      if (!generation.current.isCurrent(gen)) return;
      applySession(view, gen); setTranscript(view.originalTranscript); setNotes(view.nurseNotes); setConfirmedInput({ transcript: view.originalTranscript, notes: view.nurseNotes });
    } catch (err) { if (generation.current.isCurrent(gen)) setError(errorMessage(err)); }
    finally { if (generation.current.isCurrent(gen)) setLoading(false); }
  };

  const switchActor = async (actorId: string) => {
    const previous = workspaceRef.current.session;
    const gen = generation.current.next();
    updateWorkspace(emptyWorkspace(gen)); setLoading(true); setAnalyzing(false); setSaving(false); setError(null); setAuditOpen(false); setAudit(null); setTranscript(""); setNotes(""); renderPending.current = null; authRef.current = null;
    try {
      const identity = await api.login(actorId);
      if (!generation.current.isCurrent(gen)) return;
      authRef.current = identity; setAuth(identity);
      const view = previous ? await api.session(identity.accessToken, previous.sessionId) : await api.create(identity.accessToken, catalog?.defaultCaseId ?? "normal-adult");
      if (!generation.current.isCurrent(gen)) return;
      applySession(view, gen); setTranscript(view.originalTranscript); setNotes(view.nurseNotes); setConfirmedInput({ transcript: view.originalTranscript, notes: view.nurseNotes });
      void loadMetrics(identity.accessToken, gen);
    } catch (err) { if (generation.current.isCurrent(gen)) setError(errorMessage(err)); }
    finally { if (generation.current.isCurrent(gen)) setLoading(false); }
  };

  const refreshSession = async () => {
    const current = workspaceRef.current;
    const identity = authRef.current;
    if (!current.session || !identity) { window.location.reload(); return; }
    setLoading(true); setError(null);
    try { const view = await api.session(identity.accessToken, current.session.sessionId); if (generation.current.isCurrent(current.generation)) applySession(view, current.generation); }
    catch (err) { if (generation.current.isCurrent(current.generation)) setError(errorMessage(err)); }
    finally { if (generation.current.isCurrent(current.generation)) setLoading(false); }
  };

  const analyze = async () => {
    const current = workspaceRef.current;
    const identity = authRef.current;
    if (!current.session || !identity || analyzing || saving || loading || current.integrityError || !transcript.trim()) return;
    const gen = current.generation;
    const started = performance.now();
    const submitted = { transcript, notes };
    setAnalyzing(true); setError(null); setToast(null);
    try {
      const result = await api.triage(identity.accessToken, { sessionId: current.session.sessionId, turnId: newId("turn"), baseStateVersion: current.session.state.currentStateVersion, patientId: current.session.patient.patientId, symptomDescription: transcript, patientDemographics: current.session.patient.demographics, nurseNotes: notes, vitalSigns: null });
      if (!generation.current.isCurrent(gen)) return;
      const next = receiveResponse(workspaceRef.current, result, gen);
      updateWorkspace(next);
      if (next.integrityError) return;
      if (next.response?.responseId === result.responseId) { renderPending.current = { generation: gen, sessionId: result.sessionId, responseId: result.responseId, start: started }; setConfirmedInput(submitted); }
      const fresh = await api.session(identity.accessToken, current.session.sessionId);
      if (!generation.current.isCurrent(gen)) return;
      applySession(fresh, gen);
    } catch (err) { if (generation.current.isCurrent(gen)) setError(errorMessage(err)); }
    finally { if (generation.current.isCurrent(gen)) setAnalyzing(false); }
  };

  const performAction = async (details: Pick<NurseActionRequest, "actionType" | "rationale" | "statedPreference" | "overrideDisposition">): Promise<boolean> => {
    const current = workspaceRef.current;
    const identity = authRef.current;
    if (!hasCurrentRecommendation(current) || !current.session || !current.response || !identity || loading || analyzing || saving || transcript !== confirmedInput.transcript || notes !== confirmedInput.notes) return false;
    const gen = current.generation;
    setSaving(true); setError(null);
    try {
      const view = await api.action(identity.accessToken, current.session.sessionId, { ...details, actionId: newId("action"), targetRecommendationId: current.response.recommendation.recommendationId, baseStateVersion: current.session.state.currentStateVersion });
      if (!generation.current.isCurrent(gen)) return false;
      applySession(view, gen);
      if (workspaceRef.current.integrityError) return false;
      setToast(details.actionType === "DOCUMENT_PATIENT_REFUSAL" ? "Patient refusal recorded. The system recommendation is preserved." : "Decision documented and added to the encounter audit.");
      void loadMetrics(identity.accessToken, gen);
      return true;
    } catch (err) {
      if (generation.current.isCurrent(gen)) {
        setError(errorMessage(err));
        // A rejected action may reflect revocation or a new session version.
        // Read current permissions; never retry a sensitive write implicitly.
        try { const view = await api.session(identity.accessToken, current.session.sessionId); if (generation.current.isCurrent(gen)) applySession(view, gen); }
        catch { if (generation.current.isCurrent(gen)) { updateWorkspace({ ...workspaceRef.current, integrityError: "Current session authority could not be refreshed. Actions are paused; start a fresh encounter." }); } }
      }
      return false;
    } finally { if (generation.current.isCurrent(gen)) setSaving(false); }
  };

  const loadAudit = async () => {
    const current = workspaceRef.current; const identity = authRef.current;
    if (!current.session || !identity) return;
    setAuditOpen(true); setAuditLoading(true); setAuditError(null);
    try { const data = await api.audit(identity.accessToken, current.session.sessionId); if (generation.current.isCurrent(current.generation)) setAudit(data); }
    catch (err) { if (generation.current.isCurrent(current.generation)) setAuditError(errorMessage(err)); }
    finally { if (generation.current.isCurrent(current.generation)) setAuditLoading(false); }
  };
  const closeAudit = useCallback(() => setAuditOpen(false), []);
  const currentCase = catalog?.cases.find(item => item.caseId === workspace.session?.caseId);
  const busy = analyzing || saving;
  const dirty = transcript !== confirmedInput.transcript || notes !== confirmedInput.notes;
  const enabled = hasCurrentRecommendation(workspace) && !dirty && !loading && !analyzing && !saving;

  return <div className="app-shell">
    <aside className="sidebar"><a className="brand-mark" href="#workspace" aria-label="Meridian workspace"><span /><span /><span /><span /></a><div className="sidebar-divider" /><nav aria-label="Workspace navigation"><button className="nav-icon active" aria-label="Triage workspace" title="Triage workspace" onClick={() => document.getElementById("workspace")?.scrollIntoView()}><LayoutDashboard size={21} /></button><button className="nav-icon" aria-label="Encounter audit" title="Encounter audit" onClick={() => void loadAudit()} disabled={!workspace.session}><History size={21} /></button><button className="nav-icon" aria-label="Performance metrics" title="Performance metrics" onClick={() => setMetricsOpen(!metricsOpen)}><Activity size={21} /></button></nav><div className="sidebar-bottom"><button className="nav-icon" aria-label="Prototype information" title="Prototype information" onClick={() => setAboutOpen(true)}><CircleHelp size={21} /></button><div className="sidebar-avatar">{auth?.actor.displayName.split(" ").slice(0, 2).map(part => part[0]).join("") ?? "AC"}</div></div></aside>
    <div className="app-body"><header className="topbar"><div className="wordmark"><span>MERIDIAN</span><span>NATIONAL HEALTH</span></div><span className="topbar-divider" /><div className="workspace-name">Clinical workspace <ChevronDown size={13} /></div><div className="topbar-right"><span className="environment-badge"><span />SYNTHETIC DEMO</span><div className="identity-control"><div className="identity-avatar">{auth?.actor.role === "CLINICIAN" ? <Stethoscope size={17} /> : <Headphones size={17} />}</div><label className="sr-only" htmlFor="demo-actor">Demo identity</label><select id="demo-actor" aria-label="Demo identity" value={auth?.actor.actorId ?? "nurse-avery"} onChange={event => void switchActor(event.target.value)} disabled={loading || !catalog}>{catalog ? catalog.actors.map(actor => <option key={actor.actorId} value={actor.actorId}>{actor.displayName}</option>) : <option value="nurse-avery">Avery Chen, RN</option>}</select><ChevronDown size={12} /></div></div></header>
    <main id="workspace"><div className="page-header"><div><div className="breadcrumb">CARE OPERATIONS <span>/</span> PATIENT NAVIGATION</div><h1>Triage, with the full picture<span>.</span></h1><p>Connected context. Verified guidance. Human-led care.</p></div><div className="encounter-control"><span className="session-status"><span />{workspace.session ? "Encounter open" : loading ? "Preparing workspace" : "No encounter selected"}</span><button className="button secondary compact" onClick={() => void refreshSession()} disabled={busy || loading}><RefreshCw size={14} />Refresh</button></div></div>
      <section className="scenario-bar" aria-label="Demo scenarios"><div className="scenario-intro"><span className="demo-icon"><Play size={14} fill="currentColor" /></span><div><strong>Explore the workflow</strong><span>Start a fresh synthetic encounter</span></div></div><button className={`scenario-button ${workspace.session?.caseId === "normal-adult" ? "selected" : ""}`} onClick={() => void openCase("normal-adult")} disabled={!auth || loading}><span className="demo-letter">A</span><span><strong>Everyday uncertainty</strong><small>Guidance + missing context</small></span><ArrowRight size={15} /></button><button className={`scenario-button safety-demo ${workspace.session?.caseId === "chest-pain-ed" ? "selected" : ""}`} onClick={() => void openCase("chest-pain-ed")} disabled={!auth || loading}><span className="demo-letter">B</span><span><strong>Safety & patient choice</strong><small>Safety lock + refusal</small></span><ArrowRight size={15} /></button><div className="scenario-select"><label htmlFor="scenario">MORE SCENARIOS</label><div><select id="scenario" aria-label="Scenario picker" value={workspace.session?.caseId ?? ""} onChange={event => void openCase(event.target.value)} disabled={!catalog || loading}><option value="" disabled>Select a scenario</option>{catalog?.cases.map(item => <option value={item.caseId} key={item.caseId}>{item.label}</option>)}</select><ChevronDown size={13} /></div></div></section>
      <div className="encounter-heading"><div><Headphones size={15} /><strong>Patient navigation encounter</strong><span className="thin-divider" /><span>{currentCase?.description ?? "A safer path from information to action."}</span></div><span>{workspace.session ? `SESSION ${shortId(workspace.session.sessionId)} · V${workspace.session.state.currentStateVersion}` : "NEW SESSION"}</span></div>
      {error && <div className="global-error" role="alert"><TriangleAlert size={18} /><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError(null)}><X size={16} /></button></div>}
      {toast && <div className={`toast ${workspace.session?.recommendationStatus === "DECLINED_BY_PATIENT" ? "refusal-toast" : ""}`} role="status"><Check size={16} /><span>{toast}</span><button aria-label="Dismiss notification" onClick={() => setToast(null)}><X size={14} /></button></div>}
      {dirty && workspace.response && <div className="draft-warning"><TriangleAlert size={16} /><span>Transcript or notes changed. The advisory below belongs to the previous committed input. Analyze again to enable actions.</span></div>}
      <div className="workspace-grid"><PatientPanel session={workspace.session} transcript={transcript} notes={notes} onTranscript={setTranscript} onNotes={setNotes} onAnalyze={() => void analyze()} busy={busy} loading={loading} dirty={dirty} /><AdvisoryPanel response={workspace.response} session={workspace.session} busy={analyzing} integrityError={workspace.integrityError} /><ActionsPanel session={workspace.session} response={workspace.response} enabled={enabled} busy={busy || loading} onAction={performAction} onAudit={() => void loadAudit()} /></div>
      <div className="performance-strip"><div><span className="telemetry-dot" /><strong>Operational visibility</strong><span className="performance-separator" /><span>Local prototype</span></div><div><span>Request P95 <strong>{metrics && metrics.requestCount ? `${Math.round(metrics.stages.totalMs?.p95Ms ?? 0)} ms` : "—"}</strong></span><span>Safe render P95 <strong>{metrics && metrics.timeToSafeRender.samples ? `${Math.round(metrics.timeToSafeRender.p95Ms)} ms` : "—"}</strong></span><button onClick={() => setMetricsOpen(!metricsOpen)}>{metricsIssue ? "Metrics unavailable" : "View metrics"}<ArrowRight size={12} /></button></div></div>
      {metricsOpen && <section className="panel metrics-panel"><div className="panel-heading"><Activity size={18} /><h2>Prototype performance</h2><button className="icon-button" aria-label="Close metrics" onClick={() => setMetricsOpen(false)}><X size={16} /></button></div><p>3–4 second P95 is a prototype target, never a guarantee. Measurements reflect completed requests in this local instance.</p>{metrics ? <><div className="metrics-summary"><div><strong>{metrics.requestCount}</strong><span>Requests</span></div><div><strong>{(metrics.provider429Rate * 100).toFixed(1)}%</strong><span>Provider 429 rate</span></div><div><strong>{(metrics.deadlineExceededRate * 100).toFixed(1)}%</strong><span>Deadline exceeded</span></div><div><strong>{(metrics.degradedModeRate * 100).toFixed(1)}%</strong><span>Degraded mode</span></div></div><table><thead><tr><th>Stage</th><th>Samples</th><th>P50</th><th>P95</th><th>P99</th></tr></thead><tbody>{Object.entries({ ...metrics.stages, timeToSafeRender: metrics.timeToSafeRender }).map(([stage, metric]) => <tr key={stage}><td>{stage.replace(/([A-Z])/g, " $1")}</td><td>{metric.samples}</td><td>{Math.round(metric.p50Ms)} ms</td><td>{Math.round(metric.p95Ms)} ms</td><td>{Math.round(metric.p99Ms)} ms</td></tr>)}</tbody></table></> : <p>Metrics will appear when the local backend is available.</p>}</section>}
      <footer className="page-footer"><div><ShieldCheck size={14} /><strong>Synthetic data only.</strong><span>Prototype decision support — not a medical device or real-world medical guidance.</span></div><span>MERIDIAN / PROTOTYPE 01</span></footer>
    </main></div>
    {auditOpen && <AuditDrawer audit={audit} loading={auditLoading} error={auditError} onClose={closeAudit} onRefresh={() => void loadAudit()} />}
    {aboutOpen && <div className="drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setAboutOpen(false); }}><section className="about-dialog" role="dialog" aria-modal="true" aria-labelledby="about-title"><button className="icon-button" aria-label="Close prototype information" onClick={() => setAboutOpen(false)}><X size={18} /></button><ShieldCheck size={32} /><span className="eyebrow">MERIDIAN PROTOTYPE</span><h2 id="about-title">Built to support human judgment.</h2><p>{catalog?.disclaimer ?? "This is a synthetic demonstration, not a medical device or real-world clinical guidance."}</p><p>Supported fixture population: adults, non-pregnant. Unsupported populations and failed validation require manual review. The deterministic rules and source documents are demonstration fixtures.</p><p>Demo identities are issued by the local server. Sensitive actions are reauthorized for the current resource at execution.</p><button className="button primary" onClick={() => setAboutOpen(false)}>Return to workspace</button></section></div>}
  </div>;
}
