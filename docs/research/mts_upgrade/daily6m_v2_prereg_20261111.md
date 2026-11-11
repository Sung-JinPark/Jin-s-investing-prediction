계약이 정본이다 — `data/contracts/timeseries_daily6m_v2.yaml`. 이 문서는 해설이며, 둘이 다르면 계약을 따른다.

# daily6m v2 섀도 사전등록 해설 (U4, 2026-11-11)

- 지시 원문: "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜" (수신 상한 2026-11-11T09:03:44Z, 영수증 `data/timeseries_daily6m_v2/ledgers/approvals.jsonl`).
- 지위: 연구 섀도 · 수치 비공개 · **참고 의견, 매매 신호 아님**. v1 표시는 그대로다.
- LLM 비용 0 (월 상한 $50 무관). 계산은 로컬 CPU 와 Actions 러너뿐이다.

## ① 목적

v1(`timeseries_daily6m_v1`)의 커널(VARX 결합 경로)은 그대로 둔다. **같은 원점·같은 입력·같은 난수(v1 시드)** 에서 분산 처리만 바꾼 v2 세 팔을 매 v1 발행 직후 섀도로 발행한다. 채점은 v1 해소 원장의 같은 고정 종가를 재사용하는 쌍대 비교다.

| 팔 | 정의 |
|---|---|
| `main` | fresh 분산(σ²_{T+1\|T}, 원점 당일 잔차 포함) + 선택 전용 CRN 부트스트랩 · 21 배수 고정 검증 격자 · 1 MC SD 히스테리시스 선택 |
| `term_structure` | main + 평균회귀 분산 기간구조 σ²_{T+k} = L + φ^(k−1)(σ²_{T+1} − L), L = 느린 EWMA 0.996 — **V8 B1 과 같은 식의 재시험** |
| `zero_drift` | main 에서 나스닥 조건부 평균만 0 (같은 난수) |

## ② v1 무변경 증명

- v1 `model_code_hash` = `c3fe06c1fbe3b0862e299f8eeb0a2018f8f35940f2fe12be06366905b2fda539`, v1 계약 frozen hash = `53f023f79829778c37bfc460698ff5e2224894b9ec7ecfd03f2d18fddeeb83dc` 를 테스트(`test_daily6m_v2_contract_wiring.py`)가 핀한다.
- 매 run 에서 v1 시드·v1 기록 block/λ·v1 기록 발행 외생값으로 축약 재시뮬해 `path_hash` 가 v1 run 과 같고, 발행 시점 v1 code hash 가 v1 run 의 값과 같을 때만 `identical_inputs`(1차 표본)다. 아니면 `inputs_differ`(발행은 하되 1차 제외, 민감도만).
- `identical_inputs` run 은 재구성한 v1 경로로 v1 39분위 격자를 저장한다. 그 τ∈{.10,.25,.50,.75,.90} 행은 v1 `band_index` 와 1e-12 로 같아야 하며, 다르면 발행을 중단한다.
- v2 code hash 대상에는 v1 파일이 없다. v1 의존은 run 마다 `parent.v1_model_code_hash_at_issue` 로 기록한다.
- v2 `model_code_hash`(run 적재 게이트)는 숫자를 바꿀 수 있는 파일만 묶는다: v2 `kernel.py`·`model.py`, 봉인 `timeseries/model.py`·`timeseries/backtest.py`·`timeseries_v2/model.py`. `contracts.py`·`pipeline.py`·`scorecard.py` 는 run 의 `orchestration_code_hashes`·판정 행의 `scorecard_code_hash` 로만 기록한다(비게이트). verify 는 해소 행과 판정 행을 원장에서 다시 계산해 바이트 대조한 뒤, 기록 시점과 코드가 달라졌으면 `diagnostics` 에 공시한다.
- 축약 동일성은 같은 수치 런타임을 전제로 한다. 2026-11-11 로컬 드라이런(Windows numpy 2.4.3)으로 11-09 v1 run(CI numpy 2.5.4)을 재구성하니 입력 계보는 전부 같았지만 VARX 계수가 8.6e-16 달라 `inputs_differ(path_hash)` 였다. run 마다 `reduction_identity.runtime`·`v1_runtime`·`fit_residual_hash_equal`·`magnitude`(band 로그 최대 차·계수 최대 차·기계/BLAS 빌드 — 진단, 통과 규칙 아님)를 기록한다. CI 러너 사이의 동일성은 첫 배포 run 에서 확인한다 [미검증].
- 쓰는 곳은 `data/timeseries_daily6m_v2/` 뿐이다. 발행기 허용 목록에 approvals·prereg·v1 경로가 없다.

## ③ 수식

