# Acceptance evidence ledger

This ledger maps the assignment and architecture requirements to durable proof.
It is updated by the PR that introduces each capability.

| Requirement | Planned PR | Evidence | Status |
|---|---:|---|---|
| Reproducible repository and CI | 1 | `Makefile`, GitHub Actions, lockfiles, Compose validation | Implemented |
| Credential-free development defaults | 1 | `.env.example`, typed settings tests | Implemented |
| Category-generic procurement model | 2 | Immutable contracts and 11 focused domain tests | Implemented |
| Minimal end-to-end delivery path | 3 | Typed intake → run → events/SSE → workbench → artifact download | Implemented |
| More than 20 real tool calls | 11 | Representative parent/child run records 60 tool lifecycle events | Implemented |
| Genuine nested subagent work | 7, 11 | Real Temporal parent/child histories, production activity wiring, isolated results, worker-restart recovery, replay tests, and run-tree UI | Implemented |
| Pause, resume, redirect, queued instruction | 7, 9, 11 | Durable acknowledged Temporal updates, real HTTP/SSE gateway, responsive operator controls, and queue/redirect journeys | Implemented |
| Selective reuse after revision | 2, 7 | Direct/transitive invalidation and Temporal redirect integration preserve unaffected completed products under replay | Implemented |
| Claim-level evidence and conflicts | 5, 6 | Immutable snapshots, exact-span hashes, taint, freshness, conflicts, isolation, acceptable-evidence enforcement, and adversarial boundary tests implemented; live adapters pending | In progress |
| Exact editable approval | 8, 9, 11 | Canonical payload, semantic version diff/edit UI, real proposal endpoints, policy-bound single-use permit, commit-time authorization, durable intent/outcome transaction, concurrent-consumption, restart, and Computer Use approval tests | Implemented |
| Durable close/reopen and SSE replay | 4, 7, 9, 11 | PostgreSQL journal, projections, outbox, Last-Event-ID replay, real API-first gateway, application-lifespan tests, and workbench restoration journey | Implemented |
| Failure recovery | 7, 11, 12 | Temporal worker restart, cooperative child cancellation, activity retry, durable blocked/recoverable state, targeted retry, and replay implemented; browser termination integration pending | In progress |
| Downloadable artifacts | 3, 6, 9, 11 | Deterministic requirements Markdown, comparison XLSX, recommendation Markdown, and RFQ ZIP with run-scoped opaque downloads and real operator projections | Implemented |
| Deterministic candidate evaluation | 6 | Unit/currency normalization, conflict-aware evidence resolution, mandatory gates, weighted scoring, ranking, and 120-test real-PostgreSQL acceptance suite | Implemented |
| Controlled real email | 10, final credential gate | Credential-isolated provider boundary, Resend adapter, controlled-recipient recheck, PostgreSQL CAS outcomes, concurrent duplicate suppression, reconciliation, and sanitized audit tests implemented; one real provider receipt remains blocked by credentials and explicit approval | In progress |
| Multiple procurement categories | 11 | Industrial equipment, recurring PPE, and services use the same typed pipeline | Implemented |
| Operator-perspective demonstration | 12 | Demo checklist and recorded trace | Planned |
