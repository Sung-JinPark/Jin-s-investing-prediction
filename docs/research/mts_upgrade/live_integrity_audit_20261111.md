# MTS 라이브 실측 정합성 감사 (2026-11-11)

> 지위: **참고 의견, 매매 신호 아님.** 이 보고서와 이번 PR 의 산출물은 전부 `display_only` 또는
> `scoring_excluded` 이며 모델 숫자를 하나도 바꾸지 않는다. 기준 세션 2026-11-10(종가), 작성 2026-11-11 KST.
> 감시 임계·XNAS basis 사전고정은 이 보고서보다 먼저 커밋됐다(`9f731c0c`, 2026-11-11T12:40:49+09:00).

## 0. 판정

라이브 성적 열세(V8 h1 −4~−6%, daily6m 커버리지 53.8%, V13 vix25_h21 강등후보(산술 예상, 적용은 사용자 결정 U6))는 봉인 성적 분포 안의
**단일 에피소드 불운과 구분되지 않는다**. 표본은 주간 원점 12개, 서로 다른 목표일 18일, 사건 국면 1개
(2026-11-05)다. 반면 라벨 달력·변동성 상태 시점·근소차 선택 잡음·표시 투명성·조용한 실패의 다섯 축 결함은
결정론적이고 반복되며 고칠 수 있다. 이번 PR 은 이를 **드러내는** 도구만 넣고, 숫자를 바꾸는 개선은 후속 계약
초안(`data/contracts/multivariate_timeseries_v15_coherence.draft.yaml`)으로만 남긴다.

### 출처 약호

| 약호 | 파일 |
|---|---|
| ARC | `data/timeseries_v2/ledgers/market_observations.jsonl` (NASDAQCOM·VIX, 최신 개정) |
| V8F / V8R / V8D | `data/timeseries_v8/ledgers/shadow_forecasts.jsonl` / `shadow_resolutions.jsonl` / `daily_display_forecasts.jsonl` |
| V8C | `data/contracts/multivariate_timeseries_v8.yaml` |
| D6F / D6R | `data/timeseries_daily6m/ledgers/forecasts.jsonl` / `resolutions.jsonl` |
| V13R / V13L | `data/timeseries_v13/ledgers/vol_live_resolutions.jsonl` / `vol_live.jsonl` |
| THR | `data/mts_research/contracts/coherence_monitor_thresholds_v1.json` (canonical_hash `bcc24081…02d76`) |
| AUD#ID | 감사 워크플로 검증 발견(아래 §3 의 ID). 근거 스크립트는 세션 scratchpad 에 있었고 커밋되지 않았다 — 재현 경로는 §4 의 도구다 |

## 1. 실측 대조 (기준 2026-11-10)

| 항목 | 값 | 출처 |
|---|---|---|
| 나스닥 종합 2026-11-10 종가 | 25,065.88 **[미검증]** | 감사 세션(2026-11-11 KST) 기록은 "Nasdaq 공식값 재확인"뿐이고 URL·조회 시각·응답이 보존되지 않았다. 재확인 원천: `https://api.nasdaq.com/api/quote/COMP/historical` (저장소 `daily6m_sources.py` 의 공식 원천). 아카이브 미반영이라 저장소로 재현 불가 |
| VIX 2026-11-10 종가 | 19.46 **[미검증]** | 같은 사정. 재확인 원천: `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv`. 아카이브 미반영 |
| 아카이브 마지막 세션 | 2026-11-09 (NASDAQCOM 25,253.14 · VIX 19.92) | ARC |
| 11-10 1일 로그수익 | 나스닥 −0.744%, VIX −2.34% | 위 두 [미검증] 값과 ARC 11-09 에서 계산 |
| 2026-11-05 충격 | 나스닥 −5.68% 로그, VIX 16.61→28.18(로그 0.529) | ARC, AUD#V13E-4 |
| 공식값 대조(08-01~11-09) | VIX 71/71, NASDAQCOM 70/70, ALFRED 141/141 일치, 다중 개정 0 | AUD#PH-7, AUD#CMC-8 |
| 입력 대조 | vix_latest 132/132, V13 입력 44/44, V8 표시 앵커 39/39 | AUD#CMC-7 |

