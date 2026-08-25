from __future__ import annotations

import json
import zipfile
from pathlib import PurePosixPath

from tools.build_v7_replay_pack import build_pack


def test_replay_pack_is_deterministic_safe_and_self_manifested(tmp_path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    one = build_pack(first); two = build_pack(second)
    assert one["zip_sha256"] == two["zip_sha256"]
    assert one["qualification_claim"] is False
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert len(names) == len(set(name.casefold() for name in names))
        assert all(not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts for name in names)
        manifest = json.loads(archive.read("MANIFEST.json"))
        assert manifest["file_count"] == len(names) - 1
        assert "data/contracts/multivariate_timeseries_v7.yaml" in names
        assert "locks/timeseries_v7/requirements.replay.lock" in names


def test_replay_pack_has_no_private_raw_body_paths(tmp_path) -> None:
    output = tmp_path / "pack.zip"
    build_pack(output)
    with zipfile.ZipFile(output) as archive:
        assert all("raw_object" not in name and "private" not in name for name in archive.namelist())
