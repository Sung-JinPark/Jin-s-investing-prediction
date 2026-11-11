"""U1 — coherence-monitor --catch-up: 소급 append·준비 게이트(confirmed 포함)·결손 유예·한도.

실저장소는 읽기만 한다. 원장·derived 쓰기는 tmp_path 사본에서만 한다. as_of·now 는 고정.
감시 결과는 표시 라벨 후보일 뿐 — 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from ai_fc.mts_research import cli as research_cli
from ai_fc.mts_research.artifacts import read_chain
from ai_fc.mts_research.audits import coherence as C
from ai_fc.mts_research.monitor_thresholds import PINNED_THRESHOLD_HASH, THRESHOLDS_RELATIVE

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def base_copy(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("catchup") / "repo"
    for relative in list(C.INPUT_FILES.values()) + [THRESHOLDS_RELATIVE]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return root


def _copy(base: Path, tmp_path: Path, name: str = "repo") -> Path:
    target = tmp_path / name
    shutil.copytree(base, target)
    return target


def _args(**overrides) -> argparse.Namespace:
    body = {"as_of": "2026-11-09", "append": False, "catch_up": True, "report": None, "kind": None,
            "now": "2026-11-11T12:00:00+00:00"}
    body.update(overrides)
    return argparse.Namespace(**body)


def _seed(root: Path, as_of: str = "2026-11-04") -> None:
    code, out = C.run_monitor_cli(root, _args(as_of=as_of, append=True, catch_up=False))
    assert code == 0 and out["appended"] == 1


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _filter_jsonl(path: Path, drop) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not (line.strip() and drop(json.loads(line)))]
    path.write_text("".join(line + "\n" for line in kept), encoding="utf-8", newline="\n")
    return len(lines) - len(kept)


def _drop_v13(root: Path, as_of: str) -> None:
    assert _filter_jsonl(root / C.V13_LIVE_RELATIVE, lambda row: row.get("as_of") == as_of) >= 1


def _drop_confirmed_display(root: Path, origin: str) -> None:
    removed = _filter_jsonl(root / C.DISPLAY_RELATIVE,
                            lambda row: row.get("origin") == origin and row.get("input_state") == "confirmed")
    assert removed >= 1


def _drop_archive(root: Path, series: str, day: str) -> None:
    removed = _filter_jsonl(root / C.ARCHIVE_RELATIVE,
                            lambda row: row.get("series_id") == series
                            and str(row.get("observation_time"))[:10] == day)
    assert removed >= 1


def test_empty_ledger_appends_only_through_day(base_copy, tmp_path):
    root = _copy(base_copy, tmp_path)
    code, out = C.run_monitor_cli(root, _args(append=True))
    assert code == 0 and out["status"] == "appended" and out["appended"] == 1
    rows = read_chain(root, C.MONITOR_LEDGER_RELATIVE)
    assert [row["coherence_id"] for row in rows] == ["coh-2026-11-09-v1"]
    assert rows[0]["retrospective"] is True
    assert out["last_recorded_before"] is None


@pytest.fixture(scope="module")
def caught_up(base_copy, tmp_path_factory) -> tuple[Path, dict]:
    root = _copy(base_copy, tmp_path_factory.mktemp("caught"))
    _seed(root)
    code, out = C.run_monitor_cli(root, _args(append=True))
    assert code == 0
    return root, out


def test_catch_up_appends_every_ready_session_in_order(caught_up):
    root, out = caught_up
    assert out["status"] == "appended"
    assert [row["coherence_id"] for row in out["appended_rows"]] == [
        "coh-2026-11-05-v1", "coh-2026-11-06-v1", "coh-2026-11-09-v1"]
    rows = read_chain(root, C.MONITOR_LEDGER_RELATIVE)
    as_ofs = [row["as_of"] for row in rows]
    assert as_ofs == sorted(as_ofs) == ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09"]
    caught = rows[1:]
    assert len({row["computed_at"] for row in caught}) == 1
    for earlier, later in zip(caught, caught[1:]):
        assert set(later["input_files_sha256"]) >= set(earlier["input_files_sha256"])
    assert out["derived_n_dates"] == 4


def test_catch_up_is_idempotent_byte_for_byte(caught_up):
    root, _ = caught_up
    ledger, derived = root / C.MONITOR_LEDGER_RELATIVE, root / C.MONITOR_DERIVED_RELATIVE
    before = (_sha(ledger), _sha(derived))
    code, out = C.run_monitor_cli(root, _args(append=True, now="2026-11-12T12:00:00+00:00"))
    assert code == 0 and out["status"] == "up_to_date" and out["appended"] == 0
    assert (_sha(ledger), _sha(derived)) == before


def test_derived_latest_carries_threshold_c12_c6_fields(caught_up):
    root, _ = caught_up
    derived = json.loads((root / C.MONITOR_DERIVED_RELATIVE).read_text(encoding="utf-8"))
    latest = derived["latest"]
    assert latest["as_of"] == "2026-11-09"
    assert latest["threshold_hash"] == PINNED_THRESHOLD_HASH and latest["threshold_status"] == "ok"
    assert isinstance(latest["c12_stalled_series"], list) and isinstance(latest["c6_triggered"], list)
    assert "FED_EBP" in latest["c12_stalled_series"]


@pytest.fixture(scope="module")
def no_v13(base_copy, tmp_path_factory) -> Path:
    root = _copy(base_copy, tmp_path_factory.mktemp("nov13"))
    _drop_v13(root, "2026-11-09")
    return root


def test_waits_before_deadline_when_v13_missing(no_v13, tmp_path):
    root = _copy(no_v13, tmp_path)
    _seed(root)
    code, out = C.run_monitor_cli(root, _args(append=True, now="2026-11-10T12:00:00+00:00"))
    assert code == 0 and out["status"] == "appended"
    assert [row["coherence_id"] for row in out["appended_rows"]] == ["coh-2026-11-05-v1", "coh-2026-11-06-v1"]
    waiting = out["waiting"]
    assert waiting["reason"] == "waiting_inputs" and waiting["as_of"] == "2026-11-09"
    assert waiting["missing_surfaces"] == ["v13_vol"]
    assert waiting["deadline"] == "2026-11-10T21:15:00+00:00"
    # 대기만 남으면 status 가 대기 사유다
    code, again = C.run_monitor_cli(root, _args(append=True, now="2026-11-10T13:00:00+00:00"))
    assert code == 0 and again["status"] == "waiting_inputs" and again["appended"] == 0


@pytest.fixture(scope="module")
def provisional_v8(base_copy, tmp_path_factory) -> Path:
    root = _copy(base_copy, tmp_path_factory.mktemp("prov"))
    _drop_confirmed_display(root, "2026-11-09")
    return root


def test_waits_for_confirmed_v8_before_deadline(provisional_v8, tmp_path):
    root = _copy(provisional_v8, tmp_path)
    _seed(root)
    code, out = C.run_monitor_cli(root, _args(append=True, now="2026-11-10T12:00:00+00:00"))
    assert code == 0
    assert out["waiting"]["reason"] == "waiting_confirmed_v8" and out["waiting"]["as_of"] == "2026-11-09"
    ids = {row["coherence_id"] for row in read_chain(root, C.MONITOR_LEDGER_RELATIVE)}
    assert "coh-2026-11-09-v1" not in ids


def test_ready_before_deadline_appends_non_retrospective(base_copy, tmp_path):
    """일상 경로(confirmed V8 ∧ V13 존재, 명목 마감 전) — 대기 없이 append, retrospective False."""
    root = _copy(base_copy, tmp_path)
    _seed(root, "2026-11-06")
    code, out = C.run_monitor_cli(root, _args(append=True, now="2026-11-10T12:00:00+00:00"))
    assert code == 0 and out["status"] == "appended" and out["waiting"] is None
    assert [row["coherence_id"] for row in out["appended_rows"]] == ["coh-2026-11-09-v1"]
    row = {r["coherence_id"]: r for r in read_chain(root, C.MONITOR_LEDGER_RELATIVE)}["coh-2026-11-09-v1"]
    assert row["retrospective"] is False
    assert row["computed_at"] == "2026-11-10T12:00:00+00:00"


def test_appends_with_nulls_after_deadline(no_v13, provisional_v8, tmp_path):
    root = _copy(no_v13, tmp_path, "a")
    _seed(root)
    code, out = C.run_monitor_cli(root, _args(append=True, now="2026-11-11T00:00:00+00:00"))
    assert code == 0 and out["waiting"] is None
    row = {r["coherence_id"]: r for r in read_chain(root, C.MONITOR_LEDGER_RELATIVE)}["coh-2026-11-09-v1"]
    assert row["C4"]["null_reason"] == "no_v13_row_for_as_of"
    assert row["retrospective"] is True
    root_b = _copy(provisional_v8, tmp_path, "b")
    _seed(root_b)
    code, out = C.run_monitor_cli(root_b, _args(append=True, now="2026-11-11T00:00:00+00:00"))
    assert code == 0 and "coh-2026-11-09-v1" in [r["coherence_id"] for r in out["appended_rows"]]
    effective = C._effective_display(C.load_monitor_inputs(root_b).data["display"])[date(2026, 11, 9)]
    assert effective["input_state"] == "provisional"


@pytest.fixture(scope="module")
def archive_gap(base_copy, tmp_path_factory) -> Path:
    root = _copy(base_copy, tmp_path_factory.mktemp("gap"))
    _drop_archive(root, "NASDAQCOM", "2026-11-05")
    _seed(root)
    return root


def test_archive_gap_waits_through_grace(archive_gap, tmp_path):
    root = _copy(archive_gap, tmp_path)
    code, out = C.run_monitor_cli(root, _args(append=True, now="2026-11-11T12:00:00+00:00"))
    assert code == 0 and out["status"] == "pending_archive" and out["appended"] == 0
    assert out["waiting"]["hole_deadline"] == "2026-11-12T21:15:00+00:00"
    ids = [row["coherence_id"] for row in read_chain(root, C.MONITOR_LEDGER_RELATIVE)]
    assert ids == ["coh-2026-11-04-v1"]


def test_archive_hole_skipped_after_grace(archive_gap, tmp_path):
    root = _copy(archive_gap, tmp_path)
    code, out = C.run_monitor_cli(root, _args(append=True, now="2026-11-13T00:00:00+00:00"))
    assert code == 0
    assert [hole["as_of"] for hole in out["archive_holes"]] == ["2026-11-05"]
    assert [row["coherence_id"] for row in out["appended_rows"]] == ["coh-2026-11-06-v1", "coh-2026-11-09-v1"]
    assert all(row["retrospective"] for row in out["appended_rows"])
    ids = [row["coherence_id"] for row in read_chain(root, C.MONITOR_LEDGER_RELATIVE)]
    assert "coh-2026-11-05-v1" not in ids


def test_gap_limit_exits_4(base_copy, tmp_path, monkeypatch):
    root = _copy(base_copy, tmp_path)
    _seed(root)
    monkeypatch.setattr(C, "CATCH_UP_MAX_SESSIONS", 2)
    code, out = C.run_monitor_cli(root, _args(append=True))
    assert code == 4 and out["status"] == "catch_up_gap_exceeds_limit" and out["appended"] == 0
    assert len(read_chain(root, C.MONITOR_LEDGER_RELATIVE)) == 1


def test_threshold_mismatch_blocks_catch_up(base_copy, tmp_path):
    root = _copy(base_copy, tmp_path)
    path = root / THRESHOLDS_RELATIVE
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["coherence"]["C1_vol_staleness_max"] = 1.2
    path.write_text(json.dumps(payload), encoding="utf-8")
    code, out = C.run_monitor_cli(root, _args(append=True))
    assert code == 2 and out["status"] == "threshold_hash_mismatch"
    assert not (root / C.MONITOR_LEDGER_RELATIVE).exists()


def test_dry_run_plans_without_writing(base_copy, tmp_path):
    root = _copy(base_copy, tmp_path)
    code, out = C.run_monitor_cli(root, _args())
    assert code == 0 and out["status"] == "planned" and out["planned"] == ["2026-11-09"]
    assert out["mode"] == "catch_up_dry_run"
    assert not (root / C.MONITOR_LEDGER_RELATIVE).exists()
    assert not (root / C.MONITOR_DERIVED_RELATIVE).exists()


def test_cli_parser_accepts_catch_up_only_on_coherence(base_copy, tmp_path, capsys):
    root = _copy(base_copy, tmp_path)
    code = research_cli.main(["--root", str(root), "coherence-monitor", "--catch-up", "--as-of", "2026-11-09",
                              "--now", "2026-11-11T12:00:00+00:00"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "planned" and payload["mode"] == "catch_up_dry_run"
    with pytest.raises(SystemExit) as excinfo:
        research_cli.main(["--root", str(root), "v8-xnas-labels", "--catch-up"])
    assert excinfo.value.code == 2
