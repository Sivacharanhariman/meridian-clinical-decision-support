"""The named demonstration fixtures are part of the acceptance surface."""


REQUIRED_CASES = {
    "normal-adult", "stroke-red-flag", "negated-chest-pain", "historical-symptom",
    "family-history", "pediatric", "pregnant", "zero-evidence", "prompt-injection",
    "tampered-evidence", "malformed-model", "hallucinated-citation", "invented-fact",
    "stale-concurrent", "cross-tenant", "override-privilege", "revoked-delegation",
    "chest-pain-ed", "llm-timeout", "provider-429",
}


def test_all_twenty_required_demo_scenarios_are_available(api):
    result = api.client.get("/api/demo")
    assert result.status_code == 200
    catalog = result.json()
    cases = {case["caseId"]: case for case in catalog["cases"]}
    assert REQUIRED_CASES <= cases.keys()
    assert "synthetic" in catalog["disclaimer"].lower()
    for case_id in sorted(REQUIRED_CASES):
        session = api.create(case_id)
        assert session["patient"]["synthetic"] is True
        assert session["originalTranscript"]
        assert session["state"]["currentStateVersion"] == 0
        assert session["recommendations"] == []


def test_demo_runs_without_external_llm_credentials(api):
    result = api.client.get("/api/health")
    assert result.status_code == 200
    assert result.json()["syntheticOnly"] is True
    response = api.triage(api.create())
    assert response["mode"] == "DETERMINISTIC"
    assert response["recommendation"]["recommendedDisposition"] == "CLINICIAN_WITHIN_24H"
