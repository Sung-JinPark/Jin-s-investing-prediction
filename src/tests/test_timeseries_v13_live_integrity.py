"""V13-VOL 라이브 전진 표본의 무결성 — 원점은 한 번만 세고, 판정 verb 는 아무것도 쓰지 않는다.

2026-10-21 실측: 2026-09-04 원점이 구 계수(51815bde…)·재동결 계수(1a857850…)로 두 번 발행돼
해상 원장에 6셀 × 2행이 있다. 행 수로 세면 60 게이트를 원점 하나 먼저 넘고 첫 원점의 Brier 가 2배
가중된다. 원장은 append-only 라 무수정이고 **읽기**만 distinct 로 고친다.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from ai_fc.timeseries_v13 import contracts as C
from ai_fc.timeseries_v13 import resolve as R
from ai_fc.timeseries_v13.live_scoreboard import projection
from ai_fc.timeseries_v13.live_verdict import live_verdict, render_table

ROOT = Path(__file__).resolve().parents[2]
PINNED = "a" * 64
OLD = "b" * 64


def _row(cell: str, origin: str, sha: str, *, p: float = 0.2, label: float = 0.0,
         base: float = 0.4, cutoff: str = "2026-10-01T00:00:00+00:00") -> dict:
    body = {"schema_version": 1, "resolution_id": f"v13vol-{origin}-{sha[:8]}-{cell}",
            "run_id": f"v13vol-{origin}-{sha[:8]}", "cell": cell, "origin": origin,
            "horizon_sessions": 5, "resolved_session": origin, "probability": p, "label": label,
            "brier_model": round((p - label) ** 2, 8), "brier_climatology": round((base - label) ** 2, 8),
            "climatology_base_rate": base, "coefficients_sha256": sha,
            "finalist_id": "V13VOL_champion_aec80c65038b", "holdout_status_at_forecast": "partial",
            "knowledge_cutoff": cutoff}
    body["content_hash"] = C.canonical_hash(body)
    return body


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _tmp_repo(tmp_path: Path, *, pinned: str = PINNED) -> Path:
    """실제 계약을 복사하되 frozen_coefficients.sha256 만 합성 핀으로 바꾼 임시 저장소."""
    contract_rel = Path("data/contracts/multivariate_timeseries_v13_vol.yaml")
    src = ROOT / contract_rel
    dst = tmp_path / contract_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    contract = yaml.safe_load(src.read_text(encoding="utf-8"))
    contract["frozen_coefficients"]["sha256"] = pinned
    dst.write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tmp_path


def test_distinct_resolutions_prefers_the_pinned_coefficients_row() -> None:
    rows = [_row("rv_h5", "2026-09-04", OLD, p=0.5, cutoff="2026-09-12T00:00:00+00:00"),
            _row("rv_h5", "2026-09-04", PINNED, p=0.2, cutoff="2026-09-11T00:00:00+00:00"),
            _row("rv_h5", "2026-09-05", PINNED, p=0.3)]
    kept = R.distinct_resolutions(rows, pinned_sha=PINNED)
    assert len(kept) == 2
    sept4 = next(r for r in kept if r["origin"] == "2026-09-04")
    assert sept4["coefficients_sha256"] == PINNED and sept4["probability"] == 0.2
    # 핀이 없으면 knowledge_cutoff 가 늦은 행을 남긴다
    kept_unpinned = R.distinct_resolutions(rows, pinned_sha=None)
    sept4 = next(r for r in kept_unpinned if r["origin"] == "2026-09-04")
    assert sept4["coefficients_sha256"] == OLD


def test_matured_counts_and_scoreboard_count_each_origin_once(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path)
    rows = [_row("rv_h5", "2026-09-04", OLD, p=0.5), _row("rv_h5", "2026-09-04", PINNED, p=0.2),
            _row("rv_h5", "2026-09-05", PINNED, p=0.3, label=1.0)]
    _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, rows)
    _write_jsonl(root / C.LIVE_LEDGER_RELATIVE, [
        {"as_of": "2026-09-04", "run_id": "v13vol-2026-09-04", "coefficients_sha256": OLD},
        {"as_of": "2026-09-04", "run_id": "v13vol-2026-09-04-aaaaaaaa", "coefficients_sha256": PINNED},
        {"as_of": "2026-09-05", "run_id": "v13vol-2026-09-05-aaaaaaaa", "coefficients_sha256": PINNED}])
    assert R.matured_counts(root)["rv_h5"] == 2
    board = projection(root, minimum=60)
    assert board["origins_recorded"] == 2
    cell = next(c for c in board["cells"] if c["cell"] == "rv_h5")
    assert cell["matured"] == 2 and cell["events"] == 1
    # 핀된 행(p=0.2)이 쓰였다: Σp = 0.2 + 0.3
    assert cell["expected_events_model"] == pytest.approx(0.5)
    assert cell["expected_events_climatology"] == pytest.approx(0.8)
    assert cell["skill_degenerate"] is False
    assert board["events_total"] == 1


def test_scoreboard_flags_event_free_cells_as_degenerate(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path)
    rows = [_row("vix25_h5", f"2026-09-{d:02d}", PINNED, p=0.01, label=0.0, base=0.3)
            for d in range(8, 20)]
    _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, rows)
    board = projection(root, minimum=60)
    cell = next(c for c in board["cells"] if c["cell"] == "vix25_h5")
    assert cell["events"] == 0 and cell["skill_degenerate"] is True
    assert cell["bss"] is not None and cell["bss"] > 0   # 자명 이득 — 숫자는 있되 사건 0 이 함께 실린다
    assert board["verdict"] is None


def test_live_verdict_writes_nothing_and_reports_insufficient_sample(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path)
    rows = [_row("rv_h21", f"2026-09-{d:02d}", PINNED, p=0.4) for d in range(8, 19)]
    ledger = root / R.RESOLUTION_LEDGER_RELATIVE
    _write_jsonl(ledger, rows)
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    result = live_verdict(root, draws=5)
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == before
    assert result["read_only"] is True and result["writes"] == 0
    assert result["cells"]["rv_h21"]["status"] == "insufficient_sample"
    assert result["cells"]["rv_h21"]["matured"] == 11
    assert "paired_loss_vs_climatology" not in result["cells"]["rv_h21"]
    assert result["T7"]["would_trigger"] is False and result["T7"]["all_scope_cells_at_minimum"] is False
    assert "rv_h21" in render_table(result)


def test_live_verdict_runs_the_contract_arithmetic_once_a_cell_reaches_minimum(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path)
    minimum = int(C.load_contract_v13(root)["live_forward_gate"]["minimum_matured_origins_per_cell"])
    # 사건 0 의 60원점 — 귀무가 항등이 되어 '판정 무효' 로 떨어져야 한다 (강등도 확인도 아님)
    rows = [_row("rv_h5", f"2026-{1 + d // 28:02d}-{1 + d % 28:02d}", PINNED, p=0.05, label=0.0, base=0.55)
            for d in range(minimum)]
    _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, rows)
    result = live_verdict(root, draws=6)
    cell = result["cells"]["rv_h5"]
    assert cell["matured"] == minimum and cell["events"] == 0
    assert cell["status"] in {"untestable_by_construction", "verdict_void_negative_control"}
    assert cell["null_degenerate"] is True
    assert cell["negative_control_pass_rate"] == pytest.approx(1.0)
    assert "paired_loss_vs_climatology" in cell and cell["paired_loss_vs_climatology"]["n"] == minimum
    # 사건이 섞인 60원점 — 산술이 돌고 상태가 네 가지 중 하나로 떨어진다
    mixed = [_row("vix25_h21", f"2026-{1 + d // 28:02d}-{1 + d % 28:02d}", PINNED,
                  p=0.8 if d % 4 == 0 else 0.1, label=1.0 if d % 4 == 0 else 0.0, base=0.42)
             for d in range(minimum)]
    _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, rows + mixed)
    result = live_verdict(root, draws=6)
    cell = result["cells"]["vix25_h21"]
    assert cell["status"] in {"gate_passed_descriptive", "demotion_candidate",
                              "verdict_void_negative_control", "untestable_by_construction"}
    assert isinstance(cell["demotion_rule_would_hold"], bool)


def test_live_verdict_verb_is_registered_but_never_in_the_live_workflow() -> None:
    cli = (ROOT / "src/ai_fc/cli.py").read_text(encoding="utf-8")
    assert "timeseries-v13-vol-live-verdict" in cli
    workflow = (ROOT / ".github/workflows/timeseries-v13-vol-live.yml").read_text(encoding="utf-8")
    assert "timeseries-v13-vol-live-verdict" not in workflow, "판정 산술은 사람이 돌린다 — 자동화 밖"
    assert shutil.which("python") is not None