- fresh 분산: 적합(expanding·rolling)·열마다 σ²_{T+1|T} = λσ²_{T|T−1} + (1−λ)e_T². 과거 행 표준화 분모는 v1 과 같은 지연 EWMA(봉인 `_ewma_scale` 복사).
- 기간구조 성장 g[k−1,j] = √(max(L_j + φ_j^(k−1)(fresh_j − L_j), 1e−16) / fresh_j), g[0]=1.
- 선택: 후보 block∈{5,10,21} × λ∈{0.94,0.97}. 검증원점 = 잔차 행 위치가 21 의 배수인 격자의 최근 min(52, (n−252)/21) 개. 복제 r=0..7, 원점 j 마다 `default_rng([20261111, r, j])` 로 시작 정수·균등난수 (1000×21) 를 한 번 뽑아 6후보가 공유한다(u < 1/block 이면 재시작). 점수 = 원점 평균 표본 CRPS(나스닥 21세션 합). best = 평균 최소, 직전 v2 선택(첫 run 은 (10,0.97))과의 쌍대 차 평균이 1 MC SD(=sd/√8) 를 넘을 때만 전환.
- 시뮬: 봉인 V2 부트스트랩·같은 난수 소비 순서(축약 시 `simulate_correlated_paths_v2` 와 비트 동일).
- 1차 지표: 39분위 격자 CRPS — τ_i = i/40, CRPS39 = 2·Σ_{i=1}^{38}(τ_{i+1}−τ_i)(ρ_{τ_i}(y−q_i)+ρ_{τ_{i+1}}(y−q_{i+1}))/2, y = ln(종가/anchor). 꼬리 [0,0.025]·[0.975,1] 은 적분 밖.
- 리드 배율: **기각**(함수 없음, 상수 없음).

## ④ 설계창 실측 (2007-01-01 ~ 2014-12-31, 수치모델 예외)

설계 상수는 `ai_fc.timeseries_daily6m_v2.design` 이 V2 시장 아카이브에서 재생성한다(로컬 약 11분, 2026-11-11 실측 640.9초). canonical hash `265c48d3656142bfecbe59c76083a974821795409cab19c2e3000211153ee592`.
2015 이후 행은 읽은 뒤 건너뛴다(사용 0행, 2026-11-11 기준 건너뛴 행 16,266). r1 스크래치 재생과 **원점 278개의 선택·마진이 전부 비트 동일**했고 PIT 손실도 같은 값이었다.

GARCH(1,1) 분산타깃 가우스 QMLE φ(5자리): nasdaq_return 0.98708 · vix_change 0.88011 · dgs2_change_bps 0.99947 · curve_change_bps 0.99350 · dollar_change 0.99535. 나스닥 반창 0.99111 / 0.95690.

대리 재생(나스닥 단변량, 원점 2008-12-26~2014-06-30 5세션 간격 278개, 10,000 경로, R=8):

| 리드 | v1형 cov80/cov50 | 평탄+fresh (main) | S 기간구조 | B 기간구조 |
|---|---|---|---|---|
| 1 | 0.781 / 0.475 | 0.781 / 0.471 | 0.781 / 0.471 | 0.781 / 0.471 |
| 5 | 0.813 / 0.529 | 0.806 / 0.525 | 0.813 / 0.529 | 0.820 / 0.532 |
| 21 | 0.813 / 0.464 | 0.809 / 0.457 | 0.838 / 0.496 | 0.860 / 0.507 |
| 63 | 0.820 / 0.432 | 0.813 / 0.424 | 0.892 / 0.489 | 0.935 / 0.561 |
| 126 | 0.795 / 0.504 | 0.795 / 0.507 | 0.892 / 0.561 | 0.935 / 0.615 |
| 배율 전 PIT 손실 | — | 0.0098 | 0.0245 | 0.0599 |

- 장기수준 규칙: {sample_mean_square 0.0599, slow_ewma_0.996 0.0245} 중 최소 → **slow_ewma_0.996** 등록.
- 원시 격자 배율(기각 근거): 평탄 {1.05, 0.95, 1.05, 1.00, 1.00}, 반창 h126 1.10 ↔ 0.75. 실효 독립 창 h126 11. r1 의 사후 유의성 게이트는 어떤 리드에서도 발화하지 않았다.
- 선택: argmin 전환 158, 히스테리시스 후 전환 128, 직전값 유지 35. B 기간구조 h126 누적분산/평탄 중앙 1.990(좁히는 원점 14.0%). fresh/lagged sd 중앙 0.988.
- 상세 표: `data/timeseries_daily6m_v2/prereg/design_report_v1.json`(공시용, 판정 근거 아님).

## ⑤ 판정 규칙 (첫 v2 해소 전 고정)

