# ChatGPT 독립 검토 실행 프롬프트 — NASDAQ 구조경로·혁신사이클·2027 현실성

검토 기준 커밋: `dea62a1bd5c527ff16fb240377a6defd8f612934`

검토 스냅샷: `nasdaq-scenario:2026-08-03:r8`

검토 종류: 코드·데이터·수식·UI 독립 감사

주의: 투자 자문이나 사용자 방향성에 맞춘 튜닝이 아니다.

---

## 1. 역할

당신은 정량 리서처, 시계열 모델 검증자, 데이터 lineage 감사자, 금융 UI 의미론 검토자의 역할을 동시에 수행한다.

구현 보고서나 기존 판정을 사실로 전제하지 않는다. 패키지 안의 코드·JSON·계약·테스트를 직접 대조하고, 재현되지 않는 주장은 `BLOCKED`로 표시한다.

사용자는 상승·하락 중 어느 결론을 요구하는 것이 아니다. 사용자가 원하는 것은 다음이다.

- 왜 그래프가 그 모양인지 설명 가능할 것
- 시나리오가 다르면 근거에 따라 경로도 달라질 것
- 과거 닷컴과 혁신사이클 DB 사용 계보가 정확할 것
- 2027 경로가 단순한 직선이나 공통 파형이 아니라 조건부 분포를 정직하게 표현할 것
- 보기 좋게 수동 조작하지 않고 재현 가능한 방법일 것

---

## 2. 절대 규칙

1. 확률 `83/2/15`를 사용자 견해에 맞춰 재배정하지 않는다.
2. `scenario_conditional`, `physical_event`, `reference_only`를 결합하지 않는다.
3. 과거 결과를 보고 선택한 시대·기간·파라미터에는 hindsight 표시와 민감도 검증이 필요하다.
4. 굵은 선을 수동으로 그리거나 임의 이벤트 날짜에 맞춰 꺾지 않는다.
5. 같은 asof의 archive를 덮어쓰지 않는다.
6. 점예측보다 scenario 내부 분포와 경로군을 우선한다.
7. 검증되지 않은 개선안을 “완료”로 표시하지 않는다.
8. 코드와 데이터가 충돌하면 코드가 아니라 실제 직렬화 결과까지 함께 판정한다.
9. 사용자의 “참조선은 더 올라야 한다”는 가설은 검증 대상이지 목표가 아니다.
10. 투자 자문·목표가·사건확률로 오독될 문구를 만들지 않는다.

---

## 3. 필수 읽기 순서

1. `00_README_FIRST.md`
2. `handoff/chatgpt_ai_investing_full_handoff_260806.md`
3. `review/chatgpt_structural_path_evidence_260806.md`
4. `review/chatgpt_structural_path_acceptance_gates_260806.md`
5. `data/scenarios/nasdaq_latest.json`
6. `data/scenarios/archive/2026-08-03_CORR-260806-018.json`
7. `data/scenarios/archive/2026-08-03_CORR-260806-019.json`
8. `src/ai_fc/scenario.py`
9. `src/ai_fc/scenario_structure.py`
10. `data/contracts/scenario_structural_forecast.yaml`
11. `data/ml_history/2026.jsonl`
12. `dualdb/config.yaml`
13. `dualdb/dualdb/models/knn_analog.py`
14. `dualdb/dualdb/export/context_bridge.py`
15. `src/ai_fc/dashboard_parts/dashboard.js`
16. 관련 테스트와 correction 원장

---

## 4. 검증 질문 A — 2026-08-03부터 11월 전까지 왜 하락하는가

다음 가설을 각각 재현·반증하라.

### A-1. 위상 가설

`current_phase=42`에서 biotech2015·dotcom·japan1989의 고정 overlay 미래 구간을 읽기 때문에 8~10월 약세 파형이 생성되는가?

필수 계산:

- `phase(t)=42+(t-asof)/30.4375`
- 각 시대의 `overlay[phase]/overlay[42]`
- 세 값의 중앙값
- 연도별 기하 detrend residual
- `residual^1.735781`
- S1/S2/S3 최종 값

8/3, 8/31, 9/29, 10/27, 11/24, 12/31을 최소 표본으로 재현하라.

### A-2. 실제 k-NN 이웃 연결 가설

k-NN이 찾은 실제 이웃 날짜 이후의 forward path가 구조경로에 들어가는가, 아니면 era label만 쓰고 고정 M+42 좌표를 읽는가?

다음을 분리하라.

- neighbor selection coordinate
- overlay coordinate
- dotcom `model_anchor`
- dotcom `overlay_start`
- AI `overlay_start`

두 좌표계가 다르면 10월 하락의 timing이 어떤 경제적 의미를 갖는지 판정하라.

### A-3. 진폭 보정 가설

원형 낙폭과 화면 낙폭을 분리하라.

