# Sentinel

Operator workbench for long-running procurement agents.

The product problem is not “can the agent call tools.” It is whether a
procurement manager who will never open a terminal can understand a deep run,
interrupt it, redirect it without discarding safe work, recover a failed branch,
inspect evidence, and authorize one exact external action without losing their
place.

Sentinel is that control plane. The engine is intentionally lean: deep enough to
stress nesting, failure, and approval; not a general autonomous buyer.

## What you are looking at

| Surface | Role |
|---|---|
| React workbench | Structural operator UI: session rail, work tree, evidence canvas, action rail |
| FastAPI | Commands, projections, artifact download, resumable SSE |
| Temporal | Durable parent/child workflows, pause/resume, redirect, retry |
| PostgreSQL | Append-only run journal, projections, protected-action state |
| Protected-action broker | Exact payload digests, single-use permits, separate execute gate |
| Resend adapter | Optional controlled email after approval; never on approve alone |

Default research uses **Agent Reach** backends already on the machine: Exa
search via `mcporter` and page read via Jina Reader (`r.jina.ai`). That path
returns real public source URLs — not a hardcoded supplier list. Email stays
fake by default (no live model). The control plane (Temporal, journal, SSE,
approval, artifacts) is real either way. Set `SENTINEL_RESEARCH_PROVIDER=fake`
for offline CI fixtures only.

## System shape

```text
┌──────────────────────────────────────────────────────────────────┐
│                     Operator workbench (React)                   │
│  sessions · work tree · evidence · artifacts · exact approval    │
└───────────────────────────────┬──────────────────────────────────┘
                                │ HTTP commands + SSE (Last-Event-ID)
┌───────────────────────────────▼──────────────────────────────────┐
│                         FastAPI application                      │
│  intake · operator commands · projections · artifact download    │
└───────┬───────────────────────────────┬──────────────────────────┘
        │                               │
        ▼                               ▼
┌───────────────────┐         ┌─────────────────────┐
│   PostgreSQL      │         │   Temporal worker   │
│ journal / outbox  │◄───────►│ parent + child WF   │
│ projections       │         │ activities          │
│ permits / outcomes│         └──────────┬──────────┘
└───────────────────┘                    │
                                         ▼
                              ┌─────────────────────┐
                              │ executor            │
                              │ Agent Reach search  │
                              │ + page read · eval  │
                              │ artifacts · RFQ     │
                              └──────────┬──────────┘
                                         │ authorize + consume permit
                                         ▼
                              ┌─────────────────────┐
                              │ email execution     │
                              │ fake | Resend       │
                              │ controlled recipient│
                              └─────────────────────┘
```

Full diagrams, trust boundaries, and run lifecycle: [`architecture.md`](architecture.md).

## Operator model

Primary user: a procurement manager. They judge requirements, vendors, evidence,
and approval risk. They do not know what a tool call or workflow signal is.

The workbench answers three questions without translation:

1. What is happening now?
2. What already completed, and what is blocked?
3. What can I safely do next?

Controls are product language: pause/resume, queue, redirect, retry from
checkpoint, autonomy modes (research only / ask before external / approve and
hold), exact proposal edit, approve without send, optional separate execute.

## Honest boundary

| Layer | Behavior |
|---|---|
| Domain + evaluation | Typed procurement contracts; deterministic ranking |
| Durability | Real Temporal parent/child; real Postgres journal + SSE resume |
| Research (default) | Live public search + page read via Agent Reach (Exa/mcporter + Jina). Real URLs; heuristic fact extraction — not a negotiated quote |
| Research (`fake`) | Deterministic Northstar/Blue River/Cedar fixtures for CI only |
| Artifacts | Real Markdown / XLSX / ZIP bytes |
| Approval | Version + digest bound; single-use; approval ≠ dispatch |
| Email | Fake by default; Resend path exists for one controlled recipient after execute |
| Live LLM planner | Not in the integrated path |

The UI honesty banner states which research mode is active so operators never
confuse fixture runs with live public sources.

## Quick start

Requires Python 3.12–3.14, `uv`, Node 22, npm, Docker Compose.

```bash
cp .env.example .env
make bootstrap
make infra-up
```

Three processes from the repo root (with `.env` loaded):

```bash
.venv/bin/sentinel-api
.venv/bin/sentinel-worker
npm run dev:web
```

| Service | URL |
|---|---|
| Workbench | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/api/docs |
| Temporal UI | http://localhost:8080 |

### Demo pacing (optional)

```dotenv
SENTINEL_DEMO_MODE=true
SENTINEL_DEMO_STEP_DELAY_MS=1200
SENTINEL_DEMO_FAILURE_STEP=candidate.2.snapshot
```

Forces a first-attempt tool failure and durable recovery path. Rejected when
`SENTINEL_ENVIRONMENT=production`.

Operator recording checklist: [`docs/demo/operator-runbook.md`](docs/demo/operator-runbook.md).

## Safety invariants

- Research content is tainted; it cannot grant capabilities or invoke send.
- Proposal edit creates a new version; old permits die.
- Permits are exact-payload, attachment-digest, policy-revision, expiring, single-use.
- Controlled recipient is rechecked at execution time.
- Ambiguous provider outcomes require reconciliation before retry.
- Artifact download is run-scoped, no-store, nosniff, digest-headed.
- Autonomy “research only” suppresses the external RFQ path entirely.

## Validation

```bash
make check
npm run build
docker compose config --quiet
make trace-verify
```

Tests pin `SENTINEL_RESEARCH_PROVIDER=fake` (and other fake providers). No secrets
required for CI or local green. Live research needs `mcporter` + healthy Agent
Reach backends (`agent-reach doctor`).

## Repository map

```text
apps/api/          FastAPI, domain, Temporal, email, evaluation
apps/web/          Operator workbench
docs/              Architecture notes, runbook, acceptance ledger
traces/            Native coding-agent session exports + redaction log
MEMO.md            Product decisions, cuts, failure table, metric
architecture.md    System diagrams and trust boundaries
```

## Deliberate non-goals

No purchase orders, payments, autonomous negotiation, ERP mutation, multi-tenant
identity, or hosted multi-user deployment. Live research invents candidates from
public pages; it does not claim negotiated quotes or verified commercial
availability. The graded surface is operator control under depth and
failure—not full procurement automation.
