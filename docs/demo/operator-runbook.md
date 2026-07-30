# Operator demo runbook

This is a recording checklist from the operator's point of view, not a code
walkthrough. The recording is a human submission step. Do not claim a video
exists until a person has recorded and reviewed it.

## Producer preflight - no credentials

- Confirm `.env` still has `SENTINEL_MODEL_PROVIDER=fake`,
  `SENTINEL_EMAIL_PROVIDER=fake`, and
  `SENTINEL_CREDENTIAL_GATE=fake-only`.
- Enable the visible demo profile:

  ```dotenv
  SENTINEL_DEMO_MODE=true
  SENTINEL_DEMO_STEP_DELAY_MS=1200
  SENTINEL_DEMO_FAILURE_STEP=candidate.2.snapshot
  ```

- Start PostgreSQL, Temporal, and MinIO with `make infra-up`.
- Start `.venv/bin/sentinel-api`, `.venv/bin/sentinel-worker`, and
  `npm run dev:web` in three separate terminals with `.env` loaded.
- Open `http://localhost:5173`. Keep the worker terminal available only for the
  planned process interruption; do not show source code.
- Verify the left rail says the projection is durable/fake/no-dispatch and the
  run header says `DEMO MODE`.
- Start a clean screen recording. Credentials, `.env`, terminals containing
  environment output, and private browser content must never appear.

## The operator journey

### 1. Start a hard run

- Select **Create new request**.
- Enter:
  - title: `Replace washdown transfer pumps`
  - item/service: `316L sanitary transfer pump`
  - need: `Three continuous-duty pumps, food-contact compatible, available in 30 days`
  - quantity: `3`
  - unit: `each`
- Leave autonomy on **Ask before external contact** (default dropdown). Mention
  the other modes once: research only, approve and hold.
- Select **Start run**.
- Point out the **status hero first** (what is happening / how far), then the
  work tree / evidence / outputs stage. Open **Truth & source** only briefly for
  honesty. Expand nesting lightly — not a tool-log tour.

### 2. Break the tool path and recover

- Let the configured `candidate.2.snapshot` failure occur.
- Wait for Temporal's automatic attempts to exhaust. The run must become
  **blocked**, the branch must name a transient failure and exact attempt, and
  **Retry from checkpoint** must be enabled.
- State what remains safe: the durable run and completed journal entries still
  exist; no external action occurred.
- Select **Retry from checkpoint** once. The run should enter **recovering** and
  continue on the next workflow attempt. Do not start a new run.

### 3. Interrupt the real child, queue context, and resume

- While the recovered run is active, select **Pause run**. This is the
  operator-visible child cancellation: Temporal cooperatively cancels the
  active child/activity and holds the parent at a durable safe boundary.
- In Operator instructions, keep **Queue** selected and enter:
  `Prefer suppliers with documented washdown service support.`
- Select **Queue instruction** and show its acknowledgement/history.
- Select **Resume run**. Show the same run ID and revision continuing.

### 4. Redirect with selective reuse

- Choose **Redirect** and enter:
  `Require delivery in 21 days; preserve already verified supplier evidence.`
- Select **Apply redirect**.
- Show that the request revision increments. The durable
  `integration.selective_reuse` event retains candidate/evidence record
  references while evaluation, artifacts, and proposal outputs are invalidated
  and regenerated for the changed requirement.
- Explain the operator outcome only: verified source work is retained where
  safe; dependent decisions are recomputed.

### 5. Close and reopen

- Close the browser tab completely while the run is active.
- Wait several seconds and reopen `http://localhost:5173`.
- Show that Run history restores the same run ID and latest revision from
  PostgreSQL. The stream resumes after its last durable event through
  `Last-Event-ID`; the run is not recreated.

### 6. Terminate and restart the real worker

- While work is active, stop the actual `sentinel-worker` process with
  `Ctrl-C`. Do not stop the API or PostgreSQL.
- In the workbench, show that history and artifacts already produced remain
  readable. Progress may stop; there must be no stack trace in the UI.
- Restart `.venv/bin/sentinel-worker` with the same `.env`.
- Show the same Temporal workflow ID resume and complete without duplicating
  already journaled tool completions or protected effects.

### 7. Inspect evidence and deliverables

- Use the keyboard to move through **Comparison**, **Evidence**, and
  **Requirements**.
- Select one claim and show source label, exact excerpt, observation time, and
  content digest. Say explicitly that demo source content is deterministic
  local evidence, not live market data.
- Download at least the comparison workbook and RFQ package from the Artifact
  rail. Open them only if the recording can do so without exposing local
  personal paths.

### 8. Edit, approve, invalidate, and reapprove

- In the RFQ proposal, inspect **Exact preview** and the bound attachment
  digests.
- Edit the subject/body and save. Show that this creates a new version and the
  diff names the invalidated digest.
- Select **Approve exact vN - no send**. Show the receipt: approval occurred,
  dispatch did not.
- Select **Edit and revoke approval**, change one word, and save. Confirm the
  status returns to **pending approval** and the old approval cannot cover the
  new digest.
- Approve the new exact version only if the preview is correct. Again show the
  no-dispatch receipt.

### 9. Stop at the credential gate

- End the run after artifact download and fake-mode approval.
- Do **not** configure a provider, request a credential, call a live model,
  browse the public web, reconcile a live receipt, or send email.
- State on camera: “The remaining real-send proof requires the repository's
  fake-mode gate to be green, credentials supplied outside the recording and
  repository, a controlled recipient, and a separate explicit human approval.”

## Recording acceptance checklist

- [ ] Hard run shows more than 20 tool completions and a real nested Temporal child.
- [ ] Deterministic tool failure becomes blocked and recovers by targeted retry.
- [ ] Pause visibly cancels active child work; resume keeps the same run.
- [ ] A queued instruction is acknowledged and applied.
- [ ] Redirect increments revision and selectively retains safe evidence.
- [ ] Tab close/reopen restores the same durable session.
- [ ] Real worker stop/restart resumes without duplicate protected effects.
- [ ] Autonomy is set in plain language; truth boundary says local suppliers / no send.
- [ ] Proposal edit shows a diff; approval says no send.
- [ ] Edit after approval returns to pending and requires a new exact approval.
- [ ] At least two scoped artifacts download.
- [ ] Fake/projection disclosure is visible.
- [ ] No terminal/code walkthrough, credential, private path, or claimed live data.
- [ ] Recording ends before any real send.

## Automated pre-recording gate

Run these before recording:

```bash
make check
npm run build
docker compose config --quiet
make trace-verify
```

With local Compose services healthy:

```bash
SENTINEL_TEST_DATABASE_URL=postgresql://sentinel:sentinel@localhost:5432/sentinel \
  .venv/bin/pytest -q apps/api/tests/persistence \
  apps/api/tests/protected_actions/test_postgres.py \
  apps/api/tests/email/test_postgres_email_execution.py \
  apps/api/tests/integration/test_postgres_integration_repository.py

SENTINEL_RUN_TEMPORAL_TESTS=1 \
  .venv/bin/pytest -q apps/api/tests/workflows/test_temporal_runtime.py \
  apps/api/tests/integration/test_temporal_end_to_end.py
```

If a command is skipped or the local service is unavailable, record that as a
blocker; do not call it passing evidence.
