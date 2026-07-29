CREATE TABLE sentinel.run_projection (
    run_id uuid PRIMARY KEY REFERENCES sentinel.runs(run_id) ON DELETE CASCADE,
    parent_run_id uuid,
    title text NOT NULL,
    status text NOT NULL,
    summary text,
    active_phase text,
    request_revision_id uuid,
    policy_revision integer,
    completed_work_items integer NOT NULL DEFAULT 0 CHECK (completed_work_items >= 0),
    total_work_items integer NOT NULL DEFAULT 0 CHECK (total_work_items >= 0),
    active_subagents integer NOT NULL DEFAULT 0 CHECK (active_subagents >= 0),
    blocker_count integer NOT NULL DEFAULT 0 CHECK (blocker_count >= 0),
    event_count bigint NOT NULL DEFAULT 0 CHECK (event_count >= 0),
    last_sequence bigint NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX run_projection_session_history_idx
    ON sentinel.run_projection (updated_at DESC, run_id DESC);

CREATE INDEX run_projection_status_idx
    ON sentinel.run_projection (status, updated_at DESC);

CREATE TABLE sentinel.work_item_projection (
    run_id uuid NOT NULL REFERENCES sentinel.runs(run_id) ON DELETE CASCADE,
    work_item_id uuid NOT NULL,
    parent_work_item_id uuid,
    subagent_id uuid,
    phase text NOT NULL CHECK (btrim(phase) <> ''),
    kind text NOT NULL CHECK (btrim(kind) <> ''),
    label text NOT NULL CHECK (btrim(label) <> ''),
    status text NOT NULL CHECK (btrim(status) <> ''),
    position integer NOT NULL DEFAULT 0,
    completed_units integer CHECK (completed_units IS NULL OR completed_units >= 0),
    total_units integer CHECK (total_units IS NULL OR total_units >= 0),
    blocker text,
    last_sequence bigint NOT NULL CHECK (last_sequence >= 1),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (run_id, work_item_id),
    FOREIGN KEY (run_id, parent_work_item_id)
        REFERENCES sentinel.work_item_projection(run_id, work_item_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (
        completed_units IS NULL
        OR total_units IS NULL
        OR completed_units <= total_units
    )
);

CREATE INDEX work_item_projection_tree_idx
    ON sentinel.work_item_projection (run_id, phase, position, work_item_id);

CREATE INDEX work_item_projection_subagent_idx
    ON sentinel.work_item_projection (run_id, subagent_id)
    WHERE subagent_id IS NOT NULL;

CREATE TABLE sentinel.subagent_projection (
    run_id uuid NOT NULL REFERENCES sentinel.runs(run_id) ON DELETE CASCADE,
    subagent_id uuid NOT NULL,
    parent_subagent_id uuid,
    child_run_id uuid REFERENCES sentinel.runs(run_id) DEFERRABLE INITIALLY DEFERRED,
    label text NOT NULL CHECK (btrim(label) <> ''),
    goal text NOT NULL CHECK (btrim(goal) <> ''),
    status text NOT NULL CHECK (btrim(status) <> ''),
    tool_scope jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(tool_scope) = 'array'),
    last_sequence bigint NOT NULL CHECK (last_sequence >= 1),
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (run_id, subagent_id),
    FOREIGN KEY (run_id, parent_subagent_id)
        REFERENCES sentinel.subagent_projection(run_id, subagent_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX subagent_projection_tree_idx
    ON sentinel.subagent_projection (run_id, parent_subagent_id, subagent_id);

CREATE OR REPLACE FUNCTION sentinel.reject_journal_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'sentinel.run_events is append-only';
END;
$$;

CREATE TRIGGER run_events_reject_update
BEFORE UPDATE ON sentinel.run_events
FOR EACH ROW EXECUTE FUNCTION sentinel.reject_journal_mutation();

CREATE TRIGGER run_events_reject_delete
BEFORE DELETE ON sentinel.run_events
FOR EACH ROW EXECUTE FUNCTION sentinel.reject_journal_mutation();
