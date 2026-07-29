# Implementation PR plan

| PR | Capability | Depends on | Merge gate |
|---|---|---|---|
| 1 | Repository foundation, local infrastructure, CI, environment contract | Architecture record | Local and CI-equivalent checks pass |
| 2 | Procurement domain and shared contracts | 1 | Domain invariants and serialization tests pass |
| 3 | End-to-end walking skeleton | 2 | Request reaches API, event stream, UI, and artifact download |
| 4 | PostgreSQL event journal, outbox, projections, resumable SSE | 3 | Migration, ordering, replay, and rebuild tests pass |
| 5 | Browser, search, evidence, and provenance | 3 | Isolation, provenance, and injection-boundary tests pass |
| 6 | Deterministic evaluation and artifacts | 3 | Constraint, normalization, evidence, workbook, and report tests pass |
| 7 | Durable parent and child workflow runtime | 4–6 | Pause, resume, redirect, cancel, recovery, and replay tests pass |
| 8 | Approval and protected-action broker | 4, 6 | Digest, permit, policy, edit, and outcome tests pass |
| 9 | Structural operator workbench | 4, 7 | Operator journeys and accessibility checks pass |
| 10 | Credential-free email subsystem | 8 | Idempotency, allowlist, receipt, and reconciliation tests pass |
| 11 | Generic end-to-end integration | 5–10 | Unrelated procurement category fixtures pass |
| 12 | Reliability, security, polish, traces, memo, and demo readiness | 11 | Full automated and Computer Use acceptance passes |

Live model and email providers are configured only after PR 12's
credential-independent gate is green.
