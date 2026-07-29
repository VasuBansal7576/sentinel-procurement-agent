from uuid import uuid4

import pytest
from pydantic import ValidationError

from sentinel_api.research import (
    BrowserPrimitive,
    HelperManifest,
    HelperPatch,
    InMemoryHelperPatchStore,
)


def _manifest(**updates: object) -> HelperManifest:
    values: dict[str, object] = {
        "name": "extract_specification",
        "version": "1.0.0",
        "primitives": frozenset({BrowserPrimitive.NAVIGATE, BrowserPrimitive.READ_TEXT}),
        "allowed_domains": frozenset({"example.com"}),
    }
    values.update(updates)
    return HelperManifest(**values)


def test_helper_source_is_canonical_and_digest_bound() -> None:
    patch = HelperPatch.create(
        run_id=uuid4(),
        actor_id=uuid4(),
        manifest=_manifest(),
        source_code="value = rpc.read_text('main')\r\nreturn value   \r\n",
    )

    assert patch.source_code == "value = rpc.read_text('main')\nreturn value"
    assert len(patch.content_sha256) == 64

    with pytest.raises(ValidationError, match="digest"):
        HelperPatch.model_validate({**patch.model_dump(), "source_code": "return 'tampered'"})


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"accepts_credentials": True}, "cannot accept credentials"),
        ({"protected_tool_names": frozenset({"email.send"})}, "protected tools"),
    ],
)
def test_helper_manifest_cannot_request_privileged_capabilities(
    updates: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _manifest(**updates)


@pytest.mark.asyncio
async def test_helper_store_is_immutable_and_run_scoped() -> None:
    run_id = uuid4()
    patch = HelperPatch.create(
        run_id=run_id,
        actor_id=uuid4(),
        manifest=_manifest(),
        source_code="return rpc.read_text('main')",
    )
    store = InMemoryHelperPatchStore()
    await store.retain(patch)
    await store.retain(patch)

    assert await store.get(run_id, patch.content_sha256) == patch
    with pytest.raises(KeyError, match="not found for run"):
        await store.get(uuid4(), patch.content_sha256)


def test_helper_contract_rejects_unknown_secret_or_sink_fields() -> None:
    base = {
        "name": "malicious_helper",
        "version": "1.0.0",
        "primitives": frozenset({BrowserPrimitive.READ_TEXT}),
        "allowed_domains": frozenset({"example.com"}),
    }
    with pytest.raises(ValidationError, match="Extra inputs"):
        HelperManifest(**base, credential_value="secret")
    with pytest.raises(ValidationError, match="Extra inputs"):
        HelperManifest(**base, email_send_tool="send now")
