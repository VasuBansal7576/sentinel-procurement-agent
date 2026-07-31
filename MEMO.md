# Sentinel memo

## Disclosures first

Default CI and offline paths use deterministic research fixtures and a fake email
provider. Production-shaped local demos may enable **Agent Reach** public search
(Exa via `mcporter` + Jina Reader) and optional **Resend** dispatch to one
controlled recipient after a separate execute step. **Approve never sends.**
Public pages are not negotiated quotes; fact extraction is heuristic. Artifacts
are real Markdown/XLSX/ZIP bytes stored on run-scoped integration records (Compose
MinIO is present but not required for the integrated path). Demo delay and
first-attempt failure are explicit, non-production configuration seams. No live
LLM planner is on the critical path. Demo recording:
[Loom](https://www.loom.com/share/ba9d47061d23472b984e361d1abaf923).

## Operator and product choice

The operator is a procurement manager who judges requirements, evidence, vendors,
and approval risk—not tool calls or workflow signals. They need three answers
without translation: what is happening, what changed, what is safe next. Sentinel
treats the agent as an operations case, not a chat partner. A session rail
restores work after tab close. The status hero carries phase, revision, policy,
elapsed time, progress, and blockers. A collapsible work tree groups phase,
subagent, work, and tool detail. Evidence, artifacts, and the protected RFQ stay
spatially stable beside the run.

## Cuts and why

Cut: multi-vendor market APIs as a product dependency, LLM planner, multi-tenant
auth, ERP/PO/payment, and hosted multi-user deployment. None of those measure
whether an operator can drive a deep run; each adds irreversible risk or
credential surface. Kept: category-generic typed pipeline, >20 tool lifecycle
events per integrated run, real Temporal parent/child, claim-level evidence,
deterministic ranking, usable artifacts, and a protected-action broker with
approve ≠ execute. Fan-out breadth was spent on control surfaces, not engine
spectacle. Autonomy is plain language: **Research only**, **Ask before external
contact** (default), **Approve and hold**—never auto-send.

## Hardest rendering decision

How much execution detail to surface. Rejected a raw chronological tool log
(parent/child interleaving becomes diagnostic noise) and a single spinner
(hides blockers and retained work). Rejected chat-with-cards: redirect, approval,
evidence, and downloads lose stable spatial meaning as the transcript grows.
Chose a collapsible work tree for nesting, a center canvas for comparison and
claims, and an action rail for outputs and exact protected action. Detail remains
in the durable journal when the operator drills in.

## Failure states and the operator view

| State | Operator view |
|---|---|
| Queued / running | Phase, nested branch, completed/total, live projection |
| Paused | Safe boundary; cooperative child cancel; resume same run |
| Redirect | Revision bump; selective retention of safe candidate/evidence; dependent work recomputed |
| Transient tool failure | Blocked branch, attempt count, **Retry from checkpoint** when safe |
| Policy / auth denial | Non-retryable blocker; no unsafe retry |
| Worker death | UI stalls; history intact; worker restart resumes same workflow ID |
| Tab close / SSE drop | Same run restored; stream resumes after `Last-Event-ID` |
| Approval pending | Full exact preview + digests; place in run retained |
| Edit after approve | New version; prior permit unusable |
| Approval | Receipt: no dispatch; execute is a separate gate |
| Research only | RFQ path suppressed; evidence and artifacts remain |
| Outcome unknown | No second send until reconciliation |

## Production metric

**Operator recovery success rate:** share of blocked deep runs that reach a valid
terminal result within 30 minutes of the first operator control, without
restarting the run or duplicating a protected action. Optimizes legibility and
idempotency; a pure speed metric rewards hiding failure.

## Visual choice

Light editorial operations desk: warm paper ground, dark green session rail,
ruled structure, serif display type, compact mono labels, acid-green only for
active emphasis. Procurement is accountable document work, not entertainment AI.
Avoided purple gradients, chat bubbles, and sparkle chrome. Hierarchy comes from
type, rules, and columns; state is never color-only. Responsive collapse, visible
focus, reduced motion, no remote fonts or images.
