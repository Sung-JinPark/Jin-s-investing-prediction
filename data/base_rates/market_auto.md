# 시장내재확률 — 자동 수집 (참조 전용, 재생성 가능)

> `python -m ai_fc market` — Kalshi·Polymarket·CBOE 옵션(무료·무인증). 생성: 2026-07-19
> **기록·표시 전용** — edge 시그널 발행은 P3 게이트(해소 50+, Brier<0.18) 통과 후.

| 질문 | 시장내재확률 | 소스 | 구성 정의 |
|---|---|---|---|
| fomc-2026-07-29-hike | **5%** | polymarket | P(해당 회의에서 ≥25bp 인상) |
| fomc-2026-10-28-hike | **19%** | polymarket | P(해당 회의에서 ≥25bp 인상) |
| nasdaq-eoy-above-jul9-2026 | **44%** | options_bl | P(만기 종가 임계 상회/하회) — risk-neutral |
| nasdaq-ath-eoy-2026 | **36%** | options_bl (경로 질문의 종점 하한) | P(만기 종가 임계 상회/하회) — risk-neutral |

- 수집 실패(생략): 없음
- **구성 정의 (D-4)**: FOMC 행은 Polymarket 이벤트의 인상 버킷 합산 = P(해당 회의 ≥25bp 인상).
  버킷 = [increase-25bps, increase-50bps] (상호배타 가정, >50bp 버킷 미상장 시 미포함).
  base_rates/macro.md의 "첫 인상 타이밍 분포"(P(첫 인상=해당 월))와는 **다른 구성물** —
  같은 표·같은 라벨로 비교 금지.
- 옵션 내재확률은 risk-neutral 측도(변동성 프리미엄 포함) + ^IXIC↔QQQ 비율 프록시 가정
  — 실제 확률과 체계적 차이. 예측시장 가격은 유동성 얕으면 노이즈.
- 이력 원본: data/ml_history/*.jsonl → DB market_implied 테이블.
