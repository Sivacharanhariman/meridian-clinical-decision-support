"""Operational audit has an allowlisted schema with no raw clinical payloads."""
from datetime import datetime, timezone
from uuid import uuid4

from backend.domain.contracts import AuditEvent


POLICY_VERSION = "synthetic-policy-1.0"


def make_event(*, event_type: str, session_id: str, actor_id: str,
               action: str, outcome: str, correlation_id: str,
               state_version: int = 0, turn_id: str | None = None,
               authority_source: str = "authoritative-session-assignment",
               rule: str = "TENANT_AND_ASSIGNMENT", model_identifier: str | None = None,
               prompt_hash: str | None = None, fact_ids: list[str] | None = None,
               manifest_id: str | None = None, source_hashes: list[str] | None = None,
               validation_codes: list[str] | None = None,
               recommendation_id: str | None = None, nurse_action_id: str | None = None,
               patient_response_id: str | None = None) -> AuditEvent:
    return AuditEvent(
        eventId=f"audit-{uuid4().hex}", timestamp=datetime.now(timezone.utc),
        eventType=event_type, sessionId=session_id, turnId=turn_id,
        stateVersion=state_version, correlationId=correlation_id, actorId=actor_id,
        resource=f"session:{session_id}", action=action, outcome=outcome,
        policyVersion=POLICY_VERSION, authoritySource=authority_source, rule=rule,
        modelIdentifier=model_identifier, promptHash=prompt_hash,
        factIds=fact_ids or [], manifestId=manifest_id, sourceHashes=source_hashes or [],
        validationCodes=validation_codes or [], recommendationId=recommendation_id,
        nurseActionId=nurse_action_id, patientResponseId=patient_response_id,
    )

