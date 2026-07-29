CREATE TABLE sentinel.integration_records (
    run_id uuid NOT NULL REFERENCES sentinel.runs(run_id) ON DELETE CASCADE,
    record_ref uuid NOT NULL,
    record_kind text NOT NULL CHECK (btrim(record_kind) <> ''),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(payload) = 'object'),
    content bytea,
    filename text,
    media_type text,
    content_sha256 text
        CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[a-f0-9]{64}$'),
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (run_id, record_ref),
    CHECK (
        (content IS NULL AND filename IS NULL AND media_type IS NULL)
        OR (
            content IS NOT NULL
            AND filename IS NOT NULL
            AND btrim(filename) <> ''
            AND media_type IS NOT NULL
            AND btrim(media_type) <> ''
            AND content_sha256 IS NOT NULL
        )
    )
);

CREATE INDEX integration_records_kind_idx
    ON sentinel.integration_records (run_id, record_kind, created_at, record_ref);
