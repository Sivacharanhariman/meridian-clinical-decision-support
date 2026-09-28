"""Release blockers are challenged through the same HTTP path used by the nurse."""
from __future__ import annotations

import copy

import pytest


def assert_manual(response):
    assert response["recommendation"]["recommendedDisposition"] == "MANUAL_ESCALATION"
    assert response["readinessState"] != "READY"


RED_FLAGS = [
    ("POSSIBLE_STROKE", "I have facial droop right now."),
    ("SEVERE_RESPIRATORY_DISTRESS", "I have severe breathing difficulty right now."),
    ("SEVERE_CHEST_PAIN", "I have crushing chest pain right now."),
    ("ANAPHYLAXIS", "I have throat swelling right now."),
    ("UNCONTROLLED_BLEEDING", "I have uncontrolled bleeding right now."),
    ("ALTERED_CONSCIOUSNESS", "I have altered consciousness right now."),
    ("IMMEDIATE_SELF_HARM", "I have a plan to kill myself now."),
]


@pytest.mark.parametrize("category,transcript", RED_FLAGS)
def test_all_seven_confirmed_red_flags_lock_automation(api, category, transcript):
    session = api.create("stroke-red-flag")
    response = api.triage(session, symptomDescription=transcript)
    assert response["safety"]["safetyLocked"] is True
    assert response["safety"]["requiredDisposition"] == "EMERGENCY_911"
    assert response["recommendation"]["recommendedDisposition"] == "EMERGENCY_911"
    assert response["readinessState"] == "SAFETY_LOCKED"
    assert any(
        event["category"] == category
        and event["assertion"] == "AFFIRMED"
        and event["temporality"] == "CURRENT"
        and event["subject"] == "PATIENT"
        for event in response["safety"]["events"]
    )


@pytest.mark.parametrize(
    "case_id,field,value",
    [
        ("negated-chest-pain", "assertion", "NEGATED"),
        ("historical-symptom", "temporality", "HISTORICAL"),
        ("family-history", "subject", "FAMILY_OTHER"),
    ],
)
def test_event_context_is_not_current_affirmed_patient_event(api, case_id, field, value):
    response = api.triage(api.create(case_id))
    chest_events = [e for e in response["safety"]["events"] if e["category"] == "CHEST_PAIN"]
    assert chest_events
    assert all(event[field] == value for event in chest_events)
    assert response["safety"]["safetyLocked"] is False
    assert response["recommendation"]["recommendedDisposition"] not in {
        "HOME_MONITORING", "EMERGENCY_911", "EMERGENCY_DEPARTMENT"
    }


@pytest.mark.parametrize("transcript", [
    "Maybe I have chest pain; I cannot tell.",
    "Someone mentioned chest pain. I do not know who or when.",
    "I feel unwell but cannot explain my symptoms.",
])
def test_uncertainty_cannot_silently_clear_home_gate(api, transcript):
    response = api.triage(api.create(), symptomDescription=transcript)
    assert_manual(response)
    assert response["missingInformation"] or response["systemAlerts"]


def test_complete_curated_assessment_is_positive_home_control(api):
    response = api.triage(api.create("home-complete"))
    assert response["recommendation"]["recommendedDisposition"] == "HOME_MONITORING"
    assert response["readinessState"] == "READY"
    assert response["safety"]["supportedPopulation"] is True
    assert response["safety"]["contextCertain"] is True
    assert response["safety"]["safetyLocked"] is False
    assert response["evidence"]
    assert response["rationale"]
    assert all(claim["factRefs"] and claim["evidenceRefs"] for claim in response["rationale"])


def test_missing_cardiac_history_is_unknown_not_absent(api):
    response = api.triage(api.create())
    history = [fact for fact in response["factGraph"]["facts"] if "cardiac" in fact["factType"].lower()]
    assert history
    assert all(fact["assertionStatus"] == "UNKNOWN_NOT_STATED" for fact in history)
    assert response["recommendation"]["recommendedDisposition"] != "HOME_MONITORING"


@pytest.mark.parametrize("case_id", ["pediatric", "pregnant"])
def test_unsupported_population_is_manual_even_with_red_flag(api, case_id):
    session = api.create(case_id)
    response = api.triage(session, symptomDescription="I have crushing chest pain right now.")
    assert response["safety"]["supportedPopulation"] is False
    assert_manual(response)