도구들은 저장소 파일만 읽으므로 기본 as-of 는 아카이브 마지막 세션(11-09)이다. 11-10 종가는 당일 늦게 아카이브에 들어온다.

## 2. 표면별 성적 (n · CI · 단일 에피소드)

### 2.1 V8 주간 섀도 (원점 12, 해소 29행) — 공식은 grid 라벨, XNAS 는 진단 basis (혼합 평균 없음)

skill = 1 − ΣCRPS_model/ΣCRPS_baseline (같은 basis·같은 행 집합 안에서만). XNAS 열은 두 코호트를 나눠 적는다:
**원장 동일 행**(grid 원장이 해소한 행과 같은 (원점, 지평), `matched_ledger_rows`)과 **확정 목표 전체**(원장 미해소 잠정 행 포함,
`all_closed_targets`). grid 숫자와 견줄 수 있는 것은 원장 동일 행뿐이다.

| 지평 | grid skill (원장, 공식) | XNAS skill — 원장 동일 행 | XNAS skill — 확정 목표 전체 | 봉인 2019+ 롤링 백분위 (grid / XNAS 전체) | 출처 |
|---|---|---|---|---|---|
| h1 | −5.43% (n=11) | −5.72% (n=11) | −3.95% (n=12, 11-06 원점 잠정 포함) | 4.5~6.4 / 10.7 | V8R 재계산, derived/v8_xnas_label_summary.json, AUD#V8-LOC-03 |
| h5 | +0.68% (n=11) | −0.73% (n=11) | −0.73% (n=11, 원장 동일 행과 같음) | 51 / 37.1 | V8R, 같은 derived, AUD#CAL-01 |
| h21 | +1.55% (n=7) | −0.18% (n=7) | −3.02% (n=8, 10-09 원점 잠정 포함) | 43 / 20.1 | V8R, 같은 derived, AUD#CAL-01 |
| h63 | 해소 0 | — | — | — | V8R |

