"""Authenticated Resend HTTP transport. Secrets stay in the process environment."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sentinel_api.email.resend import (
    ResendTransportError,
    ResendTransportResponse,
    TransportEffect,
)


class HttpResendTransport:
    """Thin urllib transport that never logs bodies or credentials."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.resend.com",
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Resend API key is required for live email transport")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def request(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        json_body: Mapping[str, object] | None,
    ) -> ResendTransportResponse:
        # Async surface for the provider; I/O is short and blocking by design.
        return self._request_sync(
            method=method,
            path=path,
            headers=headers,
            json_body=json_body,
        )

    def _request_sync(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        json_body: Mapping[str, object] | None,
    ) -> ResendTransportResponse:
        url = f"{self._base_url}{path if path.startswith('/') else f'/{path}'}"
        payload = None if json_body is None else json.dumps(dict(json_body)).encode()
        request_headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            **dict(headers),
        }
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(url, data=payload, headers=request_headers, method=method.upper())
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
                body = _parse_body(raw)
                return ResendTransportResponse(status_code=int(response.status), body=body)
        except HTTPError as error:
            raw = error.read() if hasattr(error, "read") else b""
            body = _parse_body(raw)
            # 4xx: provider rejected before accept. 5xx: possible unknown effect.
            if 400 <= int(error.code) < 500:
                return ResendTransportResponse(status_code=int(error.code), body=body)
            raise ResendTransportError(
                "Resend transport returned a server error",
                effect=TransportEffect.UNKNOWN,
            ) from error
        except URLError as error:
            raise ResendTransportError(
                "Resend transport could not reach the provider",
                effect=TransportEffect.NOT_APPLIED,
            ) from error


def _parse_body(raw: bytes) -> dict[str, object]:
    if not raw:
        return {}
    try:
        parsed: Any = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if isinstance(parsed, dict):
        return {str(key): value for key, value in parsed.items()}
    return {}
