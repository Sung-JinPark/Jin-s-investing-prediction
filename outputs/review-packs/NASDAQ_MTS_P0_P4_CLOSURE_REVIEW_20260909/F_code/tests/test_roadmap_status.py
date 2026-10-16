"""로드맵 상태 도구 — 파생 숫자에 출처를 붙인다.

`ROOT` 는 스크립트 파일이 있는 체크아웃이다. 워크트리가 여럿인 이 저장소에서는 다른
워크트리에서 실행해도 항상 그 체크아웃을 읽는다. 그 체크아웃이 옛 브랜치에 머물러
있으면 원장이 뒤처진 채로 숫자가 나온다 — 2026-09-09 에 라이브 원점이 실제 2인데
1 로 보고됐다. 파생 상태를 믿으려면 어느 체크아웃을 읽었는지 보여야 한다.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
roadmap = pytest.importorskip("roadmap_status")


def test_provenance_names_the_checkout_that_was_read() -> None:
    line = roadmap._provenance()
    assert str(roadmap.ROOT) in line, "읽은 체크아웃의 경로가 드러나야 한다"
    assert "읽은 체크아웃" in line


def test_report_prints_provenance_before_any_number() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        roadmap.main()
    text = buffer.getvalue()
    assert "읽은 체크아웃" in text
    head = text.index("읽은 체크아웃")
    for marker in ("자원 잔량", "라이브 원점"):
        if marker in text:
            assert head < text.index(marker), "숫자보다 출처가 먼저 나와야 한다"


def test_tool_writes_nothing(tmp_path: Path) -> None:
    """설계도 §9.4 — 읽기 전용. 상태를 적는 파일을 만들지 않는다."""
    source = (ROOT / "tools/roadmap_status.py").read_text(encoding="utf-8")
    for forbidden in ("write_text(", "open(", "mkdir(", "touch("):
        assert forbidden not in source, f"쓰기 호출 {forbidden} 은 있어선 안 된다"
