# Sentinel

Sentinel is a credential-independent procurement agent and structural operator
workbench. A non-engineer can start a deep run, understand nested work, pause or
redirect it, recover a failed branch, inspect evidence, approve an exact
proposal version, and download the resulting files without opening a terminal.

The harness is implemented. The integrated demonstration uses deterministic
local supplier documents, a real PostgreSQL event journal, real Temporal
parent/child workflows, deterministic evaluation, generated artifacts, and a
fake email provider. It performs no live browsing, model call, or email send.
Approval records a single-use, version-bound permission; approval itself never
dispatches.

## What is real and what is fake

| Area | Current behavior |
|---|---|
| Intake and domain | Real typed, category-generic procurement contracts |
| Deep execution | Real Temporal parent/child workflow and activity boundary |
| Run history and reconnect | Real PostgreSQL journal/projections and resumable SSE |
| Research inputs | Deterministic local supplier documents; no live web request |
| Evidence and ranking | Real taint/provenance contracts and deterministic evaluation |
| Artifacts | Real Markdown, XLSX, and ZIP bytes; stored in run-scoped integration records |
| Approval | Real canonical versions, digests, policy decision, and single-use permit |
| Email | Deterministic fake provider only in the app/demo; no send on approval |
| Demo failure | Optional deterministic first-attempt tool failure, forbidden in production |
| Demo video | Not committed; final recording is a human submission step |

Production adapters for Resend and research/browser isolation exist behind
tested interfaces, but no credentialed provider is configured or exercised.
MinIO is in Compose for the intended object-store topology; the integrated
credential-free run currently retains artifact bytes in PostgreSQL records.

## Operator model

The primary operator is a procurement manager who understands requirements,
suppliers, evidence, and approval risk but does not know Temporal, tool calls, or
terminal commands. The workbench therefore uses an operations layout:

- session history and durable source disclosure on the left;
- nested phases, subagents, work, and tools as a collapsible work tree;
- requirements, comparison, and claim-level evidence in the decision canvas;
- artifacts and exact protected-action preview in the action rail;
- pause/resume and queue/redirect controls in operator language.

Blocked, failed, recovering, approval-pending, empty, loading, and API-error
states are designed states. The live run is restored from its durable ID after
a tab close, and `Last-Event-ID` resumes the event stream without replaying
already seen events.

## Local setup

Prerequisites: Python 3.12-3.14, `uv`, Node.js 22, npm, Docker, and Docker
Compose.

```bash
cp .env.example .env
make bootstrap
make infra-up
```

Run the API, worker, and workbench in three terminals from the repository root:

```bash
set -a; source .env; set +a
.venv/bin/sentinel-api
```

```bash
set -a; source .env; set +a
.venv/bin/sentinel-worker
```

```bash
npm run dev:web
```

Open `http://localhost:5173`. The API is at `http://localhost:8000`; development
API documentation is at `http://localhost:8000/api/docs`. Temporal UI is at
`http://localhost:8080`.

`make bootstrap` is lockfile-bound (`uv.lock` and `package-lock.json`).
PostgreSQL migrations are checksum-verified and local auto-migration is
idempotent. The Compose Temporal image remains pinned to
`temporalio/auto-setup:1.27`.

## Deterministic demo controls

For a visible operator-paced run, set these values in `.env` before starting
the API and worker:

```dotenv
SENTINEL_DEMO_MODE=true
SENTINEL_DEMO_STEP_DELAY_MS=250
SENTINEL_DEMO_FAILURE_STEP=candidate.2.snapshot
```

The named step fails throughout Temporal's automatic activity retries on the
first workflow attempt. The run then stays durably blocked with a targeted
“Retry from checkpoint” control; the second workflow attempt succeeds. Pacing
and failure controls require explicit demo mode, default off, and configuration
validation rejects demo mode in production.

The full operator journey is in
[`docs/demo/operator-runbook.md`](docs/demo/operator-runbook.md). It includes a
real worker termination/restart, close/reopen, queue, pause/resume, redirect,
selective reuse, recovery, edit-after-approval invalidation, artifact download,
and a hard stop before any real send.

## Safety boundaries

- Untrusted research content stays tainted and cannot grant capabilities,
  reveal credentials, or invoke a protected action.
- Research grants contain read-only tools, public-domain egress constraints,
  isolated browser handles, and no credentials.
- Editing always creates a canonical proposal version. A prior approval cannot
  authorize the edited version.
- A permit is exact-payload, exact-attachment, policy-revision bound,
  expiring, and single use.
- Controlled-recipient policy is checked again at execution time.
- Duplicate email attempts share an idempotency key; ambiguous outcomes must be
  reconciled before retry.
- Artifacts require both the run ID and opaque artifact ID, download as
  attachments, disable MIME sniffing and caching, and carry a content digest.
- The integrated UI does not expose a dispatch endpoint. Approval and execution
  are separate operations, and fake execution is the only accepted demo path.

The post-acceptance credential sequence is documented in
[`docs/release/credential-checklist.md`](docs/release/credential-checklist.md).
Do not request or configure credentials until every fake-mode gate is green.

## Validation

```bash
make check
npm run build
docker compose config --quiet
make trace-verify
```

Real PostgreSQL and Temporal acceptance commands, including worker restart and
replay, are listed in
[`docs/demo/operator-runbook.md`](docs/demo/operator-runbook.md). Tests default
to deterministic fake providers and never need network or provider secrets.

## Submission evidence

- [`MEMO.md`](MEMO.md) - two-page product and tradeoff memo
- [`docs/implementation/acceptance-ledger.md`](docs/implementation/acceptance-ledger.md) -
  requirement-to-proof map
- [`docs/demo/operator-runbook.md`](docs/demo/operator-runbook.md) -
  operator-perspective recording checklist
- [`traces/`](traces/) - redacted native Codex JSONL, append-only manifest, and
  transparent redaction records

The committed traces preserve native session event structure. The exporter
redacts only credential patterns, non-example email identifiers, and absolute
personal home paths, records every replacement by location and original-value
hash, and verifies committed byte/line counts and SHA-256 hashes.

## Deliberate cuts

Sentinel does not place orders, spend money, negotiate, modify an ERP, perform
live web research in the demo, or send a real email. It does not claim that the
deterministic local supplier set represents current market truth. Those cuts
keep the submission focused on the measured product problem: making a deep
agent legible, controllable, recoverable, and safe for a non-engineer operator.
