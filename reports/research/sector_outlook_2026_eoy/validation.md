# 2026년 연말 섹터 연구 검증 기록

분석 기준시각은 2026-10-12 09:16:14 KST다. 이 검증은 원문 계보, 계산과 원본 보존을 확인한다. 섹터 수익률 전망의 통계적 정확도나 확률 보정을 인증하지 않는다.

## 완료한 검증

| 검사 | 결과 | 범위 |
|---|---|---|
| 신규 산술 테스트 | 15개 통과 | 명시적 fraction 단위, 가중치 합계·범위, 누락, NaN, 복리 교차항, 미래 가용시각, 분할·환율 |
| 기존 안전 검증 테스트 | 36개 통과 | 확률 계약, bitemporal 사실, 평가, 논리 제약, 거래 세션, 원장 감사, 공식 통계 |
| 독립 계산·보고서 대조 | 오류 0 | Decimal 계산과 수익 범위·가중치·SPY 비교·분할·환율·보고서 숫자; qa_final.json |
| 공개 성과 산술 재현 | 6개 대조 일치 | 해소 행·독립 사건·Brier; 공개 read-model 재현이며 원장 입력 시점 인증은 아님 |
| issuer 전일 가격 대조 | 12개 일치 | issuer 10/8 가격과 10/9 가격 페이지의 previous_close; 신규 10/9 종가의 독립 인증은 아님 |
| 오프라인 계산 재생 | 산출물 8개 byte 일치 | 계산 JSON, 5개 CSV, 출처 manifest, validation을 replay 폴더에서 대조 |
| 원본 보존 | 242개 SHA-256 동일 | 감사에 등록한 기존 원장·예측·관측·모델·사이트·소스 파일 |
| 도표 육안 검증 | 완료 | 숫자·가정 범위·시나리오 표시, 한글·축·각주; 잘림과 겹침 없음 |
| 공통 비교 항목 행렬 | 12개 고유 행 | 미국 11섹터+SPY; 7개 항목·반증·신뢰도·공백·출처; 11개 전망 수정치 보존 원문 대조 |

36개 기존 검증은 다음 명령으로 실행했다. 플러그인 자동 로딩과 pytest 캐시 쓰기를 끄고 순수 계산·임시 경로·읽기 전용 검증만 선택했다.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -B -m pytest -p no:cacheprovider -q src/tests/test_probability_contract.py src/tests/test_bitemporal_facts.py src/tests/test_evaluation.py src/tests/test_logical_constraints.py src/tests/test_market_session.py src/tests/test_ledger_audit.py src/tests/test_authoritative_statistics.py
```

새 연구 폴더의 전체 산술 테스트와 재생은 다음 명령으로 실행했다.

```powershell
python -X utf8 -m unittest discover -s reports/research/sector_outlook_2026_eoy -p test_calculations.py -v
python -X utf8 reports/research/sector_outlook_2026_eoy/calculations.py --output-dir replay
```

레포 전체 기본 pytest에는 실제 dualdb 연결에서 스키마 실행·ALTER·UPDATE·commit을 하는 fixture와 환경에 따라 실제 PostgreSQL migration을 실행하는 통합 테스트가 있다. 원장 보존 조건 때문에 해당 전체 실행은 하지 않았다. 신규 계산 코드와 관련 검증을 모두 통과한 뒤, 그보다 넓은 검사를 안전성이 확인된 위 7개 파일로 확장했다.

## 결함과 제한 분류

- **이번 코드·산술 결함:** 최종 검사에서 발견한 오류가 없다. 데이터 단위나 가중치가 잘못되면 설명 가능한 오류로 중단하며 clipping·자동 normalization을 하지 않는다.
- **환경·의존성:** 번들 런타임의 matplotlib 부재는 기존 로컬 Python의 설치된 matplotlib으로 해결했다. 설치·삭제·업그레이드는 없었다. 차트 재생에는 기존 matplotlib과 한글 폰트가 필요하다.
- **자료·원문 공백:** 한국 최신 종목·ETF 종가/구성/배당, 정상화 컨센서스, 일부 valuation 산식과 CAPEX call, 과거 공개·수정 vintage를 충분히 확보하지 못했다. null·보류를 유지한다.
- **한국 가격 후보 대조:** LS의 10/8 참고값 195,500원과 다른 제공자의 일별 197,200원은 시장·세션 정의를 해소하지 못해 채택 보류했다. 재조회된 컷오프 후 장중 값은 제외했다. korea_price_crosscheck.json/md에 원문과 사유를 남겼으며 수익 계산 입력과 분리했다.
- **예측 검증 공백:** 가정 가중 수익률과 범위는 통계적 기대값·신뢰구간·승률이 아니다. 기존 모델 확률을 이전하지 않았고 공식 예측 append는 0건이다.

동적 출처의 `available_at=null`은 통과로 간주하지 않는다. 가격 페이지의 시장 종료 시각은 공개 전달 시각과 별도 필드로 유지한다. 미래 CPI 결과와 미래 실적은 입력하지 않았으며, 미리 공지된 일정과 SOXX 분할은 예정 메타데이터로만 다뤘다. 12개월 목표가를 남은 연말 기간으로 비례 환산하지 않는다.

계산·출처 검사 원본은 validation.json, 내부 원본 보존·공개 성과 재현은 internal_audit.json, 독립 대조는 qa_final.json 및 review_notes.md에 있다. 보고서의 조건부 판단과 이 검사들의 성공을 새로운 예측력 인증으로 혼동하지 않는다.
