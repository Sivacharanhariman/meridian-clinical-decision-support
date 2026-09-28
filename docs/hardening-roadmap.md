# Production-hardening roadmap

This code is not ready for real patients. The following are separate projects,
not capabilities implied by the demonstration.

1. **Clinical governance and intended use.** Define a clinically validated scope,
   approve licensed guideline content, evaluate decision support with qualified
   clinicians, establish change control and assess applicable regulatory duties.
   Replace exact synthetic language rules only after their replacements have a
   measured safety case for negation, time, subject, ambiguity and missingness.
2. **Identity and authorization.** Remove demo account selection; integrate OIDC,
   short-lived tokens and authoritative care-team/delegation services. Test
   revocation races, relationship changes and service unavailability at execution.
   Keep sensitive writes deny-by-default when authority cannot be established.
3. **Durable distributed state.** Migrate to PostgreSQL with tenant constraints
   and RLS, transactional audit/outbox publication, durable idempotency leases,
   crash recovery, backups, migration tooling and disaster recovery drills.
4. **Evidence supply chain.** Sign and version registry releases, restrict
   ingestion permissions, review suspicious content, rotate trust roots, verify
   retrieval quality and monitor expired or revoked guidance. Do not let the
   discovery service declare evidence clinically eligible.
5. **Model qualification.** Pin and validate a provider/model configuration,
   evaluate grounded claims and abstention under adversarial inputs, formalize
   deadline/retry budgets and monitor regression. A model must not introduce
   clinical rules or gain authority from retrieved text.
6. **Security and privacy.** Complete threat modeling, independent penetration
   testing, encryption and key management, minimum-necessary data access, trace
   retention enforcement and verified audit integrity. Never use the synthetic
   demo login or local plaintext store for real patient data.
7. **Clinical usability and operations.** Conduct nurse usability and
   accessibility studies; validate refusal, escalation and override workflows.
   Run realistic load/failure tests with measured P95 and capacity budgets,
   incident playbooks, supervised rollout and rollback criteria.

The 3–4 second P95 in the specification is a target. Local deterministic-mode
measurements do not establish production provider latency or clinical quality.
