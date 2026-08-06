# NASDAQ 구조경로 고도화 수용 게이트 — GATES-260806

대상: 2026·2027 NASDAQ S1/S2/S3, 혁신사이클 참조선, 역사 DB lineage

원칙: “더 현실적으로 보임”은 수용 기준이 아니다. 데이터 계보·PIT·분포 정합성·재현성이 기준이다.

---

## 1. 판정 규칙

- `PASS`: 코드·데이터·테스트로 기준을 전부 충족.
- `PARTIAL`: 일부 충족했으나 정량 또는 lineage 증거 부족.
- `FAIL`: 구현·데이터가 기준과 충돌.
- `BLOCKED`: 패키지 또는 원장만으로 재현 불가.

미충족 항목을 완료로 표시하지 않는다. UI가 좋아졌다는 이유로 모델 게이트를 통과시키지 않는다.

---

## 2. G0 — 불변성·확률 공간

| ID | 기준 | 수용 조건 |
|---|---|---|
| G0-1 | archive 불변 | r8와 이전 revision SHA가 그대로 유지되고 새 correction revision만 추가됨 |
| G0-2 | 확률 무변경 | 표시 경로 연구만으로 `83/2/15`를 변경하지 않음 |
| G0-3 | 팬 무변경 | 별도 분포 모델 승인 전 기존 p05~p95 팬을 임의 수정하지 않음 |
| G0-4 | 확률 공간 분리 | physical_event·reference_only가 scenario arithmetic에 들어가지 않음 |
| G0-5 | 방향 튜닝 금지 | 사용자 상승/하락 견해가 가중치·시대 선택·진폭 target을 바꾸지 않음 |

---

## 3. G1 — 2026 하락 원인 재현

| ID | 기준 | 수용 조건 |
|---|---|---|
| G1-1 | 단계별 산식 | raw→detrend→strength→display 값이 체크포인트에서 직렬화와 일치 |
| G1-2 | 위상 근거 | `current_phase=42`의 출처와 availability가 명시됨 |
| G1-3 | 이웃 연결 | k-NN neighbor date와 overlay phase의 관계가 계약에 명시됨 |
| G1-4 | anchor 정합 | dotcom overlay/model anchor 차이가 의도·효과와 함께 공개됨 |
| G1-5 | timing 의미론 | 10월이 사건 날짜가 아니라 월 위상 위험창임을 UI에 표시 |
| G1-6 | 진폭 분리 | native -5.7%와 calibrated -12.2%를 혼동하지 않음 |

G1-3 또는 G1-4가 재현 불가하면 2026 구조 timing은 `BLOCKED`다.

---

## 4. G2 — 시나리오별 동학

| ID | 기준 | 수용 조건 |
|---|---|---|
| G2-1 | 조건 연결 | 각 경로 shape가 S1/S2/S3 정의 또는 사전등록 state와 연결됨 |
| G2-2 | 공통 factor 공개 | 공통 shape를 유지하면 “scenario-specific dynamics 아님”을 명시 |
| G2-3 | 차별화 증거 | 서로 다른 shape를 쓰면 cohort·state·conditional sample 근거가 있음 |
| G2-4 | noise 금지 | 임의 랜덤 noise나 수동 곡선으로 차이를 만들지 않음 |
| G2-5 | 내부 분포 | scenario별 median/medoid와 내부 p25~p75 또는 동등 uncertainty 제공 |
| G2-6 | 분리도 측정 | normalized residual, 수익률 상관, timing 차이를 테스트로 고정 |
| G2-7 | 표본 게이트 | 작은 cohort는 case-list 또는 blocked로 표시, 정밀한 band 금지 |

S1/S2/S3의 정규화 residual이 동일하면서 화면이 “서로 다른 시나리오 경로”라고 주장하면 FAIL이다.

---

## 5. G3 — 혁신사이클 참조선

| ID | 기준 | 수용 조건 |
|---|---|---|
| G3-1 | lineage | 참조값 source·anchor·기간·생성시각이 직렬화됨 |
| G3-2 | 동적/정적 구분 | 하드코딩이면 명확히 legacy static이라고 표시 |
| G3-3 | 라벨 정확성 | selected-era가 아니면 “selected-era 대표” 표현 금지 |
| G3-4 | 시간 단위 | 26→52 보간의 원래 단위와 변환 의미가 설명됨 |
| G3-5 | clip 공개 | clip 전·후 종점과 잘림 구간을 UI/데이터에 표시 |
| G3-6 | 확률 오독 방지 | reference-only, 확률 아님 고지 유지 |

하드코딩 정적선을 최신 혁신 DB 선으로 표시하면 FAIL이다.

---

## 6. G4 — 닷컴 DB 정합성

