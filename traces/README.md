# Native development traces

This directory contains native Codex session JSONL, not summaries or
screenshots. JSON objects are reserialized deterministically with their native
event structure intact.

`manifest.jsonl` is append-only. Every line records:

- session ID, task label, snapshot ID, and source basename;
- source and committed byte/line counts;
- SHA-256 of the source snapshot and committed export;
- the matching transparent redaction file and its counts/hash.

Each `*.redactions.jsonl` line records the export line, JSON pointer, redaction
rule, replacement token, and SHA-256 of the original value. Original secret or
private values are never copied into the audit record.

The exporter redacts only:

- key-shaped OpenAI, Resend, GitHub, Slack, AWS, and bearer credentials;
- non-reserved email identifiers (`example.com`, `example.org`, and
  `example.test` fixtures remain readable);
- absolute `/Users/<name>` personal home prefixes, including paths used as JSON
  object keys.

## Verify committed exports

```bash
./scripts/export_codex_trace.py verify
```

Verification recomputes every committed byte count, line count, and hash;
parses every native JSONL line; rejects duplicate manifest exports; and scans
again for credential, private-email, and personal-path patterns.

## Append the two active sessions after handoff

Do not export these sessions while either task is active. After the PR 12 task
has delivered its final message, append its completed file. After the
implementation parent has delivered its final message, append that completed
file. Use the exact distinct output names below; never replace an earlier
export:

```bash
./scripts/export_codex_trace.py export \
  --source "$HOME/.codex/sessions/2026/07/29/rollout-2026-07-29T20-08-59-019fae50-8037-7070-91c3-b5d7db3acf77.jsonl" \
  --session-id 019fae50-8037-7070-91c3-b5d7db3acf77 \
  --label "PR 12 release readiness" \
  --snapshot-id completed-handoff \
  --output pr-12-release-readiness.completed-handoff.jsonl

./scripts/export_codex_trace.py export \
  --source "$HOME/.codex/sessions/2026/07/29/rollout-2026-07-29T17-51-22-019fadd2-82d7-7780-8979-7f02ca29113c.jsonl" \
  --session-id 019fadd2-82d7-7780-8979-7f02ca29113c \
  --label "implementation parent" \
  --snapshot-id final-parent-handoff \
  --output implementation-parent.final-parent-handoff.jsonl

./scripts/export_codex_trace.py verify
```

This preserves previous committed hashes while allowing the still-running
parent task to append its final native snapshot after integrating PR 12. Commit
the two new exports, their two redaction ledgers, and the two appended manifest
lines together.
