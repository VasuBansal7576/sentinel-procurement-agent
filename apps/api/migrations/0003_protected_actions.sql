CREATE TABLE sentinel.proposals (
    proposal_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES sentinel.runs(run_id) ON DELETE CASCADE,
    request_revision_id uuid NOT NULL,
    current_version integer NOT NULL DEFAULT 1 CHECK (current_version >= 1),
    status text NOT NULL CHECK (btrim(status) <> ''),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX proposals_run_idx
    ON sentinel.proposals (run_id, updated_at DESC);

CREATE TABLE sentinel.proposal_versions (
    proposal_id uuid NOT NULL REFERENCES sentinel.proposals(proposal_id) ON DELETE CASCADE,
    version integer NOT NULL CHECK (version >= 1),
    action_type text NOT NULL CHECK (btrim(action_type) <> ''),
    canonical_payload text NOT NULL CHECK (btrim(canonical_payload) <> ''),
    canonical_payload_sha256 text NOT NULL
        CHECK (canonical_payload_sha256 ~ '^[a-f0-9]{64}$'),
    attachment_artifact_ids uuid[] NOT NULL DEFAULT '{}',
    attachment_sha256 text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (proposal_id, version),
    CHECK (cardinality(attachment_artifact_ids) = cardinality(attachment_sha256)),
    CHECK (
        cardinality(attachment_sha256) = 0
        OR array_to_string(attachment_sha256, ',')
            ~ '^([a-f0-9]{64})(,[a-f0-9]{64})*$'
    )
);

CREATE TABLE sentinel.policy_decisions (
    policy_decision_id uuid PRIMARY KEY,
    proposal_id uuid NOT NULL,
    proposal_version integer NOT NULL,
    action text NOT NULL CHECK (btrim(action) <> ''),
    allowed boolean NOT NULL,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    organization_policy_id uuid NOT NULL,
    organization_revision integer NOT NULL CHECK (organization_revision >= 1),
    decided_at timestamptz NOT NULL,
    FOREIGN KEY (proposal_id, proposal_version)
        REFERENCES sentinel.proposal_versions(proposal_id, version)
);

CREATE TABLE sentinel.approval_permits (
    permit_id uuid PRIMARY KEY,
    proposal_id uuid NOT NULL,
    proposal_version integer NOT NULL,
    action_type text NOT NULL CHECK (btrim(action_type) <> ''),
    canonical_payload_sha256 text NOT NULL
        CHECK (canonical_payload_sha256 ~ '^[a-f0-9]{64}$'),
    attachment_sha256 text[] NOT NULL DEFAULT '{}',
    policy_decision_id uuid NOT NULL UNIQUE
        REFERENCES sentinel.policy_decisions(policy_decision_id),
    organization_policy_id uuid NOT NULL,
    organization_revision integer NOT NULL CHECK (organization_revision >= 1),
    risk_class text NOT NULL CHECK (btrim(risk_class) <> ''),
    approver_id uuid NOT NULL,
    approved_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    nonce uuid NOT NULL UNIQUE,
    consumed_at timestamptz,
    FOREIGN KEY (proposal_id, proposal_version)
        REFERENCES sentinel.proposal_versions(proposal_id, version),
    CHECK (expires_at > approved_at),
    CHECK (consumed_at IS NULL OR consumed_at >= approved_at)
);

CREATE INDEX approval_permits_proposal_idx
    ON sentinel.approval_permits (proposal_id, proposal_version);

CREATE TABLE sentinel.action_intents (
    action_intent_id uuid PRIMARY KEY,
    proposal_id uuid NOT NULL,
    proposal_version integer NOT NULL,
    permit_id uuid NOT NULL UNIQUE REFERENCES sentinel.approval_permits(permit_id),
    idempotency_key text NOT NULL UNIQUE CHECK (btrim(idempotency_key) <> ''),
    payload_fingerprint text NOT NULL
        CHECK (payload_fingerprint ~ '^[a-f0-9]{64}$'),
    created_at timestamptz NOT NULL,
    FOREIGN KEY (proposal_id, proposal_version)
        REFERENCES sentinel.proposal_versions(proposal_id, version)
);

CREATE TABLE sentinel.action_outcomes (
    action_intent_id uuid PRIMARY KEY
        REFERENCES sentinel.action_intents(action_intent_id) ON DELETE CASCADE,
    state text NOT NULL CHECK (btrim(state) <> ''),
    provider_reference text,
    detail text,
    updated_at timestamptz NOT NULL
);