- raw ensemble MDD
- detrended residual MDD
- native endpoint-preserving S1 MDD
- calibrated S1 MDD
- strength가 없을 때와 있을 때 trough 차이

“역사가 10월 -12.2%를 예측했다”와 “역사 파형을 -12.19% base rate에 맞춰 증폭했다” 중 어느 설명이 정확한지 판정하라.

### A 출력

| 단계 | 입력 | 변환 | 출력 | 경제적 의미 | 검증 판정 |
|---|---|---|---|---|---|

정확한 코드 위치와 JSON 필드를 함께 적는다.

---

## 5. 검증 질문 B — 왜 S1/S2/S3가 같은 형태인가

다음을 코드로 확인하라.

1. `_structural_paths()`가 source 경로의 중간점을 쓰는가, 연도 시작·끝만 쓰는가?
2. 세 시나리오가 같은 raw/residual/strength를 공유하는가?
3. `scenario_specific_alternatives`는 화면에 실제 적용되는가, disclosure-only인가?
4. 정규화한 세 경로의 1주 변화율 또는 residual correlation이 사실상 1인가?
5. 세 시나리오 정의가 ATH hit·EOY reference 조건인데, 그 조건이 역사 경로 선택과 연결되는가?

필수 정량 출력:

- 각 시나리오의 연도별 시작·끝점
- 각 시나리오 구조경로 / 기하 baseline 비율
- 세 비율 간 최대 절대차
- 주간 수익률 상관행렬
- 위험창 중심월·trough 날짜의 동일 여부

판정 기준:

- 단순한 진폭 차이만 있으면 “scenario-specific dynamics”가 아니다.
- 시나리오 차이는 사전등록된 조건·표본·상태전이 중 하나와 연결돼야 한다.
- 차이를 만들기 위해 임의 noise를 추가하는 것은 실패다.

---

## 6. 검증 질문 C — 혁신사이클 참조선은 무엇인가

`scenario.py::_ANALOG_VALUES`부터 UI의 `data-reference-path='innovation-cycle'`까지 lineage를 추적하라.

필수 확인:

1. 값이 소스 DB에서 매번 다시 생성되는가?
2. 최신 selected eras를 사용하는가?
3. dotcom 실측 어느 구간과 대응하는가?
4. 26개 값을 52개 주차로 보간하는 것이 기간 의미를 바꾸는가?
5. `clip=anchor*1.25`가 상승을 얼마나 잘라내는가?
6. 현재 라벨 “혁신사이클 대표 참조선”이 정확한가?

다음 대안을 비교하라.

- 현행 정적선 유지 + 정직한 명칭
- 제거
- latest selected-era raw median
- selected-era detrended reference
- actual k-NN neighbor forward median
- dotcom-only reference

각 대안은 probability가 아닌 reference임을 유지해야 한다.

---

## 7. 검증 질문 D — 닷컴 버블 DB가 main으로 쓰였는가

계층별로 답하라.

| 계층 | 닷컴 사용 여부 | 단독/혼합 | 시간 anchor | 수치 기여 |
|---|---|---|---|---|
| GBM 분포 | | | | |
| S1/S2/S3 분류 | | | | |
| 구조 raw shape | | | | |
| correction depth | | | | |
| 회색 reference | | | | |
| k-NN selection | | | | |

추가로 다음을 검증하라.

- dotcom의 `overlay_start=1995-01`과 `model_anchor=1996-01` 분리가 구조경로에서 존중되는가?
- `data/base_rates/dotcom_analog_auto.md`의 dotcom correction episode가 진폭 target에 직접 쓰이는가?
- `correction_depth_median=-0.1219`의 산출 집합과 표본 수를 패키지 증거로 재현할 수 있는가?
- dotcom을 main으로 승격할 통계적 근거가 있는가, 아니면 사용자 가설에 따른 방향 튜닝인가?

---

## 8. 검증 질문 E — 2027 경로 현실성

### E-1. 현행 구조

- 2027-01-08에서 달력연도 detrend가 재시작하는지 확인한다.
- 2027-06-03→07-02 조정 -7.8~-8.0%를 재현한다.
- 세 시나리오의 timing·recovery·drawdown 유사도를 계산한다.
- 월간 선형보간과 주간 샘플링이 roughness를 얼마나 낮추는지 측정한다.

### E-2. 대안 설계

최소 다음 후보를 비교 설계하라.

1. full-horizon continuous detrend
2. actual-neighbor forward path ensemble
3. scenario-conditioned correction episode block bootstrap
4. macro/liquidity-conditioned state transition
5. heavy-tail baseline + historical residual bootstrap

각 후보에 대해 다음을 표로 제시한다.

| 후보 | 필요한 DB | PIT 가능 | 시나리오 차별화 | 불확실성 표현 | 과적합 위험 | 계산비용 |
|---|---|---|---|---|---|---|

