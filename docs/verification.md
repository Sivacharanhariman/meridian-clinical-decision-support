# Delivered build verification

Verified on 2026-09-28 with Python 3.12.14, Node.js 24.19.0 and the checked-in
Python/npm dependency locks. All data, policy and failure injections are synthetic.

| Gate | Result |
|---|---|
| Backend unit/integration/adversarial tests | **153 passed**, zero failures or errors |
| Frontend Vitest / React Testing Library | **23 passed**, zero failures |
| Current backend OpenAPI versus frozen artifact | Exact match |
| Generated TypeScript versus current OpenAPI | Exact match |
| TypeScript and Next.js production compilation | Passed |
| Python dependency consistency | No broken requirements |
| Actual API HTTP rehearsal | Three paths passed: accepted clinician advisory, ED refusal, timeout/manual |
| Chromium rehearsal against production Next.js and FastAPI | 7 checks passed; 0 page errors |
| Responsive layout at 390 px | No horizontal overflow |

## Reproduce

```bash
.venv/bin/python -m pytest -q --junitxml=docs/backend-tests.xml
npm --prefix frontend test
.venv/bin/python scripts/export_openapi.py --check
npm --prefix frontend run generate:check
npm --prefix frontend run build
npm --prefix frontend exec -- playwright install chromium
.venv/bin/python scripts/run_rehearsal.py --browser --production
```

The browser was launched from a local Chromium executable in the verification
environment. On a regular workstation, the Playwright install command supplies it.
The optional `PLAYWRIGHT_CHROMIUM_EXECUTABLE` variable selects an existing binary.

## Observed local timings

The production-mode rehearsal recorded 8 deterministic requests and
4 safe-render measurements. Request P95 was
**15.69 ms**; safe-render P95 was
**127.29 ms**. These are small local smoke-test
samples, not a statistically established latency guarantee or live-LLM benchmark.
The target remains 3–4 seconds P95. Simulated timeouts intentionally exercise manual
mode without making an external provider call or waiting for a real outage.

Per-stage P50/P95/P99, provider 429/deadline/manual-mode rates, and safe-render
samples are retained in `browser-rehearsal.json`. The immutable clinical response
captures transaction preparation time; operational metrics measure the completed
disk commit separately to avoid changing a committed response on replay.

## UI checks

- No clinical recommendation before analysis.
- Demo A: evidence, clinician advisory, nurse acceptance, audit; no inferred patient consent.
- Demo B: ED safety lock and refusal persist as separate states; emergency styling preserved.
- Outage: explicit manual mode, acceptance disabled, escalation available.
- Complete home positive control; edits disable decisions and uncertain new input requires manual review.
- Authorized clinician override records a separate human decision without changing advisory.
- 390px responsive layout: no horizontal overflow.

## Scope and unresolved production work

The live OpenAI adapter was not called with real credentials. Its message-channel,
strict-schema, retry and missing-credential boundaries are unit tested; hosted
model behavior and performance still require qualification. No claim of clinical
validation, medical-device readiness or real-patient safety is made.

Security tests cover prototype object authorization, revocation, CAS/idempotency,
source integrity, grounding and immutable provenance. They do not substitute for
an independent security review or a clinical safety case. See the hardening roadmap.

Machine-readable results: `backend-tests.xml`, `frontend-tests.json`,
`api-rehearsal.json`, `browser-rehearsal.json`. Screenshots are under `screenshots/`.
