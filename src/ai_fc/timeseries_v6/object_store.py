"""Immutable content-addressed raw-object storage for local CI and S3/R2."""

from __future__ import annotations

import gzip
import hashlib
import io
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


class ObjectIntegrityError(RuntimeError):
    """Raised when object bytes or immutable metadata do not match the address."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_object(data: bytes, compression: str) -> bytes:
    if compression == "none":
        return data
    if compression == "gzip":
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0, filename="") as handle:
            handle.write(data)
        return buffer.getvalue()
    raise ObjectIntegrityError(f"unsupported object compression: {compression}")


def decode_object(data: bytes, compression: str) -> bytes:
    if compression == "none":
        return data
    if compression == "gzip":
        return gzip.decompress(data)
    raise ObjectIntegrityError(f"unsupported object compression: {compression}")


@dataclass(frozen=True)
class RawObjectMetadata:
    object_sha256: str
    stored_sha256: str
    decompressed_bytes: int
    stored_bytes: int
    object_uri: str
    compression: str
    encryption_status: str
    license_class: str

    def validate(self) -> None:
        for name in ("object_sha256", "stored_sha256"):
            value = getattr(self, name)
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ObjectIntegrityError(f"invalid {name}")
        if self.decompressed_bytes < 0 or self.stored_bytes < 0:
            raise ObjectIntegrityError("object byte counts must be nonnegative")
        if self.compression not in {"none", "gzip"}:
            raise ObjectIntegrityError("unsupported compression metadata")
        if self.encryption_status not in {
            "provider_managed", "customer_managed", "local_ci_unencrypted"
        }:
            raise ObjectIntegrityError("invalid encryption status")
        if not self.license_class:
            raise ObjectIntegrityError("license class is required")
        lowered = self.object_uri.lower()
        credential_parameters = ("api_key", "apikey", "token", "password", "secret")
        if any(f"{name}=" in lowered for name in credential_parameters):
            raise ObjectIntegrityError("credential-bearing object URI is prohibited")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metadata_for(
    *, raw: bytes, stored: bytes, uri: str, compression: str,
    encryption_status: str, license_class: str,
) -> RawObjectMetadata:
    metadata = RawObjectMetadata(
        object_sha256=sha256_bytes(raw),
        stored_sha256=sha256_bytes(stored),
        decompressed_bytes=len(raw),
        stored_bytes=len(stored),
        object_uri=uri,
        compression=compression,
        encryption_status=encryption_status,
        license_class=license_class,
    )
    metadata.validate()
    return metadata


class LocalContentAddressedStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, object_sha256: str, compression: str) -> Path:
        suffix = ".raw.gz" if compression == "gzip" else ".raw"
        return self.root / object_sha256[:2] / f"{object_sha256}{suffix}"

    def put(
        self, raw: bytes, *, compression: str = "gzip",
        license_class: str, encryption_status: str = "local_ci_unencrypted",
    ) -> RawObjectMetadata:
        object_sha = sha256_bytes(raw)
        stored = encode_object(raw, compression)
        path = self._path(object_sha, compression)
        relative = path.relative_to(self.root).as_posix()
        uri = f"local-content://sha256/{relative}"
        metadata = _metadata_for(
            raw=raw, stored=stored, uri=uri, compression=compression,
            encryption_status=encryption_status, license_class=license_class,
        )
        if path.exists():
            existing = path.read_bytes()
            if sha256_bytes(existing) != metadata.stored_sha256:
                raise ObjectIntegrityError(f"immutable object collision/tamper at {uri}")
            self.revalidate(metadata)
            return metadata
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        if temporary.exists():
            raise ObjectIntegrityError(f"stale atomic-write file exists: {temporary.name}")
        with temporary.open("xb") as handle:
            handle.write(stored)
            handle.flush()
        temporary.replace(path)
        self.revalidate(metadata)
        return metadata

    def read_stored(self, metadata: RawObjectMetadata) -> bytes:
        metadata.validate()
        path = self._path(metadata.object_sha256, metadata.compression)
        if not path.is_file():
            raise ObjectIntegrityError(f"object missing: {metadata.object_uri}")
        return path.read_bytes()

    def get(self, metadata: RawObjectMetadata) -> bytes:
        stored = self.read_stored(metadata)
        if sha256_bytes(stored) != metadata.stored_sha256 or len(stored) != metadata.stored_bytes:
            raise ObjectIntegrityError(f"stored object integrity mismatch: {metadata.object_uri}")
        raw = decode_object(stored, metadata.compression)
        if sha256_bytes(raw) != metadata.object_sha256 or len(raw) != metadata.decompressed_bytes:
            raise ObjectIntegrityError(f"decompressed object integrity mismatch: {metadata.object_uri}")
        return raw

    def revalidate(self, metadata: RawObjectMetadata) -> dict[str, Any]:
        raw = self.get(metadata)
        return {
            "object_sha256": metadata.object_sha256,
            "bytes": len(raw),
            "pass": True,
        }


class S3Client(Protocol):
    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def head_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


class S3ContentAddressedStore:
    """S3/R2 adapter with immutable conditional put and full GET validation."""

    def __init__(self, client: S3Client, *, bucket: str, prefix: str = "timeseries-v6/raw") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, object_sha256: str, compression: str) -> str:
        suffix = ".raw.gz" if compression == "gzip" else ".raw"
        return f"{self.prefix}/sha256/{object_sha256[:2]}/{object_sha256}{suffix}"

    def put(
        self, raw: bytes, *, compression: str = "gzip", license_class: str,
        encryption_status: str = "provider_managed",
    ) -> RawObjectMetadata:
        object_sha = sha256_bytes(raw)
        stored = encode_object(raw, compression)
        key = self._key(object_sha, compression)
        uri = f"s3://{self.bucket}/{key}"
        metadata = _metadata_for(
            raw=raw, stored=stored, uri=uri, compression=compression,
            encryption_status=encryption_status, license_class=license_class,
        )
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=stored,
                IfNoneMatch="*",
                ContentType="application/octet-stream",
                Metadata={
                    "object-sha256": metadata.object_sha256,
                    "stored-sha256": metadata.stored_sha256,
                    "compression": compression,
                    "license-class": license_class,
                },
            )
        except Exception as exc:
            # Existing content is safe only after a full byte revalidation.
            try:
                self.revalidate(metadata)
            except Exception as validation_error:
                raise ObjectIntegrityError(f"immutable S3 put failed for {uri}") from validation_error
        self.revalidate(metadata)
        return metadata

    def revalidate(self, metadata: RawObjectMetadata) -> dict[str, Any]:
        metadata.validate()
        key = self._key(metadata.object_sha256, metadata.compression)
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        if int(head.get("ContentLength", -1)) != metadata.stored_bytes:
            raise ObjectIntegrityError(f"S3 HEAD size mismatch: {metadata.object_uri}")
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        stored = body.read() if hasattr(body, "read") else bytes(body)
        if sha256_bytes(stored) != metadata.stored_sha256:
            raise ObjectIntegrityError(f"S3 stored SHA mismatch: {metadata.object_uri}")
        raw = decode_object(stored, metadata.compression)
        if sha256_bytes(raw) != metadata.object_sha256 or len(raw) != metadata.decompressed_bytes:
            raise ObjectIntegrityError(f"S3 decompressed SHA mismatch: {metadata.object_uri}")
        return {"object_sha256": metadata.object_sha256, "bytes": len(raw), "pass": True}
