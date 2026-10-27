"""시간 검증 기반 테스트 — T38·T39 + 실원장 재채점(read-only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc.mts_research.prequential import (
    LabeledRow,
    MtsPrequentialError,
    OofRecord,
    ValidationSlice,
    chronological_train_rows,
    mature_oof_view,
    purge_ok,
    reject_regenerated_oof,
    rescore_resolved,
)
from mts_research_fixtures import ROOT, utc


def _validation():
    return ValidationSlice(
        origin_session="2026-06-01",
        target_start_session="2026-06-02",
        information_cutoff_at=utc(2026, 6, 1, 21),
    )


def test_t38_purge_requires_all_four_conditions():
    """train_origin < val_origin 만으로는 부족하다 — 라벨 창·가용 시각까지 (T38, §12.3)."""
    validation = _validation()
    clean = LabeledRow("2026-02-02", "2026-03-05", utc(2026, 3, 6))
    assert purge_ok(clean, validation).ok

    overlapping_label = LabeledRow("2026-05-20", "2026-06-10", utc(2026, 6, 11))
    verdict = purge_ok(overlapping_label, validation)
    assert not verdict.ok and any("라벨 창 중첩" in v for v in verdict.violated)

    late_label = LabeledRow("2026-02-02", "2026-03-05", utc(2026, 6, 15))
    verdict = purge_ok(late_label, validation)
    assert not verdict.ok and any("미래 라벨" in v for v in verdict.violated)

    future_origin = LabeledRow("2026-07-01", "2026-07-10", utc(2026, 7, 11))
    assert not purge_ok(future_origin, validation).ok

    rows = [clean, overlapping_label, late_label, future_origin]
    assert chronological_train_rows(rows, validation) == [clean]


def test_t38_registered_gap_rule():
    validation = ValidationSlice(
        origin_session="2026-06-01", target_start_session="2026-06-02",
        information_cutoff_at=utc(2026, 6, 1, 21), gap_sessions_required=5,
    )
    row = LabeledRow("2026-05-28", "2026-05-29", utc(2026, 5, 30))
    index = {"2026-05-28": 100, "2026-06-01": 102}
    assert not purge_ok(row, validation, session_index=index).ok  # gap 2 < 5
    index_far = {"2026-05-28": 90, "2026-06-01": 102}
    verdict = purge_ok(row, validation, session_index=index_far)
    assert verdict.ok


def test_t39_regenerated_oof_cannot_replace_original():
    """과거 OOF 를 최신 fit 으로 재생성해 덮어쓰기 거부 — 재구성 ID 필수 (T39)."""
    original = OofRecord(
        forecast_id="f1", origin_session="2026-05-01",
        issued_at=utc(2026, 5, 1, 22), state_fit_cutoff_at=utc(2026, 5, 1, 20),
        label_available_at=utc(2026, 6, 5),
    )
    regenerated = OofRecord(
        forecast_id="f1-new", origin_session="2026-05-01",
        issued_at=utc(2026, 10, 1), state_fit_cutoff_at=utc(2026, 9, 30),
        label_available_at=utc(2026, 6, 5),
    )
    with pytest.raises(MtsPrequentialError):
        reject_regenerated_oof(original, regenerated)
    reconstruction = OofRecord(
        forecast_id="f1-recon", origin_session="2026-05-01",
        issued_at=utc(2026, 10, 1), state_fit_cutoff_at=utc(2026, 9, 30),
        label_available_at=utc(2026, 6, 5), reconstruction_of_forecast_id="f1",
    )
    reject_regenerated_oof(original, reconstruction)  # 재구성 표시 — 허용(별도 증거)
    # 보정 학습 뷰: 재구성 제외 + 미래 라벨 제외 + 미성숙 제외
    pending = OofRecord(
        forecast_id="f2", origin_session="2026-09-01",
        issued_at=utc(2026, 9, 1, 22), state_fit_cutoff_at=utc(2026, 9, 1, 20),
        label_available_at=None,
    )
    late = OofRecord(
        forecast_id="f3", origin_session="2026-06-01",
        issued_at=utc(2026, 6, 1, 22), state_fit_cutoff_at=utc(2026, 6, 1, 20),
        label_available_at=utc(2026, 8, 1),
    )
    view = mature_oof_view(
        [original, reconstruction, pending, late], calibration_fit_cutoff=utc(2026, 7, 1)
    )
    assert [r.forecast_id for r in view] == ["f1"]


def test_oof_posthoc_fit_rejected():
    bad = OofRecord(
        forecast_id="f1", origin_session="2026-05-01",
        issued_at=utc(2026, 5, 1, 22), state_fit_cutoff_at=utc(2026, 5, 2),
        label_available_at=utc(2026, 6, 5),
    )
    with pytest.raises(MtsPrequentialError):
        mature_oof_view([bad], calibration_fit_cutoff=utc(2026, 7, 1))


HAS_LEDGERS = (ROOT / "data/timeseries_v8/ledgers/shadow_resolutions.jsonl").is_file() and (
    ROOT / "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl"
).is_file()


@pytest.mark.skipif(not HAS_LEDGERS, reason="실원장 없음")
def test_rescore_resolved_matches_ledgers(tmp_path: Path):
    """기존 해소 원장을 우리 채점기로 재채점 — 원장 손실과 일치 + parquet 산출.

    출력은 합성 루트의 data/mts_research/derived 에만 쓴다 (실저장소 무변경).
    """
    import shutil

    root = tmp_path / "repo"
    for relative in (
        "data/timeseries_v8/ledgers/shadow_forecasts.jsonl",
        "data/timeseries_v8/ledgers/shadow_resolutions.jsonl",
        "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    result = rescore_resolved(root)
    assert result["ok"], result["mismatches"][:5]
    # F09 — V13 은 (cell, origin) dedupe 후 모델+기준선 2행씩, V8 은 해소 행당 2행
    import json as _json

    v13_rows = [
        _json.loads(line)
        for line in (ROOT / "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl")
        .read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    v8_rows = [
        _json.loads(line)
        for line in (ROOT / "data/timeseries_v8/ledgers/shadow_resolutions.jsonl")
        .read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    distinct_v13 = len({(str(r["cell"]), str(r["origin"])) for r in v13_rows})
    assert result["rows"] == 2 * (len(v8_rows) + distinct_v13)
    assert result["v13_dropped_duplicates"] == len(v13_rows) - distinct_v13
    out_path = root / "data/mts_research/derived/origin_losses.parquet"
    assert out_path.is_file()
    # 추론 패널 입력에 (track, cell, origin, model) 중복이 없다 — 이중 가중 차단 (F09)
    import pyarrow.parquet as pq

    table = pq.read_table(out_path)
    keys = list(zip(
        table.column("track").to_pylist(), table.column("cell").to_pylist(),
        table.column("origin").to_pylist(), table.column("model").to_pylist(),
    ))
    assert len(keys) == len(set(keys))


def test_f05_operational_oof_requires_recorded_at():
    """operational replay 보정 입력은 라벨 기록 시각까지 cutoff 이내여야 한다 (F05)."""
    base = dict(
        forecast_id="f1", origin_session="2026-05-01",
        issued_at=utc(2026, 5, 1, 21), state_fit_cutoff_at=utc(2026, 5, 1, 20),
        label_available_at=utc(2026, 6, 5),
    )
    no_recorded = OofRecord(**base)
    with pytest.raises(MtsPrequentialError, match="label_recorded_at"):
        mature_oof_view(
            [no_recorded], calibration_fit_cutoff=utc(2026, 7, 1),
            replay_mode="operational_replay",
        )
    late_recorded = OofRecord(**base, label_recorded_at=utc(2026, 7, 15))
    assert mature_oof_view(
        [late_recorded], calibration_fit_cutoff=utc(2026, 7, 1),
        replay_mode="operational_replay",
    ) == []  # 당시 원장에 없던 라벨 — 제외
    ok = OofRecord(**base, label_recorded_at=utc(2026, 6, 6))
    assert len(mature_oof_view(
        [ok], calibration_fit_cutoff=utc(2026, 7, 1),
        replay_mode="operational_replay",
    )) == 1
    # historical 모드는 기존 동작 유지 (recorded_at 불요)
    assert len(mature_oof_view([no_recorded], calibration_fit_cutoff=utc(2026, 7, 1))) == 1
