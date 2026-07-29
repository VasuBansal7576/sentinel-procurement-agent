# Acceptance evidence ledger

This ledger maps the assignment and architecture requirements to durable proof.
It is updated by the PR that introduces each capability.

| Requirement | Planned PR | Evidence | Status |
|---|---:|---|---|
| Reproducible repository and CI | 1 | `Makefile`, GitHub Actions, lockfiles, Compose validation | Implemented |
| Credential-free development defaults | 1 | `.env.example`, typed settings tests | Implemented |
| Category-generic procurement model | 2 | Immutable contracts and 11 focused domain tests | Implemented |
| Minimal end-to-end delivery path | 3 | Typed intake → run → events/SSE → workbench → artifact download | Implemented |
| More than 20 real tool calls | 11 | End-to-end run event journal | Planned |
| Genuine nested subagent work | 7 | Real Temporal parent/child histories, isolated results, worker-restart recovery, replay tests, and run-tree UI implemented; final activity wiring pending | In progress |
| Pause, resume, redirect, queued instruction | 7, 9 | Durable acknowledged Temporal updates, responsive operator controls, queue/redirect journeys, and Computer Use verification implemented; HTTP gateway wiring pending | In progress |
| Selective reuse after revision | 2, 7 | Direct/transitive invalidation and Temporal redirect integration preserve unaffected completed products under replay | Implemented |
| Claim-level evidence and conflicts | 5, 6 | Immutable snapshots, exact-span hashes, taint, freshness, conflicts, isolation, acceptable-evidence enforcement, and adversarial boundary tests implemented; live adapters pending | In progress |
| Exact editable approval | 8, 9 | Canonical payload, semantic version diff/edit UI, policy-bound single-use permit, commit-time authorization, durable intent/outcome transaction, concurrent-consumption, restart, and Computer Use approval tests implemented; real UI endpoint wiring pending | In progress |
| Durable close/reopen and SSE replay | 4, 7, 9 | PostgreSQL journal, projections, outbox, Last-Event-ID replay, application-lifespan tests, and workbench restoration journey implemented; workflow-to-UI wiring pending | In progress |
| Failure recovery | 7, 12 | Temporal worker restart, cooperative child cancellation, activity retry, and parent/child history replay implemented; browser termination integration pending | In progress |
| Downloadable artifacts | 3, 6, 9 | Deterministic requirements Markdown, comparison XLSX, recommendation Markdown, and RFQ ZIP generators implemented with stable hashes and spreadsheet-injection protection; artifact rail implemented, real projection wiring pending | In progress |
| Deterministic candidate evaluation | 6 | Unit/currency normalization, conflict-aware evidence resolution, mandatory gates, weighted scoring, ranking, and 120-test real-PostgreSQL acceptance suite | Implemented |
| Controlled real email | 10, final credential gate | Credential-isolated provider boundary, Resend adapter, controlled-recipient recheck, PostgreSQL CAS outcomes, concurrent duplicate suppression, reconciliation, and sanitized audit tests implemented; one real provider receipt remains blocked by credentials and explicit approval | In progress |
| Multiple procurement categories | 11 | Genericity suite | Planned |
| Operator-perspective demonstration | 12 | Demo checklist and recorded trace | Planned |
