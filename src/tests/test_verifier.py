"""v3.5 WS-T1: 검증기 — 현 리포 PASS + 조작 시뮬 3종 FAIL (합성 미래 픽스처)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERIFIER = REPO / "tools" / "verify_track_record.py"

FM = """---
forecast_id: 2099-06-01_fx-q_r1
question_id: fx-q
timestamp: 2099-06-01 09:00 KST
probability: 40
window_end: null
---
본문
"""

LEDGER = ("resolved_date,question_id,forecast_id,forecast_date,probability,"
          "outcome,brier,domain,notes\n"
          "2099-06-11,fx-q,2099-06-01_fx-q_r1,2099-06-01,40,0,0.16,fixture,\n")

REGISTRY = "version: 1\nquestions:\n- id: fx-q\n  deadline: 2099-06-10\n"


def _git(cwd: Path, *args: str, env_extra: dict | None = None) -> None:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, env=env, check=True, capture_output=True)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _build_fixture(tmp: Path) -> Path:
    (tmp / "forecasts" / "2099").mkdir(parents=True)
    (tmp / "calibration").mkdir()
    (tmp / "questions").mkdir()
    f = tmp / "forecasts" / "2099" / "2099-06-01_fx-q_r1.md"
    f.write_text(FM, encoding="utf-8", newline="\n")
    (tmp / "forecasts" / ".hashes").write_text(
        f"{_sha(f)}  forecasts/2099/2099-06-01_fx-q_r1.md\n", encoding="utf-8")
    (tmp / "calibration" / "ledger.csv").write_text(LEDGER, encoding="utf-8")
    (tmp / "questions" / "registry.yaml").write_text(REGISTRY, encoding="utf-8")
    _git(tmp, "init", "-b", "main")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-m", "baseline")
    return tmp


def _run(root: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(VERIFIER)],
                       env={**os.environ, "AIFC_VERIFY_ROOT": str(root),
                            "PYTHONUTF8": "1"},
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout


def test_real_repo_passes() -> None:
    code, out = _run(REPO)
    assert code == 0, out
    assert "PASS" in out and "B급 21" in out


def test_fixture_baseline_passes(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path)
    code, out = _run(root)
    assert code == 0, out
    assert "B급 1" in out


def test_sim1_file_tamper_fails(tmp_path: Path) -> None:
    """조작 ①: 예측 파일 1바이트 변경 → [1] 해시 FAIL."""
    root = _build_fixture(tmp_path)
    f = root / "forecasts" / "2099" / "2099-06-01_fx-q_r1.md"
    f.write_text(f.read_text(encoding="utf-8") + "!", encoding="utf-8")
    code, out = _run(root)
    assert code == 1 and "해시 불일치" in out


def test_sim2_ledger_row_deletion_fails(tmp_path: Path) -> None:
    """조작 ②: 원장 행 삭제 커밋 → [2b] append-only FAIL."""
    root = _build_fixture(tmp_path)
    lp = root / "calibration" / "ledger.csv"
    lp.write_text(LEDGER.splitlines()[0] + "\n", encoding="utf-8")  # 데이터 행 삭제
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "tamper")
    code, out = _run(root)
    assert code == 1 and "append-only 위반" in out


def test_sim3_late_commit_fails(tmp_path: Path) -> None:
    """조작 ③: 마감(2099-06-10) 후 커밋된 A급 예측 → [3] 시점 FAIL."""
    root = _build_fixture(tmp_path)
    f2 = root / "forecasts" / "2099" / "2099-06-05_fx-q_r2.md"
    f2.write_text(FM.replace("_r1", "_r2").replace("2099-06-01 09:00", "2099-06-05 09:00")
                  .replace("2099-06-01_fx-q", "2099-06-05_fx-q"), encoding="utf-8",
                  newline="\n")
    anchor = root / "forecasts" / ".hashes"
    anchor.write_text(anchor.read_text(encoding="utf-8")
                      + f"{_sha(f2)}  forecasts/2099/2099-06-05_fx-q_r2.md\n",
                      encoding="utf-8")
    late = {"GIT_AUTHOR_DATE": "2099-07-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2099-07-01T00:00:00+00:00"}
    _git(root, "add", "-A", env_extra=late)
    _git(root, "commit", "-m", "late r2", env_extra=late)
    code, out = _run(root)
    assert code == 1 and "시점 위반" in out
    assert "A급 1" in out          # 등급 판정 자체는 정확
