"""질문 ↔ 시계열·임계값 매핑의 단일 진실.

registry.yaml의 question_id와 정확히 일치해야 divergence 트리거·프롬프트 주입·
frontmatter 기록이 배선된다 (기존 THRESHOLDS는 한글 라벨 키라 qid 조회 불가 — 대체).

mode 의미:
  above_path / below_path      — 판정기준이 '기간 중 1회라도 터치' (경로 질문)
  above_terminal / below_terminal — 판정기준이 '기간 말 종가' (종점 질문)
window: 배리어 검사 구간이 예측 지평 전체가 아닌 질문(F2의 8~10월)만 ISO 날짜쌍.
deadline: 질문 기한(ISO). 러너가 시리즈 지평을 '매핑 질문 중 가장 먼 기한'까지 잡고,
  종점 질문의 평가 스텝·경로 질문의 검사 구간 끝을 이 날짜로 맞춘다 (C3 — 이전에는
  지평이 연말 고정이라 연말 너머 기한의 질문은 표현할 수 없었다). None = 러너 기본
  지평(rolling 질문 등).

구조상 표현 불가 — 추가하지 않는다 ([미구현] 새 mode 필요):
  spx-drawdown-7pct-by-2026-11-30 · nasdaq-drawdown-15pct-by-2027-03-31 (롤링 고점 대비
  드로다운 — 경로 의존 기준가), vix-above20-40days-by-2027-01-15 (초과 거래일 횟수),
  vix-weekly-spike-50pct-by-2026-12-18 (주간 변화율), t10y2y-100bp-by-2027-01-15 ·
  hy-oas-500bp-2026q4-2027q1 (시리즈 없음 — DGS10−DGS2 스프레드·HY OAS).
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
    deadline: str | None = None             # ISO 기한 — 지평·종점 스텝 정렬 (C3)

    @property
    def end_date(self) -> str | None:
        """지평이 닿아야 하는 마지막 날짜 (window 끝 > deadline > None)."""
        if self.window is not None:
            return self.window[1]
        return self.deadline


QUESTION_MAPS: tuple[QuestionMap, ...] = (
    # F1: "연말까지 종가 기준 ATH(27,093.90) 초과일이 1일 이상 존재" — 경로 질문
    QuestionMap("nasdaq-ath-eoy-2026", "F1 연말 ATH 경신 (^IXIC)",
                "q_ixic", 27093.90, "above_path", deadline="2026-12-31"),
    # F2: "8/1~10/31 중 −10% 임계(24,384.51) 하향 터치" — 부분 윈도우 경로 질문
    QuestionMap("nasdaq-corr10-augoct-2026", "F2 −10% 터치 8~10월 (^IXIC)",
                "q_ixic", 24384.51, "below_path", window=("2026-08-01", "2026-10-31"),
                deadline="2026-10-31"),
    # F3: "연말 종가 > 7/9 종가(26,206.89)" — 종점 질문
    QuestionMap("nasdaq-eoy-above-jul9-2026", "F3 연말 > 7/9 종가 (^IXIC)",
                "q_ixic", 26206.89, "above_terminal", deadline="2026-12-31"),
    # SOXX: "연말 종가 ≤ 468.94 (−15%)" — 종점 질문
    QuestionMap("soxx-eoy-down15", "SOXX 연말 −15% (≤468.94)",
                "q_soxx", 468.94, "below_terminal", deadline="2026-12-31"),
    # VIX: "90일 내 종가 25 이상 1회" — 경로 질문 (q_vix 13주 지평과 정합, rolling → deadline 없음)
    QuestionMap("vix-25-90d", "VIX 25 터치 (90일)",
                "q_vix", 25.00, "above_path"),
    # ── C3 (2026-10-21) 추가 — 레지스트리 원문 임계·기한 ──
    # vix-30-touch-by-2026-11-30: "2026-09-10~2026-11-30 중 어느 거래일이든 VIX 종가 >= 30.0"
    QuestionMap("vix-30-touch-by-2026-11-30", "VIX ≥30 터치 ~2026-11-30 (^VIX)",
                "q_vix", 30.00, "above_path", window=("2026-09-10", "2026-11-30"),
                deadline="2026-11-30"),
    # vix-13-touch-by-2026-12-18: "2026-09-10~2026-12-18 중 어느 거래일이든 VIX 종가 <= 13.0"
    QuestionMap("vix-13-touch-by-2026-12-18", "VIX ≤13 하회 ~2026-12-18 (^VIX)",
                "q_vix", 13.00, "below_path", window=("2026-09-10", "2026-12-18"),
                deadline="2026-12-18"),
    # vix-40-touch-by-2027-01-15: "2026-09-11 이후 2027-01-15 까지 어느 거래일이든 VIX 종가 >= 40.00"
    QuestionMap("vix-40-touch-by-2027-01-15", "VIX ≥40 터치 ~2027-01-15 (^VIX)",
                "q_vix", 40.00, "above_path", window=("2026-09-11", "2027-01-15"),
                deadline="2027-01-15"),
    # nasdaq-comp-30000-close-2027-01-15: "FRED NASDAQCOM 의 2027-01-15 값 >= 30,000.00" — 종점
    QuestionMap("nasdaq-comp-30000-close-2027-01-15", "^IXIC 2027-01-15 종가 ≥30,000",
                "q_ixic", 30000.00, "above_terminal", deadline="2027-01-15"),
)
