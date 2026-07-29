# Sentinel persistence migrations

These migrations own the `sentinel` PostgreSQL schema. Apply them through
`PostgresEventStore.migrate()` or `apply_migrations()` before serving traffic.
The runner serializes concurrent migrators with an advisory lock and refuses to
continue if an already-applied file's checksum changes.

Migration order:

1. `0001_run_journal_and_outbox.sql` creates current run state, the append-only
   per-run event journal, and transactional outbox.
2. `0002_operator_projections.sql` creates session, work-tree, and subagent
   projections and installs the journal immutability triggers.
3. `0003_protected_actions.sql` stores immutable proposal versions, policy
   decisions, single-use approval permits, action intents, and external-effect
   outcomes.
4. `0004_email_execution.sql` extends external-effect outcomes with payload-bound
   email request fingerprints, attempt counts, sanitized receipts, and audit
   transitions.

## Projection event payloads

Every event updates the run's durable cursor and event count. The following
event families additionally update read models in the same transaction:

- `run.*`: may include `title`, `status`, `summary`, `active_phase`,
  `request_revision_id`, `policy_revision`, `started_at`, or `completed_at`.
- `work.*`: requires the envelope's `work_item_id`. Its first event also
  requires `phase`, `kind`, and `label`; later events may patch any work
  projection field.
- `subagent.*`: requires `payload.subagent_id`. Its first event also requires
  `label` and `goal`; later events may patch status, hierarchy, child run,
  tool scope, or lifecycle timestamps.

Unknown event families remain journaled and delivered but do not create a
specialized projection. Callers should pass domain models using
`model_dump(mode="json")` so payload values are JSON-native.

## Application wiring

The FastAPI lifespan composes `event_store_runtime()`, exposes the yielded store
on `app.state.event_store`, and mounts resumable event delivery under `/api`.
Local development may set `SENTINEL_PERSISTENCE_MODE=postgres` and
`SENTINEL_AUTO_MIGRATE=true`. Production deployments should normally apply
migrations as a release step and leave automatic migration disabled.
