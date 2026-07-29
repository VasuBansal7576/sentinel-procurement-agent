# Email execution boundary

Email is a protected external effect. Research, browser, helper, and evidence
capabilities never receive an email provider or transport. The only entry point
to the sink is an `AuthorizedAction` created by the durable protected-action
broker.

## Boundary

`EmailExecutionService` performs the following checks before invoking a
provider:

1. Require the concrete `AuthorizedAction` contract.
2. Recompute the SHA-256 digest of the canonical approved payload.
3. Decode only the strict `to`, `subject`, and `body` contract.
4. Recheck the current controlled recipient at the sink.
5. Atomically claim the existing `APPROVED`, `SAFE_TO_RETRY`, or
   `FAILED_BEFORE_EFFECT` outcome.
6. Dispatch with the broker-generated stable idempotency key.

The store uses compare-and-set transitions. Concurrent or repeated execution
therefore lets only one worker call the provider. A confirmed action is
terminal. It also stores a fingerprint of the complete provider-neutral request
(including the configured sender), so a retry cannot reuse the same
idempotency key with changed provider request bytes.

Reconciliation is deliberately still allowed after a policy revision: it can
only inspect an already-attempted effect and cannot send a new message. Any
subsequent retry re-enters execution and rechecks the current controlled
recipient.

An ambiguous response is `OUTCOME_UNKNOWN`, never failure. Calling execution
again does not dispatch. Reconciliation must first transition through
`RECONCILING` and produce one of:

- `CONFIRMED` with a sanitized provider receipt;
- `SAFE_TO_RETRY`, after which the same idempotency key is replayed; or
- `NEEDS_OPERATOR`, which is terminal.

## Provider and credential isolation

`EmailProvider` is provider-neutral. `DeterministicFakeEmailProvider` scripts
confirmed, pre-effect failure, ambiguous-confirmed, ambiguous-not-sent, and
unresolved outcomes without I/O.

`ResendEmailProvider` translates neutral requests to `/emails` and maps
provider responses into the explicit outcomes. It accepts only an injected
`ResendTransport`; it has no API-key parameter, never creates an authorization
header, and never logs transport errors or response bodies. Production
authentication belongs to the transport installed by app composition.

A transport failure must declare whether an effect was impossible
(`NOT_APPLIED`) or possible (`UNKNOWN`). HTTP 4xx responses are treated as
definite rejection before effect. HTTP 5xx responses are conservative unknown
outcomes. When an unknown result has no provider reference, replay is allowed
only inside the configured Resend idempotency window; after that, an operator is
required.

## Receipts and audit

Receipts retain only provider name, provider message ID, acceptance time, and
status. Audit events retain state, timestamps, provider reference, and
controlled details. Message bodies, authorization material, transport error
text, response bodies, and full idempotency keys are not stored in audit
events.

## Parent integration request

App wiring and persistence integration remain parent-owned:

1. Install the email execution service only in the protected action executor,
   never in research/browser dependency graphs.
2. Read the sender and controlled recipient from the parent-owned effective
   configuration/policy at execution time.
3. Provide an authenticated Resend transport from the secret-owning runtime;
   do not pass credentials into this package.
4. Implement `EmailExecutionStore` over the existing `action_intents` and
   `action_outcomes` rows with an atomic PostgreSQL
   `UPDATE ... WHERE action_intent_id = %s AND state = %s RETURNING ...`; zero
   returned rows must become `ExecutionStateConflict`.
5. Persist the provider-request fingerprint and sanitized receipt/audit
   envelope in parent-owned storage. If structured columns are desired, add
   them in a parent-owned migration.
6. Keep the final controlled external send behind an explicit user/parent gate.
   Unit and integration tests use only injected fakes and must never perform a
   real send.
