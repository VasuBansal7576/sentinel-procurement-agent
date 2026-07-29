# Sentinel memo

## Disclosures first

The demonstrated suppliers and source pages are deterministic local documents,
not current market research. No live model or browser call is made. The
integrated email provider is fake, and clicking Approve never sends anything.
The Resend adapter is transport-injected and tested without network access;
credentials are not configured. Artifacts are real generated Markdown, XLSX,
and ZIP bytes, but the integrated path stores them in run-scoped PostgreSQL
records rather than the Compose MinIO service. The optional demo delay and
first-attempt failure are hardcoded configuration seams: off by default,
explicitly disclosed in the UI, and rejected in production. The final demo
video is not fabricated or committed; recording it remains a human submission
step.

## Operator and product choice

I designed for a procurement manager who can judge requirements, evidence,
vendors, and approval risk but does not know what a tool call, workflow replay,
or process signal is. They need to answer three questions without translation:
What is happening? What changed? What can I safely do now? Sentinel therefore
treats the agent as an operations case, not a chat partner. A persistent session
index restores work after closing the tab. The run header gives phase, revision,
policy, elapsed time, progress, and attention count. The work tree groups
phases, isolated subagents, work, and optional tool detail. Requirements,
comparison, claim evidence, artifacts, and the protected action stay beside the
run rather than arriving as transient messages.

## Cuts and why

I cut live research, an LLM, real email, purchase orders, payments, autonomous
negotiation, ERP integration, multi-user identity, and hosting. None helps
evaluate whether an operator can understand or control a deep run, and each
would add credentials or irreversible effects. I kept a category-generic typed
procurement pipeline, sixty tool lifecycle events, a real Temporal child, exact
evidence/ranking modules, and usable artifacts so the harness has genuine depth.
The single integrated child is intentionally broad; the runtime supports
multiple concurrent work items, but expanding the demo agent would spend the
time budget on engine breadth instead of operator control.

## Hardest rendering decision

The hardest choice was how much execution detail to show. I rejected a raw
chronological tool log because parent and child events become an interleaved
diagnostic stream, and I rejected a single progress spinner because it hides
blocked branches and retained work. I also rejected a chat transcript with
status cards: redirects, approvals, evidence, and downloads lose their stable
spatial relationship as the transcript grows. The chosen middle layer is a
collapsible work tree. Phase and subagent nodes summarize by default; state,
progress, blockers, attempts, and targeted recovery stay visible; tool events
remain available through the durable event source. The center canvas holds
decision evidence, and the action rail holds outputs and the exact protected
action. This makes nesting coherent without pretending the details do not
exist.

## Failure states and the operator view

| State | What the operator sees and can do |
|---|---|
| Queued/running | Current phase, nested active branch, completed/total work, and live durable updates. |
| Paused | Amber paused state; active cancellable child is cooperatively stopped at a safe boundary. Resume continues from durable state. |
| Redirecting/invalidated | Acknowledged redirect, incremented request revision, retained product IDs, and only affected work returned to the queue. |
| Transient or rate-limited tool failure | Failed branch, exact attempt, blocker, and enabled “Retry from checkpoint.” Prior durable evidence remains. |
| Authentication or policy denial | Non-retryable blocker with no unsafe retry control; configuration or policy must change outside the run. |
| Input required/source changed/conflict | Designed blocked explanation; the operator supplies direction or revises requirements instead of blind retry. |
| Tool bug/model-invalid output/terminal | Failed state and sanitized summary; no stack trace or automatic consequential action. |
| Outcome unknown | Dispatch is not repeated. The action stays ambiguous until receipt reconciliation proves confirmed or safe-to-retry. |
| Worker termination | The UI stops advancing but the Temporal history and PostgreSQL projection remain. Restarting the real worker resumes the same workflow ID without duplicating completed effects. |
| Browser/tool process termination | The injected first attempt exhausts retry, exposes targeted recovery, and succeeds on the next workflow attempt without restarting the run. |
| Parent/child cancellation | Pause or redirect cancels the active Temporal child/activity cooperatively; pause holds it, redirect restarts only invalidated work. |
| Tab close/SSE disconnect | Reopening selects the stored run ID; EventSource reconnects with `Last-Event-ID`, replaying only later journal rows. |
| Approval pending | The run and evidence remain readable. Exact recipient, subject, body, attachments, digests, and version diff are inline. |
| Edited after approval | Saving creates a new version, returns status to pending approval, and makes the earlier permit unusable. |
| Approval/rejection | Approval receipt explicitly says no dispatch occurred; rejection authorizes nothing. Execution is a separate fake-only gate. |
| Artifact unavailable/wrong run | A clear 404 rather than cross-run disclosure; valid downloads are no-store attachments with digest and nosniff headers. |
| API unavailable/empty/loading | Persistent alert with retry, explicit empty-session invitation, or restoration status; an acknowledged API conflict never silently switches to fixture data. |

## Production metric

I would watch **operator recovery success rate**: the percentage of blocked deep
runs that reach a valid terminal result within 30 minutes of the first operator
control, without restarting the run or duplicating a protected action. It joins
legibility, control, durability, and safety. A fast completion metric could
reward hiding failures; this metric fails when the operator cannot understand
the blocker, when a retry discards work, or when idempotency breaks.

## Visual choice

I chose a light editorial operations desk: warm paper surfaces, dark green
session rail, ruled structure, serif display type, compact mono labels, and
acid-green only for active emphasis. Procurement work is document-heavy and
accountable, so the interface should feel closer to a case file and control
room than entertainment software. The palette avoids the default dark-purple
AI aesthetic, glowing status theatre, chat bubbles, and sparkle metaphors.
Hierarchy comes from typography, rules, whitespace, and stable columns; state
never depends on color alone. The layout collapses deliberately on smaller
screens, retains visible focus, honors reduced motion, and uses no remote font
or image request.
