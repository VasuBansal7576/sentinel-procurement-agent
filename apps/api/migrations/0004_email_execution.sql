ALTER TABLE sentinel.action_outcomes
    ADD COLUMN provider_request_fingerprint text
        CHECK (
            provider_request_fingerprint IS NULL
            OR provider_request_fingerprint ~ '^[a-f0-9]{64}$'
        ),
    ADD COLUMN idempotency_key_sha256 text
        CHECK (
            idempotency_key_sha256 IS NULL
            OR idempotency_key_sha256 ~ '^[a-f0-9]{64}$'
        ),
    ADD COLUMN attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    ADD COLUMN provider text,
    ADD COLUMN receipt jsonb
        CHECK (receipt IS NULL OR jsonb_typeof(receipt) = 'object'),
    ADD COLUMN audit_events jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(audit_events) = 'array');

CREATE INDEX action_outcomes_state_idx
    ON sentinel.action_outcomes (state, updated_at);