- 위상 원점 o₀ = 첫 v2 run 원점. 리드 k 의 적격 원점 = XNAS 세션 순번 i(o) mod k == 0. 원점당 대표 run = 가장 먼저 발행된 v2 run. 결손·`inputs_differ` 는 대체하지 않고 센다.
- 표본 = 적격 원점을 순서대로 훑어 채점된 것의 처음 n 개(h1·h5 n=50, h21 n=30). x = crps39(팔) − crps39(v1).
- iid 부트스트랩 B=9999, rng 키 [20261111, k, arm_index], p = (1+#{m*≥0})/(B+1) 단측, CI90 백분위.
- 1차 가족 5 = {main, zero_drift}×h1 ∪ {main, term_structure, zero_drift}×h5. term_structure h1 은 main 과 비트 동일이라 검정이 아니라 항등 검사(verify).
- Holm 단측 α 0.05. superior = Holm 기각 & 평균 < 0, inferior = CI90 하한 > 0(공시), 그 외 indistinguishable.
- **단일 관찰**: h1 p 값은 h1 표본이 처음 50 이 되는 scorecard 실행에서, 가족 판정은 h5 표본이 처음 50 이 되는 실행에서 한 번만 계산해 `ledgers/verdicts.jsonl` 에 남긴다(kind 당 1행, 이후 재계산·정정 없음). 문턱 전 p 값은 내지 않는다.
- 크기 근거: r1 규칙(목표일 균등·블록 21·50일) 거짓 기각 0.29~0.46 / 비중첩 iid h1·h5 n50 0.04~0.06(가우스·GARCH-t), h21 n30 0.073.
- 예상 시점(결손 0 가정): h1 ≈ 50세션(≈ 2027-01 말), h5 ≈ 250세션(≈ 2027-11), h21 ≈ 630세션(≈ 2029-05).
- 승격 = 가족 판정 superior + h21 비중첩 n≥30 CI90 하한 ≤ 0(열등이 입증되지 않음 — 마진 있는 비열등 검정이 아니다) + 소유자 결정 + 새 계약. 자동 승격 없음. 판정 행 키는 `ci90_lower_le_0`.
- 목표일 균등 전 리드 Δ̄·리드 구간 표·QS5·Brier 는 서술(라벨 없음). coverage80 2차 = |cov_팔 − 0.8| − |cov_v1 − 0.8|(양수 = 팔이 명목에서 더 멂), 같은 솎음 표본·같은 부트스트랩 인덱스로 CI.
- 솎음 표본은 첫 미해소 적격 원점에서 멈춘다(접두 고정). 막힌 원점은 scorecard `blocking_origin` 과 verify `warnings` 로 드러난다.

## ⑥ 하지 말 것

v1 계약·코드·원장·워크플로 바이트 변경 · v1·v2 확률/밴드 산술 결합 · 라이브 결과를 본 뒤 상수·문턱·지표·표본 규칙 변경(새 계약으로만) · 판정 원장 행 수정·재기록, 문턱 전 라벨, 판정 시점 선택 · 2015 이후 데이터로 φ·장기수준 적합 · V8 B4·FHS 이식 · 놓친 원점 소급 발행 · 해소 행을 독립 표본으로 보고.

## ⑦ 오염 공시

- 설계는 v1 라이브 결함(EWMA 1세션 지연, 선택 근소차 전환 16 run 중 10회, 커버리지 원시 0.538)을 본 뒤 했다. 상수에 라이브 행은 0개 쓰였다.
- term_structure 는 V8 `B1_volatility_term_structure` 와 같은 식이고, V8 이 같은 설계창에서 dev run 2개(`tsv8-exp-92d143bb7d6754e673c7`, `tsv8-exp-b3d95536b64d0aa07e20`)로 이미 평가했다(GFC p10–p90 커버리지 0.615·0.551, 과소). 이 설계의 장기 리드 과대 커버와 방향이 반대다 — 원인 [미검증].
- 장기수준 S 후보는 B 앵커 과대 커버 결과를 본 뒤 추가됐다(anchor_variants.py 18:31 > replay 18:16·18:30). 팔 분리·배율 기각도 설계창 결과를 본 뒤 정했다.
- 설계창은 V8·V13·V14·V15 가 반복 열람했다. 대리모형(단변량)→VARX 전이 [미검증]. 설계창 곡선 DGS10−DGS2 ≠ 라이브 T10Y2Y, 아카이브 VIX ≠ VIXCLS, 최신 revision 리더(PIT 아님).
- 대리 재생의 선택은 봉인 부트스트랩·이동 격자·B 기간구조 점수로 돌았다(r1 스크래치 그대로 — 라이브 선택 규칙과 다르다).
- 한계 대장: KNOWN_LIMITS 63·64.

## ⑧ U2 이관 (d)(g) 처분

U2 명세가 U4 로 넘긴 `daily6m_sources.py` 파싱 순서 교정(d)과 새 Nasdaq 원천(g)은 **받지 않았다**. v2 의 동일 입력 쌍대 설계는 v1 과 같은 번들을 전제로 하고, 교정은 v1 호환 체인(v1 바이트 변경)을 요구한다. 현재 영향은 U2a 분류기 `intraday_pending` 이 흡수한다. 교정은 별도 'daily6m v1 호환 r2' 결정을 기다린다. daily6m v1 해시를 의도적으로 바꾸는 PR 은 같은 커밋에서 v2 핀 테스트를 갱신한다(계약의 등록 시점 값은 바꾸지 않는다).
