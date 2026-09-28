# Acceptance and adversarial test matrix

These tests exercise synthetic demonstration rules. Passing them does not establish
clinical validity or suitability for patient care. The expected dispositions below
come from the checked-in demonstration policy, never from test-generated clinical rules.

Run the backend suite from the repository root:

```bash
.venv/bin/python -m pytest -q
```

The frontend suite separately tests the committed response version gate. The
repository README records the exact frontend command and final verification results.

## Absolute release blockers

| Required invariant | Acceptance coverage |
| --- | --- |
| Confirmed safety rule cannot become low-acuity automation | `tests/adversarial/test_safety_and_grounding.py::test_all_seven_confirmed_red_flags_lock_automation`, `test_well_formed_synthesis_must_pass_semantic_grounding[lower_acuity_disposition]` |
| Uncertainty cannot become home monitoring | `test_uncertainty_cannot_silently_clear_home_gate`, `test_missing_cardiac_history_is_unknown_not_absent`; complete curated home assessment is a positive control |
| Unsupported population escalates | `test_unsupported_population_is_manual_even_with_red_flag`; pediatric and pregnant cases |
| Zero eligible evidence forbids home monitoring | `test_no_eligible_evidence_fails_closed[zero-evidence]` |
| Malformed model output fails closed | `test_malformed_required_model_fields_are_never_repaired`; eight structural attacks, including empty evidence refs |
| Hallucinated evidence refs fail validation | `test_well_formed_synthesis_must_pass_semantic_grounding[hallucinated_alias]`, catalog hallucinated citation case |
| Invented patient facts fail validation | Semantic attacks use both nonexistent IDs and existing UNKNOWN fact IDs; altered text with otherwise valid refs is also rejected |
| Tampered guidelines are excluded | `test_no_eligible_evidence_fails_closed[tampered-evidence]`; independent registry unit tests verify trust checks |
| Stale turn cannot persist | `tests/adversarial/test_concurrency_and_idempotency.py::test_two_turns_from_same_base_have_exactly_one_cas_winner`, `test_delayed_stale_turn_never_persists_or_publishes_a_clinical_payload` |
| Stale turn cannot render | Frontend committed-response gate tests; backend stale responses contain no clinical payload |
| Retry cannot duplicate execution | Sequential and concurrent exact retries assert one provider execution and one persisted recommendation |
| Reused idempotency key with different content is rejected | `test_idempotency_key_with_different_content_is_rejected`; action identity reuse is also checked |
| Cross-tenant modifications fail | `tests/adversarial/test_authorization.py` covers triage and all four action types; reads/listing/audit hide foreign sessions |
| Insufficient privilege fails | Standard nurse override rejected and audit denial recorded |
| Revocation defeats stale cached/token ALLOW | Obtain token and allowed permissions, revoke live delegation, then attempt override with same token |
| Patient refusal does not rewrite recommendation | `tests/integration/test_decision_provenance.py::test_patient_refusal_preserves_ed_recommendation_and_records_separate_outcome` |
| Commit before publish | `tests/integration/test_durable_publish.py` reads SQLite through a separate connection at the first ASGI success send and compares immutable stored payload with published bytes |

## Required synthetic fixtures

`tests/integration/test_fixture_catalog.py` requires every case to exist and creates
a clean synthetic session for each. The tests below exercise the actual behavior.

| # | Required scenario | Catalog case | Behavioral acceptance |
| --- | --- | --- | --- |
| 1 | Normal ambiguous adult symptoms | `normal-adult` | Clinician review, missing facts, evidence, accept action, audit |
| 2 | Confirmed red flag | `stroke-red-flag` | All seven policy categories parameterized through real triage API |
| 3 | No chest pain | `negated-chest-pain` | NEGATED event; no emergency from keyword alone |
| 4 | Historical symptom | `historical-symptom` | HISTORICAL event; no current patient emergency |
| 5 | Family history only | `family-history` | FAMILY_OTHER event; no patient misattribution |
| 6 | Pediatric patient | `pediatric` | Manual even if red-flag transcript is supplied |
| 7 | Pregnant patient | `pregnant` | Manual; client demographic substitution also challenged |
| 8 | Zero eligible guidance | `zero-evidence` | Empty manifest and UNGROUNDED/manual |
| 9 | Injected guideline | `prompt-injection` | Excluded from evidence, violation retained and audited |
| 10 | Tampered vector content | `tampered-evidence` | Hash failure excludes source and forbids home |
| 11 | Malformed synthesis | `malformed-model` | Required fields cannot be silently repaired |
| 12 | Hallucinated citation | `hallucinated-citation` | Out-of-manifest alias rejected |
| 13 | Unsupported fact assertion | `invented-fact` | Unknown/nonexistent facts and changed claim text rejected |
| 14 | Stale concurrent response | `stale-concurrent` | Barrier-coordinated CAS race; only one durable winner |
| 15 | Cross-tenant access | `cross-tenant` | Read, listing, triage, all actions, audit denied or scoped |
| 16 | Insufficient override privilege | `override-privilege` | Standard nurse denied; authorized clinician action separate |
| 17 | Revoked delegation | `revoked-delegation` | Same old token cannot prove current authority |
| 18 | Patient refusal of ED care | `chest-pain-ed` | ED recommendation immutable; refusal/action/outcome separate |
| 19 | LLM timeout | `llm-timeout` | Manual alert; evidence/context retained; deadline metric |
| 20 | Provider 429 | `provider-429` | Manual alert, no weaker fallback, rate-limit metric |

## Additional transactional and security coverage

- Nurse acceptance cannot invent patient consent, and later nurse/clinician
  actions cannot erase a recorded patient refusal.
- A new explicit patient subject cannot inherit another clause's negation or
  family subject. Uninterpreted vitals and extra unsupported notes cannot clear
  the exact home gate. Refresh retains the input that produced the advisory.
- The primary provider adapter keeps evidence in the data channel, requests a
  strict schema, disables SDK retries, and fails when credentials are missing.

- Same-tenant unassigned users cannot read, triage, or act on sessions.
- Assignment revoked during synthesis is rechecked before the commit.
- Unavailable authority denies override while independent escalation remains usable.
- Client-supplied tenant/privilege properties and swapped patient identity are rejected.
- Append-only database triggers reject UPDATE and DELETE for recommendations,
  responses, actions, patient responses, and operational audit records.
- Injected database failure rolls back session version and clinical inserts;
  the HTTP error contains no published disposition.
- A successor recommendation retains its predecessor byte-for-byte, and actions
  cannot target a superseded recommendation even with a fresh session version.
- Action retries are idempotent and a changed request under the same key fails.
- Audit links include facts, manifest/hash provenance, model/prompt identifiers,
  actor/action/outcome and correlation, without the raw transcript or patient name.
- Stage percentiles, provider/manual failure rates, and safe-render measurements
  are exposed. The 4-second P95 value is explicitly a target, not a test guarantee.

## Test design

Each test has a temporary SQLite database and calls the real FastAPI routes.
Provider faults are injected at the provider abstraction; semantic attacks otherwise
use valid schema shapes. Thread races use barriers/events and bounded waits rather
than sleeps. Persistence observations use independent SQLite connections. No
release-blocking assertion is weakened to accommodate implementation behavior.