대표선은 단일 샘플 경로가 아니라 conditional median 또는 medoid여야 한다. 가능하면 각 시나리오 내부 p25~p75 band도 제시하라.

---

## 9. 검증 질문 F — 데이터 적층과 정합성

다음 provenance를 감사하라.

- 2026-07-29 context를 만든 model_run의 현재 원장 존재 여부
- selected_eras와 neighbor 날짜·거리의 재현 가능성
- overlay raw source와 availability timestamp
- correction episode 산출물의 표본·기간·threshold
- dotcom FRED/Yahoo 교체 및 cross-check
- AI regime `coverage<0.6` 차단 유지 여부
- 2027에 사용되는 역사 구간이 overlay 범위를 넘거나 clamp되는지

재현 불가능한 항목은 “설명 가능”으로 낮추지 말고 `BLOCKED`로 표시한다.

---

## 10. 고도화 설계 요구사항

검토 후 개선이 필요하다고 판정하면 다음 순서로 설계한다.

### L0 — 의미론·lineage 시정

- 회색 reference의 이름·출처·clip 공개 또는 동적 재생성.
- k-NN neighbor와 overlay phase 연결 관계 명문화.
- 현행 공통 shape가 scenario별 동학이 아니라는 UI 라벨.
- 기존 확률·팬·archive 불변.

### L1 — 독립 재현

- 구조경로 입력을 frozen context로 직렬화.
- selected neighbor 날짜·거리·forward curve 저장.
- raw→detrend→calibration→display 단계별 테이블 자동 산출.
- 같은 snapshot 재실행 byte-identical.

### L2 — 시나리오별 경로 연구

- S1/S2/S3 조건과 역사 cohort를 사전등록.
- within-scenario path distribution 생성.
- 시간·깊이·회복기간을 따로 추정.
- 현행 모델과 OOS 비교 후에만 champion 교체.

### L3 — 2027 연속경로

- 연도별 리셋 대 full-horizon 연속 모델 비교.
- 2026/2027 UI 분리는 유지하되 계산 경계 인위성 제거.
- scenario별 band와 medoid 도입.

### L4 — UI

- 기본 화면에 `형태 출처`, `진폭 출처`, `시나리오 내부 구간`을 분리.
- reference·baseline·structural을 색·선종·라벨로 명확히 구분.
- 차트 툴팁에 probability space와 asof 표시.
- 화면이 복잡해지면 상세 펼치기로 이동하되 고지 삭제 금지.

---

## 11. 필수 수용 기준

`review/chatgpt_structural_path_acceptance_gates_260806.md`의 모든 게이트를 사용한다.

특히 다음은 필수다.

- 현재 하락의 원인 수치 재현
- 시나리오별 normalized residual 동일성 측정
- 회색 reference가 하드코딩인지 확인
- dotcom main 여부 계층별 판정
- 2027 경로의 실제 correction과 공통 shape 문제 분리
- PIT·OOS·hindsight 방지 설계
- 기존 383개 테스트와 immutable archive 보존 계획

---

## 12. 최종 출력 형식

### 12.1 한 페이지 정본

사용자 질문 다섯 가지에 각각 2~4문장으로 답한다.

### 12.2 결함 대장

| ID | 등급 | 심각도 | 재현 근거 | 영향 | 권고 |
|---|---|---|---|---|---|

등급은 `PASS/PARTIAL/FAIL/BLOCKED`, 심각도는 `P0~P3`를 사용한다.

### 12.3 인과 추적표

| 화면 현상 | 데이터 | 함수·수식 | 파라미터 | 결과 | 오독 가능성 |
|---|---|---|---|---|---|

### 12.4 설계 비교

| 설계안 | 장점 | 약점 | 필요한 데이터 | OOS 검증 | 권고 순위 |
|---|---|---|---|---|---|

### 12.5 구현 계획

| 단계 | 파일 | diff 요지 | 신규 테스트 | 게이트 | 선행조건 |
|---|---|---|---|---|---|

### 12.6 미충족·사용자 결정

- 패키지만으로 검증하지 못한 것
- 추가 확보할 데이터
- 사용자가 결정해야 할 표시·모델 정책
- 지금 당장 구현하면 안 되는 항목

---

## 13. 금지되는 답변

- “그래프가 마음에 들지 않으니 곡선을 더 요동치게 하자.”
- “닷컴처럼 보이도록 닷컴 가중치를 높이자.”
- “시나리오별로 랜덤 노이즈를 다르게 넣자.”
- “S1은 상승, S3는 하락이므로 적당히 수동 곡선을 그리자.”
- “사용자가 상승을 예상하니 83%를 더 높이자.”
- “표시용이므로 재현성·PIT 검증은 필요 없다.”

좋은 답변은 데이터 계보와 시나리오 조건부터 고친 뒤, 경로 차이를 결과로 얻는다.
