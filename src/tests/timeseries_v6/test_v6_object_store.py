from __future__ import annotations

import io
from pathlib import Path

import pytest

from ai_fc.timeseries_v6.object_store import (
    LocalContentAddressedStore,
    ObjectIntegrityError,
    RawObjectMetadata,
    S3ContentAddressedStore,
    encode_object,
)


def test_local_content_address_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    store = LocalContentAddressedStore(tmp_path / "objects")
    first = store.put(b"official raw response", license_class="public_official")
    second = store.put(b"official raw response", license_class="public_official")
    assert first == second
    assert store.get(first) == b"official raw response"
    assert store.revalidate(first)["pass"] is True
    assert first.object_uri.startswith("local-content://sha256/")
    assert first.encryption_status == "local_ci_unencrypted"
    assert encode_object(b"x", "gzip") == encode_object(b"x", "gzip")


def test_local_store_rejects_tampered_immutable_path(tmp_path: Path) -> None:
    store = LocalContentAddressedStore(tmp_path / "objects")
    metadata = store.put(b"original", license_class="public_official")
    path = store._path(metadata.object_sha256, metadata.compression)
    path.write_bytes(b"tampered")
    with pytest.raises(ObjectIntegrityError, match="integrity mismatch"):
        store.get(metadata)
    with pytest.raises(ObjectIntegrityError, match="collision/tamper"):
        store.put(b"original", license_class="public_official")


def test_metadata_rejects_secret_uri_bad_hash_and_missing_license() -> None:
    base = dict(
        object_sha256="a" * 64, stored_sha256="b" * 64,
        decompressed_bytes=1, stored_bytes=1, compression="none",
        encryption_status="provider_managed", license_class="public",
    )
    RawObjectMetadata(object_uri="s3://bucket/key", **base).validate()
    with pytest.raises(ObjectIntegrityError, match="credential"):
        RawObjectMetadata(object_uri="https://x/key?token=secret", **base).validate()
    with pytest.raises(ObjectIntegrityError, match="license"):
        RawObjectMetadata(object_uri="s3://bucket/key", **dict(base, license_class="")).validate()


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls: list[dict[str, object]] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        key = (kwargs["Bucket"], kwargs["Key"])
        if key in self.objects:
            raise RuntimeError("precondition failed")
        self.objects[key] = kwargs["Body"]
        return {}

    def head_object(self, **kwargs):
        return {"ContentLength": len(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}


def test_s3_adapter_uses_conditional_put_and_revalidates_existing_bytes() -> None:
    client = FakeS3()
    store = S3ContentAddressedStore(client, bucket="research-private")
    first = store.put(b"raw", license_class="licensed_private")
    second = store.put(b"raw", license_class="licensed_private")
    assert first == second
    assert client.put_calls[0]["IfNoneMatch"] == "*"
    assert client.put_calls[0]["Metadata"]["license-class"] == "licensed_private"
    assert store.revalidate(first)["pass"] is True


def test_s3_existing_corrupt_bytes_fail_closed() -> None:
    client = FakeS3()
    store = S3ContentAddressedStore(client, bucket="research-private")
    metadata = store.put(b"raw", license_class="public")
    key = ("research-private", store._key(metadata.object_sha256, metadata.compression))
    client.objects[key] = b"corrupt"
    with pytest.raises(ObjectIntegrityError):
        store.put(b"raw", license_class="public")