- 부트스트랩 90% CI 는 두 basis 전 지평에서 0 을 포함한다.
  - XNAS(확정 목표 전체, AUD#V8-LOC-03): h1 [−11.1%, +2.9%] (n=12), h5 [−5.3%, +6.3%] (n=11), h21 블록 [−5.4%, +10.1%] (n=8).
  - grid(원장, 원점 클러스터 percentile·5000회·seed 20261111, derived): h1 [−13.2%, +4.0%] (n=11), h5 [−3.2%, +6.2%] (n=11), h21 [−4.0%, +10.9%] (n=7).
- 단일 에피소드 민감도 — basis 마다 따로 적는다(행 집합이 같을 때만 비교):
  - 11-05 충격을 포함한 h5 창(원점 10-30) 제외: **XNAS** −0.73% → +0.35% (n=10) / **grid** +0.68% → +2.22% (n=10).
  - 11-05 를 포함한 h21 잠정 창(원점 10-09) 제외: **XNAS 확정 목표 전체** −3.02% → −0.18% (n=7). grid 원장에는 이 행이 아직 없다.
  - 콜럼버스데이 재라벨 창(원점 10-09 h5) 제외: **grid·XNAS 모두** +2.94% (n=10) — 남은 10행은 두 basis 라벨이 같다.
  - h1 은 금요일 원점이라 11-05 를 포함한 창이 없다.
  - 탐지 가능 최소 열세 약 −8%(n=12) — THR.
- 봉인 구간 12주 창의 45%(h1)·46%(h5)·33%(h21)가 음수 skill 이었다 (AUD#V8-LOC-03).
- h1 은 12/12 발행 시점에 이미 실현(발행 지연 중앙 3.58일, 정의: 원점 XNAS 종가 16:00 ET → `knowledge_cutoff`,
  derived `emission_timing.emit_lag_days_median`) → 대표 지표가 아닌 pseudo-OOS (V8F, AUD#CAL-02).
- 코드 해시: live `869418cc` 대 sealed `8361899f` (V8F, `sealed_evaluations.jsonl`). 동일 모델 근거는 identity replay PASS.

### 2.2 daily6m (발행 16 중 해소 기여 15, 해소 132행 — 독립 표본 아님)

| 지표 | 값 | 출처 |
|---|---|---|
| 커버리지 원시 | 71/132 = 0.538 | D6R 재계산 |
| 목표일 균등 | 0.648 (서로 다른 날 18) | D6R 재계산 |
| 최신 원점 / 주간 최종 | 10/18 / 20/37 | AUD#D6C-1 |
| 원점 클러스터 90% CI | [0.42, 0.63], 실효 독립 시행 약 5~8 | AUD#D6C-1 |
| 모형 정확 귀무에서 P(원시 ≤ 0.538) | 0.08~0.16 (5% 유의 아님) | AUD#D6C-1 |
| 11-05 충격 0 대체 민감도 | 0.735 | AUD#D6C-2 |
| 일간 z sd | 1.69 (χ² 90% CI 1.33~2.37), 11-05 제외 1.40 | AUD#D6C-3 |
| 방향 Brier | 0.2452 (상수 0.55 기준 0.2434와 구분 불가, 날짜 클러스터 CI [−0.003, +0.007]) | D6R 재계산, AUD#D6C-6 |

단일 에피소드: 11-05 이후 날짜에 가중 31.8%(균등이면 16.7%) 집중.

### 2.3 V13 변동성 사건 (해소 189행, distinct ≤ 2026-11-09)

| 셀 | n | 사건 | Brier | 기후 | BSS | 출처 |
|---|---|---|---|---|---|---|
| vix25_h5 | 38 | 3 | 0.0657 | 0.125 | 0.474 | V13R 재계산 |
| vix25_h21 | 23 | 3 | 0.1224 | 0.197 | 0.378 (11-10 반영 시 0.247) | V13R, AUD#V13E-2 |
| rv_h5 | 38 | 12 | 0.0841 | 0.272 | 0.691 | V13R |
| rv_h21 | 23 | 11 | 0.1997 | 0.287 | 0.303 | V13R |

- 라벨·resolved_session 독립 재계산 189/189 일치, p 재현 |Δ| ≤ 5e-7 (AUD#V13E-6).
- 모든 vix25 양성이 11-05 단일 에피소드(event runs=1). rv_h5 양성 8/13(11-10 포함)은 원점에서 기계 확정 (AUD#V13E-7).
- T7 예상: vix25_h21 은 60원점(약 2026-12-03, 성숙 약 2027-01-05)에서 모든 경로 CI90 하한 < 0 → 강등후보 산술 확정.
  rv_h21 CI90 하한 약 +0.002(칼날). **예상 산술이며 적용은 사용자 결정** (AUD#V13E-2, `docs/DECISIONS.md` 2026-11-11 선공시).
- 기후 기준선(설계 0.31/0.42)은 GFC 로 부풀어 있어 "기후 대비 통과 ≠ 보정됨" (AUD#V13E-3).

## 3. 결함 D1~D16 (검증 발견 42건 묶음)

등급: 중상 > 중 > 하. "봉인"은 근본 수정이 봉인 코드에 있어 이번 PR 범위 밖이라는 뜻이다.

| ID | 결함 | 묶은 발견 | 근본 원인 (위치) | 등급 | 이번 PR 대응 |
|---|---|---|---|---|---|
| D1 | V8 grid 라벨: 해소 6/29 1세션 밀림, 10-12 수익(−0.4405% log) 누락, 미해소 18/19 노출(10-12·11-11) | CAL-01, PH-2, CAL-05 | 5계열 `dropna(how="any")` (봉인 V2 features.py:119), resolver grid 합산 | 중상 | P1 진단 원장, P5 휴장 배지 |
| D2 | h1 12/12 발행 시점 실현, "strictly before" docstring 거짓 | CAL-02, V8-LOC-06 | origin=bundle.dates[-1] + H.10 월 16:15ET + cron 화 03:10Z (봉인 V8) | 중 | P1 post_dated 필드, P3 pseudo-OOS 블록, P5 공시, KNOWN_LIMITS |
| D3 | 해소가 H.10 대기(h1 중앙 7.5일), 표시 성숙 11-12 대 원장 ≥ 11-24 | CAL-03, PH-4 | resolver 5계열 bundle (봉인), 표시는 NYSE 달력 | 하 | P1 `ledger_resolution_eta`, P5 이중 표기 |
| D4 | EWMA 1세션 지연 — 원점일 충격 미반영 (11-05 폭 V8 ×1/1.287, daily6m ×1/1.41~1.47) | V8-LOC-07, D6C-4, CMC-1, CMC-3 | `variance[-1]`=σ²_{T\|T−1} (봉인 V2/V8) | 중 | P2 C1·C3, P4 κ 경고 |
| D5 | λ·block 근소차 argmin(마진 0.11~1.54%) — 표면 간 폭 최대 27% 차 | CMC-2, D6C-7 | CRN 없음·MODEL_ID별 시드·hard argmin (봉인 V2) | 중 | P2 C6, P4 선택 마진 표기 |
| D6 | VIX 휴장일 행 33개로 vix_change 비누적(부호 편향 +0.026, 다음 노출 11-27) | CMC-5, PH-3 | VIX 자체 인덱스 차분 후 reindex (봉인 features.py:112) | 하 | P2 C9 |
| D7 | V8 h21/h63 p_up = 기저율+왜도+B4 상향, 비공시. h1/h5 위치 신호 미검출 | V8-LOC-01, V8-LOC-04, V8-LOC-05 | omega=0·tilt 0·확장 μ̂·B4 정적 맵 (봉인 구성) | 하 | P3 연구 쌍둥이, P5 기저율 라벨 |
| D8 | 라이브 성적 자동 감시 공백(약 2027-05까지) | V8-LOC-02, V8-LOC-03 | 동결 operational_gate 가 h63 26원점 뒤에만 작동 (V8C) | 중 | P3 L1~L4 감시기 |
| D9 | daily6m 132행을 독립 n처럼 표시, 경로 의존·폭 과소·위치 비공시 | D6C-1, D6C-2, D6C-3, D6C-6 | forward_record 원시 n/N 주표기 (비봉인 display.py) | 중 | P4 표시 정직성 |
| D10 | daily6m 대 V8 p_up 모순(h63 평균 −10.5%p) 비공시 | CMC-4, D6C-5 | 위치모형 설계 차이(VARX 조건부 대 FHS 무조건) | 하 | P2 C10(연구 원장 기록만) |
| D11 | V13 판정이 GFC 기후만 사용, 보정 진단 없음, T7 이 단일 에피소드 종속 | V13E-1, V13E-2, V13E-3, V13E-4, V13E-5, V13E-7 | live_forward_gate 설계 (동결 계약) | 중 | P6 읽기 전용 진단, DECISIONS 선공시 |
| D12 | FED_EBP 35일 조용한 정지(10-07부터 ISO 날짜), market.failures 초록 통과 | PH-5 | 봉인 파서 + refresh 가 market.ok 미검사 | 중 | P2 C12, P7 분류, P8 사이드카 |
| D13 | v2-refresh 날짜 경계 거짓 실패(최근 19건 중 6건, 에피소드 2) | PH-1 | prepare/verify 컷오프 정의 불일치 (봉인 pipeline·dfm_cache) | 중 | P7 `pending_date_boundary` |
| D14 | daily6m Nasdaq 403·장중 파싱 실패 오분류 | PH-6 | urllib 지문 차단, strptime 이 marketStatus 판정보다 먼저 (daily6m_sources.py:255, 해시 대상) | 중 | P7 `transport_pending`·`intraday_pending` |
| D15 | 일일 'confirmed'가 달러 캐리 0변화(최대 5세션)를 숨김, confirmed 행 재대체 | CAL-04, CMC-6 | collect_inputs 캐리·input_state 정의 (비봉인 timeseries_v8_daily.py) | 하 | P2 C5, P5 캐리 라벨 |
| D16 | coherence_audit.md "2행" 기재가 현재 6행과 불일치 | (CAL-01·PH-2 근거) | 갱신 누락 | 하 | P0 정정 노트 append(완료) |

**결함이 아닌 정합 확인(5건)**: CAL-06(해시체인·ID 유도·CRPS 29/29 비트 재현 PASS), CMC-7(입력 정합, 장후 시세 센트 단위 차이 1건), CMC-8(σ21/VIX 밴드 26/27, V8 꼬리–V13 수준 Spearman 0.789 n=14 p≈0.04, rv 부등식 위반 0/23, h21/h63 grid 해시 26/26), PH-7(공식값 불일치 0, 주간 hold 6회 187.6h 중 원천 지연 2회는 게이트가 정당하게 막음), V13E-6(V13 라벨·resolved_session 독립 재계산 189/189 일치, p 재현 |Δ| ≤ 5e-7 PASS). 앞의 넷은 감시기 C2·C3·C5·C7·C8 의 설계 근거로, V13E-6 은 P6 진단의 재현 기준으로 쓴다.

**합계**: D1 3 + D2 2 + D3 2 + D4 4 + D5 2 + D6 2 + D7 3 + D8 2 + D9 4 + D10 2 + D11 6 + D12~D14 각 1 + D15 2 = 37 (D16 은 새 발견이 아니라 CAL-01·PH-2 근거의 문서 정정이라 0), 정합 확인 5 → **42**. ID 대조: `workflow_result.json` 의 검증 발견 42건과 누락·중복·추가 없이 일치한다.

## 4. 이번 PR 구현 항목과 위치

| 항목 | 위치 | 해결 | 재현·실행 |
|---|---|---|---|
| P0 사전고정 (완료, `9f731c0c`) | THR, `docs/research/mts_upgrade/coherence_monitor_prereg_20261111.md`, `xnas_label_basis_prereg_20261111.md`, `docs/KNOWN_LIMITS.md` 42~47, `docs/DECISIONS.md`, `coherence_audit.md` 정정 노트 | D16, 해석 조작 방지 | `monitor_thresholds.load_pinned_thresholds` (해시 불일치 → 지표 전부 null) |
| 공유 배선 (완료, `6c10af0e`) | `src/ai_fc/mts_research/cli.py` RESEARCH_TOOLS, `artifacts._IDENTITY_FIELDS`, `data/contracts/ledger_registry.yaml` | — | 원장 4종 identity 등록 |
| P1 XNAS 진단 원장 | `src/ai_fc/mts_research/v8_xnas_labels.py`, `data/mts_research/ledgers/v8_xnas_label_diagnostics.jsonl`, `data/mts_research/derived/v8_xnas_label_summary.json` | D1·D2·D3 | `python -m ai_fc.mts_research.cli v8-xnas-labels [--append]` |
| P2 정합 감시 C1~C12 | `src/ai_fc/mts_research/audits/coherence.py`, `data/mts_research/ledgers/coherence_daily.jsonl` | D4·D5·D6·D10·D12·D15 | `coherence-monitor --as-of YYYY-MM-DD [--append]` |
| P3 V8 라이브 감시 L1~L4 (진행 중 — 이 문서 개정 시점 워크트리에 파일 미존재, 최종 커밋 전 재확인) | `src/ai_fc/mts_research/v8_live_monitor.py`, `data/mts_research/ledgers/v8_live_monitor.jsonl`, `derived/v8_live_monitor.json` | D7·D8 | `v8-live-monitor [--append]` |
| P4 daily6m 표시 정직성 | `src/ai_fc/timeseries_daily6m/display.py`, `dashboard.js`, `data/mts_research/contracts/daily6m_display_constants_v1.json` | D9 | 대시보드 빌드 |
| P5 V8 표시 공시 (진행 중 — 이 문서 개정 시점 변경·상수 파일 미존재, 최종 커밋 전 재확인) | `src/ai_fc/timeseries_v8_display.py`, `timeseries_v8_daily.py`(표시 필드만), `data/mts_research/contracts/v8_display_constants_v1.json` | D2·D3·D7·D15 | 대시보드 빌드 |
| P6 V13 진단·T7 도달가능성 | `src/ai_fc/mts_research/audits/v13_live_diagnostics.py`, `derived/v13_live_diagnostics.json` (원장 쓰기 0) | D11 | `v13-diagnostics` |
| P7 수집 신호 분류기 | `src/ai_fc/mts_research/ingest_triage.py` (워크플로 배선 없음) | D12·D13·D14 | `ingest-triage --report <json> --kind …` |
| P8 FED_EBP 사이드카 | `src/ai_fc/mts_research/fed_ebp_sidecar.py`, `data/mts_research/ledgers/fed_ebp_v1.jsonl` | D12(데이터 복원) | `fed-ebp-sidecar [--append]` |
| DOC 이 보고서 + 후속 계약 초안 | 이 파일, `data/contracts/multivariate_timeseries_v15_coherence.draft.yaml` | U3 사전등록 자리 | — |

공통: 봉인 파일(`timeseries_v8/**`, V2 model·features·dfm_cache·backtest·pipeline·market_archive, `daily6m_sources.py`)
무수정, 공통 규칙의 보호 glob 5종(`.github/workflows/timeseries*.yml`, `tools/*timeseries*`, `tools/*scenario*`, `tools/*v6*`,
`src/tests/test_multivariate_timeseries*.py`) 신규 파일 없음, 워크플로 무수정, 네트워크 접근 없음, 장중 값 미사용, 기본 dry-run.
공시: 계약 초안 `multivariate_timeseries_v15_coherence.draft.yaml` 은 V7 보호 범위 `timeseries_v7/protection.py` GLOB_SPECS 의
`data/contracts/multivariate_timeseries_v[1-6]*`(predecessor_contract)에 걸린다(`v1` + `5…`). v10·v12·v13·v14 계약도 이미 같은 식으로
걸려 있고 `verify_baseline` 은 tmp_path 사본에서만 돌아 현재 깨지는 검사는 없지만, V7 보호 매니페스트를 다시 찍으면 이 파일이 들어간다.
각 항목의 실제 수치·테스트 결과는 해당 커밋과 테스트 파일(`src/tests/test_mts_research_*.py`)이 정본이다.

## 5. 사용자 결정 U1~U7 (이번 PR 미구현)

| ID | 결정 | 기본값(결정 전) |
|---|---|---|
| U1 | 감시 결과를 사이트 배지·일일 배치에 연결 — 표시 진단 계약 `mts_display_diagnostics_v1.yaml` 사전등록 + 새 워크플로(`timeseries*` glob 회피). XNAS 진단 수치 화면 병기도 여기서만 | 연결 없음(`audit_only`, `production_publish_enabled=false`) |
| U2 | 보호 워크플로(`timeseries-v2-refresh.yml` 등)에 P7 분류기 배선, FED_EBP known_stall 정책(첫 24h error → 이후 warning), `daily6m_sources.py:255` 파싱 순서(호환 파일 절차), V8 일일 캐리에서 연방휴일 제외 | 현행 유지. Akamai 지문 위장 우회 금지 |
| U3 | V15 정합성 후속 섀도 개시(A0~A7, 초안 계약) — A2·A6 변형 선택, MDE 산출 뒤 gates.armed. 판정은 지평별 최소 원점(h5·h21 26, h63 39 = 3·ℓ_63) 도달 뒤 가족 1회 | `draft_prereg`, track_open false, armed false |
| U4 | daily6m v2 계약(fresh 분산, 경로별 분산 재귀, 리드별 폭 배율은 설계창 PIT 만, CRN, 드리프트 0 팔) | 미등록. V8 B4·FHS 이식 금지 |
| U5 | V13 후속 변동성 트랙(설계창 반창 교차전이 재보정, 점프 해저드, 국면 기저율 혼합, 독립 에피소드 ≥ 5) | 미등록 |
| U6 | V13 live_verdict 출력 확장, vix25_h21 60원점 강등 적용, V13 카드 점프 caveat | 현행 유지. P0 선공시가 근거 자료 |
| U7 | V8 공식 채점 basis: grid 유지 / XNAS 전환 / 후속 계약 A3 로만 | grid 유지 |

## 6. 하지 않은 것

봉인 코드·docstring 수정, V8 휴장 영향 6행의 supersedes 정정, 게이트·T7·임계 변경, 재학습·재보정·B4 해제,
학습형 보정(ML 게이트 전), probability_space 간 산술 결합, daily6m 132행 독립 표본 보고, W34 소급 발행,
2015~2018 홀드아웃 재개봉, 감시 경보로 재예측 자동 트리거, V14 라이브·자동화 — 모두 하지 않았다.
