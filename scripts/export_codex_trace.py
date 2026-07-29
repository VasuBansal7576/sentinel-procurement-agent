#!/usr/bin/env python3
"""Deterministically redact, export, manifest, and verify native Codex JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PERSONAL_PATH = re.compile(r"/Users/[A-Za-z0-9._-]+")
# The extra backslash guard prevents JSON escape sequences such as
# ``\n@pytest.mark.asyncio`` from being mistaken for email addresses.
EMAIL = re.compile(r"(?<![\\\w.+-])[\w.+-]{2,}@([\w.-]+\.[A-Za-z]{2,})(?![\w.-])")
SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.test"}
CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}\b")),
    ("resend_key", re.compile(r"\bre_[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "bearer_token",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}\b"),
    ),
)


@dataclass(frozen=True)
class Redaction:
    line: int
    pointer: str
    rule: str
    replacement: str
    original_sha256: str

    def as_json(self) -> dict[str, object]:
        return {
            "line": self.line,
            "pointer": self.pointer,
            "rule": self.rule,
            "replacement": self.replacement,
            "original_sha256": self.original_sha256,
        }


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def line_count(data: bytes) -> int:
    return len(data.splitlines())


def json_pointer(parent: str, key: str | int) -> str:
    escaped = str(key).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"


def redact_string(value: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Return redacted text and opaque audit facts, never original values."""

    changes: list[tuple[str, str, str]] = []

    def replace_match(rule: str, replacement: str):
        def replace(match: re.Match[str]) -> str:
            original = match.group(0)
            changes.append((rule, replacement, digest(original.encode())))
            return replacement

        return replace

    redacted = PERSONAL_PATH.sub(
        replace_match("absolute_personal_path", "$USER_HOME"),
        value,
    )

    def replace_email(match: re.Match[str]) -> str:
        domain = match.group(1).lower()
        if domain in SAFE_EMAIL_DOMAINS:
            return match.group(0)
        replacement = "[REDACTED_PRIVATE_EMAIL]"
        changes.append(("private_email", replacement, digest(match.group(0).encode())))
        return replacement

    redacted = EMAIL.sub(replace_email, redacted)
    for rule, pattern in CREDENTIAL_PATTERNS:
        replacement = f"[REDACTED_{rule.upper()}]"
        redacted = pattern.sub(replace_match(rule, replacement), redacted)
    return redacted, changes


def redact_value(
    value: Any,
    *,
    line: int,
    pointer: str = "",
) -> tuple[Any, list[Redaction]]:
    if isinstance(value, str):
        redacted, changes = redact_string(value)
        return redacted, [
            Redaction(
                line=line,
                pointer=pointer or "/",
                rule=rule,
                replacement=replacement,
                original_sha256=original_sha256,
            )
            for rule, replacement, original_sha256 in changes
        ]
    if isinstance(value, list):
        result: list[Any] = []
        redactions: list[Redaction] = []
        for index, item in enumerate(value):
            next_value, next_redactions = redact_value(
                item,
                line=line,
                pointer=json_pointer(pointer, index),
            )
            result.append(next_value)
            redactions.extend(next_redactions)
        return result, redactions
    if isinstance(value, dict):
        result = {}
        redactions = []
        for key, item in value.items():
            redacted_key, key_changes = redact_string(str(key))
            item_pointer = json_pointer(pointer, redacted_key)
            redactions.extend(
                Redaction(
                    line=line,
                    pointer=f"{item_pointer}#key",
                    rule=rule,
                    replacement=replacement,
                    original_sha256=original_sha256,
                )
                for rule, replacement, original_sha256 in key_changes
            )
            if redacted_key in result:
                raise ValueError("redaction produced duplicate JSON object keys")
            next_value, next_redactions = redact_value(
                item,
                line=line,
                pointer=item_pointer,
            )
            result[redacted_key] = next_value
            redactions.extend(next_redactions)
        return result, redactions
    return value, []


