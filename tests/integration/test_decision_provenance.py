from __future__ import annotations

import json


def test_patient_refusal_preserves_ed_recommendation_and_records_separate_outcome(api):
    session = api.create("chest-pain-ed")
    response = api.triage(session)
    assert response["recommendation"]["recommendedDisposition"] == "EMERGENCY_DEPARTMENT"
    original = response["recommendation"]
    result = api.action(
        response, "DOCUMENT_PATIENT_REFUSAL",
        statedPreference="Patient states they will remain home despite the recommendation.",
    )
    assert result.status_code == 200, result.text
    view = result.json()
    assert view["state"]["currentStateVersion"] == response["stateVersion"] + 1
    assert view["latestResponse"] == response
    assert view["recommendations"] == [original]
    assert view["recommendationStatus"] == "DECLINED_BY_PATIENT"
    assert view["patientOutcome"] == "REMAINS_HOME"
    assert view["actions"][0]["actionType"] == "DOCUMENT_PATIENT_REFUSAL"
    assert view["actions"][0]["overrideDisposition"] is None
    assert view["patientResponses"][0]["responseType"] == "REFUSED_RECOMMENDED_CARE"
    assert view["actions"][0]["patientResponse"] == view["patientResponses"][0]
    assert api.get(session["sessionId"])["recommendations"] == [original]
    audit = api.audit(session["sessionId"])
    assert any(event["nurseActionId"] == view["actions"][0]["actionId"] for event in audit)
    assert any(event["patientResponseId"] == view["patientResponses"][0]["responseId"] for event in audit)


def test_successor_appends_without_mutating_original_recommendation(api):
    session = api.create()
    first = api.triage(session)
    first_stored = api.get(session["sessionId"])
    second = api.triage(first_stored, symptomDescription="I have chest pain right now.")
    view = api.get(session["sessionId"])
    assert second["stateVersion"] == first["stateVersion"] + 1
    assert second["recommendation"]["recommendationId"] != first["recommendation"]["recommendationId"]
    assert second["recommendation"]["supersedesRecommendationId"] == first["recommendation"]["recommendationId"]
    assert view["recommendations"] == [first["recommendation"], second["recommendation"]]
    assert view["latestResponse"] == second


def test_authorized_override_is_a_separate_clinician_action(api):
    response = api.triage(api.create("chest-pain-ed"))
    result = api.action(
        response, "CLINICIAN_OVERRIDE", headers=api.login("clinician-morgan"),
        overrideDisposition="CLINICIAN_WITHIN_24H",
        rationale="Synthetic clinician assumes responsibility after independent review.",
    )
    assert result.status_code == 200, result.text
    view = result.json()
    assert view["recommendations"] == [response["recommendation"]]
    assert view["latestResponse"] == response
    assert view["actions"][0]["overrideDisposition"] == "CLINICIAN_WITHIN_24H"
    assert view["actions"][0]["actorId"] == "clinician-morgan"
    assert view["recommendationStatus"] == "OVERRIDDEN"


def test_stale_action_cannot_target_superseded_recommendation(api):
    response = api.triage(api.create())
    current = api.get(response["sessionId"])
    newest = api.triage(current, symptomDescription="I have chest pain right now.")
    result = api.action(response, "ACCEPT_RECOMMENDATION", baseStateVersion=newest["stateVersion"])
    assert result.status_code == 409
    view = api.get(response["sessionId"])
    assert view["latestResponse"] == newest
    assert view["actions"] == []


def test_action_retry_is_idempotent_and_changed_request_is_rejected(api):
    response = api.triage(api.create())
    request = api.action_request(response, "ACCEPT_RECOMMENDATION")
    url = f"/api/sessions/{response['sessionId']}/actions"
    first = api.client.post(url, json=request, headers=api.headers)
    again = api.client.post(url, json=request, headers=api.headers)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    conflict = api.client.post(url, json={**request, "rationale": "A changed rationale under the same key."}, headers=api.headers)
    assert conflict.status_code == 409
    view = api.get(response["sessionId"])
    assert len(view["actions"]) == 1
    assert view["state"]["currentStateVersion"] == response["stateVersion"] + 1


def test_normal_path_accept_audit_has_bound_provenance_without_raw_text(api):
    session = api.create("normal-adult")
    response = api.triage(session)
    assert response["recommendation"]["recommendedDisposition"] == "CLINICIAN_WITHIN_24H"
    assert response["evidence"] and response["rationale"]
    accepted = api.action(response, "ACCEPT_RECOMMENDATION")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["recommendationStatus"] == "ACCEPTED"
    audit = api.audit(session["sessionId"])
    assert audit
    recommendation_events = [e for e in audit if e["recommendationId"] == response["recommendation"]["recommendationId"]]
    assert recommendation_events
    assert any(event["manifestId"] == response["retrievalManifest"]["manifestId"] for event in recommendation_events)
    assert any(event["factIds"] and event["sourceHashes"] and event["modelIdentifier"] and event["promptHash"] for event in recommendation_events)
    encoded_audit = json.dumps(audit)
    assert session["originalTranscript"] not in encoded_audit
    assert session["patient"]["displayName"] not in encoded_audit
    assert all(event["correlationId"] and event["actorId"] and event["resource"] and event["action"] and event["outcome"] for event in audit)


def test_metrics_expose_measured_stages_and_non_guaranteed_target(api):
    response = api.triage(api.create())
    registered = api.client.post(
        "/api/metrics/render", headers=api.headers,
        json={"sessionId": response["sessionId"], "responseId": response["responseId"], "durationMs": 123.0},
    )
    assert registered.status_code == 200
    result = api.client.get("/api/metrics", headers=api.headers)
    assert result.status_code == 200
    metrics = result.json()
    assert metrics["requestCount"] >= 1
    assert metrics["targetIsGuarantee"] is False
    assert metrics["timeToSafeRender"]["samples"] >= 1
    for stage in ["extractionMs", "retrievalMs", "synthesisMs", "policyValidationMs", "authorizationMs", "databaseCommitMs", "totalMs"]:
        assert response["timings"][stage] >= 0
        assert stage in metrics["stages"]
        summary = metrics["stages"][stage]
        assert summary["samples"] >= 1
        assert 0 <= summary["p50Ms"] <= summary["p95Ms"] <= summary["p99Ms"]
