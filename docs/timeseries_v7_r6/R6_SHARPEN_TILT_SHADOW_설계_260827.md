# [R6 설계] SHARPEN · TILT · SHADOW — R5 G4 HOLD 이후 다음 단계 (2026-08-27)

> 계보: GATE-PASS-260826(R4) → R5 설계·실행 → **G4 HOLD (본 검토)** → R6.
> 헌법: 인계문서 §1의 금지 6항 전부 승계 — outer 재생성·재채점 금지, outer 수치를 목표함수로
> 삼는 파라미터 선택 금지, 임계·E0·역할해시 불변, exposure counter 초기화 금지.
> 성공 상태는 오직 `READY_FOR_PROSPECTIVE_SHADOW`.

## A. R5 판정 정본 (검토 결과)

**역사적 진전**: 이 계보 최초로 outer 전 지평 CRPS skill 양수 — h1 +1.09 / h5 +1.80 /
h21 +2.09 / h63 +2.40%, paired CI 상단 음수(유의), Brier도 base rate 우위, 스트레스 통과.
R4의 "성분 가족 오류" 진단과 R5의 E0-내포 조건부 스케일 설계가 **실증으로 입증**됐다.

**HOLD의 실체**: skill 축이 아니라 신규 3축 —
| 결함 | 실측 | 명목 | 기제 가설 |
|---|---|---|---|
| coverage80_fail | 95.20% | 80% | 예측분포 과광폭(과소확신) |
| coverage50_high | 81.83% | 50% | 동일 |
| balanced_direction_low | 정확히 50.0% | (계약 임계) | 방향 성분 퇴화 — 위치항을 설계상 배제(F-tier)한 필연 + 상수 예측 의심 |

**거버넌스 무결**: outer exposure_count=1·retry_allowed=false, grid 불변, 역할해시 R4 동결값
유지, 독립 재계산 대사(stored_gate_recompute) 존재. 이 팩 자체는 결함 없음.

**핵심 관찰**: 과광폭 95.2%는 사실상 "숨은 여력"이다 — CRPS는 보정 조건 하 예리함(sharpness)을
보상하므로, 폭을 명목에 맞추면 skill이 **추가로 상승**할 개연성이 높다. 즉 coverage 결함의
수리는 skill을 희생하는 교환이 아니라 같은 방향이다.

## B. 결함 → 기제 → 후보 (전부 사전등록, calibration cross-fit로만 적합, shadow 전 동결)

### B-1. 폭 축소 (SHARPEN) — coverage 2건 동시 해소
| ID | 후보 | 내용 | 파라미터 수 |
|---|---|---|---|
| C1 | 분산 보정 스칼라 | q'_τ = m + c_h·(q_τ−m), c_h는 cross-fit에서 Var(PIT)=1/12 또는 coverage 일치로 적합 | 지평당 1 |
| C2 | PIT-isotonic 재보정 | R4 §S-4 방법1 그대로 — 양 밴드 동시 교정 | 비모수 |
| C3 | 구조 원인 수리 | ① z-풀 표준화 일관성 감사(std(z)≈1? 예측 σ̂와 동일 σ로 표준화했나) ② 구간폭 분해 리포트: E0 성분 vs 조건부 성분의 폭 기여(평온/스트레스 레짐별) — **w_E0 floor가 평온기 과광폭의 주범이면 floor 값 변경은 사용자 결정 R6-D1**(calibration 증거로만 정당화, outer 수치 인용 금지) | 0(감사) |
선택 규칙(사전등록): cross-fit에서 |coverage−명목| 최소 + CRPS 비열화 제약. C3 감사는 무조건 수행.

### B-2. 방향 주입 (TILT) — balanced_direction 해소
| ID | 후보 | 내용 | 전제 |
|---|---|---|---|
| T0 | 계측 감사(최우선) | balanced accuracy 산출 경로 검사 — P(up) 또는 중앙값 부호가 상수인지. 상수면 "지표 배관" 수리 대상인지 계약 재확인 | 없음 |
| T1 | VRP 위치 틸트 | μ_t = δ0 + δ1·VRP_t (강한 축소, δ1 사전 상한) — BTZ(2009) 문헌 근거. **VIXCLS 온보딩 필요 → V8R-D1과 결합, DV-1 승인이 전제** | DV-1 |
| T2 | 레버리지 비대칭 z-풀 | 직전 수익 부호·크기 조건부 잔차 풀(EGARCH 성격) → 조건부 중앙값 미세 틸트. 신규 데이터 0 | 없음 |
| T3 | E0 방향 읽기 | P(up)를 스택 분포의 P(r>0)로 산출(시점별 가변) — 상수 예측 제거 | 없음 |
정직한 기대: 문헌상 방향 엣지는 미미. 계약 임계(R6-A1에서 원문 인용)가 지속적 >52%류라면
이 축이 최종 병목으로 남을 수 있음 — 그 경우도 그대로 기록한다.

