# NASDAQ 다변량 시계열 V3 연구 감사 팩

## 판정

`shadow.nasdaq_direct_regime_distribution_v3`의 구현과 2007년 이후 963개 주간 원점 연구평가를 완료했다. V2는 바이트·계약·모델 해시 기준으로 불변이다.

최종 판정은 **RESEARCH HOLD**다. 63일 CRPS는 기준선보다 2.02% 개선됐고 paired 90% 신뢰구간도 0 아래였지만, 21·63일 평균 개선은 1.39%로 사전등록 기준 2%에 미달했다. 극단 변동 Q4와 일부 위기 구간의 p10–p90 coverage도 기준을 통과하지 못했다.

따라서 고객 숫자, `#timeseries`, 공식 전망, Scenario V5.2, champion, 자동 투자에는 연결하지 않았다. Gate를 낮추지 않았고 main merge·Pages 배포도 수행하지 않았다.

## 중요한 해석

- 2007–2026 평가는 설계 과정에서 사용한 `research_pseudo_oos`이며 진정한 sealed OOS가 아니다.
- 최종 후보는 이 상태에서 동결한다.
- 최초의 진정한 sealed 평가는 동결 이후의 126거래일 forward shadow다.
- 연구 Gate가 실패했으므로 forward shadow Stage A와 고객 공개는 시작하지 않는다.

## 구성

- `EXECUTION_AND_GATE_REPORT_260821.md`: 실행값·Gate·차단 조치.
- `IMPLEMENTATION_CROSSWALK_260821.md`: 감사 명세와 구현 파일의 1:1 매핑.
- `MODEL_RISK_AND_LIMITATIONS_260821.md`: 남은 모델 리스크와 다음 버전 조건.
- `HISTORICAL_RESEARCH_LOG_260821.md`: 설계 진단과 최종 4,000-path 판정의 구분.
- `V3_GATE_RESULTS_260821.json`: 기계 판독 가능한 최종 Gate 결과.
- `V2_PROTECTED_HASHES_260821.json`: 봉인 V2 기준선과 불변 증거.
- `TEST_EVIDENCE_260821.md`: 테스트·Excel·재현 검증.
- `workbook_previews/`: Excel 8개 시트 렌더 증거.
- `BUILD_MANIFEST.ps1`, `MANIFEST.sha256`, `MANIFEST.json`: 파일별 SHA-256 manifest.

## 정본 산출물

- 계약: `data/contracts/multivariate_timeseries_v3.yaml`
- 최종 연구 run: `data/timeseries_v3/runs/tsv3-research-1f80a06bf6e991d887a5be40.json`
- 최신 연구 pointer: `data/timeseries_v3/runs/backtest_latest.json`
- 숨김 forecast ledger: `data/timeseries_v3/ledgers/forecasts.jsonl`
- fail-closed latest: `data/timeseries_v3/multivariate_v3_latest.json`
- 8-sheet 감사 Excel: `data/timeseries_v3/workbooks/multivariate_timeseries_v3_latest.xlsx`
