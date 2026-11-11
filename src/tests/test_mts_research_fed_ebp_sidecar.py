"""P8 FED_EBP 연구 사이드카 — 두 날짜 형식 파서·빈티지 재생·멱등 append.

실제 저장소 데이터는 읽기만 한다(오라클은 2026-11-10 이하 영수증으로 범위를 묶는다).
쓰기 테스트는 전부 tmp_path 합성 루트에서 한다.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from ai_fc.mts_research.artifacts import MtsArtifactError, read_chain
from ai_fc.mts_research.fed_ebp_sidecar import (
    LEDGER_RELATIVE,
    RECEIPTS_RELATIVE,
    SOURCE_ID,
    UPSTREAM_SOURCE_ID,
    V2_FACTS_RELATIVE,
    compare_with_v2,
    parse_ebp_csv_any,
    replay_receipts,
    run_cli,
    state_at,
)

ROOT = Path(__file__).resolve().parents[2]
ORACLE_CUTOFF = "2026-11-10T23:59:59+00:00"
SHA_MDY = "cc51b2747654e3ed003e0a6ce5500de054c1a8dcd3ec00bace1c6742416ab2eb"
SHA_ISO_1 = "d7a7ddf7bdaa6f577cffb5e668cbe8ba5202bc864813c6e17fb73ea339fd5663"
SHA_ISO_2 = "caa16e0619cb5399b9c8f44433868351f01973f9594c50a4f1f87dd0856542c5"


def _args(**overrides) -> argparse.Namespace:
    body = {"as_of": None, "append": False, "report": None, "kind": None, "now": None}
    body.update(overrides)
    return argparse.Namespace(**body)


# ---------------------------------------------------------------------------
# 파서
# ---------------------------------------------------------------------------


def test_parse_both_date_formats_with_bom_and_crlf():
    mdy = "﻿date,gz_spread,ebp,est_prob\r\n1/1/1973,1.13,-0.046854494,0.18\r\n2/1/1973,1.07,-0.05,\r\n"
    iso = "date,gz_spread,ebp,est_prob\n1973-02-01,1.07,-0.05,0.17\n1973-01-01,1.13,-0.0475,0.18\n"
    rows_mdy = parse_ebp_csv_any(mdy)
    rows_iso = parse_ebp_csv_any(iso)
    assert [row.observation_time for row in rows_mdy] == ["1973-01-01", "1973-02-01"]
    assert [row.observation_time for row in rows_iso] == ["1973-01-01", "1973-02-01"]
    assert {row.date_format for row in rows_mdy} == {"mdy"}
    assert {row.date_format for row in rows_iso} == {"iso"}
    assert rows_mdy[0].ebp == -0.046854494
    assert rows_mdy[1].est_prob is None  # 선택 열 빈칸은 None


def test_parse_skips_blank_ebp_like_sealed_parser():
    rows = parse_ebp_csv_any("date,ebp\n2026-01-01,.\n2026-02-01,\n2026-03-01,0.1\n")
    assert [row.observation_time for row in rows] == ["2026-03-01"]


@pytest.mark.parametrize("text, fragment", [
    ("date,ebp\n2026.01.01,0.1\n", "날짜 형식 미지원"),
    ("date,ebp\n2026-01-01,0.1\n1/1/2026,0.2\n", "날짜 중복"),
    ("day,ebp\n2026-01-01,0.1\n", "헤더"),
    ("date,ebp\n2026-01-01,nan\n", "비유한값"),
    ("date,ebp\n2026-01-01,abc\n", "숫자 아님"),
])
def test_parse_fails_closed(text, fragment):
    with pytest.raises(MtsArtifactError, match=fragment):
        parse_ebp_csv_any(text)


def test_receipt_path_constants_match_sealed_module():
    from ai_fc.timeseries_v2.market_archive import ARCHIVE_FACTS, ARCHIVE_RECEIPTS

    assert ARCHIVE_RECEIPTS == RECEIPTS_RELATIVE
    assert ARCHIVE_FACTS == V2_FACTS_RELATIVE


# ---------------------------------------------------------------------------
# 실제 저장소 오라클 (읽기 전용, 2026-11-10 이하 영수증으로 고정)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_rows() -> list[dict]:
    return replay_receipts(ROOT, retrieved_until=ORACLE_CUTOFF)


def _first_receipt_at(digest: str) -> str:
    rows = [json.loads(line) for line in (ROOT / RECEIPTS_RELATIVE).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    times = sorted(row["retrieved_at"] for row in rows
                   if row.get("source_id") == UPSTREAM_SOURCE_ID and row["raw_sha256"] == digest)
    return times[0]


def test_real_receipts_three_vintages_all_parse(real_rows):
    by_vintage: dict[int, set[str]] = {}
    for row in real_rows:
        by_vintage.setdefault(row["vintage_seq"], set()).add(row["raw_sha256"])
    assert by_vintage == {1: {SHA_MDY}, 2: {SHA_ISO_1}, 3: {SHA_ISO_2}}
    formats = {row["vintage_seq"]: row["source_date_format"] for row in real_rows}
    assert formats == {1: "mdy", 2: "iso", 3: "iso"}
    kinds = {}
    for row in real_rows:
        kinds[(row["vintage_seq"], row["change_kind"])] = kinds.get((row["vintage_seq"], row["change_kind"]), 0) + 1
    assert kinds == {(1, "new"): 643, (2, "new"): 2, (2, "revised"): 643, (3, "new"): 1, (3, "revised"): 645}
    assert len(real_rows) == 1934  # 영수증 152 × 관측 ~645 가 아니라 빈티지 델타만


def test_real_last_observation_and_1973_revisions(real_rows):
    current = state_at(real_rows)
    assert max(current) == "2026-10-01"
    assert current["2026-10-01"]["ebp"] == pytest.approx(-0.26533114775416333, abs=1e-15)
    chain = sorted((row for row in real_rows if row["observation_time"] == "1973-01-01"),
                   key=lambda row: row["revision_seq"])
    assert [round(row["ebp"], 6) for row in chain] == [-0.046854, -0.047587, -0.047659]
    assert [row["revision_seq"] for row in chain] == [1, 2, 3]
    assert chain[1]["supersedes"] == chain[0]["observation_id"]
    assert chain[2]["supersedes"] == chain[1]["observation_id"]


def test_real_available_at_is_first_receipt_retrieved_at(real_rows):
    for digest in (SHA_MDY, SHA_ISO_1, SHA_ISO_2):
        stamps = {row["available_at"] for row in real_rows if row["raw_sha256"] == digest}
        assert stamps == {_first_receipt_at(digest)}
    # PIT 재구성: ISO 전환 이전 시각에서는 07-01 이 마지막, 개정 전 값
    before_iso = state_at(real_rows, cutoff="2026-10-07T07:46:52+00:00")
    assert max(before_iso) == "2026-07-01"
    assert before_iso["1973-01-01"]["ebp"] == -0.046854494


def test_real_vintage1_bit_identical_to_v2_archive(real_rows):
    report = compare_with_v2(ROOT, real_rows)
    assert report["comparable"] is True
    assert report["compared_through_vintage_seq"] == 1
    assert report["n_mismatched"] == 0
    assert report["n_v2"] >= 643


def test_real_rows_are_research_only(real_rows):
    for row in real_rows:
        assert row["source_id"] == SOURCE_ID
        assert row["scoring_excluded"] is True and row["display_only"] is True
        assert row["live_forecast_use"] is False
        assert row["notice"] == "참고 의견, 매매 신호 아님"
    assert len({row["observation_id"] for row in real_rows}) == len(real_rows)


def test_committed_ledger_matches_replay(real_rows):
    """커밋된 원장이 있으면: 체인 무결 + 2026-11-10 이하 재생 행과 바이트 동일."""
    if not (ROOT / LEDGER_RELATIVE).is_file():
        pytest.skip("fed_ebp_v1.jsonl 아직 없음")
    ledger = {row["observation_id"]: row for row in read_chain(ROOT, LEDGER_RELATIVE)}
    for row in real_rows:
        body = {k: v for k, v in ledger[row["observation_id"]].items()
                if k not in ("previous_hash", "content_hash")}
        assert body == row


def test_real_dry_run_reports_sealed_parser_failure_without_writing():
    before = (ROOT / LEDGER_RELATIVE).read_bytes() if (ROOT / LEDGER_RELATIVE).is_file() else None
    code, payload = run_cli(ROOT, _args(now=ORACLE_CUTOFF))
    after = (ROOT / LEDGER_RELATIVE).read_bytes() if (ROOT / LEDGER_RELATIVE).is_file() else None
    assert code == 0 and before == after
    assert payload["rows_appended"] == 0
    assert payload["n_vintages"] == 3 and payload["n"] == 1934 and payload["n_dates"] == 646
    sealed = [vintage["sealed_v2_parser"]["ok"] for vintage in payload["vintages"]]
    assert sealed == [True, False, False]
    assert "%m/%d/%Y" in payload["vintages"][1]["sealed_v2_parser"]["error"]
    assert payload["v2_comparison"]["v2_months_behind"] == 3
    assert payload["display_only"] is True and payload["single_episode"] is False


# ---------------------------------------------------------------------------
# 합성 루트 — 쓰기·멱등·철회·복귀·fail-closed
# ---------------------------------------------------------------------------


def _write_receipts(root: Path, payloads: list[tuple[str, str]]) -> None:
    """(retrieved_at, csv 본문) 목록을 V2 영수증 원장·원본 gzip 형태로 합성한다."""
    lines = []
    for index, (retrieved_at, text) in enumerate(payloads):
        payload = text.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        relative = f"data/timeseries_v2/raw/market/{UPSTREAM_SOURCE_ID}/{digest}.gz"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gzip.compress(payload, mtime=0))
        lines.append(json.dumps({
            "receipt_id": f"market-receipt-{index:024d}", "source_id": UPSTREAM_SOURCE_ID,
            "retrieved_at": retrieved_at, "raw_sha256": digest, "raw_path": relative,
            "redistribution": "repository_raw_allowed", "http_status": 200,
        }))
    path = root / RECEIPTS_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


A = "date,gz_spread,ebp,est_prob\n1/1/2026,1.0,-0.10,0.2\n2/1/2026,1.1,-0.20,0.3\n"
B = "date,gz_spread,ebp,est_prob\n2026-01-01,1.0,-0.11,0.2\n2026-03-01,1.2,-0.30,0.4\n"


@pytest.fixture
def synthetic_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _write_receipts(root, [
        ("2026-09-01T06:00:00+00:00", A),
        ("2026-09-02T06:00:00+00:00", A),  # 재수신 — 행 없음
        ("2026-10-07T07:00:00+00:00", B),  # 01 개정 · 02 철회 · 03 신규
        ("2026-11-05T16:00:00+00:00", A),  # A 복귀 — 새 빈티지
    ])
    return root


def test_synthetic_vintage_rules(synthetic_root):
    rows = replay_receipts(synthetic_root)
    summary = [(row["vintage_seq"], row["observation_time"], row["change_kind"], row["ebp"]) for row in rows]
    assert summary == [
        (1, "2026-01-01", "new", -0.10),
        (1, "2026-02-01", "new", -0.20),
        (2, "2026-01-01", "revised", -0.11),
        (2, "2026-03-01", "new", -0.30),
        (2, "2026-02-01", "withdrawn", None),
        (3, "2026-01-01", "revised", -0.10),
        (3, "2026-02-01", "revised", -0.20),
        (3, "2026-03-01", "withdrawn", None),
    ]
    assert {row["available_at"] for row in rows if row["vintage_seq"] == 1} == {"2026-09-01T06:00:00+00:00"}
    mid = state_at(rows, cutoff="2026-10-31T00:00:00+00:00")
    assert sorted(mid) == ["2026-01-01", "2026-03-01"]


def test_synthetic_dry_run_then_append_is_idempotent(synthetic_root):
    code, dry = run_cli(synthetic_root, _args())
    assert code == 0 and dry["rows_to_append"] == 8 and dry["rows_appended"] == 0
    assert not (synthetic_root / LEDGER_RELATIVE).exists()

    code, first = run_cli(synthetic_root, _args(append=True))
    assert code == 0 and first["rows_appended"] == 8
    ledger_bytes = (synthetic_root / LEDGER_RELATIVE).read_bytes()
    assert len(read_chain(synthetic_root, LEDGER_RELATIVE)) == 8

    code, second = run_cli(synthetic_root, _args(append=True))
    assert code == 0 and second["rows_appended"] == 0 and second["rows_to_append"] == 0
    assert (synthetic_root / LEDGER_RELATIVE).read_bytes() == ledger_bytes


def test_synthetic_prefix_cutoff_then_full_append_extends_chain(synthetic_root):
    code, early = run_cli(synthetic_root, _args(append=True, as_of="2026-09-30"))
    assert code == 0 and early["rows_appended"] == 2 and early["n_vintages"] == 1
    code, full = run_cli(synthetic_root, _args(append=True))
    assert code == 0 and full["rows_appended"] == 6
    assert full["ledger_rows_not_in_replay"] == 0
    assert len(read_chain(synthetic_root, LEDGER_RELATIVE)) == 8


def test_synthetic_raw_hash_mismatch_fails_closed(synthetic_root):
    receipt = json.loads((synthetic_root / RECEIPTS_RELATIVE).read_text(encoding="utf-8").splitlines()[0])
    (synthetic_root / receipt["raw_path"]).write_bytes(gzip.compress(b"date,ebp\n2026-01-01,9\n", mtime=0))
    code, payload = run_cli(synthetic_root, _args(append=True))
    assert code == 2 and "sha256 불일치" in payload["error"]
    assert not (synthetic_root / LEDGER_RELATIVE).exists()


def test_synthetic_missing_raw_fails_closed(synthetic_root):
    receipt = json.loads((synthetic_root / RECEIPTS_RELATIVE).read_text(encoding="utf-8").splitlines()[-1])
    (synthetic_root / receipt["raw_path"]).unlink()
    code, payload = run_cli(synthetic_root, _args())
    assert code == 2 and "원본 gzip 없음" in payload["error"]


def test_synthetic_v2_archive_untouched(synthetic_root):
    facts = synthetic_root / V2_FACTS_RELATIVE
    facts.write_text("", encoding="utf-8")
    receipts_before = (synthetic_root / RECEIPTS_RELATIVE).read_bytes()
    run_cli(synthetic_root, _args(append=True))
    assert facts.read_bytes() == b""
    assert (synthetic_root / RECEIPTS_RELATIVE).read_bytes() == receipts_before


# ---------------------------------------------------------------------------
# 순수 확장 가드 — 소급 영수증·cutoff·중단 이어쓰기
# ---------------------------------------------------------------------------


B2 = "date,gz_spread,ebp,est_prob\n2026-01-01,1.0,-0.11,0.2\n2026-02-01,1.1,-0.21,0.3\n"
C = "date,gz_spread,ebp,est_prob\n2026-01-01,1.0,-0.50,0.2\n2026-02-01,1.1,-0.60,0.3\n"


def test_backdated_receipt_fails_closed_without_writing(tmp_path):
    """리뷰 재현: A(09-01)·B2(10-07) append 뒤 C(09-15) 소급 영수증 → 갈라진 가지를 붙이지 않는다."""
    root = tmp_path / "repo"
    _write_receipts(root, [("2026-09-01T06:00:00+00:00", A), ("2026-10-07T07:00:00+00:00", B2)])
    code, first = run_cli(root, _args(append=True))
    assert code == 0 and first["rows_appended"] == 4
    ledger_bytes = (root / LEDGER_RELATIVE).read_bytes()

    _write_receipts(root, [("2026-09-01T06:00:00+00:00", A), ("2026-10-07T07:00:00+00:00", B2),
                           ("2026-09-15T06:00:00+00:00", C)])
    for append in (False, True):  # dry-run 도 같은 검사로 미리 막는다
        code, payload = run_cli(root, _args(append=append))
        assert code == 2 and payload["status"] == "error"
        assert "접두부가 아님" in payload["error"]
        assert (root / LEDGER_RELATIVE).read_bytes() == ledger_bytes


def test_backdated_receipt_after_cutoff_ledger_fails_closed(tmp_path):
    """cutoff 이내 원장은 접두부지만 붙일 행이 원장 최대 available_at 보다 이르면 막는다."""
    root = tmp_path / "repo"
    _write_receipts(root, [("2026-09-01T06:00:00+00:00", A), ("2026-10-07T07:00:00+00:00", B2)])
    assert run_cli(root, _args(append=True))[0] == 0
    ledger_bytes = (root / LEDGER_RELATIVE).read_bytes()
    _write_receipts(root, [("2026-09-01T06:00:00+00:00", A), ("2026-10-07T07:00:00+00:00", B2),
                           ("2026-09-15T06:00:00+00:00", C)])
    code, payload = run_cli(root, _args(append=True, as_of="2026-09-30"))
    assert code == 2 and "순수 확장 아님" in payload["error"]
    assert (root / LEDGER_RELATIVE).read_bytes() == ledger_bytes


def test_earlier_cutoff_after_full_append_is_noop(synthetic_root):
    assert run_cli(synthetic_root, _args(append=True))[0] == 0
    ledger_bytes = (synthetic_root / LEDGER_RELATIVE).read_bytes()
    code, payload = run_cli(synthetic_root, _args(append=True, as_of="2026-09-30"))
    assert code == 0 and payload["rows_appended"] == 0 and payload["rows_to_append"] == 0
    assert payload["ledger_rows_not_in_replay"] == 6  # cutoff 밖 정당한 행 — 대조 대상 아님
    assert (synthetic_root / LEDGER_RELATIVE).read_bytes() == ledger_bytes


def test_interrupted_vintage_resumes(synthetic_root):
    """빈티지 중간에서 끊긴 원장(같은 영수증·같은 available_at)은 이어서 붙인다."""
    from ai_fc.mts_research.artifacts import append_event

    rows = replay_receipts(synthetic_root)
    for row in rows[:3]:  # 빈티지 2 첫 행까지만 쓰인 상태
        append_event(synthetic_root, LEDGER_RELATIVE, row)
    code, payload = run_cli(synthetic_root, _args(append=True))
    assert code == 0 and payload["rows_appended"] == 5
    assert [row["observation_id"] for row in read_chain(synthetic_root, LEDGER_RELATIVE)] == \
        [row["observation_id"] for row in rows]


def test_receipts_backdated_in_file_is_reported(tmp_path):
    root = tmp_path / "repo"
    _write_receipts(root, [("2026-10-07T07:00:00+00:00", B2), ("2026-09-01T06:00:00+00:00", A)])
    code, payload = run_cli(root, _args())
    assert code == 0 and payload["receipts_backdated_in_file"] == 1
    assert [vintage["available_at"] for vintage in payload["vintages"]] == [
        "2026-09-01T06:00:00+00:00", "2026-10-07T07:00:00+00:00"]


def test_same_sha_other_missing_path_fails_closed(synthetic_root):
    """같은 sha 를 캐시에 들고 있어도 영수증마다 raw_path 존재를 확인한다."""
    path = synthetic_root / RECEIPTS_RELATIVE
    lines = path.read_text(encoding="utf-8").splitlines()
    second = json.loads(lines[1])
    second["raw_path"] = "data/timeseries_v2/raw/market/missing/elsewhere.gz"
    lines[1] = json.dumps(second)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    code, payload = run_cli(synthetic_root, _args())
    assert code == 2 and "원본 gzip 없음" in payload["error"]


def test_malformed_receipt_line_fails_closed(synthetic_root):
    path = synthetic_root / RECEIPTS_RELATIVE
    path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    code, payload = run_cli(synthetic_root, _args())
    assert code == 2 and "JSON 아님" in payload["error"]


def test_committed_ledger_inside_cutoff_equals_replay_exactly(real_rows):
    """역방향: 2026-11-10 이하 원장 행은 재생 행과 순서까지 같다(모르는 행·갈라진 가지 0)."""
    if not (ROOT / LEDGER_RELATIVE).is_file():
        pytest.skip("fed_ebp_v1.jsonl 아직 없음")
    ledger = read_chain(ROOT, LEDGER_RELATIVE)
    limit = datetime.fromisoformat(ORACLE_CUTOFF)
    inside = [row["observation_id"] for row in ledger
              if datetime.fromisoformat(row["available_at"].replace("Z", "+00:00")) <= limit]
    assert inside == [row["observation_id"] for row in real_rows]
