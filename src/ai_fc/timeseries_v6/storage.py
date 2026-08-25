"""Secret-free storage resolution for local, S3/R2, and CI artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .object_store import (
    LocalContentAddressedStore,
    ObjectIntegrityError,
    RawObjectMetadata,
    S3ContentAddressedStore,
)


class StorageResolutionError(RuntimeError):
    """Raised when a storage backend is unsafe, incomplete, or unauthorized."""


@dataclass(frozen=True)
class StorageConfiguration:
    backend: str
    local_root: str | None = None
    bucket: str | None = None
    prefix: str = "timeseries-v6/raw"
    endpoint_url: str | None = None
    read_only: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StorageConfiguration":
        allowed = {"backend", "local_root", "bucket", "prefix", "endpoint_url", "read_only"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise StorageResolutionError(f"unknown storage configuration fields: {unknown}")
        config = cls(**dict(value))
        config.validate()
        return config

    def validate(self) -> None:
        if self.backend not in {"local", "s3", "artifact"}:
            raise StorageResolutionError(f"unsupported storage backend: {self.backend}")
        serialized = " ".join(str(item) for item in (self.local_root, self.bucket, self.prefix, self.endpoint_url))
        forbidden = ("api_key", "apikey", "token", "password", "secret", "access_key")
        if any(f"{name}=" in serialized.lower() for name in forbidden):
            raise StorageResolutionError("credential-bearing storage configuration is prohibited")
        if self.backend in {"local", "artifact"}:
            if not self.local_root or self.bucket or self.endpoint_url:
                raise StorageResolutionError("local/artifact storage requires only local_root")
            if self.backend == "artifact" and not self.read_only:
                raise StorageResolutionError("artifact storage must be read-only")
        if self.backend == "s3":
            if not self.bucket or self.local_root:
                raise StorageResolutionError("S3 storage requires bucket and no local_root")
            if "/" in self.bucket or "\\" in self.bucket or not self.bucket.strip():
                raise StorageResolutionError("invalid S3 bucket")
            if self.endpoint_url:
                parsed = urlsplit(self.endpoint_url)
                if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
                    raise StorageResolutionError("S3 endpoint must be credential-free HTTPS")


class ReadOnlyArtifactStore:
    """A local content-addressed view whose mutation capability is removed."""

    def __init__(self, root: Path) -> None:
        self.delegate = LocalContentAddressedStore(root)

    def get(self, metadata: RawObjectMetadata) -> bytes:
        return self.delegate.get(metadata)

    def revalidate(self, metadata: RawObjectMetadata) -> dict[str, Any]:
        return self.delegate.revalidate(metadata)

    def put(self, *_args: Any, **_kwargs: Any) -> RawObjectMetadata:
        raise StorageResolutionError("CI artifact storage is immutable/read-only")


def resolve_storage(
    configuration: StorageConfiguration,
    *,
    repository_root: Path,
    s3_client: Any | None = None,
) -> LocalContentAddressedStore | S3ContentAddressedStore | ReadOnlyArtifactStore:
    configuration.validate()
    root = repository_root.resolve()
    if configuration.backend in {"local", "artifact"}:
        candidate = Path(configuration.local_root or "")
        path = candidate if candidate.is_absolute() else root / candidate
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise StorageResolutionError("local storage must remain within repository workspace") from exc
        if configuration.backend == "artifact":
            return ReadOnlyArtifactStore(path)
        if configuration.read_only:
            raise StorageResolutionError("use artifact backend for read-only local storage")
        return LocalContentAddressedStore(path)
    if s3_client is None:
        raise StorageResolutionError("S3 client must be injected by the collector process")
    return S3ContentAddressedStore(
        s3_client,
        bucket=configuration.bucket or "",
        prefix=configuration.prefix,
    )
