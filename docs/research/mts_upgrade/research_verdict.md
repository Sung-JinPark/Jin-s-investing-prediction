# MTS Research 계층 — 연구 판정 (W0~W5 구현분)

**Thesis: 동결 V8/PB 의 기록을 세 수준 — ① 발행물 무결성(해시체인·유도 필드), ② 채점 경로
재현(저장 입력 기준 bit/1e-9), ③ 전체 모델 재계산(1행 등록 실행) — 에서 재현하는 adapter 와
§19 수용 테스트를 통과하는 정합성·평가 기반이 구축됐고, 감사는 'RV 양성의 과반이 원점에서
기계적으로 확정' 등 다섯 가지 사실을 확인했다 — 이 중 어느 것도 예측력 개선 주장이 아니다.**

작성: 2026-10-26 · 설계 정본: `docs/design/NASDAQ_forecasting_upgrade_design_20261026.md`
정정: 2026-10-27 — 외부 적대적 리뷰 반영 (`external_review_resolution_20261027.md` 참조):
검증 수준 3단 구분(F07), BSS 귀속 문구 축소(F01), ulp 표현 정정(F07u), 읽기 범위 문구
정밀화(F03), (lag,α) 재튜닝 문구 정정(F12).

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
   하한)>θ 인 양성이 h5 **85%**·h21 **70%**·h63 **55%** — 그 양성들은 미래 수익과 무관하게
   원점에서 확정돼 있었다. **V13 BSS 에 대한 기여 분해는 미실행** — "큰 몫" 류 귀속은 2026-10-27
   정정으로 철회하고, per-origin 기계적 플래그 × 원장 Brier 분해를 사전등록 후속으로 남긴다
   (F01). (`rv_mechanics_audit.md`, prereg 선기록)
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
  h1/h5 grid 만 max|Δ| = 2.4e-17(h1)·2.0e-16(h5) — 부동소수 재결합(BLAS/배열 정렬) 수준.
  §19.2 대로 허용오차를 넓히지 않아 strict 판정은 MISMATCH 로 기록한다. 크기 표현 정정
  (2026-10-27, F07u): 절대 크기는 기계 엡실론(2.22e-16)의 0.1~0.9배이나, 해당 grid 원소
  크기(|v| ≤ 0.085)의 **ulp 로는 3.5~114 ulp**(상대오차 ≤ ~1.4e-14) — 종전 "1~2 ulp" 는
  eps 단위를 ulp 로 오기한 것 (원 행은 주간 잡 산출 — 실행 환경 비동일 가능, 행에 BLAS/CPU
  기록 없음). `data/mts_research/derived/v8_tier2_replay.json`.
- DFM smoothed-state 유입·원점 지연(ASOF_AGE) 가설: 미확인 — 후속 감사.
- window-mechanics baseline 의 PB 대비 증분: **주장하지 않음** — 사전등록된 비교가 아님.
- 새 후보(hazard 실측·옵션/일중 블록)의 예측력: 증거 없음 — 실험 미실행이 정상 결과.

## 금지 준수 선언

구현 완료 ≠ 예측력 향상. 미실행 결과를 추정 숫자로 채우지 않았고(NOT_RUN/BLOCKED 명기),
연구 PASS 를 공개/승격 승인으로 표현하지 않는다. 모든 출력은 참고 의견이며 매매 신호가
아니다. 동결 파일 수정 0, 예산 소모 0. **읽기 범위 정밀화 (2026-10-27, F03)**: "홀드아웃·봉인
bytes 읽기 0" 은 **guarded purpose(research_fit/evaluation) 기준**이다 — replay_identity/audit
은 OPEN purpose 로 시장 아카이브 전 기간(홀드아웃·봉인 구간 날짜의 bytes 포함)을 읽으며
`data/mts_research/ledgers/exposures.jsonl` 에 기록된다. 이는 생산 경로(주간 shadow)와 동일한
읽기이고, 계약이 정의하는 '소모'(finalist 홀드아웃 채점·봉인 1회 공개)에 해당하지 않는다.
