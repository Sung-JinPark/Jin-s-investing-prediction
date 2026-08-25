# NASDAQ V5 봉인 Research Gate 결과

- 모델: `shadow.nasdaq_pit_hybrid_distribution_v5`
- run: `tsv5-research-92c262efafd01118e1dd82cc`
- 평가: 963개 주간 원점 × 1·5·21·63거래일, 4,000개 분포 표본, stationary bootstrap 2,000회
- 데이터: 82 receipts, 1,466,821 append-only observation revisions, 1,466,872 receipt links, 연결률 100%
- 보호 범위: V1~V4·Scenario·official ledger 추가/삭제/변경 0

## 판정

`HOLD`다. Research Gate 기준은 변경하지 않았으며 고객용 예상값과 경로는 숨긴다.

| 기간 | V5 CRPS | 고정 비교군 CRPS | 개선률 |
|---|---:|---:|---:|
| 1일 | 0.007190 | 0.007205 | +0.21% |
| 5일 | 0.015121 | 0.015114 | -0.04% |
| 21일 | 0.033261 | 0.030049 | -10.69% |
| 63일 | 0.055641 | 0.051818 | -7.38% |

21·63일 평균 개선률은 -9.03%이며 요구값은 +2% 이상이다. paired stationary-bootstrap 90% 손실차 CI는 `[0.001330, 0.006073]`으로 개선을 지지하지 않는다. 극단 움직임 Q4와 일부 위기 국면 coverage도 기준에 미달했다.

운영 Gate도 NASDAQ 입력이 마지막 완료 XNAS 세션보다 6세션 뒤처져 HOLD다. Research Gate와 운영 Gate를 모두 통과하기 전에는 `#timeseries`가 숫자를 표시하지 않는다.

## 구현 검증

- 전체 회귀: `617 passed`
- V5 계보: receipt 82건, observation 1,466,821건, receipt link 1,466,872건, 연결률 100%
- PIT: Pandas 2/3에서 발표시각을 나노초 단위로 통일하고 장 마감 직후 관측치의 같은 세션 역류 방지 테스트 PASS
- 보호 manifest: V1~V4·Scenario·official 추가/삭제/변경 0
- 정적 빌드: V5 HOLD artifact를 `timeseries` read model로 투영하며 `numbers_visible=false`, horizon/path 빈 객체 확인
- UI: 1280px·390px에서 가로 overflow 0
- Excel 감사본: 8 sheets, 수식 오류 0, SHA-256 `d3f5a2b0fd1a03dfc8811502af2fe936da1e6af89156c7fd08afb1147fde716f`

## 해석

공개 DB를 크게 늘린 것만으로 장기 분포 예측력이 자동 개선되지는 않았다. 특히 하락 원점과 2020·2022 구간에서 직접분포 expert가 고정 비교군보다 불안정했다. 이 결과를 보고 V5 후보·Gate·평가 구간을 다시 조정하지 않는다. 후속 모델은 새 버전 계약과 별도 봉인 평가가 필요하다.
