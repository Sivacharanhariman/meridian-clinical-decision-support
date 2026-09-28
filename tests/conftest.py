"""Acceptance fixtures use the HTTP surface and an isolated durable SQLite store."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@dataclass
class ApiHarness:
    app: Any
    client: TestClient
    database_path: Path
    headers: dict[str, str]

    def login(self, actor_id: str = "nurse-avery") -> dict[str, str]:
        result = self.client.post("/api/auth/demo", json={"actorId": actor_id})
        assert result.status_code == 200, result.text
        return {"Authorization": f"Bearer {result.json()['accessToken']}"}

    def create(self, case_id: str = "normal-adult", *, headers=None) -> dict:
        result = self.client.post(
            "/api/sessions", json={"caseId": case_id}, headers=headers or self.headers
        )
        assert result.status_code == 200, result.text
        return result.json()

    def request(self, session: dict, **changes) -> dict:
        request = {
            "sessionId": session["sessionId"],
            "turnId": f"turn-{uuid4().hex}",
            "baseStateVersion": session["state"]["currentStateVersion"],
            "patientId": session["patient"]["patientId"],
            "symptomDescription": session["originalTranscript"],
            "patientDemographics": session["patient"]["demographics"],
            "nurseNotes": session["nurseNotes"],
        }
        request.update(changes)
        return request

    def triage(self, session: dict, *, headers=None, **changes) -> dict:
        result = self.client.post(
            "/api/triage", json=self.request(session, **changes),
            headers=headers or self.headers,
        )
        assert result.status_code == 200, result.text
        return result.json()

    def get(self, session_id: str, *, headers=None) -> dict:
        result = self.client.get(
            f"/api/sessions/{session_id}", headers=headers or self.headers
        )
        assert result.status_code == 200, result.text
        return result.json()

    def action_request(self, response: dict, action_type: str, **changes) -> dict:
        request = {
            "actionId": f"action-{uuid4().hex}",
            "targetRecommendationId": response["recommendation"]["recommendationId"],
            "baseStateVersion": response["stateVersion"],
            "actionType": action_type,
            "rationale": "Synthetic nurse review for acceptance testing.",
        }
        request.update(changes)
        return request

    def action(self, response: dict, action_type: str, *, headers=None, **changes):
        return self.client.post(
            f"/api/sessions/{response['sessionId']}/actions",
            json=self.action_request(response, action_type, **changes),
            headers=headers or self.headers,
        )

    def audit(self, session_id: str) -> list[dict]:
        result = self.client.get(
            f"/api/sessions/{session_id}/audit", headers=self.headers
        )
        assert result.status_code == 200, result.text
        return result.json()["events"]


@pytest.fixture
def api(tmp_path):
    from backend.app import create_app
    from backend.config import Settings

    path = tmp_path / "acceptance.sqlite3"
    app = create_app(Settings(database_path=str(path), provider_mode="deterministic"))
    with TestClient(app) as client:
        harness = ApiHarness(app, client, path, {})
        harness.headers = harness.login()
        yield harness
