"""Trace integrity tests for native JSONL redaction and append-only manifests."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from scripts.export_codex_trace import main, redact_string


def test_redaction_is_narrow_and_records_opaque_original_hashes() -> None:
    redacted, changes = redact_string(
        "cwd=/Users/alice/project mail=alice@private.invalid "
        "fixture=demo@example.test key=sk-proj-abcdefghijklmnop"
    )

    assert redacted == (
        "cwd=$USER_HOME/project mail=[REDACTED_PRIVATE_EMAIL] "
        "fixture=demo@example.test key=[REDACTED_OPENAI_KEY]"
    )
    assert [change[0] for change in changes] == [
        "absolute_personal_path",
        "private_email",
        "openai_key",
    ]
    assert all(len(change[2]) == 64 for change in changes)


def test_export_and_verify_append_only_native_jsonl(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "rollout-session.jsonl"
    source.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": "session-1",
                    "cwd": "/Users/alice/project",
                },
            }
        )
        + "\n"
    )
    trace_dir = tmp_path / "traces"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_codex_trace.py",
            "export",
            "--source",
            str(source),
            "--session-id",
            "session-1",
            "--label",
            "unit proof",
            "--snapshot-id",
            "complete",
            "--output",
            "session-1.complete.jsonl",
            "--trace-dir",
            str(trace_dir),
        ],
    )
    assert main() == 0
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_codex_trace.py",
            "verify",
            "--trace-dir",
            str(trace_dir),
        ],
    )
    assert main() == 0
    exported = (trace_dir / "session-1.complete.jsonl").read_text()
    assert "$USER_HOME/project" in exported
    assert "/Users/alice" not in exported
    manifest = [
        json.loads(line) for line in (trace_dir / "manifest.jsonl").read_text().splitlines()
    ]
    assert manifest[0]["source_filename"] == source.name
    assert manifest[0]["export_line_count"] == 1
