# Sentinel

Operator control plane for long-running procurement agents.

The product problem is not whether an agent can call tools. It is whether a
procurement manager who will never open a terminal can follow a deep run,
interrupt it, redirect it without discarding safe work, recover a failed branch,
inspect claim-level evidence, and authorize one exact external action without
losing their place.

Sentinel is that harness. The engine is intentionally lean—deep enough to stress
nesting, failure, and approval—not a general autonomous buyer.

## Demo

Operator-perspective recording (hard run: interrupt, redirect, evidence,
approve ≠ send, controlled execute):

**[Watch the demo on Loom](https://www.loom.com/share/ba9d47061d23472b984e361d1abaf923)**

Repository: [VasuBansal7576/sentinel-procurement-agent](https://github.com/VasuBansal7576/sentinel-procurement-agent)

## Stack

| Surface | Role |
|---|---|
| React workbench | Session rail, status hero, nested work tree, evidence canvas, action rail |
| FastAPI | Intake, operator commands, projections, artifact download, SSE |
| Temporal | Durable parent/child workflows: pause, resume, redirect, retry |
| PostgreSQL | Append-only journal, projections, protected-action state |
| Protected-action broker | Exact payload digests, single-use permits, execute separate from approve |
| Research | Public web via Agent Reach backends (Exa/`mcporter` + Jina Reader); offline fixtures for CI |
| Email | Fake by default; optional Resend to one controlled recipient after execute |

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
                              │ public research     │
                              │ evaluate · artifacts│
                              │ RFQ proposal        │
                              └──────────┬──────────┘
                                         │ authorize + consume permit
                                         ▼
                              ┌─────────────────────┐
                              │ email execution     │
                              │ fake | Resend       │
                              │ controlled recipient│
                              └─────────────────────┘
```

Topology, trust boundaries, and run lifecycle: [`architecture.md`](architecture.md).  
Product decisions and failure table: [`MEMO.md`](MEMO.md).

## Operator model

Primary user: a procurement manager. They evaluate requirements, vendors,
evidence, and approval risk. They do not speak in tool calls or workflow signals.

The workbench answers three questions without translation:

1. What is happening now?
2. What already completed, and what is blocked?
3. What can I safely do next?

Controls use product language: pause/resume, queue instruction, redirect with
selective reuse, retry from checkpoint, autonomy modes (**Research only** /
**Ask before external contact** / **Approve and hold**), exact proposal edit,
approve without send, and optional separate execute.

## Honest boundary

| Layer | Behavior |
|---|---|
| Domain + evaluation | Typed procurement contracts; deterministic ranking |
| Durability | Temporal parent/child; Postgres journal; SSE with `Last-Event-ID` |
| Research (default) | Live public search + page read (Agent Reach: Exa via `mcporter`, Jina Reader). Real URLs; heuristic extraction—not negotiated quotes |
| Research (`fake`) | Deterministic fixtures for CI only |
| Artifacts | Generated Markdown / XLSX / ZIP, run-scoped download |
| Approval | Version- and digest-bound; single-use permit; **approval never dispatches** |
| Email | Fake by default; Resend path for one controlled recipient after **execute** |
| LLM planner | Not on the integrated critical path |

The workbench honesty banner states the active research and execution mode so
fixture runs cannot be confused with live sources or live dispatch.

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

### Optional demo profile (failure + pacing)

```dotenv
SENTINEL_DEMO_MODE=true
SENTINEL_DEMO_STEP_DELAY_MS=1200
SENTINEL_DEMO_FAILURE_STEP=candidate.2.snapshot
```

Arms a first-attempt tool failure and slows steps for operator controls. Rejected
when `SENTINEL_ENVIRONMENT=production`.

Recording checklist: [`docs/demo/operator-runbook.md`](docs/demo/operator-runbook.md).

### Live research / live email (optional)

```dotenv
SENTINEL_RESEARCH_PROVIDER=agent_reach   # default; use fake for offline CI
SENTINEL_EMAIL_PROVIDER=resend           # default fake
SENTINEL_CREDENTIAL_GATE=live-approved
SENTINEL_CONTROLLED_RECIPIENT=you@example.com
RESEND_API_KEY=...                       # never commit
```

Requires healthy Agent Reach backends (`agent-reach doctor`) for live research.
Resend free tier typically restricts senders/recipients to the account identity
unless a domain is verified.

## Safety invariants

- Research content is tainted; it cannot grant capabilities or invoke send.
- Proposal edit creates a new version; prior permits die.
- Permits are exact-payload, attachment-digest, policy-bound, expiring, single-use.
- Controlled recipient is rechecked at execution time.
- Ambiguous provider outcomes require reconciliation before retry.
- Artifact download is run-scoped, `no-store`, `nosniff`, digest-headed.
- Autonomy **Research only** suppresses the external RFQ path entirely.

## Validation

```bash
make check
npm run build
docker compose config --quiet
make trace-verify
```

Tests pin fake providers. No secrets required for CI. Temporal test-server
suites are opt-in via `SENTINEL_RUN_TEMPORAL_TESTS=1`.

## Repository map

```text
apps/api/          FastAPI, domain, Temporal, email, evaluation, research
apps/web/          Operator workbench
docs/              Runbook, acceptance ledger, architecture notes
traces/            Native coding-agent session exports + redaction log
MEMO.md            Operator, cuts, rendering, failures, metric, taste
architecture.md    Topology and trust boundaries
```

## Deliberate non-goals

No purchase orders, payments, autonomous negotiation, ERP mutation, multi-tenant
identity, or hosted multi-user deployment. Public-web research does not claim
negotiated commercial availability. The graded surface is **operator control
under depth and failure**—not full procurement automation.
