"""WS5: 쓰기 원자성 — evidence 선행·본문 커밋 포인트 · 크래시 시 E6 검출, 본문 고아 0."""

from __future__ import annotations

from pathlib import Path

import pytest

import ai_fc.files as F
from ai_fc.db import ingest
from ai_fc.orchestrator import _write_records


def test_write_order_evidence_first(tmp_path: Path, monkeypatch) -> None:
    order: list[str] = []
    real = F.write_forecast_exclusive

    def spy(path: Path, content: str) -> None:
        order.append(path.name)
        real(path, content)

    monkeypatch.setattr("ai_fc.orchestrator.F.write_forecast_exclusive", spy)
    target = _write_records(tmp_path, 2099, "2099-01-01_fx_r1", "본문", "증거")
    assert order == ["2099-01-01_fx_r1_evidence.md", "2099-01-01_fx_r1.md"]
    assert target.exists()


def test_crash_leaves_orphan_evidence_only_and_e6(tmp_path: Path, monkeypatch) -> None:
    """본문 쓰기 직전 예외 주입 → 고아 evidence만 남고(본문 고아 0), sync가 E6 경고."""
    real = F.write_forecast_exclusive

    def crash_on_main(path: Path, content: str) -> None:
        if not path.name.endswith("_evidence.md"):
            raise RuntimeError("주입된 크래시 (본문 쓰기 직전)")
        real(path, content)

    monkeypatch.setattr("ai_fc.orchestrator.F.write_forecast_exclusive", crash_on_main)
    with pytest.raises(RuntimeError, match="주입된 크래시"):
        _write_records(tmp_path, 2099, "2099-01-01_fx_r1", "본문", "증거")

    fdir = tmp_path / "forecasts" / "2099"
    assert (fdir / "2099-01-01_fx_r1_evidence.md").exists()
    assert not (fdir / "2099-01-01_fx_r1.md").exists()   # 본문 고아 0 (커밋 포인트)

    # sync — 최소 루트 구성 후 E6 경고 검출
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(
        "version: 1\nquestions: []\n", encoding="utf-8")
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(
        ",".join(F.LEDGER_HEADER) + "\n", encoding="utf-8")
    conn = ingest.connect(tmp_path / "db" / "index.db")
    report = ingest.sync(conn, tmp_path)
    assert any("E6" in w and "고아 evidence" in w for w in report.warnings)
    assert report.ok  # E6는 경고 — 오류 아님 (자동 삭제도 안 함)
    assert (fdir / "2099-01-01_fx_r1_evidence.md").exists()
