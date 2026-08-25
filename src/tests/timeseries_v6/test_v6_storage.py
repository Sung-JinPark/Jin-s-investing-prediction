from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc.timeseries_v6.storage import (
    ReadOnlyArtifactStore,
    StorageConfiguration,
    StorageResolutionError,
    resolve_storage,
)


def test_local_resolver_is_workspace_scoped_and_round_trips(tmp_path: Path) -> None:
    store = resolve_storage(
        StorageConfiguration(backend="local", local_root="objects"),
        repository_root=tmp_path,
    )
    metadata = store.put(b"payload", license_class="public_official")
    assert store.get(metadata) == b"payload"
    with pytest.raises(StorageResolutionError, match="workspace"):
        resolve_storage(
            StorageConfiguration(backend="local", local_root=str(tmp_path.parent / "escape")),
            repository_root=tmp_path,
        )


def test_artifact_backend_has_no_write_capability(tmp_path: Path) -> None:
    writer = resolve_storage(
        StorageConfiguration(backend="local", local_root="objects"), repository_root=tmp_path
    )
    metadata = writer.put(b"payload", license_class="public_official")
    reader = resolve_storage(
        StorageConfiguration(backend="artifact", local_root="objects", read_only=True),
        repository_root=tmp_path,
    )
    assert isinstance(reader, ReadOnlyArtifactStore)
    assert reader.get(metadata) == b"payload"
    with pytest.raises(StorageResolutionError, match="read-only"):
        reader.put(b"other", license_class="public_official")


def test_s3_requires_injected_client_and_safe_endpoint(tmp_path: Path) -> None:
    config = StorageConfiguration(backend="s3", bucket="v6-private", endpoint_url="https://r2.example.com")
    with pytest.raises(StorageResolutionError, match="injected"):
        resolve_storage(config, repository_root=tmp_path)
    with pytest.raises(StorageResolutionError, match="credential-free"):
        credential_endpoint = "https://" + "user" + ":" + "pass" + "@r2.example.com"
        StorageConfiguration(
            backend="s3", bucket="v6-private", endpoint_url=credential_endpoint
        ).validate()


def test_unknown_fields_credentials_and_writable_artifacts_fail_closed() -> None:
    with pytest.raises(StorageResolutionError, match="unknown"):
        StorageConfiguration.from_mapping({"backend": "local", "local_root": "x", "extra": 1})
    with pytest.raises(StorageResolutionError, match="credential-bearing"):
        StorageConfiguration(backend="local", local_root="objects?token=value").validate()
    with pytest.raises(StorageResolutionError, match="read-only"):
        StorageConfiguration(backend="artifact", local_root="objects").validate()
