# AI_INVESTING_STATISTICS_FUTURE_DATA_INTEGRITY_REVIEW_PACK_260813

이 ZIP은 통계 DB, 미래 전망 연구 후보, 다년 스트레스, 배포·갱신 체인을 외부 GPT가 원자료 수준으로 재검토하도록 만든 자체완결 증거 팩입니다.

## 결론

- 통계 live 수집 계열 22개 중 원문 SHA가 정확히 일치한 계열은 22개입니다. `gate_pass=true`.
- 통계 계산 계약과 KOSPI 재계산, IPO 영향력 집계, 다년 스트레스 재계산은 모두 기계적으로 대조했습니다.
- V5.2는 계산·원천 해시가 재현되지만 **공식 forecast/champion이 아닙니다**. S2 기원 표본 16/20, distinctness shadow 0/30, 일부 kernel gate 실패가 남습니다.
- 선택한 낙폭 사례 4개는 확률 모집단이 아닙니다. 합성 그래프도 발생확률·목표가격이 아닌 조건부 민감도입니다.
- 공식 보호범위는 `origin/main` 대비 무단 변경 0건입니다. V5.2 연구 후보 변경 0건은 별도 표시되며 official snapshot·ledger·archive 변경으로 세지 않습니다.

## 검토 순서

1. `00_EXECUTIVE_VERDICT.md`
2. `01_SOURCE_INTEGRITY_MATRIX.csv`
3. `02_REFRESH_CADENCE_AND_RUN_AUDIT.md`
4. `03_STATISTICS_FORMULA_AUDIT.md`
5. `04_SCENARIO_V52_ALGORITHM_AUDIT.md`
6. `05_MULTI_YEAR_STRESS_METHOD.md`
7. `06_KOSPI_SIGNAL_METHOD.md`
8. `07_LIMITATIONS_AND_OPEN_RISKS.md`
9. `08_GPT_REVIEW_CHECKLIST.md`
10. `evidence/` 원문·테스트·스크린샷
