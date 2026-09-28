import pytest

@pytest.mark.parametrize("text", [
    "No chest pain and I have throat swelling right now.",
    "My mother says I have throat swelling right now.",
    "My father had chest pain last month but I have throat swelling now.",
])
def test_a_new_patient_subject_cannot_inherit_prior_negation_or_family_context(api, text):
    response = api.triage(api.create(), symptomDescription=text)
    assert response["safety"]["safetyLocked"]
    assert response["recommendation"]["recommendedDisposition"] in {"EMERGENCY_911", "MANUAL_ESCALATION"}

def test_nurse_acceptance_does_not_invent_patient_consent(api):
    response = api.triage(api.create())
    accepted = api.action(response, "ACCEPT_RECOMMENDATION")
    assert accepted.status_code == 200
    assert accepted.json()["recommendationStatus"] == "ACCEPTED"
    assert accepted.json()["patientResponses"] == []
    assert accepted.json()["patientOutcome"] == "UNRECORDED"

def test_uninterpreted_vitals_forbid_home_without_inventing_threshold_rules(api):
    response = api.triage(api.create("home-complete"), vitalSigns={"oxygenSaturation": 91})
    assert response["recommendation"]["recommendedDisposition"] == "MANUAL_ESCALATION"
    assert any(f["factType"] == "VITAL:oxygenSaturation" for f in response["factGraph"]["facts"])

def test_added_nurse_observations_cannot_clear_exact_home_fixture(api):
    response = api.triage(api.create("home-complete"), nurseNotes="Patient describes additional symptoms I cannot interpret.")
    assert response["recommendation"]["recommendedDisposition"] == "MANUAL_ESCALATION"

def test_refresh_retains_the_input_that_produced_the_advisory(api):
    session = api.create()
    text = "I have chest pain right now."
    response = api.triage(session, symptomDescription=text, nurseNotes="Updated synthetic assessment.")
    saved = api.get(session["sessionId"])
    assert saved["originalTranscript"] == text
    assert saved["nurseNotes"] == "Updated synthetic assessment."
    assert saved["latestResponse"] == response

@pytest.mark.parametrize("action", ["ACCEPT_RECOMMENDATION", "ESCALATE_TO_CLINICIAN", "CLINICIAN_OVERRIDE"])
def test_a_later_human_action_cannot_erase_patient_refusal(api, action):
    response = api.triage(api.create("chest-pain-ed"))
    refused = api.action(response, "DOCUMENT_PATIENT_REFUSAL", statedPreference="I choose to remain home in this simulation.")
    assert refused.status_code == 200
    extra = {"overrideDisposition": "CLINICIAN_WITHIN_24H", "headers": api.login("clinician-morgan")} if action == "CLINICIAN_OVERRIDE" else {}
    later = api.action(response, action, baseStateVersion=refused.json()["state"]["currentStateVersion"], **extra)
    assert later.status_code == 200
    assert later.json()["recommendationStatus"] == "DECLINED_BY_PATIENT"
    assert later.json()["patientOutcome"] == "REMAINS_HOME"
    assert later.json()["recommendations"] == [response["recommendation"]]
    assert len(later.json()["patientResponses"]) == 1
