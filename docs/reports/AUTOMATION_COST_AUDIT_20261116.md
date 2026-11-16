# 자동화 비용 전수조사 — 2026-11-16

## 결론

- 직접 확인된 반복 API 과금은 Anthropic 공식 예측과 `investing-refresh`의 OpenAI 키 smoke였다.
- 공식 예측은 주 1건, 전역·Anthropic 월 상한 $15, 회차당 $4로 조정했다. 새 회차는 월 누적이
  $11 이하일 때만 시작한다. 실패 비용과 수동 실행도 같은 append-only 원장 합계에 포함한다.
- 2026년 11월 Anthropic 전체 원장은 $41.94로 이미 상한을 넘었으므로 11월에는 새 유료 회차를
  시작하지 않고 12월부터 재개한다. 과거 비용 행은 수정하지 않았다.
- 예약 GitHub 갱신의 OpenAI 키 smoke, 키 주입, 결과 검사는 제거했다. 수동 진단 명령은 남겼다.
- 원격 DB·S3와 GitHub artifact/cache 초과 저장공간은 저장소만으로 실제 청구액을 확정할 수 없다.

## 자동화별 판정과 조치

| 분류 | 자동화 | 확인 결과 | 조치 |
|---|---|---|---|
| 직접 과금 | Claude `weekly-forecast-3-2` | 11월 4·7일 자동 배치 약 $20.59, 11월 Anthropic 전체 $41.94 | `--max 1`, 월 $15, 회차 $4와 전체 회차 여유 가드 |
| 직접 과금·불필요 | GitHub `investing-refresh` OpenAI smoke | 회당 $0.000114, 11월 3회 $0.000342 | 예약 호출·비밀값 주입·결과 검사 제거 |
| 구독 한도 | Claude `weekly-model-refresh`, `weekly-ml-reference-2` | 로컬 모델·공개 자료 중심, 별도 API 과금 근거 없음 | 유지 |
| 구독 한도 | Codex `fred` heartbeat | FRED·공개 GitHub Actions 점검, 직접 API 과금 없음 | 6시간 주기 유지 |
| 구독 한도 | Codex `bnp-ai` | `LOCAL_DATA_ONLY`, 최근 `provider_calls=0` | 2026-11-30 13:30 KST를 마지막 실행으로 설정 |
| 만료 정리 | Codex `bnp-10-17` | 종료일 2026-10-20, 미래 실행 없음, 상태만 ACTIVE였음 | PAUSED |
| 로컬 예약 | `JinsInvesting-PrivateTrendlines` | 공개 자료·로컬 계산, 유료 API 근거 없음 | 유지 |
| 청구 콘솔 필요 | V5 원격 DB·S3 | 비밀값·청구 계정 없이 금액 확정 불가 | 중단하지 않고 콘솔 확인 대상으로 유지 |
| 청구 콘솔 필요 | GitHub artifact/cache 저장공간 | 공개 저장소 표준 러너 실행 시간과 별개로 초과 저장공간 가능 | 콘솔 확인 대상으로 유지 |

## GitHub 예약 워크플로 27개

모두 공개 저장소의 표준 `ubuntu-latest` 러너를 사용한다. 공개 저장소의 표준 호스티드 러너 실행
시간은 이번 감사에서 직접 과금으로 분류하지 않았다. artifact/cache 저장공간 초과분은 별도다.
[GitHub Actions 과금 기준](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

1. `ai-regime-refresh`
2. `c5-resolve-draft`
3. `daily6m-sources-refresh`
4. `daily6m-v2-shadow`
5. `earnings-refresh`
6. `investing-refresh`
7. `ipo-edgar-watch`
8. `market-mood-refresh`
9. `mts-coherence-monitor`
10. `ops-backlog-alert`
11. `overheat-watchdog`
12. `pages`
13. `research-pack`
14. `scenario-refresh`
15. `source-monitoring`
16. `statistics-refresh`
17. `timeseries-daily6m`
18. `timeseries-inputs-refresh`
19. `timeseries-refresh`
20. `timeseries-v13-vol-live`
21. `timeseries-v2-refresh`
22. `timeseries-v5-refresh`
23. `timeseries-v8-daily`
24. `timeseries-v8-shadow`
25. `trendlines-refresh`
26. `v15-coherence-shadow`
27. `v15-vol-shadow`

## 유료 LLM과 분리한 공개 자료 경로

FRED·BLS·BEA·EIA·SEC, 키 없는 Nasdaq·Yahoo·CBOE·Treasury·Kalshi·Polymarket 조회는
유료 LLM 호출과 분리한다. 비용 절감을 이유로 공개 API 자료 갱신을 끄지 않는다.

## 검증 기준

- 월 누적 $11.00에서는 $4 회차를 시작할 수 있고 $11.01에서는 시작하지 못한다.
- `stage=failed` 비용 행도 월 합계와 다음 회차 가드에 포함한다.
- 예약 예측은 `--max 1`이고 `investing-refresh`에는 OpenAI 비밀값과 smoke가 없다.
- FRED는 `FREQ=HOURLY;INTERVAL=6`을 유지했다.
- BNP 일일 검수는 2026-11-30 13:30 KST까지, 만료 캠페인은 PAUSED다.

이 감사는 투자 모델·확률·구조 경로를 변경하지 않는다.
