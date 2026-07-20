"""WS8: 모의 원장 20행 픽스처 → Murphy 분해·n_excluded 병기·섀도·드라이버 섹션 렌더."""

from __future__ import annotations

import textwrap
from pathlib import Path

from ai_fc.db import ingest, queries
from ai_fc.report import render_report

REG = """\
    version: 1
    questions:
      - id: fx-a
        title: "픽스처 A"
        question: "A?"
        deadline: 2099-12-31
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule: [{per_week: 1}]
        status: active
        created: 2026-07-01
        drivers: [fx-driver]
      - id: fx-b
        title: "픽스처 B"
        question: "B?"
        deadline: 2099-12-31
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule: [{per_week: 1}]
        status: active
        created: 2026-07-01
        drivers: [fx-driver]
"""


def _seed(tmp_path: Path):
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(
        textwrap.dedent(REG), encoding="utf-8")
    conn = ingest.connect(tmp_path / "db" / "index.db")
    # 모의 해소 20행 (2도메인) + 최신 예측 2행 (드라이버 표 + 섀도용)
    for i in range(20):
        p = 30 + i * 3          # 30~87%
        o = 1 if i % 3 == 0 else 0
        conn.execute(
            """INSERT INTO resolutions (forecast_id, resolved_date, question_id,
                 probability, outcome, brier, domain)
               VALUES (?,?,?,?,?,?,?)""",
            (f"f{i}", f"2099-01-{i + 1:02d}", "fx-a" if i % 2 else "fx-b",
             p, o, round((p / 100 - o) ** 2, 4), "fixture" if i % 2 else "macro"))
        conn.execute(
            """INSERT INTO forecasts (forecast_id, question_id, round, probability,
                 path, file_sha256, shadow_extremized)
               VALUES (?,?,?,?,?,?,?)""",
            (f"f{i}", "fx-a" if i % 2 else "fx-b", i + 1, p, f"{i}.md", f"h{i}",
             min(99, max(1, int(p * 1.2)))))
    conn.commit()
    return conn


def test_report_renders_all_ws8_sections(tmp_path: Path) -> None:
    conn = _seed(tmp_path)
    out = render_report(conn, tmp_path)
    html = out.read_text(encoding="utf-8")
    assert "Murphy 분해" in html and "Reliability" in html
    assert "제외 0건: failed" in html                    # n_excluded 상시 병기
    assert "rolling Brier" in html
    assert "섀도(α=√3)" in html                          # 가상 Brier 표시
    assert "드라이버 일관성 점검" in html and "fx-driver" in html
    assert "벤치마크 3자 비교" in html
    assert "표본 5 미만" not in html                     # n=20 — 다이어그램 유효


def test_murphy_identity(tmp_path: Path) -> None:
    """Brier ≈ REL − RES + UNC (십분위 근사 오차 허용)."""
    conn = _seed(tmp_path)
    m = queries.murphy_decomposition(conn)
    assert m and m["n"] == 20
    assert abs(m["brier"] - (m["reliability"] - m["resolution"] + m["uncertainty"])) < 0.02


def test_sparse_sample_notice(tmp_path: Path) -> None:
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(
        "version: 1\nquestions: []\n", encoding="utf-8")
    conn = ingest.connect(tmp_path / "db" / "index.db")
    conn.execute(
        """INSERT INTO resolutions (forecast_id, resolved_date, question_id,
             probability, outcome, brier, domain)
           VALUES ('f1', '2099-01-01', 'q', 50, 0, 0.25, 'fixture')""")
    conn.commit()
    html = render_report(conn, tmp_path).read_text(encoding="utf-8")
    assert "표본 5 미만" in html                         # 표본 부족 정직 명시