@pytest.mark.parametrize("case_id", ["zero-evidence", "prompt-injection", "tampered-evidence"])
def test_no_eligible_evidence_fails_closed(api, case_id):
    response = api.triage(api.create(case_id))
    assert_manual(response)
    assert response["readinessState"] == "UNGROUNDED"
    assert response["evidence"] == []
    assert response["retrievalManifest"]["evidence"] == []
    if case_id != "zero-evidence":
        assert response["retrievalManifest"]["integrityViolations"]
        audit = api.audit(response["sessionId"])
        assert any(event["validationCodes"] for event in audit)


@pytest.mark.parametrize("case_id", [
    "malformed-model", "hallucinated-citation", "invented-fact"
])
def test_catalog_model_attacks_fail_closed(api, case_id):
    response = api.triage(api.create(case_id))
    assert_manual(response)
    assert response["mode"] == "MANUAL"
    assert response["validationCodes"]


def _payload(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else copy.deepcopy(value)


@pytest.mark.parametrize("attack", [
    "missing_disposition", "missing_rationale", "empty_rationale", "empty_fact_refs",
    "empty_evidence_refs", "invalid_disposition", "unknown_field", "not_an_object",
])
def test_malformed_required_model_fields_are_never_repaired(api, monkeypatch, attack):
    original = api.app.state.provider.synthesize

    def corrupt(context):
        result = _payload(original(context))
        if attack == "missing_disposition":
            result.pop("recommendedDisposition")
        elif attack == "missing_rationale":
            result.pop("rationale")
        elif attack == "empty_rationale":
            result["rationale"] = []
        elif attack == "empty_fact_refs":
            result["rationale"][0]["factRefs"] = []
        elif attack == "empty_evidence_refs":
            result["recommendedDisposition"] = "HOME_MONITORING"
            result["rationale"][0]["evidenceRefs"] = []
        elif attack == "invalid_disposition":
            result["recommendedDisposition"] = "SAFE_AT_HOME"
        elif attack == "unknown_field":
            result["forceApproved"] = True
        else:
            return "HOME_MONITORING"
        return result

    monkeypatch.setattr(api.app.state.provider, "synthesize", corrupt)
    response = api.triage(api.create("home-complete"))
    assert_manual(response)
    assert response["mode"] == "MANUAL"


@pytest.mark.parametrize("attack", [
    "hallucinated_alias", "invented_fact_id", "unknown_existing_fact",
    "invented_text_existing_refs", "lower_acuity_disposition",
])
def test_well_formed_synthesis_must_pass_semantic_grounding(api, monkeypatch, attack):
    original = api.app.state.provider.synthesize

    def corrupt(context):
        result = _payload(original(context))
        if attack == "hallucinated_alias":
            result["rationale"][0]["evidenceRefs"] = ["Ref-999"]
        elif attack == "invented_fact_id":
            result["rationale"][0]["factRefs"] = ["Fact-never-in-this-turn"]
        elif attack == "unknown_existing_fact":
            unknown = next(f for f in context.facts.facts if f.assertionStatus == "UNKNOWN_NOT_STATED")
            result["rationale"][0]["factRefs"] = [unknown.factId]
            result["rationale"][0]["claim"] = "The patient has no cardiac history."
        elif attack == "invented_text_existing_refs":
            result["rationale"][0]["claim"] = "The patient has normal vital signs and no cardiac history."
        else:
            result["recommendedDisposition"] = "HOME_MONITORING"
        return result

    monkeypatch.setattr(api.app.state.provider, "synthesize", corrupt)
    response = api.triage(api.create("chest-pain-ed"))
    assert response["recommendation"]["recommendedDisposition"] not in {
        "HOME_MONITORING", "CLINICIAN_WITHIN_24H"
    }
    assert response["mode"] == "MANUAL"
    assert response["validationCodes"]
    assert all("normal vital signs" not in claim["claim"] for claim in response["rationale"])


@pytest.mark.parametrize("case_id", ["llm-timeout", "provider-429"])
def test_provider_failures_preserve_context_and_enter_manual_mode(api, case_id):
    session = api.create(case_id)
    response = api.triage(session)
    assert_manual(response)
    assert response["mode"] == "MANUAL"
    assert response["evidence"]
    assert response["factGraph"]["facts"]
    assert "AI synthesis unavailable — manual clinical review required." in response["systemAlerts"]
    persisted = api.get(session["sessionId"])
    assert persisted["originalTranscript"] == session["originalTranscript"]
    assert persisted["patient"] == session["patient"]
    metrics = api.client.get("/api/metrics", headers=api.headers).json()
    assert metrics["degradedModeRate"] > 0
    assert metrics["deadlineExceededRate" if case_id == "llm-timeout" else "provider429Rate"] > 0