def serialized_jsonl(values: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        (
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode()
        for value in values
    )


def relative_trace_path(trace_dir: Path, path: Path) -> str:
    resolved_dir = trace_dir.resolve()
    resolved = path.resolve()
    if resolved.parent != resolved_dir:
        raise ValueError(
            "export and redaction files must be direct children of traces/"
        )
    return path.name


def read_manifest(manifest: Path) -> list[dict[str, Any]]:
    if not manifest.exists():
        return []
    return [json.loads(line) for line in manifest.read_text().splitlines() if line]


def export_trace(args: argparse.Namespace) -> int:
    source = Path(args.source)
    trace_dir = Path(args.trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    output = trace_dir / args.output
    redactions_path = output.with_suffix(".redactions.jsonl")
    manifest = trace_dir / "manifest.jsonl"
    relative_trace_path(trace_dir, output)
    relative_trace_path(trace_dir, redactions_path)
    if output.exists() or redactions_path.exists():
        raise ValueError(
            "snapshot output already exists; append a newly named snapshot"
        )

    source_bytes = source.read_bytes()
    exported_values: list[dict[str, Any]] = []
    redactions: list[Redaction] = []
    for number, raw_line in enumerate(source_bytes.splitlines(), start=1):
        parsed = json.loads(raw_line)
        if not isinstance(parsed, dict):
            raise TypeError(f"source line {number} is not a JSON object")
        redacted, line_redactions = redact_value(parsed, line=number)
        exported_values.append(redacted)
        redactions.extend(line_redactions)

    exported_bytes = serialized_jsonl(exported_values)
    redaction_bytes = serialized_jsonl(redaction.as_json() for redaction in redactions)
    output.write_bytes(exported_bytes)
    redactions_path.write_bytes(redaction_bytes)

    existing = read_manifest(manifest)
    if any(entry["export_filename"] == output.name for entry in existing):
        raise ValueError("manifest already contains this export filename")
    entry = {
        "schema_version": SCHEMA_VERSION,
        "label": args.label,
        "session_id": args.session_id,
        "snapshot_id": args.snapshot_id,
        "source_filename": source.name,
        "source_byte_count": len(source_bytes),
        "source_line_count": line_count(source_bytes),
        "source_sha256": digest(source_bytes),
        "export_filename": output.name,
        "export_byte_count": len(exported_bytes),
        "export_line_count": line_count(exported_bytes),
        "export_sha256": digest(exported_bytes),
        "redactions_filename": redactions_path.name,
        "redactions_byte_count": len(redaction_bytes),
        "redactions_line_count": line_count(redaction_bytes),
        "redactions_sha256": digest(redaction_bytes),
    }
    with manifest.open("ab") as stream:
        stream.write(serialized_jsonl([entry]))
    print(
        f"exported {entry['export_line_count']} lines to {output.name}; "
        f"{entry['redactions_line_count']} redactions; sha256={entry['export_sha256']}"
    )
    return 0


def unsafe_findings(text: str) -> list[str]:
    findings = []
    if PERSONAL_PATH.search(text):
        findings.append("absolute_personal_path")
    for rule, pattern in CREDENTIAL_PATTERNS:
        if pattern.search(text):
            findings.append(rule)
    for match in EMAIL.finditer(text):
        if match.group(1).lower() not in SAFE_EMAIL_DOMAINS:
            findings.append("private_email")
            break
    return findings


def verify_traces(args: argparse.Namespace) -> int:
    trace_dir = Path(args.trace_dir)
    manifest_path = trace_dir / "manifest.jsonl"
    entries = read_manifest(manifest_path)
    if not entries:
        raise ValueError("trace manifest has no entries")
    errors: list[str] = []
    seen_exports: set[str] = set()
    for entry in entries:
        export_name = str(entry["export_filename"])
        if export_name in seen_exports:
            errors.append(f"duplicate manifest export: {export_name}")
            continue
        seen_exports.add(export_name)
        for prefix in ("export", "redactions"):
            path = trace_dir / str(entry[f"{prefix}_filename"])
            if not path.is_file():
                errors.append(f"missing {prefix} file: {path.name}")
                continue
            data = path.read_bytes()
            if len(data) != entry[f"{prefix}_byte_count"]:
                errors.append(f"{path.name}: byte count mismatch")
            if line_count(data) != entry[f"{prefix}_line_count"]:
                errors.append(f"{path.name}: line count mismatch")
            if digest(data) != entry[f"{prefix}_sha256"]:
                errors.append(f"{path.name}: sha256 mismatch")
        export_path = trace_dir / export_name
        if export_path.is_file():
            findings = unsafe_findings(export_path.read_text())
            if findings:
                errors.append(f"{export_name}: unsafe patterns {sorted(set(findings))}")
            for number, line in enumerate(
                export_path.read_text().splitlines(), start=1
            ):
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    errors.append(f"{export_name}:{number}: invalid JSON")
                    break
                if not isinstance(parsed, dict):
                    errors.append(
                        f"{export_name}:{number}: JSONL item is not an object"
                    )
                    break
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(
        f"verified {len(entries)} native JSONL snapshots; no credential patterns remain"
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(required=True)
    export = subcommands.add_parser("export")
    export.add_argument("--source", required=True)
    export.add_argument("--session-id", required=True)
    export.add_argument("--label", required=True)
    export.add_argument("--snapshot-id", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--trace-dir", default="traces")
    export.set_defaults(handler=export_trace)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--trace-dir", default="traces")
    verify.set_defaults(handler=verify_traces)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.handler(args))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"trace export failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
