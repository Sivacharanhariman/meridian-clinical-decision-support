# Frozen contract v1

`backend/domain/contracts.py` is the sole schema authority; FastAPI emits
`contracts/openapi.json`; openapi-typescript emits `frontend/generated/api.ts`.
Feature workstreams must report needed changes to the principal integrator.
No hand-authored frontend DTOs and no permissive defaults for clinical fields.

## API surface

GET /api/health; GET /api/demo; POST /api/auth/demo; GET/POST /api/sessions;
GET /api/sessions/{sessionId}; POST /api/triage;
POST /api/sessions/{sessionId}/actions; GET /api/sessions/{sessionId}/audit;
GET /api/metrics; POST /api/metrics/render.

Demo login takes actorId; roles and tenant are server fixture identities. Tokens
carry stable identity only. Resource and revocable delegation checks are fresh.
No client-selected fault flags on triage: faults belong to server demo fixtures.

Every triage commit and nurse-action commit increments the session version.
A response's version always denotes its immutable triage commit. Nurse actions
leave all previous responses and recommendations unchanged. Actions target the
current recommendation and compare against the current *session* version.
UI keeps the current session version separately from the clinical response gate.

Clinical response equal-version replay requires matching turn and canonical full
response content. Lower versions are dropped. Responses are delivered only after
durable commit. Action IDs also have digest-based idempotency.

Rationale is a closed catalog of exact server-constructed claims. Synthesis may
select only claims from that turn's catalog; validators check exact text and
references, not just the existence of IDs. Unknown facts may be shown as missing
information but cannot substantiate a positive or negative clinical assertion.

## Internal workstream boundaries

Retrieval exposes `Retriever.retrieve(request, scenario_mode="normal") ->
RetrievalManifest` in `backend/rag/retriever.py`. Registry in a separately loaded,
trusted fixture; vector records are untrusted. Manifest stateVersion is the
candidate commit version (baseStateVersion + 1). All violations are logged by
the backend from manifest.integrityViolations. Registry verification runs after
discovery, and before aliases are assigned. Retrieval modes: normal,
zero_evidence, injection, tampered. Constructor and helper tests can add explicit
dependency injection as long as that call shape remains supported.

Fixture file `backend/fixtures/cases.json` has top-level `actors` and `cases`.
Each case has catalog fields plus patient, transcript, nurseNotes, scenarioMode.
Default IDs: normal-adult, chest-pain-ed, home-complete. Actors: nurse-avery,
clinician-morgan, nurse-cross-tenant, nurse-delegated. All are synthetic.

Backend must expose `create_app(settings=None)` and Settings; tests use a unique
temporary SQLite database per test. App state should expose service, repository,
auth, retriever, provider for explicit test injection. Tests may use TestClient
against the actual API. Coordinate method naming, do not weaken gates.