| ID | 기준 | 수용 조건 |
|---|---|---|
| G4-1 | 계층별 사용표 | GBM·분류·shape·depth·reference에서 닷컴 기여를 분리 |
| G4-2 | 원자료 | dotcom source와 FRED/Yahoo 교체·검증 기록 포함 |
| G4-3 | anchor | 1995 overlay와 1996 model anchor 사용 목적 분리 |
| G4-4 | 표본 | correction episode 수·threshold·기간 재현 |
| G4-5 | 비교군 | dotcom-only·multi-era·leave-one-out 결과 비교 |
| G4-6 | main 승격 | OOS 또는 사전등록 근거 없이 닷컴 가중치 임의 상향 금지 |

---

## 7. G5 — 2027 경로

| ID | 기준 | 수용 조건 |
|---|---|---|
| G5-1 | 연속성 비교 | calendar-year reset과 full-horizon continuous 결과 비교 |
| G5-2 | 조정 재현 | 현행 6~7월 drawdown을 수치로 재현 |
| G5-3 | 시나리오 차이 | timing·depth·recovery가 조건부 데이터로 구분됨 |
| G5-4 | clamp 방지 | 역사 overlay 범위 초과·끝값 반복 여부 검사 |
| G5-5 | roughness | 월간 보간이 변동성을 과도하게 축소하는지 측정 |
| G5-6 | 경로군 | 단일 선보다 scenario 내부 분포를 우선 제공 |
| G5-7 | 연도 UI | 2026/2027 화면 분리는 유지하되 모델 경계로 오인시키지 않음 |

---

## 8. G6 — PIT·OOS·과적합 방지

| ID | 기준 | 수용 조건 |
|---|---|---|
| G6-1 | availability | 모든 feature·regime이 해당 시점에 실제 공개된 값 |
| G6-2 | selection freeze | 시대·episode 선택 규칙을 결과 보기 전에 사전등록 |
| G6-3 | rolling OOS | 최소 rolling-origin 또는 leave-era-out 검증 |
| G6-4 | benchmark | 현행 GBM·현행 구조경로와 CRPS/log score/coverage 비교 |
| G6-5 | 다중비교 | 후보가 많으면 selection bias와 연구 자유도 보고 |
| G6-6 | 표본 독립성 | 같은 시대 중복 neighbor의 자기상관을 처리 |
| G6-7 | 피처 공선성 | k-NN 상관 피처 미백색화 민감도 보고 |

---

## 9. G7 — UI 의미론·접근성

| ID | 기준 | 수용 조건 |
|---|---|---|
| G7-1 | 선 종류 | fan·GBM baseline·structural·reference가 선종과 범례로 구분 |
| G7-2 | 출처 카드 | 형태·진폭·종점·확률 출처가 서로 다른 카드로 보임 |
| G7-3 | 시나리오 내부 band | 색상만으로 구분하지 않고 텍스트·패턴·접근성 라벨 제공 |
| G7-4 | clipping | 잘린 reference는 화살표와 원시 종점 표시 |
| G7-5 | 모바일 | 390px에서 범례·축·우측 라벨 겹침 없음 |
| G7-6 | 키보드 | 차트 주차 탐색과 토글을 키보드로 조작 가능 |
| G7-7 | 고지 유지 | asof·probability space·투자자문 아님 문구가 스크린샷에도 남음 |

---

## 10. G8 — 테스트·페이로드·성능

| ID | 기준 | 수용 조건 |
|---|---|---|
| G8-1 | 기존 회귀 | 최소 기존 383개 테스트 유지 |
| G8-2 | 결정성 | 같은 frozen input에서 byte-identical output |
| G8-3 | 단계 테스트 | raw/detrend/calibration/display 체크포인트 테스트 |
| G8-4 | scenario 분리 테스트 | normalized residual 동일·차이를 명시적으로 검사 |
| G8-5 | reference lineage 테스트 | 하드코딩·동적 source 상태와 라벨 일치 검사 |
| G8-6 | archive | 이전 revision SHA 불변 검사 |
| G8-7 | 정적 예산 | data.json 320KB 상한; 초과 시 정당한 예산 변경 승인 |
| G8-8 | 렌더 즉시성 | 정적 사이트에서 차트 전환·조회가 즉시 동작 |

---

## 11. 단계별 완료 판정

### 검토 완료

- G1~G5에 대한 재현 표가 있고, 미재현 항목이 BLOCKED로 분리돼야 한다.

### 설계 완료

- 후보 모델 비교, PIT/OOS 계획, 데이터 요구사항, migration이 있어야 한다.
- 구현되지 않은 후보를 PASS로 표시하지 않는다.

### 구현 완료

- 관련 게이트 테스트가 추가되고 전체 회귀가 통과해야 한다.
- 새 revision과 correction 원장이 있어야 한다.
- Pages 정적 빌드와 1280/390 화면 검증이 있어야 한다.

### 배포 완료

- main push SHA, verify/pages run URL, live data spot check를 보고해야 한다.

---

## 12. 최종 보고 표

| 게이트 | 상태 | 실측값 | 파일·테스트 | 남은 일 |
|---|---|---|---|---|

모든 행을 채우고, `PARTIAL/FAIL/BLOCKED`가 하나라도 있으면 전체를 무조건 PASS로 결론내리지 않는다.
