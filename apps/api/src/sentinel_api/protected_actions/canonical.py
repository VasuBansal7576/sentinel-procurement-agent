"""Deterministic canonicalization for approval-bound JSON payloads."""

import hashlib
import json
from collections.abc import Mapping, Sequence

type JsonScalar = str | int | bool | None
type JsonValue = JsonScalar | Mapping[str, "JsonValue"] | Sequence["JsonValue"]


class CanonicalizationError(ValueError):
    """Raised when a payload cannot be represented without ambiguity."""


def _normalize(value: object, path: str = "$") -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalizationError(
            f"{path}: floating-point values are forbidden; use an integer minor unit or string"
        )
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"{path}: object keys must be strings")
            normalized[key] = _normalize(child, f"{path}.{key}")
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(child, f"{path}[{index}]") for index, child in enumerate(value)]
    raise CanonicalizationError(f"{path}: unsupported value type {type(value).__name__}")


def canonical_json(value: object) -> bytes:
    """Encode the supported JSON subset into stable UTF-8 bytes."""

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def payload_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
