"""§12 nested temporal 검증 기반 — purge 술어·성숙 OOF 가드·기존 해소 재채점.

이번 구현 범위(W3)는 **합성 검증 + 기존 해소 원장의 read-only 재채점**이다.
새 실자료 실험·새 예측 생산은 없다 (W7 BLOCKED).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .records import require_utc

ORIGIN_LOSSES_RELATIVE = Path("data/mts_research/derived/origin_losses.parquet")


class MtsPrequentialError(RuntimeError):
    """시간 검증 불변조건 위반 — fail-closed."""


# ---------------------------------------------------------------------------
# §12.3 purge 술어 (T38)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LabeledRow:
    origin_session: str
    label_end_session: str
    label_available_at: datetime


@dataclass(frozen=True)
class ValidationSlice:
    origin_session: str
    target_start_session: str
    information_cutoff_at: datetime
    gap_sessions_required: int = 0  # 등록된 추가 gap 규칙


@dataclass(frozen=True)
class PurgeVerdict:
    ok: bool
    violated: tuple[str, ...]


def purge_ok(
    train: LabeledRow,
    validation: ValidationSlice,
    *,
    session_index: dict[str, int] | None = None,
) -> PurgeVerdict:
    """훈련 행이 검증 slice 를 오염시키지 않는지 — 4조건 전부 (§12.3).

    train_origin < val_origin 만으로는 부족하다.
    """
    require_utc(train.label_available_at, field="label_available_at")
    require_utc(validation.information_cutoff_at, field="information_cutoff_at")
    violated: list[str] = []
    if not train.origin_session < validation.origin_session:
        violated.append("train_origin >= validation_origin")
    if not train.label_end_session < validation.target_start_session:
        violated.append("label_end_session >= validation_target_start_session (라벨 창 중첩)")
    if not train.label_available_at <= validation.information_cutoff_at:
        violated.append("label_available_at > validation_information_cutoff (미래 라벨)")
    if validation.gap_sessions_required > 0:
        if session_index is None:
            violated.append("gap 규칙 검사에 세션 인덱스 필요")
        else:
            gap = session_index[validation.origin_session] - session_index[train.origin_session]
            if gap < validation.gap_sessions_required:
                violated.append(f"등록 gap {validation.gap_sessions_required} 미달 ({gap})")
    return PurgeVerdict(ok=not violated, violated=tuple(violated))


def chronological_train_rows(
    rows: Sequence[LabeledRow], validation: ValidationSlice,
    *, session_index: dict[str, int] | None = None,
) -> list[LabeledRow]:
    """검증 slice 에 대해 purge 를 통과하는 훈련 행만 — '뒤에 embargo 를 뒀으니
    미래 학습이 괜찮다' 는 해석은 없다: 미래 행 자체가 들어오지 않는다 (§12.3)."""
    return [row for row in rows if purge_ok(row, validation, session_index=session_index).ok]


# ---------------------------------------------------------------------------
# 성숙 OOF 가드 (T39·T56)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OofRecord:
    forecast_id: str
    origin_session: str
    issued_at: datetime
    state_fit_cutoff_at: datetime
    label_available_at: datetime | None
    reconstruction_of_forecast_id: str | None = None
    label_recorded_at: datetime | None = None  # 라벨이 우리 원장에 기록된 시각 (T59, F05)


def mature_oof_view(
    records: Iterable[OofRecord],
    *,
    calibration_fit_cutoff: datetime,
    replay_mode: str = "historical_information_set_reconstruction",
) -> list[OofRecord]:
    """보정기 학습에 쓸 수 있는 OOF — §10.1 조건 전부.

    - raw forecast 가 자신의 outcome 을 보기 전에 생성됐음: fit cutoff <= 발행 원점 cutoff
      (여기서는 state_fit_cutoff_at <= issued_at 로 표현).
    - label_available_at <= calibration_fit_cutoff (T56).
    - 재구성(reconstruction_of != None)은 원본 OOF 를 대체할 수 없다 (T39) — 제외.
    - 외부 리뷰 F05 (2026-10-27): operational_replay 에서는 maturity.matured_view 와
      같은 규율로 **라벨 기록 시각**(label_recorded_at)도 cutoff 이내여야 한다 —
      가용성만 보면 '그때 우리 원장에 없던 라벨' 로 보정기를 학습하게 된다.
    """
    require_utc(calibration_fit_cutoff, field="calibration_fit_cutoff")
    if replay_mode not in (
        "operational_replay", "historical_information_set_reconstruction",
    ):
        raise MtsPrequentialError(f"알 수 없는 replay_mode: {replay_mode}")
    selected: list[OofRecord] = []
    for record in records:
        if record.reconstruction_of_forecast_id is not None:
            continue  # 재구성은 별도 증거 — 과거 OOF 발행을 사후 대체하지 않는다 (T39)
        if record.state_fit_cutoff_at > record.issued_at:
            raise MtsPrequentialError(
                f"{record.forecast_id}: fit cutoff 가 발행 이후 — OOF 아님 (사후 적합)"
            )
        if record.label_available_at is None:
            continue  # 미성숙
        if record.label_available_at > calibration_fit_cutoff:
            continue  # 미래 라벨 (T56)
        if replay_mode == "operational_replay":
            if record.label_recorded_at is None:
                raise MtsPrequentialError(
                    f"{record.forecast_id}: operational_replay 는 label_recorded_at 필수 (F05)"
                )
            if record.label_recorded_at > calibration_fit_cutoff:
                continue  # 당시 원장에 아직 없던 라벨 (T59 규율의 보정판)
        selected.append(record)
    return selected


