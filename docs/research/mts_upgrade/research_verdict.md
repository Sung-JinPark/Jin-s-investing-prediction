# MTS Research 계층 — 연구 판정 (W0~W5 구현분)

**Thesis: 동결 V8/PB 를 바이트 수준으로 재현하는 adapter 와 §19 의 수용 테스트를 통과하는
정합성·평가 기반이 구축됐고, 감사는 'RV 양성의 과반이 원점에서 기계적으로 확정' 등
네 가지 사실을 확인했다 — 이 중 어느 것도 예측력 개선 주장이 아니다.**

작성: 2026-10-26 · 설계 정본: `docs/design/NASDAQ_forecasting_upgrade_design_20261026.md`

## 결과 표 (§20.2 형식)

| 검증 축 | 상태 | 증거 |
|---|---|---|
| baseline identity | **PASS** — PB 재계산가능 32행+해소 123행 전부 1e-9/1e-8 재현, V8 tier-1 전행(9 예측+19 해소+봉인+포인터) 재현 | `baseline_identity.json` |
| data/label integrity | **PASS(구축)** — 두 재생 모드·checkpoint·성숙 코호트·T01~T19 통과; 실측: T12·T13 PASS | `data_time_audit.md` |
| coherence | **PASS(실측)** — V8 단일 artifact 파생 전행, V13 33행 h/K 단조 위반 0 | `coherence_audit.md` |
| calibration | **미판정** — 보정 후보 적합 없음(identity 기본, 실측 보정은 W7) | — |
| incremental skill | **미판정 — 증거 없음이 정상** — 신규 후보 실측 실험 0 (예산·등록 게이트) | §3.3 |
| operational | **PASS(코드)** — 원자 발행·CAS·복구·오프라인 재생 테스트 통과; 운영 연결은 W8 BLOCKED | `test_results.json` |

코드 테스트 PASS(127/127)와 성능 evidence PASS 는 다른 판정이다 (§19.2) — 본 작업은 전자다.

## 확인된 사실 (감사 가설 → 승격)

1. **RV 양성의 기계적 확정**: 설계창(2007-2014, stride 21, 96원점)에서 rv_floor(닫힌형
   하한)>θ 인 양성이 h5 **85%**·h21 **70%**·h63 **55%** — V13 RV 셀 BSS 의 큰 몫은
   지속성+창 역학이다. (`rv_mechanics_audit.md`, prereg 선기록)
2. **목적 정렬**: h21/h63 최종 분포에서 VARX(lag,α)는 λ 스위치·PIT 이력 경유만
   (INDIRECT_VIA_LAMBDA), block_length 는 BYPASSED, h1/h5 는 ACTIVE — '1일 MSE vs
   장기 CRPS 불일치' 가설은 부분 확인이며, 재정렬 실험은 영향 경로가 있는 파라미터에만
   의미가 있다. (`objective_align_audit.md`)
3. **grid-종속 라벨**: V8 bundle grid 가 국채 휴장 주식 거래일(실측 2026-10-12)을
   제외해 h세션 누적수익 라벨이 그 날 수익을 누락 — 동결 코드의 공시 대상 성질
   (두 해소 행을 탈락일 차감 항등식으로 정확 재현). (`coherence_audit.md`)
4. **달러 splice 정상**: return-먼저-연결 구조로 인공 return 경로 없음(T13 PASS),
   공개일 전 native 가용 주장 0행(T12 PASS). 실효 전환점은 2006-01-02(backcast 우선)
   — 원고의 2019-01-02 는 FRED 계열 교체 시점. (`data_time_audit.md`)
5. **captured_forward 의 역사 증거 부재**: NASDAQCOM·VIX 백필은 available_at=수집
   시각 — 역사 재구성에서 과거 cutoff 에 보이지 않는다(승격 금지를 저장소가 이미 지킴).

## 정상 동작 확인

- V13 라이브 표면 33행: 지평·임계 단조성 위반 0.
- V8 채점 경로: 전 해소 행 bit 재현(저장 grid+actual), 아카이브 독립 검증 일치.
- 동결 재현 중 보호 파일 변경 0 (read-only 확인 테스트 포함).

## 미확인 / 판단 불가 (정직한 한계)

- V8 tier-2 전체 모델 재계산(1회, 원점 2026-10-16, 5,456s): **h21/h63(FHS) quantile_grid
  200개 전부 bit 동일**, ensemble_weights·blend·PIT 상태·p_up 등 전 필드 동일.
  h1/h5 grid 만 max|Δ| ≤ 2.0e-16 — 부동소수 재결합(BLAS/배열 정렬) 수준.
  §19.2 대로 허용오차를 넓히지 않아 strict 판정은 MISMATCH 로 기록하되, 크기가
  기계 엡실론 1~2 ulp 임을 병기한다 (원 행은 주간 잡 산출 — 실행 환경 비동일 가능,
  행에 BLAS/CPU 기록 없음). `data/mts_research/derived/v8_tier2_replay.json`.
- DFM smoothed-state 유입·원점 지연(ASOF_AGE) 가설: 미확인 — 후속 감사.
- window-mechanics baseline 의 PB 대비 증분: **주장하지 않음** — 사전등록된 비교가 아님.
- 새 후보(hazard 실측·옵션/일중 블록)의 예측력: 증거 없음 — 실험 미실행이 정상 결과.

## 금지 준수 선언

구현 완료 ≠ 예측력 향상. 미실행 결과를 추정 숫자로 채우지 않았고(NOT_RUN/BLOCKED 명기),
연구 PASS 를 공개/승격 승인으로 표현하지 않는다. 모든 출력은 참고 의견이며 매매 신호가
아니다. 홀드아웃·봉인 bytes 읽기 0, 동결 파일 수정 0, 예산 소모 0.
