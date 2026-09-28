"""Exercise the actual HTTP API: normal accept, safety refusal, and outage.

Start backend first. This creates fresh synthetic sessions and does not delete
or reset any existing sessions. Exit nonzero if a release invariant fails.
"""
import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=20, trust_env=False) as client:
        def call(method, path, payload=None):
            response = client.request(method, path, json=payload)
            response.raise_for_status()
            return response.json()

        health = call("GET", "/api/health")
        assert health["syntheticOnly"] is True
        login = call("POST", "/api/auth/demo", {"actorId": "nurse-avery"})
        client.headers["Authorization"] = "Bearer " + login["accessToken"]
        report = {"mode": health["mode"], "syntheticOnly": True, "scenarios": []}

        def analyze(case_id):
            session = call("POST", "/api/sessions", {"caseId": case_id})
            started = perf_counter()
            request = {
                "sessionId": session["sessionId"], "turnId": str(uuid4()),
                "baseStateVersion": session["state"]["currentStateVersion"],
                "patientId": session["patient"]["patientId"],
                "symptomDescription": session["originalTranscript"],
                "patientDemographics": session["patient"]["demographics"],
                "nurseNotes": session["nurseNotes"],
            }
            response = call("POST", "/api/triage", request)
            assert response["stateVersion"] == request["baseStateVersion"] + 1
            persisted = call("GET", f'/api/sessions/{session["sessionId"]}')
            assert persisted["latestResponse"] == response, "Published response must already be durable"
            replay = call("POST", "/api/triage", request)
            assert replay == response, "Network retry must replay identical committed content"
            return persisted, response, round((perf_counter() - started) * 1000, 2)

        session, advisory, elapsed = analyze("normal-adult")
        assert advisory["recommendation"]["recommendedDisposition"] == "CLINICIAN_WITHIN_24H"
        assert advisory["rationale"] and advisory["evidence"]
        accepted = call("POST", f'/api/sessions/{session["sessionId"]}/actions', {
            "actionId": str(uuid4()), "targetRecommendationId": advisory["recommendation"]["recommendationId"],
            "baseStateVersion": session["state"]["currentStateVersion"], "actionType": "ACCEPT_RECOMMENDATION",
            "rationale": "Synthetic demo: nurse reviewed the verified context and advisory.",
        })
        assert accepted["recommendationStatus"] == "ACCEPTED"
        assert accepted["recommendations"][0] == advisory["recommendation"]
        audit = call("GET", f'/api/sessions/{session["sessionId"]}/audit')
        assert any(event["nurseActionId"] for event in audit["events"])
        report["scenarios"].append({"caseId": "normal-adult", "disposition": "CLINICIAN_WITHIN_24H", "action": "ACCEPT_RECOMMENDATION", "auditEvents": len(audit["events"]), "roundTripWithReadAndReplayMs": elapsed, "passed": True})

        session, advisory, elapsed = analyze("chest-pain-ed")
        assert advisory["recommendation"]["recommendedDisposition"] == "EMERGENCY_DEPARTMENT"
        assert advisory["safety"]["safetyLocked"] is True
        refused = call("POST", f'/api/sessions/{session["sessionId"]}/actions', {
            "actionId": str(uuid4()), "targetRecommendationId": advisory["recommendation"]["recommendationId"],
            "baseStateVersion": session["state"]["currentStateVersion"], "actionType": "DOCUMENT_PATIENT_REFUSAL",
            "rationale": "Synthetic demo: recommended care discussed; patient declined.",
            "statedPreference": "I choose to remain home in this synthetic scenario.",
        })
        assert refused["recommendationStatus"] == "DECLINED_BY_PATIENT"
        assert refused["patientOutcome"] == "REMAINS_HOME"
        assert refused["recommendations"][0] == advisory["recommendation"]
        assert refused["latestResponse"] == advisory
        assert refused["patientResponses"][0]["responseType"] == "REFUSED_RECOMMENDED_CARE"
        report["scenarios"].append({"caseId": "chest-pain-ed", "disposition": "EMERGENCY_DEPARTMENT", "action": "DOCUMENT_PATIENT_REFUSAL", "recommendationPreserved": True, "safetyLocked": True, "passed": True})

        session, advisory, elapsed = analyze("llm-timeout")
        assert advisory["recommendation"]["recommendedDisposition"] == "MANUAL_ESCALATION"
        assert advisory["mode"] == "MANUAL"
        assert any("manual clinical review required" in alert.lower() for alert in advisory["systemAlerts"])
        assert advisory["evidence"], "Verified context should survive provider failure"
        report["scenarios"].append({"caseId": "llm-timeout", "disposition": "MANUAL_ESCALATION", "evidenceRetained": True, "passed": True})
        report["metrics"] = call("GET", "/api/metrics")
        result = json.dumps(report, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result + "\n")
        print(result)


if __name__ == "__main__":
    main()