def reject_regenerated_oof(original: OofRecord, candidate: OofRecord) -> None:
    """같은 논리 예측의 최신-상태 재생성이 원본을 덮어쓰려 하면 거부 (T39)."""
    if (
        candidate.origin_session == original.origin_session
        and candidate.forecast_id != original.forecast_id
        and candidate.reconstruction_of_forecast_id is None
    ):
        raise MtsPrequentialError(
            "과거 OOF 를 최신 fit 으로 재생성해 원본처럼 등록할 수 없다 — "
            "reconstruction_of_forecast_id 필수 (T39)"
        )


# ---------------------------------------------------------------------------
# 기존 해소 원장의 read-only 재채점 → origin_losses.parquet (§19.3)
# ---------------------------------------------------------------------------


def rescore_resolved(root: Path) -> dict[str, Any]:
    """V8 shadow·V13 vol 해소 원장을 우리 채점기로 재채점해 손실 패널 행을 만든다.

    - V8: 저장된 quantile_grid + 저장된 actual 로 CRPS 재계산 — 원장 값과 1e-12 대조.
    - V13: 기록된 p·label 로 Brier 재계산 — 원장 값과 1e-8 대조(8자리 반올림 저장).
    - 출력: data/mts_research/derived/origin_losses.parquet (재생성 가능한 파생물).
    """
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    from .scores import brier as brier_score
    from .scores import crps_weighted_empirical

    rows: list[dict[str, Any]] = []
    mismatches: list[str] = []

    v8_forecasts = root / "data/timeseries_v8/ledgers/shadow_forecasts.jsonl"
    v8_resolutions = root / "data/timeseries_v8/ledgers/shadow_resolutions.jsonl"
    if v8_forecasts.is_file() and v8_resolutions.is_file():
        forecasts = {
            row["forecast_id"]: row
            for row in (
                json.loads(line)
                for line in v8_forecasts.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        }
        for row in (
            json.loads(line)
            for line in v8_resolutions.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ):
            forecast = forecasts.get(row["forecast_id"])
            if forecast is None:
                mismatches.append(f"v8 {row['resolution_id']}: forecast 행 없음")
                continue
            payload = forecast["horizons"][str(int(row["horizon"]))]
            actual = float(row["actual_log_return"])
            model_crps = crps_weighted_empirical(payload["quantile_grid"], None, actual)
            baseline_crps = crps_weighted_empirical(payload["baseline_quantile_grid"], None, actual)
            if abs(model_crps - float(row["model_crps"])) > 1e-12:
                mismatches.append(f"v8 {row['resolution_id']}: model_crps 재채점 불일치")
            if abs(baseline_crps - float(row["baseline_crps"])) > 1e-12:
                mismatches.append(f"v8 {row['resolution_id']}: baseline_crps 재채점 불일치")
            for model, value in (("v8_champion", model_crps), ("v8_best_baseline", baseline_crps)):
                rows.append({
                    "track": "v8_shadow", "origin": str(row["origin"]),
                    "model": model, "cell": f"h{int(row['horizon'])}",
                    "metric": "crps", "value": float(value),
                    "forecast_id": str(row["forecast_id"]),
                    "resolution_id": str(row["resolution_id"]),
                    "eligibility": True,
                })

    v13_resolutions = root / "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl"
    v13_dropped_duplicates = 0
    if v13_resolutions.is_file():
        # 외부 리뷰 F09 (2026-10-27): 원장은 무수정이되 읽기는 V13 계약의 dedupe_rule 을
        # 따른다 — (cell, origin) 당 1행 (핀 계수 sha 우선, 다음 knowledge_cutoff 최신).
        # 재동결 중복(2026-09-04)을 그대로 넣으면 그 원점 손실이 추론 패널에서 2배 가중된다.
        from ..timeseries_v13.resolve import distinct_resolutions, pinned_coefficients_sha

        raw_v13 = [
            json.loads(line)
            for line in v13_resolutions.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        deduped_v13 = distinct_resolutions(raw_v13, pinned_sha=pinned_coefficients_sha(root))
        v13_dropped_duplicates = len(raw_v13) - len(deduped_v13)
        for row in sorted(deduped_v13, key=lambda r: (str(r.get("origin")), str(r.get("cell")))):
            label = int(float(row["label"]))
            brier_model = brier_score(float(row["probability"]), label)
            brier_clim = brier_score(float(row["climatology_base_rate"]), label)
            if abs(round(brier_model, 8) - float(row["brier_model"])) > 1e-8:
                mismatches.append(f"v13 {row['resolution_id']}: brier_model 재채점 불일치")
            if abs(round(brier_clim, 8) - float(row["brier_climatology"])) > 1e-8:
                mismatches.append(f"v13 {row['resolution_id']}: brier_climatology 재채점 불일치")
            for model, value in (("persistence_pb", brier_model), ("climatology", brier_clim)):
                rows.append({
                    "track": "v13_vol_live", "origin": str(row["origin"]),
                    "model": model, "cell": str(row["cell"]),
                    "metric": "brier", "value": float(value),
                    "forecast_id": str(row["run_id"]),
                    "resolution_id": str(row["resolution_id"]),
                    "eligibility": True,
                })

    out = root / ORIGIN_LOSSES_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, out, compression="zstd")
    return {
        "rows": len(rows),
        "v13_dropped_duplicates": v13_dropped_duplicates,
        "mismatches": mismatches,
        "output": str(ORIGIN_LOSSES_RELATIVE).replace("\\", "/"),
        "ok": not mismatches,
    }
