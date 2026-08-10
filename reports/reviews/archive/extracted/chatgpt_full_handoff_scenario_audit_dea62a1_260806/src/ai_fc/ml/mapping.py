"""질문 ↔ 시계열·임계값 매핑의 단일 진실.

registry.yaml의 question_id와 정확히 일치해야 divergence 트리거·프롬프트 주입·
frontmatter 기록이 배선된다 (기존 THRESHOLDS는 한글 라벨 키라 qid 조회 불가 — 대체).

mode 의미:
  above_path / below_path      — 판정기준이 '기간 중 1회라도 터치' (경로 질문)
  above_terminal / below_terminal — 판정기준이 '기간 말 종가' (종점 질문)
window: 배리어 검사 구간이 예측 지평 전체가 아닌 질문(F2의 8~10월)만 ISO 날짜쌍.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionMap:
    question_id: str            # registry.yaml id와 정확히 일치
    label: str                  # 렌더용 짧은 라벨
    series_key: str             # "q_ixic" | "q_soxx" | "q_vix"
    threshold: float
    mode: str                   # above_path | below_path | above_terminal | below_terminal
    window: tuple[str, str] | None = None   # (ISO 시작, ISO 끝) — 부분 배리어 윈도우


QUESTION_MAPS: tuple[QuestionMap, ...] = (
    # F1: "연말까지 종가 기준 ATH(27,093.90) 초과일이 1일 이상 존재" — 경로 질문
    QuestionMap("nasdaq-ath-eoy-2026", "F1 연말 ATH 경신 (^IXIC)",
                "q_ixic", 27093.90, "above_path"),
    # F2: "8/1~10/31 중 −10% 임계(24,384.51) 하향 터치" — 부분 윈도우 경로 질문
    QuestionMap("nasdaq-corr10-augoct-2026", "F2 −10% 터치 8~10월 (^IXIC)",
                "q_ixic", 24384.51, "below_path", window=("2026-08-01", "2026-10-31")),
    # F3: "연말 종가 > 7/9 종가(26,206.89)" — 종점 질문
    QuestionMap("nasdaq-eoy-above-jul9-2026", "F3 연말 > 7/9 종가 (^IXIC)",
                "q_ixic", 26206.89, "above_terminal"),
    # SOXX: "연말 종가 ≤ 468.94 (−15%)" — 종점 질문
    QuestionMap("soxx-eoy-down15", "SOXX 연말 −15% (≤468.94)",
                "q_soxx", 468.94, "below_terminal"),
    # VIX: "90일 내 종가 25 이상 1회" — 경로 질문 (q_vix 13주 지평과 정합)
    QuestionMap("vix-25-90d", "VIX 25 터치 (90일)",
                "q_vix", 25.00, "above_path"),
)
