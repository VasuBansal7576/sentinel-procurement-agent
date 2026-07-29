# PR 5 implementation plan: browser and evidence system

## Scope and dependency assumptions

This worker owns the public-research boundary: search and fetch interfaces,
isolated browser sessions, evidence snapshot persistence abstractions,
claim-level provenance, freshness and conflict handling, untrusted-content
taint, prompt-injection boundaries, and adaptive browser-helper contracts.

The implementation consumes the immutable contracts in `sentinel_api.domain`
at commit `dcd0ddf`. It assumes PR 3 or a later integration PR will wire the
interfaces into the durable runtime. It adds no runtime dependency: concrete
Playwright, search-provider, and S3-compatible adapters remain replaceable
integration work and require parent-owned manifest decisions.

## File ownership

Owned by this PR:

- `apps/api/src/sentinel_api/research/`
- `apps/api/tests/research/`
- `docs/implementation/pr-05-browser-evidence.md`

Not owned by this PR:

- `apps/api/src/sentinel_api/domain/`
- root and application dependency manifests
- cross-cutting CI, runtime orchestration, approval, and protected-action code

Any required change outside the owned paths must be reported to the
implementation parent before it is made.

## Implementation sequence

1. Define typed async search and fetch provider contracts whose results always
   carry untrusted taint.
2. Implement a broker that issues opaque, run- and actor-bound handles and
   gives each research actor a distinct browser context with restricted egress.
3. Define adaptive helper patches with canonical content digests, explicit
   browser-only capability manifests, and per-run retention.
4. Add content-addressed snapshot storage interfaces and an in-memory reference
   implementation for deterministic tests.
5. Build observations from verified exact spans and stored snapshot digests.
6. Add deterministic freshness state and conflict detection/resolution without
   silently inventing values.
7. Enforce capability boundaries so research actors cannot receive credentials
   or protected sinks, even when untrusted content asks for them.

## Test matrix

- Unit: URL policy, taint propagation, snapshot immutability/deduplication,
  exact-span offsets and hashes, freshness boundaries, conflict grouping and
  resolution, helper canonicalization and tamper detection.
- Integration: fetch result to stored snapshot to domain
  `EvidenceObservation`, including artifact/source linkage and derived taint.
- Adversarial: cross-run and cross-actor browser-handle reuse; disallowed
  schemes, domains, redirects, and private-network targets; credential and
  protected-capability requests; prompt injections in HTML and tool results;
  altered content/spans; stale volatile claims; helper digest substitution.

## Risks and mitigations

- PR 3 may add overlapping tool/runtime abstractions. Keep provider, broker,
  storage, and helper boundaries structural and adapter-oriented.
- A lightweight broker abstraction is not a production sandbox. Make the
  isolation contract explicit and testable; defer concrete Playwright and
  microVM adapters instead of overstating isolation.
- Prompt-injection detection is fallible. Treat all remote content as tainted
  and make least privilege the boundary; detection produces telemetry only.
- In-memory persistence is test/reference infrastructure. Content addressing
  and immutable write semantics allow an S3-compatible implementation later.

## Exit criteria

- Search, fetch, browser, evidence, and helper interfaces are strict and typed.
- Isolation, provenance, freshness/conflict, taint, and injection-boundary
  behavior have complete unit, integration, and adversarial coverage.
- Existing tests remain green.
- Ruff lint/format, strict mypy, and relevant pytest gates pass.
- Changes are committed coherently on `codex/pr-05-browser-evidence`; nothing
  is pushed, merged, or written to another worktree.
