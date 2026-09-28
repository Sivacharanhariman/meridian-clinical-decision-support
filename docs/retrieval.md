# Independent retrieval boundary

The eleven sources are **fake demonstration fixtures**. Their contents and
approval labels are not validated clinical guidance and must never be used for
real patient care. The source corpus mirrors only the repository's synthetic
`policy.json` scenarios: mild headache, a complete home fixture, current chest
pain, seven safety categories, and manual handling of uncertainty.

`Retriever.retrieve(request, scenario_mode="normal")` returns the frozen
`RetrievalManifest` contract. Its `stateVersion` is `baseStateVersion + 1`.
The constructor accepts independent `registry_path` and `store_path`, an
optional fixed date/date callable, and a `top_k` bound. No network service,
embedding provider, or clinical protocol source is required.

## Storage and authority

| File | Role | Trust |
| --- | --- | --- |
| `backend/fixtures/guidelines.json` | Clearly labeled synthetic source text | Ingestion input; does not establish eligibility |
| `backend/fixtures/vector_store.json` | Text, source-hash claims, vectors, and discovery metadata | Untrusted |
| `backend/fixtures/registry.json` | Approved identity, exact text hash, population, age range, and dates | Independent trusted fixture |

Ingestion never creates or updates registry approval. A production replacement
would require an authenticated, separately controlled approval process; this
prototype demonstrates the software boundary only. Editing both registry and
index deliberately changes the trust authority and is not an untrusted-index
attack. The deterministic policy and exact claim validator remain separate.

## Pipeline

1. Ingestion validates a strict internal source schema. Instruction-like
   payloads, duplicate identities, and invalid fields go to quarantine. The
   persisted quarantine contains codes and content hashes, not raw payloads.
2. A SHA-256 token hashing algorithm embeds words and bigrams into 384 signed
   dimensions. Scores use cosine similarity. There is no Python salted hash,
   stochastic model, or external embedding request.
3. Retrieval uses untrusted metadata for discovery filtering and ranks positive
   matches deterministically. Metadata may reduce discovery; it never certifies
   approval. Similarity is approximate and never establishes clinical facts,
   context, safety, or disposition.
4. After discovery, the independently loaded registry must match the complete
   chunk identity: chunk ID, guideline ID, guideline version, and chunk index.
   The exact UTF-8 text hash is recomputed and compared against both the index
   claim and registry hash. Stored vectors are also compared with a fresh
   embedding of the text. Registry and candidate metadata must agree.
5. Eligibility is independently evaluated from the registry: approved status,
   adult population, age within the registry interval, pregnancy explicitly
   false, effective date reached, and expiry date not passed. Date endpoints
   are inclusive. Unknown pregnancy is ineligible, even with `ANY` applicability.
   Pediatric and pregnant populations are outside this demonstration.
6. Suspicious instruction text is checked again. Invalid candidates are
   quarantined before aliases exist. Only the surviving returned subset gets
   contiguous `Ref-1`, `Ref-2`, … aliases. These are local to the request's
   manifest and carry no authority in any other turn.

The registry and index are read separately on every call, so a retired approval
takes effect on the next request. A canonical digest binds the manifest ID to
the complete request, scenario mode, verified evidence, and integrity codes.
Identical inputs and artifacts yield identical manifests, regardless of vector
file ordering. No previous manifest or candidate can authorize new evidence.

## Quarantine and faults

Quarantine is exclusion from the evidence manifest, with safe diagnostic codes
in `integrityViolations`. The backend persists these codes in its audit events;
the retriever has no independent mutable audit database or clinical side effects.
Malformed/missing stores and ambiguous/missing trusted registries fail closed.

| Internal fixture mode | Behavior |
| --- | --- |
| `normal` | Discover and independently validate sources |
| `zero_evidence` | Return an empty evidence manifest |
| `injection` | Isolate one returned candidate, append a simulated instruction, and quarantine it |
| `tampered` | Isolate one returned candidate, change source text, and reject its hashes |
| Other synthesis fault modes | Perform ordinary retrieval; synthesis handles its own fault |

The fault modes leave no positive evidence that could authorize home monitoring.
These switches are internal server fixtures, not user-selectable triage fields.
Normal retrieval can still return a healthy subset alongside integrity codes;
the backend requires the exact applicable source and applies its policy gates.

The injection detector is intentionally limited to transparent heuristics:
role delimiters, instruction overrides, forced output fields, and requests for
secrets. Unicode compatibility normalization and format-character removal catch
simple obfuscation. It is not a universal injection detector. Exact registry
hashes and the downstream closed claim catalogue supply independent defenses.

## Rebuild and verification

To rebuild **only discovery data**, run from the repository root:

```python
from backend.rag.ingestion import ingest_file
ingest_file("backend/fixtures/guidelines.json", "backend/fixtures/vector_store.json")
```

An edit to source text will fail independent registry verification until a
separate trusted approval update is deliberately made. Never automatically copy
hashes or eligibility from the vector index into the approval registry.

`tests/unit/test_retrieval.py` checks deterministic binding, all synthetic policy
phrase coverage, index-order independence, every identity component, forged
metadata, approval/date/age/population boundaries, unknown pregnancy, source
hash recomputation attacks, altered vectors, strict candidate schemas,
ingestion/runtime quarantine, duplicates, missing artifacts, per-call approval
refresh, contiguous aliases, and fault modes with no eligible evidence.
