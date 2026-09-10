"""P5 외부 정보집합 스토어 — 봉인 불가침·라이선스·PIT 라벨을 고정한다.

이 트랙에서 새로 생긴 위험은 두 가지다. ① 봉인 V2 아카이브에 쓰는 것(계약 36행 위반),
② 라이선스가 정리되지 않은 CBOE 직접 경로를 쓰는 것. 둘 다 코드로 막는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
TOOL = ROOT / "tools/v13_fetch_external_vol.py"
STORE = ROOT / "data/timeseries_v13/external"


def test_tool_never_writes_to_the_sealed_archive() -> None:
    source = TOOL.read_text(encoding="utf-8")
    for sealed in ("data/timeseries_v2", "data/timeseries_v8", "market_observations"):
        assert sealed not in source, f"봉인 경로 {sealed} 가 수집기에 나타나면 안 된다"
    assert "data/timeseries_v13/external" in source


def test_tool_uses_only_the_approved_license_path() -> None:
    """CBOE 직접 CDN 은 라이선스 보류 상태다 — 승인된 FRED 경유만 쓴다."""
    source = TOOL.read_text(encoding="utf-8")
    assert "fred.stlouisfed.org" in source
    assert "cdn.cboe.com" not in source, "CBOE 직접 경로는 licenses.generated.md 27행에서 보류"
    assert "fred_market_signals" in source

    ledger = (ROOT / "docs/generated/licenses.generated.md").read_text(encoding="utf-8")
    approved = [line for line in ledger.splitlines()
                if "fred_market_signals" in line and "approved" in line]
    assert approved, "fred_market_signals 가 라이선스 대장에서 approved 여야 한다"


def test_registered_in_the_ledger_registry() -> None:
    import yaml

    registry = yaml.safe_load((ROOT / "data/contracts/ledger_registry.yaml").read_text(encoding="utf-8"))
    entries = registry.get("ledgers") or registry.get("entries") or []
    if isinstance(registry, dict) and not entries:
        for value in registry.values():
            if isinstance(value, list) and value and isinstance(value[0], dict) and "path" in value[0]:
                entries = value
                break
    paths = {e.get("path") for e in entries if isinstance(e, dict)}
    assert "data/timeseries_v13/external/vol_indices.jsonl" in paths
    assert "data/timeseries_v13/external/raw_receipts.jsonl" in paths


@pytest.mark.skipif(not (STORE / "vol_indices.jsonl").is_file(), reason="스토어 미수집")
def test_observations_carry_an_honest_pit_label() -> None:
    rows = [json.loads(line) for line in
            (STORE / "vol_indices.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    for row in rows[:200]:
        assert row["data_grade"] == "published_close_no_revision"
        # available_at 은 관측일 종가 배포 시각이어야 한다 — 미래로 새면 누수다
        assert row["available_at"].startswith(row["observation_time"]), (
            "available_at 이 관측일과 다른 날짜면 PIT 라벨이 거짓이다")
        assert row["source_id"] == "fred_market_signals"


@pytest.mark.skipif(not (STORE / "vol_indices.jsonl").is_file(), reason="스토어 미수집")
def test_no_duplicate_series_date_pairs() -> None:
    seen: set[tuple[str, str]] = set()
    for line in (STORE / "vol_indices.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (row["series_id"], row["observation_time"])
        assert key not in seen, f"중복 관측 {key} — 수집기가 멱등이어야 한다"
        seen.add(key)


@pytest.mark.skipif(not (STORE / "raw_receipts.jsonl").is_file(), reason="영수증 미수집")
def test_receipts_pin_the_raw_bytes() -> None:
    import gzip
    import hashlib

    receipts = [json.loads(line) for line in
                (STORE / "raw_receipts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert receipts
    for receipt in receipts:
        blob = ROOT / receipt["raw_path"]
        assert blob.is_file(), f"원자료 {receipt['raw_path']} 가 없다"
        digest = hashlib.sha256(gzip.decompress(blob.read_bytes())).hexdigest()
        assert digest == receipt["raw_sha256"], "영수증 sha256 이 보관된 원자료와 어긋난다"
