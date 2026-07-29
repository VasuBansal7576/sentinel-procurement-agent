# PR 11: credential-free end-to-end integration

PR 11 connects typed, category-generic procurement intake to the merged durable
runtime and operator workbench without adding a model, browser, email, or object
store credential.

## Runtime path

`POST /api/operator/runs` normalizes an immutable `ProcurementCase` and
`RequestRevision`, persists them behind a run-scoped opaque record reference,
and submits one bounded end-to-end `WorkItem` to the existing Temporal
parent/child workflow. PostgreSQL mode connects to Temporal lazily, so health
and walking-skeleton routes do not depend on Temporal availability. The
`sentinel-worker` entry point registers the centrally owned parent/child
workflows plus production `RuntimeActivities`.

The `CredentialFreeWorkExecutor` is the real execute-work activity adapter. It
uses deterministic local source documents but passes them through the real
untrusted-content, immutable snapshot, exact-span provenance, evidence,
evaluation, ranking, artifact, proposal, and approval modules. A representative
run records 60 `tool.started`/`tool.completed` events plus parent/child lifecycle
events. Every event has a deterministic attempt/revision idempotency key.

## Persistence and protected actions

Migration `0005_integration_records.sql` is strictly additive. It stores compact
JSON records and optional artifact bytes under the composite key
`(run_id, record_ref)`. Artifact IDs are opaque UUIDs and cannot be downloaded
outside their owning run. Journal payloads contain references, hashes, counts,
and summaries; they never contain artifact bytes.

Proposal versions and exact approval permits continue to use the protected
action tables introduced in PR 8. Editing always creates a new canonical
version. Approval binds the current canonical payload and every attachment
digest. Approval never dispatches. The integration-only protected execution
proof accepts only `DeterministicFakeEmailProvider`, enforces the controlled
recipient at commit time, and retains the existing unknown-outcome
reconciliation state machine.

## Operator API

- `GET /api/operator/sessions`
- `POST /api/operator/runs`
- `GET /api/operator/runs/{run_id}`
- `GET /api/operator/runs/{run_id}/work-tree`
- `POST /api/operator/runs/{run_id}/controls/{pause|resume}`
- `POST /api/operator/runs/{run_id}/messages`
- `POST /api/operator/runs/{run_id}/redirect`
- `POST /api/operator/runs/{run_id}/work/{work_id}/retry`
- `PUT /api/operator/runs/{run_id}/proposal`
- `POST /api/operator/runs/{run_id}/proposal/decision`
- `GET /api/runs/{run_id}/events` with `Last-Event-ID`
- `GET /api/runs/{run_id}/artifacts/{artifact_id}`

Safe retry is fail-closed. The projection marks only `transient` and
`rate_limited` failures as intrinsically retryable, but the endpoint denies the
command without changing state until the parent-owned durable
blocked/recoverable state and targeted retry update are merged. That update
must keep the parent open, preserve prior attempts and evidence, requeue only
the targeted work item, and reject non-retryable and `outcome_unknown`
failures. Redirect creates a real successor request revision and records
retained and invalidated compact references.

### Parent retry binding seam

After the parent-owned retry contract lands, integration should require only
these adapter changes:

1. Add `retry(run_id, RetryCommand)` to `RuntimeLauncher`.
2. Implement it in `TemporalRuntimeLauncher` with
   `ProcurementParentWorkflow.retry`; delegate through
   `LazyTemporalRuntimeLauncher`. The inline launcher may apply the same
   command handler for memory-mode tests.
3. In `IntegrationService.retry_work`, keep the existing projection checks,
   construct the targeted command from `command_id` and `work_id`, await the
   runtime acknowledgement, and return the refreshed projection.
4. Replace the current 409 seam test with acceptance tests proving one item is
   requeued, sibling outputs and evidence refs are retained, the attempt number
   increases, duplicate command IDs are idempotent, and non-retryable plus
   `outcome_unknown` failures remain denied.

## Web gateway and acceptance

The workbench defaults to `createApiFirstGateway()`. It uses the real HTTP and
SSE projections and falls back to the existing fixture only when initial API
availability fails. Application conflicts, including unsafe retry, remain
visible and never trigger fixture fallback. The active projection source stays
visible in the workbench.

Automated integration coverage runs the same path for industrial transfer
pumps, recurring chemical-resistant PPE, and accredited calibration services.
Each run produces three requirements, three candidates, nine verified evidence
observations, deterministic evaluation/ranking, four downloadable artifacts,
and one exact-approval proposal. PostgreSQL tests cover migration checksum and
second-run idempotency; Temporal tests cover the real sandboxed parent/child
worker and runtime activity registration.
