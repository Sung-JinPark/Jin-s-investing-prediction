"""CLI 동작 테스트 — exit code 규약 + T53(네트워크 차단 재생)."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from ai_fc.mts_research.cli import main
from mts_research_fixtures import ROOT, build_synthetic_snapshot, make_event, research_root, utc


@pytest.fixture()
def no_network(monkeypatch):
    """socket 차단 — replay 는 저장된 raw·계약·lock 만으로 동작해야 한다 (T53)."""

    def _blocked(*args, **kwargs):
        raise AssertionError("네트워크 호출 발생 — replay 는 오프라인이어야 한다 (T53)")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def test_validate_contract_draft_blocks_run(tmp_path: Path, capsys, no_network):
    root = research_root(tmp_path)
    contract = str(root / "data/mts_research/contracts/mts_research_v1.draft.yaml")
    assert main(["--root", str(root), "validate-contract", "--contract", contract]) == 0
    assert main([
        "--root", str(root), "validate-contract", "--contract", contract, "--action", "run",
    ]) == 2  # 검증 차단 exit code


def test_run_experiment_refused_without_dry_run(tmp_path: Path, capsys, no_network):
    root = research_root(tmp_path)
    assert main(["--root", str(root), "run-experiment"]) == 2
    assert main(["--root", str(root), "run-experiment", "--dry-run"]) == 4  # 필수 null 미해결
    out = capsys.readouterr().out
    assert "budget_consumed" in out and '"protected_payload_read": 0' in out


def test_evaluate_refused_without_scope(tmp_path: Path, no_network):
    root = research_root(tmp_path)
    assert main(["--root", str(root), "evaluate", "--experiment-id", "X"]) == 4


def test_t53_snapshot_build_offline(no_network):
    """네트워크 차단 하에 snapshot 생성 — 저장된 이벤트만으로 재생 (T53)."""
    events = [
        make_event("VIX", "2026-10-15", 15.0, available_at=utc(2026, 10, 15, 21)),
        make_event("VIX", "2026-10-16", 16.0, available_at=utc(2026, 10, 16, 21)),
    ]
    snap = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20))
    assert snap.manifest.snapshot_id.startswith("mts-snap-")


HAS_V13 = (ROOT / "data/timeseries_v13/ledgers/vol_live.jsonl").is_file()


@pytest.mark.skipif(not HAS_V13, reason="실원장 없음")
def test_t53_pb_replay_offline(no_network):
    """실원장 PB replay 도 네트워크 없이 동작한다 (T53 — 저장 원자료만)."""
    from ai_fc.mts_research.adapters.pb import replay_vol_live_rows

    result = replay_vol_live_rows(ROOT, max_rows=2)
    assert result["rows"] == 2 and result["failures"] == []


def test_inventory_smoke(capsys, no_network):
    assert main(["--root", str(ROOT), "inventory"]) == 0
    out = capsys.readouterr().out
    assert "environment_lock_hash" in out
