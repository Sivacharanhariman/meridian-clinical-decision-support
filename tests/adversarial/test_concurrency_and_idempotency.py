"""Threaded races use barriers/events, never sleeps or timing-only assertions."""
from __future__ import annotations

import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock


def _post(api, request):
    return api.client.post("/api/triage", json=request, headers=api.headers)


def test_two_turns_from_same_base_have_exactly_one_cas_winner(api, monkeypatch):
    session = api.create("stale-concurrent")
    first = api.request(session, turnId="race-first")
    second = api.request(session, turnId="race-second")
    barrier = Barrier(2)
    original = api.app.state.provider.synthesize
    reached = []
    lock = Lock()

    def concurrent_synthesis(context):
        with lock:
            reached.append(context.request.turnId)
        barrier.wait(timeout=4)
        return original(context)

    monkeypatch.setattr(api.app.state.provider, "synthesize", concurrent_synthesis)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_post, api, request) for request in [first, second]]
        results = [future.result(timeout=10) for future in futures]
    assert set(reached) == {"race-first", "race-second"}, "Expensive work must run outside a database lock."
    assert sorted(result.status_code for result in results) == [200, 409]
    winning = next(result.json() for result in results if result.status_code == 200)
    stale = next(result.json() for result in results if result.status_code == 409)
    assert "recommendation" not in stale
    view = api.get(session["sessionId"])
    assert view["state"]["currentStateVersion"] == 1
    assert view["latestResponse"] == winning
    assert view["recommendations"] == [winning["recommendation"]]
    with sqlite3.connect(api.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM responses WHERE session_id=?", (session["sessionId"],)).fetchone()[0] == 1


def test_delayed_stale_turn_never_persists_or_publishes_a_clinical_payload(api, monkeypatch):
    session = api.create("stale-concurrent")
    delayed = api.request(session, turnId="delayed-turn")
    fresh = api.request(session, turnId="fresh-turn", symptomDescription="I have chest pain right now.")
    entered, release = Event(), Event()
    original = api.app.state.provider.synthesize

    def ordered(context):
        if context.request.turnId == "delayed-turn":
            entered.set()
            assert release.wait(timeout=5)
        return original(context)

    monkeypatch.setattr(api.app.state.provider, "synthesize", ordered)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(_post, api, delayed)
        try:
            assert entered.wait(timeout=3)
            newest = _post(api, fresh)
            assert newest.status_code == 200, newest.text
        finally:
            release.set()
        stale = pending.result(timeout=8)
    assert stale.status_code == 409
    assert "recommendation" not in stale.json()
    view = api.get(session["sessionId"])
    assert view["latestResponse"] == newest.json()
    assert len(view["recommendations"]) == 1


def test_exact_retry_returns_same_committed_payload_without_reexecution(api, monkeypatch):
    session = api.create()
    request = api.request(session, turnId="retry-turn")
    calls = []
    original = api.app.state.provider.synthesize

    def count(context):
        calls.append(context.request.turnId)
        return original(context)

    monkeypatch.setattr(api.app.state.provider, "synthesize", count)
    first = _post(api, request)
    replay = _post(api, dict(reversed(list(request.items()))))
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert calls == ["retry-turn"]
    assert len(api.get(session["sessionId"])["recommendations"]) == 1


def test_concurrent_exact_retry_reserves_work_once(api, monkeypatch):
    session = api.create()
    request = api.request(session, turnId="simultaneous-retry")
    entered, duplicate_reserved, release = Event(), Event(), Event()
    calls = []
    original = api.app.state.provider.synthesize
    reserve = api.app.state.repository.reserve_turn

    def blocking(context):
        calls.append(context.request.turnId)
        entered.set()
        assert release.wait(timeout=5)
        return original(context)

    def observe_reservation(*args, **kwargs):
        result = reserve(*args, **kwargs)
        if result[0] == "IN_PROGRESS":
            duplicate_reserved.set()
        return result

    monkeypatch.setattr(api.app.state.provider, "synthesize", blocking)
    monkeypatch.setattr(api.app.state.repository, "reserve_turn", observe_reservation)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_post, api, request)
        try:
            assert entered.wait(timeout=3)
            second = pool.submit(_post, api, copy.deepcopy(request))
            assert duplicate_reserved.wait(timeout=3), "Retry must see the existing in-flight identity."
        finally:
            release.set()
        a, b = first.result(timeout=8), second.result(timeout=8)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert calls == ["simultaneous-retry"]
    assert api.get(session["sessionId"])["state"]["currentStateVersion"] == 1


def test_idempotency_key_with_different_content_is_rejected(api, monkeypatch):
    session = api.create()
    request = api.request(session, turnId="reused-key")
    result = _post(api, request)
    assert result.status_code == 200

    def should_not_execute(_context):
        raise AssertionError("An idempotency conflict must not invoke synthesis.")

    monkeypatch.setattr(api.app.state.provider, "synthesize", should_not_execute)
    conflict = _post(api, {**request, "symptomDescription": "I have chest pain right now."})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_REUSE"
    assert api.get(session["sessionId"])["latestResponse"] == result.json()


def test_stale_base_version_fails_before_new_clinical_work(api, monkeypatch):
    session = api.create()
    first = api.triage(session)
    calls = []
    original = api.app.state.provider.synthesize

    def observe(context):
        calls.append(context.request.turnId)
        return original(context)

    monkeypatch.setattr(api.app.state.provider, "synthesize", observe)
    stale = _post(api, api.request(session))
    assert stale.status_code == 409
    assert calls == []
    assert api.get(session["sessionId"])["latestResponse"] == first


def test_assignment_revoked_during_synthesis_is_rechecked_at_commit(api, monkeypatch):
    session = api.create()
    delegated = api.login("nurse-delegated")
    original = api.app.state.provider.synthesize

    def revoke_before_commit(context):
        result = original(context)
        api.app.state.auth.revoke_assignment("nurse-delegated", session["sessionId"])
        return result

    monkeypatch.setattr(api.app.state.provider, "synthesize", revoke_before_commit)
    denied = api.client.post("/api/triage", json=api.request(session), headers=delegated)
    assert denied.status_code in {403, 404}
    view = api.get(session["sessionId"])
    assert view["state"]["currentStateVersion"] == 0
    assert view["latestResponse"] is None
    assert view["recommendations"] == []
