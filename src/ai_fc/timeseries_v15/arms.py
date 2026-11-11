"""V15 팔 정의(A0~A5)와 A5 발행 꼬리 구조 규칙 — kernel.

각 팔은 A0(V8 비트 동일 대조군) 대비 정확히 한 축만 바꾼다. 결합 팔은 없다
(계약 combination.allowed false). A6·A7·A2b 는 미등록(rejected_arms)이다.
모든 팔의 원점 시드는 V8 의 model_id·version 에서 유도한다(공통 난수 CRN — A0 identity 의 전제).
참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

VolMode = Literal["v8", "fresh", "lambda_mix"]
FrameMode = Literal["v8", "xnas_label", "vix_align", "v8_dollar_tail_asof"]
IssuanceMode = Literal["v8_snapshot", "next_open_asof"]


@dataclass(frozen=True)
class ArmSpec:
    arm_id: str                 # "A0".."A5"
    vol_mode: VolMode
    frame_mode: FrameMode
    issuance_mode: IssuanceMode

    def as_manifest(self) -> dict[str, str]:
        return {"vol_mode": self.vol_mode, "frame_mode": self.frame_mode,
                "issuance_mode": self.issuance_mode}


ARMS: dict[str, ArmSpec] = {
    "A0": ArmSpec("A0", "v8", "v8", "v8_snapshot"),
    "A1": ArmSpec("A1", "fresh", "v8", "v8_snapshot"),
    "A2": ArmSpec("A2", "lambda_mix", "v8", "v8_snapshot"),
    "A3": ArmSpec("A3", "v8", "xnas_label", "v8_snapshot"),
    "A4": ArmSpec("A4", "v8", "vix_align", "v8_snapshot"),
    "A5": ArmSpec("A5", "v8", "v8_dollar_tail_asof", "next_open_asof"),
}
WEEKLY_ARMS = ("A0", "A1", "A2", "A3", "A4")
ARM_INDEX = {arm: index for index, arm in enumerate(ARMS)}
VERDICT_HORIZONS = (5, 21, 63)
SUPERIORITY_FAMILY = tuple((arm, h) for arm in ("A1", "A2", "A3", "A4") for h in VERDICT_HORIZONS)  # m=12
NONINFERIORITY_FAMILY = tuple(("A5", h) for h in VERDICT_HORIZONS)                                # m=3
MIX_DECAYS = (0.94, 0.97)
MIX_WEIGHTS = (0.5, 0.5)  # V8 계약 model.distribution.ewma_lambda_candidates 그대로, 고정(학습 아님)
SEED_MODEL_ID = "shadow.mf_dfm_varx_calibrated_v8"
SEED_MODEL_VERSION = 8
DOLLAR_INDEX = 4  # CORE_ENDOGENOUS 순서의 dollar_change


def arm_spec(arm_id: str) -> ArmSpec:
    try:
        return ARMS[arm_id]
    except KeyError as exc:
        raise ValueError(f"등록되지 않은 V15 팔: {arm_id!r} (A6·A7·A2b 는 미등록)") from exc


def apply_issuance_tail(training_endog: np.ndarray, training_dates) -> np.ndarray:
    """원점(= training_dates[-1])의 ISO 주에 속한 행의 dollar_change 를 0 으로 둔다.

    근거: H.10(DTWEXBGS)은 주 1회 월 16:15 ET 에 직전 주(금까지)를 발표한다. 따라서 원점 다음
    세션 개장 전(월 09:30 ET)에는 원점 주 달러가 미발표다 → as-of 캐리 = 0 변화.
    날짜는 오름차순이라 원점 주의 행은 끝에 연속한다 — 뒤에서부터 같은 ISO 주인 행만 고른다
    (전 행을 훑는 것과 같은 집합). 라벨·실현값은 바꾸지 않는다 — 학습 입력만 바꾼다.
    """
    out = np.array(training_endog, dtype=float, copy=True)
    dates = list(training_dates)
    if not len(dates):
        return out
    if out.shape[0] != len(dates):
        raise ValueError("발행 꼬리: 학습 행 수와 날짜 수가 다르다")
    week = date.fromisoformat(str(dates[-1])).isocalendar()[:2]
    rows: list[int] = []
    for index in range(len(dates) - 1, -1, -1):
        if date.fromisoformat(str(dates[index])).isocalendar()[:2] != week:
            break
        rows.append(index)
    out[sorted(rows), DOLLAR_INDEX] = 0.0
    return out
