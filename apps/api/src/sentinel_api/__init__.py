"""Sentinel procurement operator API."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel_api.app import create_app

__all__ = ["create_app"]


def __getattr__(name: str) -> object:
    """Keep package imports deterministic while preserving the public app factory."""

    if name == "create_app":
        from sentinel_api.app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
