"""Observe the ASGI send boundary and read SQLite through a separate connection."""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient


class CommitObserver:
    def __init__(self, app, database_path, session_id):
        self.app = app
        self.database_path = database_path
        self.session_id = session_id
        self.observations = []

    async def __call__(self, scope, receive, send):
        success = False

        async def observed_send(message):
            nonlocal success
            if scope.get("path") == "/api/triage":
                if message["type"] == "http.response.start":
                    success = message["status"] == 200
                    if success:
                        with sqlite3.connect(self.database_path) as reader:
                            version, response_id = reader.execute(
                                "SELECT version,latest_response_id FROM sessions WHERE session_id=?",
                                (self.session_id,),
                            ).fetchone()
                            assert version == 1 and response_id, "200 publication began before a durable commit."
                        self.observations.append("durable-before-status")
                elif message["type"] == "http.response.body" and success:
                    assert not message.get("more_body", False), "Clinical payloads must not stream."
                    published = json.loads(message["body"])
                    with sqlite3.connect(self.database_path) as reader:
                        row = reader.execute("SELECT payload FROM responses WHERE response_id=?", (published["responseId"],)).fetchone()
                        assert row is not None
                        assert json.loads(row[0]) == published
                    self.observations.append("durable-identical-before-body")
            await send(message)

        await self.app(scope, receive, observed_send)


def test_commit_precedes_first_success_byte_and_matches_published_payload(api):
    session = api.create()
    observer = CommitObserver(api.app, api.database_path, session["sessionId"])
    with TestClient(observer) as client:
        result = client.post("/api/triage", json=api.request(session), headers=api.headers)
    assert result.status_code == 200, result.text
    assert observer.observations == ["durable-before-status", "durable-identical-before-body"]


def test_failed_database_write_never_publishes_or_leaves_partial_clinical_state(api):
    session = api.create()
    with sqlite3.connect(api.database_path) as conn:
        conn.execute("CREATE TRIGGER simulate_disk_failure BEFORE INSERT ON responses BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END")
    with TestClient(api.app, raise_server_exceptions=False) as client:
        result = client.post("/api/triage", json=api.request(session), headers=api.headers)
    assert result.status_code in {500, 503}
    assert "recommendedDisposition" not in result.text
    view = api.get(session["sessionId"])
    assert view["state"]["currentStateVersion"] == 0
    assert view["latestResponse"] is None
    assert view["recommendations"] == []
    with sqlite3.connect(api.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM responses WHERE session_id=?", (session["sessionId"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM recommendations WHERE session_id=?", (session["sessionId"],)).fetchone()[0] == 0


@pytest.mark.parametrize("table", ["recommendations", "responses", "actions", "patient_responses", "audit"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_clinical_provenance_is_append_only_in_durable_storage(api, table, operation):
    response = api.triage(api.create("chest-pain-ed"))
    action = api.action(response, "DOCUMENT_PATIENT_REFUSAL", statedPreference="Patient elects to remain home in this simulation.")
    assert action.status_code == 200
    with sqlite3.connect(api.database_path) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
        statement = f"UPDATE {table} SET payload='{{}}'" if operation == "UPDATE" else f"DELETE FROM {table}"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)
    assert api.get(response["sessionId"])["recommendations"] == [response["recommendation"]]
