# Post-acceptance credential checklist

This checklist is intentionally inactive. Do not request credentials until all
credential-independent tests, the operator journey, trace verification, and a
human review of the exact controlled action are green.

## Gate zero - required before asking

- [ ] `SENTINEL_MODEL_PROVIDER=fake`
- [ ] `SENTINEL_EMAIL_PROVIDER=fake`
- [ ] `SENTINEL_CREDENTIAL_GATE=fake-only`
- [ ] Full backend and frontend gate passes.
- [ ] Real local PostgreSQL acceptance passes.
- [ ] Real Temporal replay, targeted retry, child cancellation, and worker
      restart acceptance passes.
- [ ] Artifact scoping and download-header tests pass.
- [ ] Approval edit invalidation, single-use permit, controlled recipient,
      duplicate suppression, and unknown-outcome reconciliation tests pass.
- [ ] Trace verifier reports no credential/private-identifier patterns.
- [ ] Human demo recording is complete and contains no secret or private path.
- [ ] Owner explicitly chooses to attempt one controlled external proof.

If any item is false, stop. Fake mode is the submission behavior.

## Minimal credential request

Only after Gate zero, ask the owner for:

1. the selected provider (`resend` only for the implemented adapter);
2. one short-lived/revocable API key passed through the process environment,
   never chat, Git, `.env`, screenshots, traces, or shell history;
3. one recipient address controlled by the owner;
4. an explicit statement authorizing one exact test send to that address.

Do not request OpenAI/model credentials for the email proof. Do not request
Gmail OAuth credentials; Gmail is not an implemented production adapter.

## Configuration and dry verification

- [ ] Set `SENTINEL_CREDENTIAL_GATE=live-approved`.
- [ ] Set `SENTINEL_EMAIL_PROVIDER=resend`.
- [ ] Set `SENTINEL_CONTROLLED_RECIPIENT` to the owner-controlled address.
- [ ] Inject `RESEND_API_KEY` only into the worker/executor process environment.
- [ ] Keep `SENTINEL_DEMO_MODE=false`.
- [ ] Confirm startup rejects a missing controlled recipient.
- [ ] Run adapter contract tests with injected transport; do not send yet.
- [ ] Inspect the exact canonical recipient, subject, body, attachment IDs,
      attachment SHA-256 values, policy revision, and approval expiry.
- [ ] Confirm approval alone produced zero provider dispatch calls.

## One explicitly approved action

- [ ] Obtain fresh, explicit approval for the exact current proposal digest.
- [ ] Consume the single-use permit through the protected executor, never from
      research/browser code.
- [ ] Record the idempotency key and sanitized provider receipt.
- [ ] If the result is unknown, reconcile it. Never issue a blind second send.
- [ ] Confirm a second consumption of the permit is denied.
- [ ] Revoke the provider key immediately after the proof.
- [ ] Scan logs, traces, screenshots, and Git diff again for credentials and
      private recipient data before any submission update.

This PR does not execute this checklist.
