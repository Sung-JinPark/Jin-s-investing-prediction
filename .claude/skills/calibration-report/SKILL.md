---
name: calibration-report
description: Generate a calibration report (Brier score, calibration curve, per-domain skill, phase-gate status) from the resolution ledger. Use when the user says /calibration-report, asks "지금까지 얼마나 맞혔어", or asks about Brier/gate progress.
---

# /calibration-report

> v2 (2026-07-20): `python -m ai_fc report`가 WS8/WS9 섹션을 포함한다 — Murphy 분해,
> 신뢰도 다이어그램(표본 5+ 유의), 대표 Brier의 제외표본 상시 병기, rolling Brier,
> 벤치마크 3자 비교(LLM vs ML vs 시장 — 쌍대 표본만), 섀도 extremized 가상 Brier,
> **드라이버 일관성 표**(같은 드라이버 질문들의 최신 확률 — 자동 판정 없음, 정합 판단은 사람).
> 수동 리포트 작성 시에도 이 섹션 구성을 따를 것. — 캘리브레이션 리포트 (L7)

## 절차

1. **집계**: `calibration/ledger.csv` 로드. 해소 0건이면 "표본 없음 — 현재 활성 질문 수와 예상 첫 해소일"만 보고하고 종료.
2. **지표 산출**:
   - 전체 Brier (평균), 해소 문항 수
   - 도메인별 Brier + 문항 수 — **문항 5개 미만 도메인은 "표본 부족" 표기** (조기 차단 판정 금지)
   - 캘리브레이션 커브: 확률 구간(0-20/20-40/40-60/60-80/80-100)별 예측 수 vs 실현율
   - 과신/과소신 진단 (커브 기울기)
3. **게이트 판정**:
   - P2 게이트: 해소 30+ AND Brier < 0.20
   - P3 게이트: 해소 50+ AND Brier < 0.18
   - 무능 도메인: 문항 5+ AND Brier > 0.22 → "시그널 차단 권고" 목록에 추가
4. **리포트 생성**: `reports/calibration_YYYY-MM-DD.html`로 저장 (다크 테마, 기존 설계서와 동일한 색 체계 — docs/design의 CSS 변수 재사용). 요약은 채팅으로도 보고.
5. **주의 주석**: rolling 질문의 겹치는 윈도우는 독립 표본이 아님을 리포트에 명시. 표본 30 미만이면 "통계적으로 미성숙" 배너 필수.

## 산식

- Brier = mean over resolved forecasts of (p/100 − outcome)²
- 참고선: 무지성 50% = 0.25, 톱 인간 슈퍼포캐스터 ≈ 0.12~0.15 (설계서 §11)
