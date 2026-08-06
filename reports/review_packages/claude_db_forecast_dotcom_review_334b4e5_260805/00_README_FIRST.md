# Claude 정밀 검토 패키지 — DB 구조경로 + 닷컴 5개년 교차자산 비교

작성일: 2026-08-05 KST

## 1. 검토 대상

- 저장소: `Sung-JinPark/Jin-s-investing-prediction`
- 기준 커밋: `6a0ce0d` (`feat(future): restore analog and add five-year shock map`)
- 기능 커밋: `311b2ad` (`feat(market): add DB-shaped forecasts and dotcom asset map`)
- 생성물 후속 커밋: `334b4e5` (`chore(generated): refresh inventory and read-model schema`)
- 최종 HEAD: `334b4e54bbe11ced37404415f5e9326996376cb5`
- 검토 범위: `6a0ce0d..334b4e5`

이 ZIP은 위 두 커밋만 검토하도록 설계했다. 작업 폴더에 별도로 존재하던 이전 검토 ZIP,
임시 아키텍처 HTML, L0 임시 보고서는 포함하지 않았다.

## 2. Claude에게 요청하는 검토 방식

보고서의 결론을 신뢰하지 말고 `patches/`, `files/`, snapshot JSON, 계약 YAML, 테스트를
서로 대조해 독립적으로 판정하라. 특히 다음 두 기능을 별도 확률공간으로 취급한다.

1. **NASDAQ DB 조건부 구조 경로**
   - 기존 GBM 분포와 S1/S2/S3 비중은 유지한다.
   - 혁신사이클·다중시대 조정 DB에서 월별 굴곡만 추출한다.
   - `scenario_conditional`이며 등록 질문의 `physical_event` 확률과 결합하지 않는다.
2. **2001-03 닷컴 5개년 교차자산 비교**
   - NASDAQ/O는 2001-03~2006-03 실측이다.
   - Bitcoin은 당시 데이터가 없어 현대 beta를 적용한 반사실 민감도다.
   - `reference_only`이며 사건확률·목표가격·기대수익이 아니다.

## 3. 우선 읽기 순서

1. `00_README_FIRST.md`
2. `review/01_IMPLEMENTATION_AND_LINEAGE.md`
3. `review/02_MODEL_MATH_AND_SEMANTICS.md`
4. `review/03_ACCEPTANCE_GATES.md`
5. `review/04_VALIDATION_EVIDENCE.md`
6. `review/05_REVIEW_RESPONSE_TEMPLATE.md`
7. `patches/*.patch`
8. `files/data/contracts/*.yaml`
9. `files/src/ai_fc/scenario_structure.py`, `scenario.py`, `cross_asset.py`
10. snapshot JSON과 UI·테스트

## 4. 반드시 답할 핵심 질문

### A. NASDAQ 구조 경로

- 선택한 역사 시대와 현재 AI 위상 정렬에 hindsight leakage가 과도하게 들어갔는가?
- 연도별 기하 추세 제거가 시작·종점은 보존하면서 중간 굴곡만 전달하는가?
- 2026 S1 최대낙폭을 역사 DB 중앙값에 맞춘 강도를 S2/S3·2027에 공통 적용하는 것이
  정합적인가, 아니면 시나리오별 진폭 캘리브레이션이 필요한가?
- 굵은 구조선과 기존 GBM fan이 서로 다른 생성 규칙을 쓰는 사실이 UI에서 충분히
  분리되는가?
- 특정 하락일을 예측한 것처럼 읽힐 문자열이나 시각 요소가 남았는가?

### B. 닷컴 교차자산

- 2001-03을 닷컴 정점이 아닌 “붕괴 진행 기준점”으로 표현하고 있는가?
- NASDAQ/O 실측선이 네 BTC 사례에서 완전히 동일한가?
- 2009년 이전 BTC 데이터가 실측처럼 오인될 수 있는 필드·문구·선 스타일이 있는가?
- 일간 downside/full beta를 월간 NASDAQ 수익에 적용하는 frequency transfer가 과도한가?
- p10/p90 beta 조합을 sensitivity envelope로만 표현하며 확률 band로 오인시키지 않는가?
- Yahoo adjusted close를 O 총수익 proxy라고 부르는 수준이 적절한가?

### C. 계약·불변성·배포

- schema 2/3 legacy archive를 읽으면서 schema 4를 `reference_only`로 강제하는 분기가 안전한가?
- `CORR-260805-014`와 `CORR-260805-015`가 원본 archive를 덮어쓰지 않고 새 revision을
  만들었는가?
- 생성 inventory·schema가 코드와 동기화되어 있는가?
- 정적 사이트에서 구형 완화 시나리오 문구나 금지 문자열이 노출되지 않는가?

## 5. 판정 등급

각 항목을 다음 중 하나로 판정하라.

- `PASS`: 코드·데이터·테스트에서 직접 확인
- `PARTIAL`: 구현은 있으나 의미론·근거·테스트가 불충분
- `FAIL`: 계약 위반 또는 결과를 바꿀 결함
- `BLOCKED`: 패키지 증거만으로 확인 불가

심각도는 `P0` 데이터/확률공간 오염, `P1` 모델 결과 오류, `P2` UI 오인·회귀,
`P3` 문서·운영 개선으로 구분한다. 근거 없는 개선 아이디어와 실제 결함을 분리하라.

