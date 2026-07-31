# Sentinel: an operator control plane for procurement agents

## Truth boundary

Sentinel's claim is deliberately narrow: it makes a long-running procurement
agent legible, interruptible, and safe to operate. Default CI and offline runs use
deterministic research fixtures and a fake email provider. The production-shaped
demo can use public-web research through **Agent Reach** (Exa via `mcporter` plus
Jina Reader) and **Resend** for one controlled recipient. Public pages are
evidence, not negotiated quotes, and fact extraction is heuristic.

Generated Markdown, XLSX, and ZIP artifacts are real bytes stored on run-scoped
integration records. Compose includes MinIO, but the integrated path does not
depend on it. Demo latency and first-attempt failure are explicit test seams, not
production behavior. No live LLM planner is on the critical path. Most
importantly, **approval never sends**: dispatch requires a second, separately
authorized execute step. [Demo recording](https://www.loom.com/share/ba9d47061d23472b984e361d1abaf923).

## Operator and product thesis

The operator is a procurement lead. They understand requirements, supplier risk,
evidence quality, commercial tradeoffs, and approval accountability. They should
not need to understand prompts, tool calls, workflow engines, retry semantics, or
event streams.

The interface therefore answers three questions continuously: **What is happening
now? What changed? What is safe to do next?** Sentinel presents the agent as an
operations case, not a conversation. A durable session rail restores prior work;
the status header carries phase, revision, autonomy, progress, elapsed time, and
blockers; a nested work tree explains execution; and evidence, artifacts, and the
protected RFQ retain stable positions throughout the run.

## Scope decisions

I cut multi-vendor market APIs as a product dependency, a live LLM planner,
multi-tenant identity, ERP/PO/payment integration, and hosted deployment. Those
systems expand credential and failure surfaces without improving the capability
being evaluated: whether a non-engineer can safely drive deep work.

I kept the parts that establish that capability: a category-generic typed
pipeline, more than 20 lifecycle events per integrated run, genuine Temporal
parent/child execution, claim-level provenance, deterministic evaluation,
downloadable artifacts, and a protected-action broker where approval and
execution are different state transitions. Breadth was invested in operator
control, not engine spectacle.

Autonomy uses product language rather than infrastructure language:
**Research only**, **Ask before external contact** (default), and **Approve and
hold**. None can auto-send.

## Hardest rendering decision

The central design problem was how much execution structure to expose. A raw
timeline preserves fidelity but turns concurrent parent/child work into
interleaved noise. A single progress indicator is calm but conceals retained
work, blockers, and recovery. A chat transcript was also rejected: evidence,
approval, redirects, and files lose stable spatial meaning as messages accumulate.

The chosen model separates concerns. The work tree communicates hierarchy and
progress; the center canvas carries requirements, comparison, and claim-level
evidence; the action rail owns artifacts and protected actions. The durable
journal preserves full diagnostic detail without making it the default operator
experience.

## Failure and control states

| State | What the operator sees |
|---|---|
| Queued or running | Current phase, active branch, completed/total work, and live progress |
| Paused | A confirmed safe boundary; resume continues the same run |
| Redirected | A new revision, retained safe evidence, and dependent work marked for recomputation |
| Tool or research-provider failure | Blocked branch, attempt count, failure class, and **Retry from checkpoint** when safe |
| Policy or authorization denial | A non-retryable explanation; no unsafe retry control |
| Worker termination | Stalled execution, intact history, and recovery on worker restart under the same workflow ID |
| Tab close or SSE interruption | The same session restores and streaming resumes after `Last-Event-ID` |
| Approval pending | Exact payload, diff, evidence digests, and the operator's position in the run retained |
| Proposal edited after approval | A new version; the previous permit is invalid |
| Approved | A durable receipt and no dispatch; execute remains separately gated |
| Research only | External RFQ actions disappear while evidence and artifacts remain available |
| External outcome unknown | Reconciliation is required before another send is permitted |

## Production metric

I would own **operator recovery success rate**: the percentage of blocked deep runs
that reach a valid terminal result within 30 minutes of the first operator
intervention, without restarting the run or duplicating a protected action. This
metric couples legibility, recoverability, and idempotency. A speed-only metric
would reward hiding failure rather than designing for it.

## Visual position

Sentinel uses a light editorial operations-desk aesthetic: warm paper, a dark
green session rail, ruled structure, serif display type, compact mono labels, and
acid green reserved for active emphasis. Procurement is accountable document
work, not entertainment AI. Hierarchy comes from type, rules, and columns; state
is never color-only. The design includes responsive collapse, visible focus,
reduced motion, and no remote fonts or imagery.
