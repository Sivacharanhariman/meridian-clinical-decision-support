"""Short SQLite transactions, immutable clinical records, and CAS commits.

No retrieval or model call occurs inside a transaction. Reservations serialize
the session/turn identity before expensive work; clinical state advances only in
the final compare-and-swap transaction.
"""
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Condition
from uuid import uuid4

from backend.audit.events import make_event
from backend.domain.contracts import (
    Actor, ActionType, AuditEvent, NurseAction, NurseActionRequest, PatientResponse,
    PatientResponseType, SystemRecommendation, TriageRequest, TriageResponse,
)
from backend.errors import ApiFailure


def canonical_digest(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class Repository:
    def __init__(self, database_path: str | Path):
        self._condition = Condition()
        self._keeper = None
        if str(database_path) == ":memory:":
            self.path = f"file:meridian-{uuid4().hex}?mode=memory&cache=shared"
            self.uri = True
            self._keeper = sqlite3.connect(self.path, uri=True, check_same_thread=False)
        else:
            path = Path(database_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(path)
            self.uri = False
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
              CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                care_team_id TEXT NOT NULL, case_id TEXT NOT NULL,
                patient_json TEXT NOT NULL, transcript TEXT NOT NULL, nurse_notes TEXT NOT NULL,
                scenario_mode TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
                processing_status TEXT NOT NULL DEFAULT 'PENDING',
                readiness_state TEXT NOT NULL DEFAULT 'INCOMPLETE',
                active_turn_id TEXT, latest_response_id TEXT,
                recommendation_status TEXT NOT NULL DEFAULT 'AWAITING_REVIEW',
                patient_outcome TEXT NOT NULL DEFAULT 'UNRECORDED', created_at TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS assignments (
                actor_id TEXT NOT NULL, session_id TEXT NOT NULL,
                active INTEGER NOT NULL, PRIMARY KEY(actor_id, session_id)
              );
              CREATE TABLE IF NOT EXISTS delegations (
                actor_id TEXT PRIMARY KEY, active INTEGER NOT NULL
              );
              CREATE TABLE IF NOT EXISTS turns (
                session_id TEXT NOT NULL, turn_id TEXT NOT NULL, digest TEXT NOT NULL,
                status TEXT NOT NULL, response_id TEXT, failure_json TEXT, created_at REAL NOT NULL,
                PRIMARY KEY(session_id, turn_id)
              );
              CREATE TABLE IF NOT EXISTS responses (
                response_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                version INTEGER NOT NULL, payload TEXT NOT NULL, UNIQUE(session_id, version)
              );
              CREATE TABLE IF NOT EXISTS turn_inputs (
                session_id TEXT NOT NULL, turn_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(session_id, turn_id)
              );
              CREATE TABLE IF NOT EXISTS recommendations (
                recommendation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                version INTEGER NOT NULL, payload TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS actions (
                action_id TEXT NOT NULL, session_id TEXT NOT NULL,
                digest TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(session_id, action_id)
              );
              CREATE TABLE IF NOT EXISTS patient_responses (
                response_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS audit (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                session_id TEXT NOT NULL, payload TEXT NOT NULL
              );
            """)
            for table in ("responses", "recommendations", "actions", "patient_responses", "audit", "turn_inputs"):
                for operation in ("UPDATE", "DELETE"):
                    conn.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation.lower()} "
                                 f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable record'); END")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, uri=self.uri, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_session(self, session_id: str, *, conn=None, tenant_id=None) -> dict | None:
        if conn is not None:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?" + (" AND tenant_id = ?" if tenant_id is not None else ""),
                               (session_id, tenant_id) if tenant_id is not None else (session_id,)).fetchone()
            return dict(row) if row else None
        with self.connect() as connection:
            return self.get_session(session_id, conn=connection, tenant_id=tenant_id)

    def create_session(self, case: dict, actor: Actor, assign_actor_ids: list[str], correlation_id: str) -> str:
        session_id = f"session-{uuid4().hex}"
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""INSERT INTO sessions
                (session_id,tenant_id,care_team_id,case_id,patient_json,transcript,nurse_notes,scenario_mode,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                         (session_id, actor.tenantId, f"{actor.tenantId}-navigation", case["caseId"],
                          json.dumps(case["patient"]), case["transcript"], case["nurseNotes"],
                          case["scenarioMode"], datetime.now(timezone.utc).isoformat()))
            conn.executemany("INSERT INTO assignments VALUES (?, ?, 1)", [(a, session_id) for a in assign_actor_ids])
            self.append_audit(make_event(event_type="SESSION_CREATED", session_id=session_id,
                                         actor_id=actor.actorId, action="CREATE_SESSION", outcome="ALLOW",
                                         correlation_id=correlation_id), conn=conn)
        return session_id

    def list_sessions(self, actor: Actor) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("""SELECT s.* FROM sessions s
                JOIN assignments a ON a.session_id=s.session_id
                WHERE s.tenant_id=? AND a.actor_id=? AND a.active=1 ORDER BY s.created_at DESC""",
                                                     (actor.tenantId, actor.actorId))]

    def latest_response(self, session_id: str, *, conn=None) -> TriageResponse | None:
        if conn is not None:
            row = conn.execute("SELECT r.payload FROM responses r JOIN sessions s ON s.latest_response_id=r.response_id WHERE s.session_id=?", (session_id,)).fetchone()
            return TriageResponse.model_validate_json(row[0]) if row else None
        with self.connect() as connection:
            return self.latest_response(session_id, conn=connection)

    def response(self, response_id: str) -> TriageResponse | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM responses WHERE response_id=?", (response_id,)).fetchone()
            return TriageResponse.model_validate_json(row[0]) if row else None

    def records(self, session_id: str):
        with self.connect() as conn:
            recommendations = [SystemRecommendation.model_validate_json(r[0]) for r in conn.execute("SELECT payload FROM recommendations WHERE session_id=? ORDER BY version", (session_id,))]
            actions = [NurseAction.model_validate_json(r[0]) for r in conn.execute("SELECT payload FROM actions WHERE session_id=? ORDER BY version", (session_id,))]
            patient_responses = [PatientResponse.model_validate_json(r[0]) for r in conn.execute("SELECT payload FROM patient_responses WHERE session_id=? ORDER BY rowid", (session_id,))]
        return recommendations, actions, patient_responses

    def append_audit(self, event: AuditEvent, *, conn=None):
        if conn is not None:
            conn.execute("INSERT INTO audit(event_id,session_id,payload) VALUES (?,?,?)",
                         (event.eventId, event.sessionId, event.model_dump_json()))
            return
        with self.connect() as connection:
            self.append_audit(event, conn=connection)

    def audit_events(self, session_id: str) -> list[AuditEvent]:
        with self.connect() as conn:
            return [AuditEvent.model_validate_json(r[0]) for r in conn.execute("SELECT payload FROM audit WHERE session_id=? ORDER BY sequence", (session_id,))]

    def reserve_turn(self, request: TriageRequest, digest: str) -> tuple[str, TriageResponse | None]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM turns WHERE session_id=? AND turn_id=?", (request.sessionId, request.turnId)).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise ApiFailure(409, "IDEMPOTENCY_REUSE", "This turn identity was already used with different content.")
                if existing["status"] == "COMMITTED":
                    response = conn.execute("SELECT payload FROM responses WHERE response_id=?", (existing["response_id"],)).fetchone()
                    return "COMMITTED", TriageResponse.model_validate_json(response[0])
                if existing["status"] == "FAILED":
                    error = json.loads(existing["failure_json"])
                    raise ApiFailure(error["status"], error["code"], error["message"])
                return "IN_PROGRESS", None
            row = self.get_session(request.sessionId, conn=conn)
            if not row or row["version"] != request.baseStateVersion:
                raise ApiFailure(409, "STALE_STATE", "The session changed. Refresh before submitting another turn.")
            conn.execute("INSERT INTO turns VALUES (?,?,?,'IN_PROGRESS',NULL,NULL,?)", (request.sessionId, request.turnId, digest, time.time()))
        return "RESERVED", None

    def wait_for_turn(self, request: TriageRequest, digest: str, timeout_seconds: float) -> TriageResponse:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            state, response = self.reserve_turn(request, digest)
            if state == "COMMITTED":
                return response
            with self._condition:
                self._condition.wait(timeout=min(.1, max(0, deadline - time.monotonic())))
        raise ApiFailure(409, "TURN_IN_PROGRESS", "This exact turn is still processing; retry with the same content.")

    def fail_turn(self, request: TriageRequest, error: ApiFailure):
        with self.connect() as conn:
            conn.execute("UPDATE turns SET status='FAILED', failure_json=? WHERE session_id=? AND turn_id=? AND status='IN_PROGRESS'",
                         (json.dumps({"status": error.status_code, "code": error.code, "message": error.message}), request.sessionId, request.turnId))
        with self._condition:
            self._condition.notify_all()

    def commit_triage(self, request: TriageRequest, response: TriageResponse, *, actor: Actor,
                      correlation_id: str, auth, model_identifier: str | None = None,
                      prompt_hash: str | None = None) -> TriageResponse:
        begin = time.perf_counter()
        with auth.authority_lock, self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.get_session(request.sessionId, conn=conn, tenant_id=actor.tenantId)
            decision = auth.authorize(actor, row, "TRIAGE", conn=conn)
            if row["version"] != request.baseStateVersion:
                raise ApiFailure(409, "STALE_STATE", "The session changed while this turn was processing. The stale result was discarded.")
            turn = conn.execute("SELECT status,digest FROM turns WHERE session_id=? AND turn_id=?", (request.sessionId, request.turnId)).fetchone()
            if not turn or turn["status"] != "IN_PROGRESS" or turn["digest"] != canonical_digest(request):
                raise ApiFailure(409, "RESERVATION_CONFLICT", "The turn reservation is no longer valid.")
            previous = self.latest_response(request.sessionId, conn=conn)
            response.recommendation.supersedesRecommendationId = previous.recommendation.recommendationId if previous else None
            version = row["version"] + 1
            if response.stateVersion != version or response.recommendation.computedStateVersion != version:
                raise ApiFailure(409, "VERSION_INTEGRITY", "The computed response version did not match its commit.")
            changed = conn.execute("""UPDATE sessions SET version=?,processing_status='COMPLETED',readiness_state=?,
                active_turn_id=?,latest_response_id=?,recommendation_status='AWAITING_REVIEW',patient_outcome='UNRECORDED'
                WHERE session_id=? AND version=?""", (version, response.readinessState.value,
                                                      request.turnId, response.responseId, request.sessionId, request.baseStateVersion))
            if changed.rowcount != 1:
                raise ApiFailure(409, "STALE_STATE", "The session changed before commit.")
            # Clinical input storage is distinct from PHI-minimal operational audit.
            conn.execute("INSERT INTO turn_inputs VALUES (?,?,?)", (request.sessionId, request.turnId, request.model_dump_json()))
            conn.execute("UPDATE sessions SET transcript=?,nurse_notes=? WHERE session_id=?",
                         (request.symptomDescription, request.nurseNotes or "", request.sessionId))
            conn.execute("INSERT INTO recommendations VALUES (?,?,?,?)", (response.recommendation.recommendationId, request.sessionId, version, response.recommendation.model_dump_json()))
            # The immutable response captures transaction preparation time; Metrics
            # additionally measures the completed commit wall clock outside this method.
            response.timings.databaseCommitMs = round((time.perf_counter() - begin) * 1000, 3)
            response.timings.totalMs += response.timings.databaseCommitMs
            conn.execute("INSERT INTO responses VALUES (?,?,?,?,?)", (response.responseId, request.sessionId, request.turnId, version, response.model_dump_json()))
            conn.execute("UPDATE turns SET status='COMMITTED',response_id=? WHERE session_id=? AND turn_id=?", (response.responseId, request.sessionId, request.turnId))
            self.append_audit(make_event(
                event_type="RECOMMENDATION_COMMITTED", session_id=request.sessionId,
                actor_id=actor.actorId, action="TRIAGE", outcome="ALLOW",
                correlation_id=correlation_id, state_version=version, turn_id=request.turnId,
                authority_source=decision["source"], rule=decision["rule"],
                model_identifier=model_identifier, prompt_hash=prompt_hash,
                fact_ids=[f.factId for f in response.factGraph.facts],
                manifest_id=response.retrievalManifest.manifestId,
                source_hashes=[e.chunk.sourceHash for e in response.evidence],
                validation_codes=response.validationCodes, recommendation_id=response.recommendation.recommendationId,
            ), conn=conn)
            for code in response.retrievalManifest.integrityViolations:
                self.append_audit(make_event(event_type="EVIDENCE_REJECTED", session_id=request.sessionId,
                                             actor_id=actor.actorId, action="VERIFY_EVIDENCE", outcome="DENY",
                                             correlation_id=correlation_id, state_version=version, turn_id=request.turnId,
                                             rule="TRUSTED_REGISTRY", validation_codes=[code],
                                             manifest_id=response.retrievalManifest.manifestId), conn=conn)
        # Context manager commits before returning any clinical response.
        with self._condition:
            self._condition.notify_all()
        return response

    def record_action(self, session_id: str, body: NurseActionRequest, *, actor: Actor,
                      correlation_id: str, auth) -> bool:
        digest = canonical_digest({"actorId": actor.actorId, "request": body.model_dump(mode="json")})
        with auth.authority_lock, self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.get_session(session_id, conn=conn, tenant_id=actor.tenantId)
            auth.authorize(actor, row, "VIEW_SESSION", conn=conn)
            existing = conn.execute("SELECT digest FROM actions WHERE session_id=? AND action_id=?", (session_id, body.actionId)).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise ApiFailure(409, "IDEMPOTENCY_REUSE", "This action identity was already used with different content.")
                return False
            decision = auth.authorize(actor, row, body.actionType.value, conn=conn)
            if row["version"] != body.baseStateVersion:
                raise ApiFailure(409, "STALE_STATE", "The session changed. Refresh before recording an action.")
            latest = self.latest_response(session_id, conn=conn)
            if not latest or latest.recommendation.recommendationId != body.targetRecommendationId:
                raise ApiFailure(409, "RECOMMENDATION_NOT_CURRENT", "The action must target the current recommendation.")
            if body.actionType == ActionType.CLINICIAN_OVERRIDE:
                if body.overrideDisposition is None:
                    raise ApiFailure(400, "OVERRIDE_DISPOSITION_REQUIRED", "A clinician override requires an explicit disposition.")
            elif body.overrideDisposition is not None:
                raise ApiFailure(400, "OVERRIDE_NOT_PERMITTED", "Only a clinician override may specify another disposition.")
            if body.actionType == ActionType.ACCEPT_RECOMMENDATION and latest.mode == "MANUAL":
                raise ApiFailure(409, "MANUAL_REVIEW_REQUIRED", "Escalate this manual triage case to a clinician.")
            if body.actionType == ActionType.DOCUMENT_PATIENT_REFUSAL and not (body.statedPreference or "").strip():
                raise ApiFailure(400, "PATIENT_PREFERENCE_REQUIRED", "Document the patient's stated preference for a refusal.")
            now = datetime.now(timezone.utc)
            patient_response = None
            if body.actionType == ActionType.DOCUMENT_PATIENT_REFUSAL:
                patient_response = PatientResponse(responseId=f"patient-response-{uuid4().hex}",
                                                   responseType=PatientResponseType.REFUSED_RECOMMENDED_CARE,
                                                   statedPreference=body.statedPreference, timestamp=now)
                status, outcome = "DECLINED_BY_PATIENT", "REMAINS_HOME"
            elif body.actionType == ActionType.ACCEPT_RECOMMENDATION:
                # Nurse acceptance does not establish the patient's consent.
                status, outcome = "ACCEPTED", "UNRECORDED"
            elif body.actionType == ActionType.ESCALATE_TO_CLINICIAN:
                status, outcome = "ESCALATED", "CLINICIAN_REVIEW"
            else:
                status, outcome = "OVERRIDDEN", "CLINICIAN_REVIEW"
            if body.actionType != ActionType.DOCUMENT_PATIENT_REFUSAL:
                # A later nurse/clinician action cannot invent a changed patient
                # response. Declined recommended care remains declined.
                prior_actions = [NurseAction.model_validate_json(r[0]) for r in conn.execute(
                    "SELECT payload FROM actions WHERE session_id=? ORDER BY version DESC", (session_id,))]
                patient_decision = next((a.patientResponse for a in prior_actions
                    if a.targetRecommendationId == body.targetRecommendationId and a.patientResponse is not None), None)
                if patient_decision and patient_decision.responseType == PatientResponseType.REFUSED_RECOMMENDED_CARE:
                    status, outcome = "DECLINED_BY_PATIENT", "REMAINS_HOME"
            action = NurseAction(actionId=body.actionId, targetRecommendationId=body.targetRecommendationId,
                                 actorId=actor.actorId, actionType=body.actionType, rationale=body.rationale,
                                 timestamp=now, overrideDisposition=body.overrideDisposition, patientResponse=patient_response)
            version = row["version"] + 1
            conn.execute("INSERT INTO actions VALUES (?,?,?,?,?)", (body.actionId, session_id, digest, version, action.model_dump_json()))
            if patient_response:
                conn.execute("INSERT INTO patient_responses VALUES (?,?,?)", (patient_response.responseId, session_id, patient_response.model_dump_json()))
            changed = conn.execute("UPDATE sessions SET version=?,recommendation_status=?,patient_outcome=? WHERE session_id=? AND version=?",
                                   (version, status, outcome, session_id, body.baseStateVersion))
            if changed.rowcount != 1:
                raise ApiFailure(409, "STALE_STATE", "The session changed before the action committed.")
            self.append_audit(make_event(event_type="NURSE_ACTION_COMMITTED", session_id=session_id,
                                         actor_id=actor.actorId, action=body.actionType.value, outcome="ALLOW",
                                         correlation_id=correlation_id, state_version=version, turn_id=latest.turnId,
                                         authority_source=decision["source"], rule=decision["rule"],
                                         recommendation_id=body.targetRecommendationId, nurse_action_id=body.actionId,
                                         patient_response_id=patient_response.responseId if patient_response else None), conn=conn)
        return True
