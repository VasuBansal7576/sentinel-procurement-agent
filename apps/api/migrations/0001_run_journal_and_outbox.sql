CREATE TABLE sentinel.runs (
    run_id uuid PRIMARY KEY,
    parent_run_id uuid REFERENCES sentinel.runs(run_id) DEFERRABLE INITIALLY DEFERRED,
    procurement_case_id uuid,
    request_revision_id uuid,
    policy_revision integer CHECK (policy_revision IS NULL OR policy_revision >= 1),
    title text NOT NULL CHECK (btrim(title) <> ''),
    status text NOT NULL CHECK (btrim(status) <> ''),
    summary text,
    next_event_sequence bigint NOT NULL DEFAULT 1 CHECK (next_event_sequence >= 1),
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX runs_history_idx
    ON sentinel.runs (created_at DESC, run_id DESC);

CREATE INDEX runs_parent_idx
    ON sentinel.runs (parent_run_id)
    WHERE parent_run_id IS NOT NULL;

CREATE TABLE sentinel.run_events (
    event_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES sentinel.runs(run_id),
    per_run_sequence bigint NOT NULL CHECK (per_run_sequence >= 1),
    parent_run_id uuid,
    work_item_id uuid,
    actor_id text,
    event_type text NOT NULL CHECK (btrim(event_type) <> ''),
    status text NOT NULL CHECK (btrim(status) <> ''),
    causation_id uuid,
    correlation_id uuid,
    idempotency_key text,
    summary text NOT NULL CHECK (btrim(summary) <> ''),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(payload) = 'object'),
    payload_ref text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (run_id, per_run_sequence)
);

CREATE INDEX run_events_replay_idx
    ON sentinel.run_events (run_id, per_run_sequence);

CREATE INDEX run_events_work_item_idx
    ON sentinel.run_events (run_id, work_item_id, per_run_sequence)
    WHERE work_item_id IS NOT NULL;

CREATE INDEX run_events_correlation_idx
    ON sentinel.run_events (correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE UNIQUE INDEX run_events_idempotency_idx
    ON sentinel.run_events (run_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE sentinel.event_outbox (
    outbox_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE REFERENCES sentinel.run_events(event_id),
    run_id uuid NOT NULL,
    per_run_sequence bigint NOT NULL,
    topic text NOT NULL CHECK (btrim(topic) <> ''),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    claimed_by text,
    claimed_until timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error text,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (claimed_by IS NULL AND claimed_until IS NULL)
        OR (claimed_by IS NOT NULL AND claimed_until IS NOT NULL)
    )
);

CREATE INDEX event_outbox_pending_idx
    ON sentinel.event_outbox (available_at, outbox_id)
    WHERE published_at IS NULL;

CREATE INDEX event_outbox_run_idx
    ON sentinel.event_outbox (run_id, per_run_sequence);