## C. PROSPECTIVE SHADOW 게이트 (새 outer)

1. **동결**: 모델·가중·보정 전부 동결 후 새 계약 등록(후보·하이퍼·평가법 해시 고정).
2. **봉인 원장**: 주간(h21/63)+일간(h1/5) origin으로 전방 예측을 라벨 성숙 **전에** append —
   해시 체인, 예측시각 < available_at(라벨) 증명.
3. **판정 표본 산정(사전등록)**: coverage 검정은 이항 CI — 95%↔80% 구분은 origin ~30이면
   명확하나, "80%±5%p 이내" 인증은 n≈(1.645²·0.16)/0.05²≈**175 origin** 필요.
   → 단계 판정: h1/h5는 일간 origin으로 6~9개월 내 1차 판정 가능, h21/h63은 장기 축적
   (중첩은 기존 block bootstrap ℓ=13 방식 승계). skill 검정력은 calibration 분산 기반
   MDE로 사전 공표(outer 분산 인용 금지).
4. **중간 열람 규율**: 분기 1회 참고 리포트만, 파라미터 변경 시 shadow 원장 리셋+재동결.
5. PASS 주장 조건: shadow 판정뿐. (인계문서상 봉인 증명 가능한 미노출 holdout 부재 확인.)

## D. 180분 루프 매핑 (인계 예산 준수)

0–15 P0 동결(인계안 그대로, R5 outer denylist) → 15–35 PIT preflight → 35–60 **후보 계약
동결 = 본 문서 §B 등록** → 60–120 C/T 후보 적합·cross-fit 선택(C3·T0 감사 포함) →
120–150 E0 내포·재현·역할분리 테스트 → 150–180 shadow 계약·원장 초기화 + 상태
`READY_FOR_PROSPECTIVE_SHADOW` 선언 + 리뷰팩. 어느 단계든 outer 접근 시도 감지 시
`BLOCKED` 정지.

## E. Codex 킥오프 프롬프트 (붙여넣기)

```
R5 인계문서(HANDOFF/R6_THREE_HOUR_LOOP_HANDOFF.md)의 금지 6항이 헌법이다.
본 R6 설계서 §B의 후보(C1~C3, T0~T3)를 사전등록하고 §D 예산대로 진행하라.
적합·선택은 train/selection/calibration만 사용, R5 outer 경로는 denylist.
C3·T0 감사 결과가 구조 결함(표준화 불일치·지표 배관)을 밝히면 수리는 허용하되
그 수리 근거 문서에 outer 수치를 인용하지 마라(결함 벡터명까지만 허용).
w_E0 floor 변경(R6-D1)·VIXCLS 온보딩(DV-1)은 사용자 결정 대기 — 도달 시 정지·질문.
종료 상태는 READY_FOR_PROSPECTIVE_SHADOW 또는 BLOCKED 뿐이다. PASS 주장 금지.
```

## F. 사용자 결정
| # | 항목 | 선택지 |
|---|---|---|
| R6-D1 | w_E0 floor 재설정 | C3 폭 분해 결과 확인 후: 유지 / 하향(계약 개정 정식 승인) |
| R6-D2 | DV-1 연동 | VIXCLS(FRED) 온보딩 승인 → T1 활성화 / 보류 → T2·T3만 |
| R6-D3 | shadow 판정 임계 표본 | h1/h5 1차 판정 시점(6 vs 9개월) 및 coverage 허용 밴드 사전등록 |

**한 줄 정본**: R5는 "예측력이 없다"를 반증했다. R6의 일은 새 신호를 찾는 것이 아니라
이미 확보한 분포를 **명목 폭으로 조이고(SHARPEN), 최소한의 방향을 문헌 근거 채널로만
주입하고(TILT), 그 전부를 전방 데이터에서 봉인 검증(SHADOW)**하는 것이다.
