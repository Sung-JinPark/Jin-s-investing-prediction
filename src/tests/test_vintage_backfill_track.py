"""V9-D5 vintage collection track: roster, CLI seam, and workflow order contract."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_roster_registers_the_three_design_eligible_series_and_no_retired_one() -> None:
    contract = yaml.safe_load(
        (ROOT / "data/contracts/multivariate_timeseries_v1.yaml").read_text(encoding="utf-8"))
    optional = contract["sources"]["financial_optional"]
    assert {"TOTCI", "TOTLL", "WRMFNS"} <= set(optional)
    # 폐지 시리즈와 온셋 부족 시리즈는 등록 금지 (설계서 §1 제외 목록).
    assert "WRMFSL" not in optional
    for premature in ("DPSACBW027SBOG", "VXNCLS", "MMMFFAQ027S"):
        assert premature not in optional, f"{premature}는 설계창 온셋 부족 — 등록 보류"


def test_collect_series_cli_validates_against_the_roster() -> None:
    source = (ROOT / "src/ai_fc/cli.py").read_text(encoding="utf-8")
    assert "timeseries-collect-series" in source
    assert "registered_series(load_contract(config.ROOT))" in source
    assert "로스터에 등록되지 않은 시리즈" in source


def test_backfill_workflow_keeps_the_contract_hash_repin_order() -> None:
    workflow = (ROOT / ".github/workflows/timeseries-vintage-backfill.yml").read_text(
        encoding="utf-8")
    # collect → fit → forecast → verify: 계약 해시 재기록 전의 verify는 stale FAIL.
    order = [
        workflow.index("timeseries-collect-series"),
        workflow.index("timeseries-fit"),
        workflow.index("timeseries-forecast"),
        workflow.index("timeseries-verify"),
    ]
    assert order == sorted(order)
    assert 'group: investing-data-writer' in workflow
    assert 'HEAD:${GITHUB_REF_NAME}' in workflow, "백필은 main이 아니라 실행 브랜치에 커밋"
    assert "data/timeseries docs/generated/inventory.generated.md" in workflow
    # 키는 collect 단계에만 배선된다.
    assert workflow.count("secrets.FRED_API_KEY") == 1
