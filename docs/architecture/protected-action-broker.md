# Protected-action broker

Research and browser code cannot execute external effects. A protected action
must cross a deterministic broker with four separate checks:

1. A proposal version stores canonical payload bytes and attachment digests.
2. Approval binds one policy decision, proposal version, payload digest,
   attachment manifest, approver, expiry, and single-use nonce.
3. Commit-time authorization rechecks executor capability, current organization
   policy revision, proposal version, payload and attachment digests, and the
   controlled recipient.
4. Execution receives a stable idempotency key and enters the explicit
   external-outcome state machine.

Editing a proposal creates a new version and makes every permit for an older
version unusable. A permit is consumed atomically before dispatch and cannot be
reused.

An ambiguous provider timeout enters `OUTCOME_UNKNOWN`. It cannot return to
dispatch until reconciliation produces `SAFE_TO_RETRY`; reconciliation may
instead confirm the effect or require an operator.

The in-memory broker keeps the invariants fast to test without credentials.
Production composition installs the PostgreSQL broker on the application-owned
connection pool. Proposal versions, decisions, permits, action intents, and
outcomes survive restart; a row lock makes permit consumption and intent
creation a single transaction.
