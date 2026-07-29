# Sentinel domain contract ownership

The contracts under `sentinel_api.domain` are centrally owned. Feature branches
consume them and may propose changes, but only the implementation parent merges
cross-module contract changes.

## Stable language

The stable procurement model describes cases, request revisions, lots, line
items, requirements, category fields, suppliers, candidates, evidence,
artifacts, proposals, approvals, action intents, and outcomes. Category-specific
attributes are runtime data expressed through `CategorySchema`; they are not
new application code paths.

## Enforced invariants

- Contracts are immutable and reject unknown fields.
- A later request revision must reference its predecessor.
- Requirement and category field keys are unique within their scope.
- Money normalizes three-letter currency codes.
- Type-specific criteria require their unit, currency, or enumeration.
- Request policy may tighten but cannot expand organization authority.
- Platform protected-action invariants cannot be disabled by configuration.
- Research actors cannot receive a protected action sink.
- Work invalidation is dependency-driven and propagates transitively.
- Unrelated raw evidence survives a request change.

## Versioning rule

Breaking contract changes require an explicit migration and dependent feature
updates in the same merge train. Two incompatible contract versions must not be
kept merely to avoid resolving a branch conflict.
