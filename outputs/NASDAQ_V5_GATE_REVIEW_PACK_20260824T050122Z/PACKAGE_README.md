# NASDAQ V5 Gate Review Pack

## 결론

`shadow.nasdaq_pit_hybrid_distribution_v5` 구현과 데이터 백필, PIT 특징, 직접 horizon 분포모형, 봉인 워크포워드, 대시보드 HOLD 표시는 완료됐다.

최종 판정은 **Research Gate HOLD / Operational Gate HOLD**다. Gate 기준을 낮추지 않았으며 `numbers_visible=false`로 유지된다. 기존 V1~V4, Scenario V5.2, official forecast ledger는 변경하지 않았다.

## 핵심 실측

| 항목 | 결과 |
|---|---:|
| 평가 원점 | 963 weekly origins |
| horizon | 1 / 5 / 21 / 63 거래일 |
| 분포 표본 | origin당 4,000 |
| stationary bootstrap | 2,000 |
| source receipts | 82 |
| append-only observations | 1,466,821 |
| receipt-fact links | 1,466,872 |
| terminal outcome coverage | 100% |
| observation linkage | 100% |
| 전체 회귀 테스트 | 617 passed |

| 기간 | V5 CRPS | V3 fixed comparator | 개선률 |
|---|---:|---:|---:|
| 1일 | 0.007190 | 0.007205 | +0.21% |
| 5일 | 0.015121 | 0.015114 | -0.04% |
| 21일 | 0.033261 | 0.030049 | -10.69% |
| 63일 | 0.055641 | 0.051818 | -7.38% |

21·63일 평균 개선률은 -9.03%로 계약 기준 +2%에 미달한다. paired stationary-bootstrap 90% loss-difference CI는 `[0.001330, 0.006073]`이다. 최신 목표가격도 마지막 완료 XNAS 세션보다 6세션 뒤처져 운영 Gate가 HOLD다.

## 폴더 구성

- `SOURCE_SNAPSHOT/`: V5 구현 소스, 계약, migration, workflow, 공개 artifact와 Gate 결과
- `ARTIFACTS/workbook/`: 8시트 Excel 감사본, 시트별 PNG, formula scan
- `ARTIFACTS/screenshots/`: 1280px·390px `#timeseries` HOLD 화면
- `ARTIFACTS/site/`: 정적 빌드 `index.html`, `data.json`
- `EVIDENCE/FULL_TESTS.*`: 전체 테스트 원문과 JUnit XML
- `EVIDENCE/V5_VERIFY.json`: 계보·보호범위 검증 원문
- `EVIDENCE/TRACKED_CHANGES.patch`: 기준 커밋 대비 추적파일 패치
- `MANIFEST.sha256`: ZIP 내부 파일별 SHA-256
- `MANIFEST.json`: 파일 경로·크기·SHA-256 구조화 manifest

## 검토 순서

1. `SOURCE_SNAPSHOT/docs/timeseries_v5/GATE_RESULT_20260824.md`
2. `EVIDENCE/V5_VERIFY.json`
3. `ARTIFACTS/workbook/NASDAQ_TIMESERIES_V5_AUDIT.xlsx`
4. `SOURCE_SNAPSHOT/data/timeseries_v5/runs/tsv5-research-92c262efafd01118e1dd82cc.json`
5. `EVIDENCE/FULL_TESTS.junit.xml`
6. `ARTIFACTS/screenshots/`

## 재현 명령

```powershell
$env:PYTHONPATH='src'
python -m ai_fc timeseries-v5-verify
python -m pytest src/tests -q
python -m ai_fc dashboard --pages-out _site
```

수집 원문과 전체 Parquet는 라이선스·용량 정책에 따라 ZIP에 재배포하지 않는다. 대신 receipt 수, terminal outcome, observation linkage, Parquet content hash와 source별 checksum을 포함한다.

기준 커밋은 `3d2b82296ead623fd2be0152fdc59d92ec3ec3ee`다. 이 팩 생성 시점에는 commit·push·merge·라이브 배포를 수행하지 않았다.
