from __future__ import annotations

from pathlib import Path

from ai_fc.integrity import iter_truth_files, source_fingerprint


def test_fingerprint_is_deterministic_and_tracks_truth_only(tmp_path: Path) -> None:
    (tmp_path / "questions").mkdir()
    truth = tmp_path / "questions" / "registry.yaml"
    truth.write_text("version: 1\nquestions: []\n", encoding="utf-8")
    first = source_fingerprint(tmp_path)
    assert first == source_fingerprint(tmp_path)

    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "index.db").write_bytes(b"derived")
    assert source_fingerprint(tmp_path) == first

    truth.write_text("version: 2\nquestions: []\n", encoding="utf-8")
    assert source_fingerprint(tmp_path) != first
    assert truth.resolve() in iter_truth_files(tmp_path)
