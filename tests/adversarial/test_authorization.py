"""Object access and revocable authority are tested at the server, with old tokens."""
from __future__ import annotations

import pytest


def assert_unchanged(api, before):
    after = api.get(before["sessionId"])
    assert after["state"]["currentStateVersion"] == before["state"]["currentStateVersion"]
    assert after["recommendations"] == before["recommendations"]
    assert after["actions"] == before["actions"]


def test_authentication_required_for_session_resources(api):
    session = api.create()
    result = api.client.get(f"/api/sessions/{session['sessionId']}")
    assert result.status_code in {401, 403}
    result = api.client.post("/api/triage", json=api.request(session))
    assert result.status_code in {401, 403}


def test_cross_tenant_reads_hide_existence_and_listing(api):
    session = api.create("cross-tenant")
    other = api.login("nurse-cross-tenant")
    existing = api.client.get(f"/api/sessions/{session['sessionId']}", headers=other)
    missing = api.client.get("/api/sessions/session-does-not-exist", headers=other)
    assert existing.status_code == missing.status_code == 404
    assert existing.json()["code"] == missing.json()["code"]
    assert existing.json()["message"] == missing.json()["message"]
    listing = api.client.get("/api/sessions", headers=other)
    assert listing.status_code == 200
    assert session["sessionId"] not in {item["sessionId"] for item in listing.json()}
    audit = api.client.get(f"/api/sessions/{session['sessionId']}/audit", headers=other)
    assert audit.status_code == 404


@pytest.mark.parametrize("action_type", [
    "ACCEPT_RECOMMENDATION", "DOCUMENT_PATIENT_REFUSAL",
    "ESCALATE_TO_CLINICIAN", "CLINICIAN_OVERRIDE",
])
def test_cross_tenant_action_modification_is_rejected(api, action_type):
    response = api.triage(api.create("cross-tenant"))
    before = api.get(response["sessionId"])
    other = api.login("nurse-cross-tenant")
    extra = {"overrideDisposition": "HOME_MONITORING"} if action_type == "CLINICIAN_OVERRIDE" else {}
    if action_type == "DOCUMENT_PATIENT_REFUSAL":
        extra["statedPreference"] = "Patient states they will remain home."
    result = api.action(response, action_type, headers=other, **extra)
    assert result.status_code == 404
    assert_unchanged(api, before)


def test_cross_tenant_triage_is_rejected(api):
    session = api.create("cross-tenant")
    result = api.client.post("/api/triage", json=api.request(session), headers=api.login("nurse-cross-tenant"))
    assert result.status_code == 404
    assert_unchanged(api, session)


def test_same_tenant_without_assignment_cannot_read_or_modify(api):
    response = api.triage(api.create())
    before = api.get(response["sessionId"])
    delegated = api.login("nurse-delegated")
    assert api.get(response["sessionId"], headers=delegated)["permissions"]["canView"]
    api.app.state.auth.revoke_assignment("nurse-delegated", response["sessionId"])

    read = api.client.get(f"/api/sessions/{response['sessionId']}", headers=delegated)
    write = api.action(response, "ESCALATE_TO_CLINICIAN", headers=delegated)
    run = api.client.post("/api/triage", json=api.request(before), headers=delegated)
    assert read.status_code in {403, 404}
    assert write.status_code in {403, 404}
    assert run.status_code in {403, 404}
    assert_unchanged(api, before)


def test_standard_nurse_cannot_claim_override_privilege(api):
    response = api.triage(api.create("override-privilege"))
    before = api.get(response["sessionId"])
    assert before["permissions"]["canOverride"] is False
    result = api.action(response, "CLINICIAN_OVERRIDE", overrideDisposition="HOME_MONITORING")
    assert result.status_code == 403
    assert_unchanged(api, before)
    denials = [event for event in api.audit(response["sessionId"]) if event["outcome"] == "DENY"]
    assert denials
    assert any(event["actorId"] == "nurse-avery" and event["rule"] and event["policyVersion"] and event["authoritySource"] for event in denials)


def test_stale_token_and_previously_allowed_permissions_do_not_survive_revocation(api):
    session = api.create("revoked-delegation")
    response = api.triage(session)
    before = api.get(session["sessionId"])
    delegated = api.login("nurse-delegated")
    api.app.state.auth.grant_delegation("nurse-delegated")
    assert api.get(session["sessionId"], headers=delegated)["permissions"]["canOverride"] is True

    api.app.state.auth.revoke_delegation("nurse-delegated")
    result = api.action(response, "CLINICIAN_OVERRIDE", headers=delegated, overrideDisposition="HOME_MONITORING")
    assert result.status_code == 403
    assert_unchanged(api, before)
    assert api.get(session["sessionId"], headers=delegated)["permissions"]["canOverride"] is False


def test_unavailable_authority_denies_override_but_allows_independent_escalation(api):
    response = api.triage(api.create("override-privilege"))
    before = api.get(response["sessionId"])
    delegated = api.login("nurse-delegated")
    api.app.state.auth.grant_delegation("nurse-delegated")
    api.app.state.auth.set_available(False)

    denied = api.action(response, "CLINICIAN_OVERRIDE", headers=delegated, overrideDisposition="HOME_MONITORING")
    assert denied.status_code in {403, 503}
    assert_unchanged(api, before)
    escalated = api.action(response, "ESCALATE_TO_CLINICIAN", headers=delegated)
    assert escalated.status_code == 200, escalated.text
    assert escalated.json()["recommendations"] == before["recommendations"]
    assert escalated.json()["patientOutcome"] == "CLINICIAN_REVIEW"


def test_client_cannot_supply_tenant_or_permission_claims(api):
    request = api.request(api.create())
    request.update(tenantId="meridian", canOverride=True)
    result = api.client.post("/api/triage", json=request, headers=api.headers)
    assert result.status_code == 422


def test_client_cannot_swap_patient_identity(api):
    session = api.create()
    wrong_patient = api.create("home-complete")
    result = api.client.post(
        "/api/triage", json=api.request(session, patientId=wrong_patient["patient"]["patientId"]),
        headers=api.headers,
    )
    assert result.status_code in {400, 403, 404, 409, 422}
    assert_unchanged(api, session)


def test_client_cannot_disguise_unsupported_patient_as_supported(api):
    session = api.create("pregnant")
    home = api.create("home-complete")
    demographics = {**session["patient"]["demographics"], "isPregnant": False}
    result = api.client.post(
        "/api/triage", json=api.request(
            session, patientDemographics=demographics,
            symptomDescription=home["originalTranscript"],
        ), headers=api.headers,
    )
    if result.status_code == 200:
        assert result.json()["recommendation"]["recommendedDisposition"] == "MANUAL_ESCALATION"
    else:
        assert result.status_code in {400, 403, 409, 422}
        assert_unchanged(api, session)
