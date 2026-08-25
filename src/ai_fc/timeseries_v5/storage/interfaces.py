"""Storage protocols kept independent of provider SDKs."""

from __future__ import annotations

from typing import Any, Protocol


class ObjectStore(Protocol):
    def put_raw(self, source_id: str, body: bytes, *, content_type: str, metadata: dict[str, str]) -> dict[str, Any]: ...
    def get(self, uri: str) -> bytes: ...


class ControlPlane(Protocol):
    def append(self, ledger: str, row: dict[str, Any], *, identity: str) -> bool: ...
    def rows(self, ledger: str) -> list[dict[str, Any]]: ...
