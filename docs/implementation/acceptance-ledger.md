# Acceptance evidence ledger

This is the release ledger for the credential-independent harness. “Verified”
means the cited automated or local-operator evidence exists in this repository;
it does not imply live model, browser, market-data, or email execution.

| Assignment requirement | Exact repository evidence | Release status |
|---|---|---|
| Reproducible repository and fixed infrastructure | Lockfiles and locked bootstrap targets in `Makefile`; `compose.yaml` pins `temporalio/auto-setup:1.27`; `docker compose config --quiet` passes | Verified |
| Credential-free, fail-closed defaults | `.env.example`; settings validation in `apps/api/tests/test_settings.py`; fake-only credential gate rejects live providers; demo controls reject production | Verified |
| Category-generic procurement model | Immutable contracts plus industrial equipment, recurring PPE, and services through one path in `apps/api/tests/integration/test_operator_end_to_end.py` | Verified |
| More than 20 real tool calls | Each integrated run journals more than 20 `tool.started` and `tool.completed` pairs; asserted in the operator integration suite | Verified |
| Genuine nested subagent execution | Temporal parent/child histories, activity wiring, replay, cancellation, and restart coverage in `apps/api/tests/workflows/test_temporal_runtime.py` and `apps/api/tests/integration/test_temporal_end_to_end.py` | Verified |
| Pause, child cancellation, resume | Durable workflow updates and cooperative child cancellation tests; operator controls in the workbench and `docs/demo/operator-runbook.md` | Verified |
| Queued instruction | Durable acknowledgement/idempotency tests and command history projection; queue journey in the runbook | Verified |
| Redirect with selective reuse | Direct/transitive invalidation and Temporal redirect tests; HTTP redirect changes `request:requirements`, retaining candidate/evidence references while regenerating dependent evaluation, artifacts, and proposal | Verified |
| Close/reopen and `Last-Event-ID` reconnect | PostgreSQL journal/projections/outbox, SSE replay tests, API-first gateway reconnect test, and browser close/reopen checklist | Verified automatically; final recording is human-only |
| Real worker termination and restart | Temporal restart test plus two local production-worker `Ctrl-C`/restart trials against Compose, both clean exit 0 without traceback | Verified |
| Intentional tool failure and recovery without restart | Explicit development-only `DemoProfile`, production rejection, first-attempt deterministic failure test, durable blocked state, retry safety classification, and exact-work targeted retry tests | Verified |
| Clear blocked/recoverable failure state | Work-tree blocker, attempt metadata, safe-to-retry gate, recovering state, persistent API error treatment, and the failure/view table in `MEMO.md` | Verified |
| Temporal replay determinism | Replay and worker-restart suites run against local Temporal; selective reuse and protected effects remain deterministic | Verified |
| Claim-level evidence and injection boundary | Immutable source snapshots, exact-span/content hashes, isolation/taint/conflict tests, acceptable-evidence checks, and adversarial prompt-injection tests in `apps/api/tests/research` | Verified for deterministic local sources; live adapters intentionally absent |
| Deterministic evaluation | Unit/currency normalization, mandatory gates, evidence-aware scoring, withheld ranking for unresolved mandatory claims, and rounded operator coverage | Verified |
| Exact editable approval and invalidation | Canonical digest/version model, semantic diff UI, edit-after-approval returns to pending, and browser/Vitest coverage | Verified |
| Approval never dispatches | Decision endpoint records the exact-version decision only; UI says “no send”; protected execution is a separate fake boundary | Verified |
| Single-use permit and duplicate suppression | Policy-bound permit, atomic consumption, concurrent duplicate tests, durable idempotency, and fake provider receipt | Verified |
| Controlled recipient and unknown-outcome reconciliation | Recipient recheck at execution, PostgreSQL compare-and-set outcomes, ambiguous outcome/reconciliation tests, and credential checklist | Verified without live provider |
| Artifact safety | Opaque run-scoped lookup, wrong-run 404, sanitized filename, digest header, `private, no-store`, CSP sandbox, and `nosniff` assertions | Verified |
| No secrets in product logs/traces/screenshots | SSE excludes artifact content; trace verifier rejects credential/private-identifier patterns; runbook forbids credentials, environment output, and personal paths in recording | Verified for committed material |
| Downloadable deliverables | Requirements Markdown, comparison XLSX, recommendation Markdown, and RFQ ZIP generated deterministically and exposed through scoped downloads | Verified |
| Operator-first structural workbench | Persistent run rail, run header, nested work tree, evidence ledger, artifact/proposal rail, command console, explicit projection/fake boundary, and designed empty/loading/error states | Verified |
| Accessibility and responsive behavior | Semantic landmarks/tree/tabs/table, skip link, live region, keyboard tab roving, visible focus, reduced-motion rule, mobile layout with no horizontal document overflow, and frontend tests | Verified by Vitest and local in-app browser at 1280×720 and 390×844 |
| Native raw traces | Seven completed native Codex JSONL exports, transparent per-field redaction logs, append-only `traces/manifest.jsonl`, deterministic exporter, hash/count verification, and credential scan | Verified; active parent and PR 12 final snapshots intentionally deferred |
| Truthful submission documents | Current `README.md`, two-page-budget `MEMO.md`, operator demo runbook, credential checklist, and this ledger | Verified |
| Operator-perspective demonstration | `docs/demo/operator-runbook.md` covers the complete hard journey and stops before real send | Runbook verified; recording and review remain a human submission step |
| Controlled real email | Provider boundary, recipient gate, exact permit, durable outcomes, suppression, and reconciliation exist; no live provider call or send occurred | Intentionally deferred until every fake-mode gate passes, credentials are supplied out of band, and a new explicit human approval is given |

## Release-gate snapshot — 2026-07-29

- Ruff check and format check: passed.
- mypy: 72 source files, no issues.
- Exact locked bootstrap (`uv sync --locked` and `npm ci`): passed.
- Full Python suite with real Temporal enabled: 182 collected, 171 passed,
  11 skipped, one third-party warning.
- Designated real PostgreSQL suite: 15 passed.
- Frontend ESLint and TypeScript: passed.
- Frontend Vitest: 2 files, 12 tests passed.
- Frontend production build: passed.
- Docker Compose configuration: passed; PostgreSQL healthy and Temporal
  running locally.
- Real worker shutdown/restart: two clean `Ctrl-C` exits, no traceback.
- Native trace verification: seven snapshots verified; no credential patterns
  remain.
- Browser QA: API-backed create/run view, explicit fake boundary, evidence,
  artifacts, proposal, empty/error states, keyboard tabs, focus retention, and
  390 px responsive layout inspected. No remote page assets were loaded.

The skipped Python tests are service-gated tests outside the enabled Temporal
set; the designated PostgreSQL run above supplies the real database evidence.
No live model, public browser, market-data, or email call was made.

`npm ci` also reported five high-severity audit paths for the July 2026
`brace-expansion` denial-of-service advisory. The vulnerable package is present
only under the ESLint development toolchain (`npm ls brace-expansion
--omit=dev` is empty), so it is not shipped in the browser bundle or production
dependency tree. Moving the lint toolchain from ESLint 9 to ESLint 10 removes
that old `minimatch` branch; the lockfile refresh remains an explicit release
hygiene follow-up rather than an unreported runtime exposure.
