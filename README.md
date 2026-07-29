# Sentinel

Sentinel is a production-oriented procurement agent and operator harness.

It is designed for non-engineers to run, inspect, redirect, pause, resume, and approve long procurement workflows without treating the agent as a black box.

> **Project status:** architecture and acceptance criteria are defined. Implementation has not started.

## What Sentinel will do

Sentinel will accept procurement requests across product and service categories rather than relying on a hardcoded demonstration workflow.

For each request, it will:

1. Convert the request into editable, typed requirements.
2. Research real suppliers and offerings using public sources.
3. Capture claim-level evidence and disclose missing or conflicting information.
4. Compare candidates using deterministic constraints and calculations.
5. Produce usable reports, comparison workbooks, and an RFQ package.
6. Request approval for the exact external action it proposes.
7. Send the approved RFQ through a real email provider.

The demonstration email will be sent only to a clearly disclosed throwaway address controlled by the project owner. It will not pretend to contact a real supplier.

## Product principles

- **Generic by schema, not by prompt:** a stable procurement model with request-specific requirements created at runtime.
- **Operator control:** pause, resume, redirect, and queue instructions without discarding completed work.
- **Evidence before confidence:** every material claim retains its source, observation time, and derivation.
- **Exact approvals:** approval is bound to one proposal version, payload digest, and attachment set.
- **Honest failure states:** uncertain external outcomes are reconciled before retrying.
- **Durable execution:** closing the browser or restarting a worker must not restart the run from zero.
- **No fabricated demo data:** the recorded demonstration will use real public sources and real generated artifacts.

## Planned architecture

```text
React operator workbench
        │ HTTP commands + resumable SSE
        ▼
FastAPI application and UI projections
        │
        ├── PostgreSQL domain state and product event journal
        ├── S3-compatible evidence and artifact storage
        └── Temporal durable workflows
                ├── Procurement coordinator
                ├── Research child workflows
                ├── Browser and evidence tools
                ├── Deterministic evaluation
                └── Protected approval/action broker
```

Pydantic AI will provide typed agent and tool boundaries. Browser automation will follow the small, adaptable philosophy of Browser Harness while isolating agent-authored helpers from credentials and protected actions.

## Assignment demonstration

The operator-perspective demo is intended to show:

- A run with more than 20 real tool calls across several namespaces
- Genuine nested subagent work
- Legible current, completed, blocked, and remaining work
- A queued instruction and a mid-run redirect
- Selective reuse of work after requirements change
- Tab close and reopen without losing the run
- A real worker or browser failure followed by recovery
- An editable proposal with version diff and exact approval
- A real controlled email action
- Downloadable reports, workbook, RFQ package, and audit receipt

## Documentation

- [Architecture research and assignment acceptance matrix](docs/procurement-agent-architecture-research.md)
- [Implementation control and merge policy](docs/implementation/README.md)
- [Implementation PR plan](docs/implementation/pr-plan.md)
- [Acceptance evidence ledger](docs/implementation/acceptance-ledger.md)
- Development-agent traces will be stored under [`traces/`](traces/) as implementation begins.

## Local development

Prerequisites are Python 3.12–3.14, [uv](https://docs.astral.sh/uv/), Node.js 22,
npm, Docker, and Docker Compose.

```bash
cp .env.example .env
make bootstrap
make infra-up
```

Run the API and workbench in separate terminals:

```bash
.venv/bin/sentinel-api
.venv/bin/sentinel-worker
npm run dev:web
```

The API is available at `http://localhost:8000`, its development documentation
at `http://localhost:8000/api/docs`, and the workbench at
`http://localhost:5173`.

Run the same credential-independent quality gate used before every merge:

```bash
make check
npm run build
docker compose config --quiet
```

## Current scope

The first version covers research, comparison, recommendation, RFQ preparation, approval, and controlled email delivery for arbitrary procurement categories.

It will not initially perform payments, place purchase orders, negotiate autonomously, or act as a complete ERP system.

## Repository integrity

This repository will maintain:

- Small, meaningful Git commits
- Raw development-agent traces with secrets redacted
- Explicit disclosure of demo-only or unimplemented production components
- Test fixtures clearly separated from real demonstration evidence
- No scripted logs presented as live execution
