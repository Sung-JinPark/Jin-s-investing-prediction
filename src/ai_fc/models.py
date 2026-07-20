"""도메인 객체. 파일이 진실이므로 여기의 필드는 파일 포맷을 따른다."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

FORECAST_STEM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(?P<qid>.+)_r(?P<round>\d+)$")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Question:
    question_id: str
    title: str
    question: str
    deadline_kind: str  # fixed | rolling | tbd
    deadline: Optional[date]  # fixed일 때만
    rolling_days: Optional[int]  # rolling일 때만
    resolution: str
    resolution_source: str
    domain: str
    cadence_raw: str
    schedule: list[dict[str, Any]]  # 정규화 스케줄 (빈 리스트 = manual)
    action_link: str
    status: str
    created: Optional[date]
    notes: str
    required_snapshots: list[str]
    src_hash: str  # 질문 블록의 해시 (판정기준 변경 감지용)
    # 공유 불확실성 드라이버 태그 (FutureSearch world-model의 최소 구현 — ARCHITECTURE §2-⑥).
    # src_hash 미포함(판정기준 아님) — 자유 편집 가능. 드라이버별 일관성 점검의 기반.
    drivers: list[str] = field(default_factory=list)
    # v3 WS-B 파이프라인 티어: standard | lite. lite = 검색량·분량만 경량 (2에이전트+
    # 데블스 강제는 불변 — 헌법). src_hash 미포함 — 자유 편집 가능.
    tier: str = "standard"

    @property
    def is_manual(self) -> bool:
        return not self.schedule


@dataclass
class ForecastRecord:
    forecast_id: str  # 파일명 stem
    question_id: str
    round: int
    forecast_ts: Optional[datetime]
    probability: int
    ci80_lo: Optional[int]
    ci80_hi: Optional[int]
    window_end: Optional[date]
    snapshots: dict[str, Any]
    market_implied: Optional[float]
    edge: Optional[float]
    model: str
    prompt_version: str
    phase: str
    method: str
    sources_count: Optional[int]
    path: Path
    file_sha256: str
    extra: dict[str, Any] = field(default_factory=dict)  # 알 수 없는 키 보존(관대한 리더)
    # AUDIT-260715 T-3: ok|degraded|failed — 신규 예측부터 기록, 구파일 None은 ok 취급.
    # v2 WS7 세분: ok_low_primary (1차 출처 비율 < 0.3 — 표시·분석용, 대표 뷰 무변경)
    research_status: Optional[str] = None
    # v2 신규 (구파일 None 허용 — 관대한 리더):
    shadow_extremized: Optional[int] = None       # WS8: 섀도 가상 Brier용 DB 적재 (D7)
    ml_divergence_pp: Optional[float] = None      # WS6: 기록 시점 |rN − ML앙상블| (%p)
    divergence_class: Optional[str] = None        # WS6: 괴리 ≥15%p 시 분류 (enum 4종)
    pipeline_tier: Optional[str] = None           # v3 WS-B: standard|lite (구파일 None)

    @classmethod
    def parse_stem(cls, stem: str) -> Optional[tuple[str, int]]:
        """파일명 stem → (question_id, round). 예측 파일이 아니면 None."""
        m = FORECAST_STEM_RE.match(stem)
        if not m:
            return None
        return m.group("qid"), int(m.group("round"))


@dataclass
class LedgerRow:
    line_no: int  # 1-based, 헤더 제외
    resolved_date: str
    question_id: str
    forecast_id: str
    forecast_date: str
    probability: int
    outcome: int
    brier: float
    domain: str
    notes: str
    line_hash: str


@dataclass
class EvidenceBrief:
    profile: str  # fundamental | macro | flow | devil
    text: str
    sources_count: int
    cost_usd: float
    input_tokens: int
    output_tokens: int


@dataclass
class DueItem:
    question_id: str
    kind: str  # forecast | resolve | manual-review | stale | divergence(표시만 — 자동 실행 없음)
    reason: str
    last_forecast_ts: Optional[datetime] = None
