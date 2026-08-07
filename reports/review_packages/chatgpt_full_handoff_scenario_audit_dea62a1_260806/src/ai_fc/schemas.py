"""추론 코어 구조화 출력 스키마 (Pydantic → structured outputs).

주의: structured outputs는 dict(additionalProperties)를 허용하지 않으므로
key-value는 명시적 아이템 리스트로 표현한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Adjustment(BaseModel):
    evidence: str = Field(description="증거 한 줄 (출처 포함)")
    direction: Literal["up", "down"]
    delta_pp: float = Field(description="anchor 대비 조정 폭 (%p, 양수)")


class SnapshotItem(BaseModel):
    name: str
    value: str = Field(description="확정 값. 확인 실패 시 'NOT FOUND'")


class DivergenceReview(BaseModel):
    """WS6: rN 확률 확정 **후** ML 참조와의 괴리(≥15%p) 정당화 — 사후 분류.

    확률은 이미 확정·불변 — 이 리뷰는 기록용 설명이지 수정 채널이 아니다.
    (앵커링 방지: ML 값은 확률 확정 전에는 LLM에 노출되지 않는다 — base_rates.py)
    """

    divergence_class: Literal[
        "event_conditionality",   # 무조건부 모델이 이벤트 구조(FOMC·실적 등)를 모름
        "regime_view",            # 체제 판단 차이 (딥바잉 레짐, 사이클 위상 등)
        "model_limit",            # 참조 모델의 알려진 한계 (이산화·정규가정 등)
        "other",
    ]
    note: str = Field(description="정당화 한 문단 — 왜 LLM 확률이 ML 참조와 갈라지는가")


class ForecastResult(BaseModel):
    """reasoning_core [0]~[5] 절차의 구조화 출력."""

    question_check: str = Field(description="[0] 질문 검증 — 해소가능성 확인 요지")
    reference_class: str = Field(description="[1] 참조 클래스 정의")
    base_rates: list[str] = Field(description="[1] base rate 3개+ (출처 포함)")
    anchor_pct: int = Field(description="[1] outside view anchor (%)")
    adjustments: list[Adjustment] = Field(description="[2] inside view 보정 항목들")
    decomposition: str = Field(description="[3] 분해 트리 (텍스트)")
    premortem: list[str] = Field(description="[4] 틀릴 이유 3가지")
    probability: int = Field(description="[5] 최종 확률, 1~99 정수")
    ci80_lo: int
    ci80_hi: int
    key_reasons: list[str] = Field(description="핵심 근거 3줄")
    observables: list[str] = Field(description="확률을 바꿀 관찰 지표 2개")
    snapshots_filled: list[SnapshotItem] = Field(
        description="required_snapshots 각각의 확정 값")
    unverified_notes: list[str] = Field(description="[미검증] 표기 대상 목록")
