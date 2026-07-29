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
| Genuine nested subagent work | 7 | Child-workflow integration tests and run tree | Planned |
| Pause, resume, redirect, queued instruction | 7, 9 | Workflow and operator-journey tests | Planned |
| Selective reuse after revision | 2, 7 | Direct and transitive invalidation unit tests; runtime integration pending | In progress |
| Claim-level evidence and conflicts | 5, 6 | Immutable snapshots, exact-span hashes, taint, freshness, conflicts, isolation, acceptable-evidence enforcement, and adversarial boundary tests implemented; live adapters pending | In progress |
| Exact editable approval | 8, 9 | Canonical payload, version diff, single-use permit, commit-time authorization, and outcome tests implemented; UI pending | In progress |
| Durable close/reopen and SSE replay | 4, 7, 9 | PostgreSQL journal, projections, outbox, Last-Event-ID replay, and application-lifespan tests implemented; workflow/UI journeys pending | In progress |
| Failure recovery | 7, 12 | Worker/browser termination test evidence | Planned |
| Downloadable artifacts | 3, 6, 9 | Deterministic requirements Markdown, comparison XLSX, recommendation Markdown, and RFQ ZIP generators implemented with stable hashes and spreadsheet-injection protection; workbench integration pending | In progress |
| Deterministic candidate evaluation | 6 | Unit/currency normalization, conflict-aware evidence resolution, mandatory gates, weighted scoring, ranking, and 120-test real-PostgreSQL acceptance suite | Implemented |
| Controlled real email | Final credential gate | Provider receipt and audit record | Blocked by credentials |
| Multiple procurement categories | 11 | Genericity suite | Planned |
| Operator-perspective demonstration | 12 | Demo checklist and recorded trace | Planned |
