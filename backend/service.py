"""Application boundary: authorize, compute outside locks, commit, then publish."""
import json
import sqlite3
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from backend.audit.events import make_event
from backend.domain.contracts import (
    Actor, AuditResponse, DemoCase, DemoCatalog, NurseAction, PatientContext, PatientResponse,
    SessionSummary, SessionView, SystemRecommendation, TriageState,
)
from backend.errors import ApiFailure
from backend.models.providers import PROMPT_HASH
from backend.persistence.repository import canonical_digest


class Service:
    def __init__(self, repository, auth, workflow, metrics, settings):
        self.repository, self.auth, self.workflow, self.metrics, self.settings = repository, auth, workflow, metrics, settings
        fixture = json.loads((Path(__file__).parent / "fixtures/cases.json").read_text())
        self.cases = {case["caseId"]: case for case in fixture["cases"]}

    def catalog(self):
        return DemoCatalog(cases=[DemoCase(**{key: case[key] for key in DemoCase.model_fields}) for case in self.cases.values()],
            actors=list(self.auth.actors.values()), defaultCaseId="normal-adult",
            disclaimer="Synthetic data only. Prototype demonstration, not a medical device or real-world medical guidance.")

    def deny_audit(self, actor, session_id, action, error, correlation_id):
        row = self.repository.get_session(session_id, tenant_id=actor.tenantId)
        # An inaccessible ID is recorded as an attempted resource ID without
        # exposing whether another tenant actually owns such an object.
        self.repository.append_audit(make_event(event_type="AUTHORIZATION_OR_STATE_DENIED", session_id=session_id,
            actor_id=actor.actorId, action=action, outcome="DENY", correlation_id=correlation_id,
            state_version=row["version"] if row else 0, authority_source="fresh-server-identity-assignment-and-delegation",
            rule=error.code, validation_codes=[error.code]))

    def resolve(self, actor, session_id, action, correlation_id):
        row = self.repository.get_session(session_id, tenant_id=actor.tenantId)
        try:
            self.auth.authorize(actor, row, action)
        except ApiFailure as exc:
            self.deny_audit(actor, session_id, action, exc, correlation_id)
            raise
        return row

    def create(self, actor, body, correlation_id):
        case = self.cases.get(body.caseId)
        if not case:
            raise ApiFailure(404, "CASE_NOT_FOUND", "Synthetic case not found.")
        assigned = [identity.actorId for identity in self.auth.actors.values() if identity.tenantId == actor.tenantId]
        session_id = self.repository.create_session(case, actor, assigned, correlation_id)
        return self.view(actor, session_id, correlation_id)

    def list(self, actor):
        return [SessionSummary(sessionId=row["session_id"], patientName=json.loads(row["patient_json"])["displayName"],
            caseId=row["case_id"], stateVersion=row["version"], readinessState=row["readiness_state"])
            for row in self.repository.list_sessions(actor)]

    def view(self, actor, session_id, correlation_id):
        # One snapshot binds the session version, clinical response, and actions.
        try:
            with self.auth.authority_lock, self.repository.connect() as conn:
                conn.execute("BEGIN")
                row = self.repository.get_session(session_id, conn=conn, tenant_id=actor.tenantId)
                self.auth.authorize(actor, row, "VIEW_SESSION", conn=conn)
                latest = self.repository.latest_response(session_id, conn=conn)
                records = lambda table, model, order: [model.model_validate_json(r[0]) for r in conn.execute(
                    f"SELECT payload FROM {table} WHERE session_id=? ORDER BY {order}", (session_id,))]
                recommendations = records("recommendations", SystemRecommendation, "version")
                actions = records("actions", NurseAction, "version")
                patients = records("patient_responses", PatientResponse, "rowid")
                permissions = self.auth.permissions(actor, row, conn=conn)
                if latest and latest.mode == "MANUAL":
                    permissions.canAccept = False
                return SessionView(sessionId=session_id, caseId=row["case_id"], careTeamId=row["care_team_id"],
                    patient=PatientContext.model_validate_json(row["patient_json"]), originalTranscript=row["transcript"],
                    nurseNotes=row["nurse_notes"], state=TriageState(sessionId=session_id, processingStatus=row["processing_status"],
                        readinessState=row["readiness_state"], currentStateVersion=row["version"], activeTurnId=row["active_turn_id"]),
                    latestResponse=latest, recommendations=recommendations, actions=actions, patientResponses=patients,
                    recommendationStatus=row["recommendation_status"], patientOutcome=row["patient_outcome"], permissions=permissions)
        except ApiFailure as exc:
            self.deny_audit(actor, session_id, "VIEW_SESSION", exc, correlation_id)
            raise

    def triage(self, actor, request, correlation_id):
        started = perf_counter()
        row = self.resolve(actor, request.sessionId, "TRIAGE", correlation_id)
        patient = PatientContext.model_validate_json(row["patient_json"])
        if patient.patientId != request.patientId or patient.demographics != request.patientDemographics:
            exc = ApiFailure(409, "PATIENT_CONTEXT_MISMATCH", "Patient identity and demographics must match verified session context.")
            self.deny_audit(actor, request.sessionId, "TRIAGE", exc, correlation_id)
            raise exc
        auth_ms = (perf_counter() - started) * 1000
        digest = canonical_digest(request)
        try:
            status, prior = self.repository.reserve_turn(request, digest)
            if status == "COMMITTED":
                return prior
            if status == "IN_PROGRESS":
                response = self.repository.wait_for_turn(request, digest, self.settings.request_deadline_ms / 1000)
                self.resolve(actor, request.sessionId, "TRIAGE", correlation_id)
                return response
        except ApiFailure as exc:
            self.deny_audit(actor, request.sessionId, "TRIAGE", exc, correlation_id)
            raise
        try:
            try:
                response = self.workflow.run(request, row["scenario_mode"], auth_ms, started, correlation_id)
            except Exception:
                response = self.workflow.failure_response(request, started, auth_ms)
            commit_started = perf_counter()
            committed = self.repository.commit_triage(request, response, actor=actor, correlation_id=correlation_id,
                auth=self.auth, model_identifier=self.workflow.provider.identifier, prompt_hash=PROMPT_HASH)
            # Capture completed disk-commit latency separately without changing
            # the already persisted response, so retries return identical bytes.
            observed = committed.timings.model_copy(deep=True)
            observed.databaseCommitMs = (perf_counter() - commit_started) * 1000
            observed.totalMs = (perf_counter() - started) * 1000
            self.metrics.record(observed, committed.validationCodes, committed.mode == "MANUAL")
            return committed
        except ApiFailure as exc:
            self.repository.fail_turn(request, exc)
            self.deny_audit(actor, request.sessionId, "TRIAGE", exc, correlation_id)
            raise
        except sqlite3.Error as exc:
            failure = ApiFailure(503, "PERSISTENCE_FAILED", "The decision was not committed. Manual review is required; refresh before retrying.")
            self.repository.fail_turn(request, failure)
            raise failure from exc

    def action(self, actor, session_id, body, correlation_id):
        try:
            self.repository.record_action(session_id, body, actor=actor, correlation_id=correlation_id, auth=self.auth)
        except ApiFailure as exc:
            self.deny_audit(actor, session_id, body.actionType.value, exc, correlation_id)
            raise
        return self.view(actor, session_id, correlation_id)

    def audit(self, actor, session_id, correlation_id):
        self.resolve(actor, session_id, "VIEW_AUDIT", correlation_id)
        return AuditResponse(sessionId=session_id, events=self.repository.audit_events(session_id))

    def render(self, actor, body, correlation_id):
        self.resolve(actor, body.sessionId, "RENDER_METRIC", correlation_id)
        response = self.repository.response(body.responseId)
        if not response or response.sessionId != body.sessionId:
            raise ApiFailure(404, "RESPONSE_INACCESSIBLE", "Committed response not found or inaccessible.")
        self.metrics.render(actor.actorId, body.responseId, body.durationMs)
