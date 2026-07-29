# Acceptance evidence ledger

This ledger maps the assignment and architecture requirements to durable proof.
It is updated by the PR that introduces each capability.

| Requirement | Planned PR | Evidence | Status |
|---|---:|---|---|
| Reproducible repository and CI | 1 | `Makefile`, GitHub Actions, lockfiles, Compose validation | Implemented |
| Credential-free development defaults | 1 | `.env.example`, typed settings tests | Implemented |
| Category-generic procurement model | 2 | Domain model and invariant tests | Planned |
| More than 20 real tool calls | 11 | End-to-end run event journal | Planned |
| Genuine nested subagent work | 7 | Child-workflow integration tests and run tree | Planned |
| Pause, resume, redirect, queued instruction | 7, 9 | Workflow and operator-journey tests | Planned |
| Selective reuse after revision | 2, 7 | Invalidation unit and integration tests | Planned |
| Claim-level evidence and conflicts | 5 | Provenance and conflict tests | Planned |
| Exact editable approval | 8, 9 | Digest, permit, and proposal diff tests | Planned |
| Durable close/reopen and SSE replay | 4, 7, 9 | Replay and browser journey tests | Planned |
| Failure recovery | 7, 12 | Worker/browser termination test evidence | Planned |
| Downloadable artifacts | 6, 9 | Workbook, report, RFQ, and receipt tests | Planned |
| Controlled real email | Final credential gate | Provider receipt and audit record | Blocked by credentials |
| Multiple procurement categories | 11 | Genericity suite | Planned |
| Operator-perspective demonstration | 12 | Demo checklist and recorded trace | Planned |
