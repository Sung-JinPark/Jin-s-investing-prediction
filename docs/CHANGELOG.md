# CHANGELOG — ai-fc 시스템 변경 이력

> 형식: Phase/워크스트림 단위. 출처(검토 라운드·스펙) 명기. dualdb 자체 이력은 dualdb/CHANGELOG.md.

## 회귀 감사 260720 발견사항 처리 (기준선 회차 F-01~F-05 + G-1, 사용자 승인) — 2026-07-20

- **F-01 (정본 판정)**: ^IXIC 1995~2004 종가를 FRED NASDAQCOM으로 승격 (DECISIONS 9-5) — 교차 불일치 3.11%→**0.10%**, `test_dual_source_cross_check` **무수정 PASS 전환** (dualdb **39/39 전부 통과**, skip 0). 파생 재계산 완료 (Pearson 0.9056 불변 — 월말 지표 영향 미미 실증).
- **F-02/G-1 (드라이런 회계)**: dry-run도 `dry:*` stage로 cost_log 기록 (orchestrator) + 7월 누락분 $1.20 백필 → 회계 = 실지출 **$8.08** 일치.
- **F-03**: HARVEST_CALENDAR 12월에 mu-margin-qoq-fq1fy27 조건부 행 (9/29 후 확정).
- **F-04**: KNOWN_LIMITS #16·#28 FRED 복구 반영, #32 해소 처리 (잔여 한계 정직 병기).
- **F-05**: 수동 base_rates 4종 갱신은 계획대로 해당 질문 r1 리서치 부산물로 (7/28 AMD부터 — 별도 지출 없음).

## v3.5 공개 신뢰(Trust) 미니 라운드 — 2026-07-20 (스펙 aifc_v35_trust_planmode_260720 v1.0)

**WS-T1 제3자 검증기** `tools/verify_track_record.py` (stdlib+git only — pip install 0):
- 해시 앵커 대조 · git 불변성(수정/삭제 이벤트 0 + 원장 prefix-확장) · 시점 불변식 · Brier 독립 재계산.
- **증명 2등급 정직 구분**: A급(baseline 이후 커밋 — 리모트 시계) / B급(baseline 포함 — 자기증명). 현행 [A 0 / B 21] PASS. 경계 = 공개 루트 커밋(스펙의 9a8dbae는 이력 스쿼시로 부재 — D1).
- 조작 시뮬 3종(파일 변조·원장 행 삭제·마감 후 커밋) 전부 FAIL 검출 — test_verifier 5케이스 고정.

**WS-T2 CI**: `.github/workflows/verify.yml` — src pytest + sync --check + 검증기 (시크릿 0, fetch-depth 0). README 배지.

**WS-T3 즉시 푸시 규율**: P1_OPERATIONS·HARVEST_CALENDAR·post-FOMC 태스크 — "기록 직후 커밋+푸시 = 등급 A 성립 조건" (7/30부터). **OTS 실행(사용자 결정 9-4)**: 로컬 이중 차단(AppControl·OpenSSL3)으로 **CI 스탬프 봇**(ots-stamp.yml)이 .hashes 변경마다 비트코인 앵커 후 .ots 커밋백.

**WS-T4 README**: "제3자 검증 방법" 섹션 — 3단계 안내 + 등급 한계 그대로 명시 (과장 금지).

**WS-T5 FRED 복구 (사용자 승인)**: net.py **3단 폴백**(python→curl 기본 UA→공개DNS nslookup+`--resolve`) — 정밀 진단: 로컬 리졸버의 간헐 DNS 차단 + 서버측 파이썬 읽기 차단 2층 구조 (NETWORK_RECOVERY 2차 기록). **13시리즈 전 이력 ~99,000행 수집 성공** — 이중 소스 교차검증 재가동 (KNOWN_LIMITS 11 부분 상환).
- 재가동 즉시 실측 발견: Yahoo↔FRED 2003~04 구간 3.11% 불일치 (벤더 원천 차이, 재수집 불변) — 센티널 교차검증 테스트는 §10.4대로 무수정 FAIL 유지, **정본 판정 사용자 결정 대기** (KNOWN_LIMITS 32).

## v3 수확 라운드 (2026-07-21 → 12-31) — 스펙 aifc_v3_harvest_planmode_260720 v1.0

### P-Op0 즉시 조치 — 2026-07-20

**WS-B 경량(lite) 티어** (예산 해방 — 헌법 준수: 2에이전트+데블스 불변, 검색량·분량만):
- registry `tier: standard|lite` (관대한 리더 — 미지정/오타는 standard) → run_research가 lite 시 검색 상한 8→4(`research_call` per-call 파라미터)·분량 900→450(`get_profile` 치환, 임무 텍스트 불변).
- frontmatter/DB `pipeline_tier` 기록 — 티어별 Brier 분해 대비 (lite−standard > +0.05면 폐지 판정, 표본 10+).
- 지정: 시리즈 E/M 20문 lite (팩토리 13 + 충전 7) · EXIT 직결 6문 standard 명시 (fomc×2·corr10·soxx·vix·mu).
- D5: fomc-2026-10-28-hike schedule D-14 일 1회 → **주 3회** 완화 ($20 체제 정합).

**WS-D 판정 이중화** (Yahoo 단일 의존 — 7/14 일봉 철회 실사례 대응):
- `DraftVerdict.secondary_check_needed=True` 상수 + `--draft` 출력 경고 · resolve SKILL 개정: 가격형 판정 2차 출처(WSJ/Nasdaq/거래소) 필수, 불일치 시 보류·기록 — 7/29 FOMC부터 적용.
- `docs/NETWORK_RECOVERY.md` 신설 + 1회 실행: **FRED가 curl로는 200 OK, 파이썬 urllib은 행업** — 네트워크 차단이 아니라 파이썬 클라이언트 시그니처 표적 봇 필터로 진단 정정. 수집 경로 개선은 8월 WS-F 슬롯 제안 (사용자 승인 대기).

**WS-C P2 도달 플랜**:
- 충전 질문 7 등록 (질문 38, active 35): nfp-oct·cpi-oct·nvda-nov·nfp-nov·fomc-12-09·gdp-q3adv·santa-week — 날짜 전건 공식 확정(OMB PFEI PDF 직접 판독·Fed 캘린더, NVDA만 추정+재확인 표기), 전건 필터 마커+lite.
- `docs/P2_DECISION_FRAME.md` — K=3 결정 트리·비용 사전 계산, **결정 권한 사용자** (즉흥 결정 방지).

**WS-A 수확 캘린더**: `questions/HARVEST_CALENDAR.md` — 주차별 [해소|r1 마감 D-7|재예측 트리아지|비용], 월별 ≤$20 시뮬 (10월 $18 집중 — TSMC/ASML 선행 분산). 주간 태스크에 캘린더 갱신 스텝 추가.

**WS-E 회고 리추얼**: `forecasts/2026/retro/` 신설 (가변 노트 — **sync 제외 처리** D1: iter_forecast_files retro 제외, 미처리 시 파싱 오류) + 5줄 TEMPLATE (**포지션 언급 금지** — 공개 리포 규율) + post-FOMC 태스크에 벤치마크 확인·첫 회고 스텝.

**테스트**: test_lite_tier 5케이스 신규 — 전체 161+1s 통과. WS-F 4건은 8월 슬롯 (섀도 표시는 v2 기완료 — D2 종결).

## 구조 개편 + HF 생태계 리서치 — 2026-07-20 (v2 라운드 후속)

**구조 개편** (업계/HF 벤치마킹 리서치 기반 — "결핍은 배치가 아니라 선언 파일 부재", 이동 0건):
- 루트 `pyproject.toml` (uv_build·`ai-fc` 스크립트·uv 워크스페이스) + `dualdb/pyproject.toml` — `cd src && python -m ai_fc` 경로와 병존. **휠 배포 금지** (config.py `__file__` 루트 앵커).
- `.gitattributes` — 라인엔딩 표준화. **불변 경로(forecasts/·calibration/·ml_history/)는 `-text` 예외**: 신규 클론에서 autocrlf가 해시 앵커(E1 오탐)를 깨는 것을 차단. `git add --renormalize` 의도적 미실행.
- 루트 `conftest.py` + pyproject testpaths → **루트 단일 `python -m pytest`로 전체 스위트(156+1s)** 실행.
- `data/README.md` (CCDS 계층 대응표) · `docs/models/` HF 스타일 모델 카드 4종(frontmatter — 라이선스·게이트 감사 기계화 기반) · README 갱신.
- uv.lock 보류 (uv 미설치 확인 — 설치 시 `uv lock` 1회로 완성).

**HF 심층 리서치** (4트랙 병렬, 정본: `reports/research/hf_landscape_260720.md`):
- 시계열: 현 스택 전부 Chronos 혈통 → TiRex-2·TimesFM-2.5·Sundial 이질 앙상블 권고 (전부 Apache).
- 금융 NLP: 토픽 라우터 + FOMC-RoBERTa 1순위, ModernFinBERT 조건부 교체(A/B 후).
- 물류: HF 생산급 모델 부재 — 방법론(간헐 수요·계층 조정)만 이식 가치.
- 평가: scoringrules(ECE·log score)·fev 부트스트랩 skill score·ForecastBench 외부 base rate.
- **도입 실행은 전부 별도 지시 대기** (§6 다음 단계 6건 — 비용·게이트 순종).

**예산**: 월 상한 $100 → **$20** (사용자 결정) — FACTORY_GUIDE 트리아지 4단계 규율.

## v2 고도화 라운드 (2026-07-20~) — 검토패키지 260720 응답 (스펙 aifc_v2_upgrade_planmode_260720 v1.0)

### P-A: 표본·증명 (WS1 + WS2) — 2026-07-20

**WS1 질문 팩토리** (게이트 병목 = 표본 속도 직격):
- `questions/FACTORY_GUIDE.md` 신설 — 등록 필터 (a) base rate/시장내재 [35,65] 밖 또는 (b) 정보 우위 논거. 코인플립성 질문의 Brier 오염 차단.
- 필터 코드 집행: `registry.factory_filter_violation` (created ≥ 2026-07-21 대상, grandfather) — forecast 프리플라이트 오류 + sync W2 경고.
- schedule 세그먼트 `{from: D-N, once: true}` 지원 — "r1 + D-3 재예측 1회" cadence (registry.py, 스펙 대비 차이 D6).
- 신규 질문 13개 등록 (active 15 → 28): 실적 beat 시리즈 11 (AMD 8/4 확정 · AVGO·ORCL·ADBE·ASML·TSMC·MSFT·GOOGL·META·AMZN·AAPL — 추정일은 notes에 D-30 재확인 표기) + 지표 시리즈 2 (cpi-jul2026-reaccel 8/12 · nfp-aug2026-below100k 9/4, OMB 일정 확정). 발표일·beat 이력 출처: 실적 캘린더 리서치 2026-07-20.
- 기계 판정 초안: `resolver.machine_check`/`draft_verdicts` + `resolve --draft` — 가격 임계형(QUESTION_MAPS) 질문의 outcome 초안·증빙 출력. **원장 무기록 — 확정은 사람** (헌법 §2-4 준수).

**WS2 벤치마크 3자 원장** (edge 증명 전제 배관):
- `calibration/benchmark_ledger.csv` 신설 (append-only, 기존 원장 무접촉) — 해소 시 LLM/ML앙상블/시장내재 병행 채점.
- 룩어헤드 차단: ML 참조는 예측 시점 **이전** 최신만 (`resolver._ml_ref_before`), 부재는 NULL (소급 조회 금지).
- sync 드리프트 검사 **E7** (벤치마크 원장 축소·변조 — E4·E5는 기존 override 검사가 선점, 스펙 대비 차이 D1).
- DB: `benchmark_scores`·`benchmark_lines` 테이블 + `v_benchmark_pairwise` 뷰 (쌍대 표본만 집계 — 불공정 비교 차단). 리포트에 3자 비교 섹션.
- 기해소 2건 소급: spx-up/soxx-up — ml/market 당시 기록 부재로 전부 NULL (정직 기록, notes에 backfill 명기).

**테스트**: test_ws1_factory.py (6) + test_ws2_benchmark.py (4) 신규, 전체 99 통과.
기존 테스트 수정 1건 보고: test_sprint2 픽스처 질문(created 2099)에 등록필터 마커 추가 — WS1 신규 규약이 컷오프 이후 질문에 근거 기재를 강제하므로 픽스처도 준수 (동작 변경 아님).

### P-B: 정확성 (WS3 + WS4 + WS5) — 2026-07-20

**WS3 경로 터치 이산화 보정 (T-11 상환)** — 결정론 수식, 파라미터 학습 0 (ML 게이트 비저촉):
- GBM: 경로 질문 시리즈에 **일간 스텝 시뮬** 추가 (52주 일간 수익률 재추정, `gbm_daily` — 근본 해결). 일간 수집 실패 시 주간 폴백 fail-soft.
- Chronos-T5 (주간 고정): **브라운 브리지 보정** `chronos_fc.bridge_touch_prob` — 미터치 인접 쌍마다 p=exp(−2·d₀·d₁/σ_w²) (log 공간), 경로 확률 = 1−Π(1−pᵢ), 기터치=1. σ_w는 경로 내 증분 std(ddof=0) 근사 (KNOWN_LIMITS 신규 항).
- ml_auto.md에 **raw 주간/보정 병기** + 방법 1줄. ml_history 기록값·divergence 판정 기준 = **보정값** (DECISIONS 기록 예정 — P-D).
- 성질 고정: 보정 ≥ raw 단조성 테스트.

**WS4 다이제스트 재현성 스냅샷** (검토질문 #8 응답):
- frontmatter 신규 `digest_hash`(주입 원문 sha256)·`digest_inputs`(ml run_ts·market 출처 좌표).
- 다이제스트 원문 **전문을 evidence 말미에 첨부** (현행 미첨부 실측 확인 후 추가) — "그때 무엇을 보고 판단했나" 불변 완결.
- `base_rates.ml_digest_with_meta` 신설 (기존 ml_digest는 호환 래퍼).

**WS5 쓰기 원자성 교정** (PART F-7 응답):
- 쓰기 순서 **evidence → 본문**으로 교정 (`orchestrator._write_records`) — 본문 = 커밋 포인트, 크래시 잔재는 무해한 고아 evidence 방향.
- sync 검사 **E6**: 본문 없는 evidence 경고 (자동 삭제 금지). ※ 스펙의 "E4" 명명은 기존 override 검사(E4·E5)와 충돌해 E6 채택 (차이 D1).

**테스트**: test_ws3_bridge (4) + test_ws4_digest (2) + test_ws5_atomicity (2) 신규, 전체 107 통과.

### P-C: 품질·증명 인프라 (WS6 + WS7 + WS8 + WS9) — 2026-07-20

**WS6 divergence 정당화의 스키마 승격** (검토질문 #2 응답):
- frontmatter 신규 3필드: `ml_divergence_pp`(기록 시점 |rN−ML| — orchestrator가 산출)·`divergence_note`·`divergence_class`(enum 4종: event_conditionality/regime_view/model_limit/other). 기존 `divergence` 필드(앙상블 산포)는 의미 무변경 (차이 D2).
- validate 강제: pp ≥ 15%p인데 note/class 없으면 **기록 거부**.
- 정당화 생성: 확률 확정 **후** 사후 리뷰 콜(`_divergence_review` — 소형 structured call). 앵커링 방지 유지: ML 값은 확률 확정 전 LLM에 미노출, 리뷰는 기록용 설명이며 확률 수정 채널 아님.
- due divergence 표시에 직전 회차 class 병기.

**WS7 리서치 품질 스코어** (PART F-5 응답):
- `source_tiers.yaml`(T1 공시·1차/T2 IB·데이터/T3 언론/T4 블로그) + `quality.py` — 본문 `[source: URL]` 정규식 추출(D4), 미등재 도메인은 unknown으로 분모 포함(보수).
- frontmatter `research_quality`{등급 분포·primary_ratio} + evidence 헤더 자동 기입.
- research_status 세분: `ok_low_primary`(primary_ratio < 0.3) — **표시·분석용만, v_brier_primary 정의 무변경** (게이트 조작 금지, 테스트로 고정).

**WS8 캘리브레이션 과학 인프라** (검토질문 #3 응답 + 백로그 선행):
- queries: Murphy 분해(REL−RES+UNC, 도메인별)·rolling Brier(윈도우 10)·n_excluded·섀도 가상 Brier.
- report: 신뢰도 다이어그램(표본 5 미만 정직 명시)·Murphy 표·**대표 Brier에 "제외 m건: failed" 상시 병기**·rolling·섀도 vs 공식 병기 — 전부 표시 계층, 게이트 산정식 무접촉.
- DB additive: forecasts에 shadow_extremized·ml_divergence_pp·divergence_class 컬럼 (ALTER 가드, 구파일 NULL — D7).

**WS9 드라이버 일관성 리포트** (백로그 ⑥ 활성):
- report에 드라이버 그룹별 최신 확률 표 + "점검 후보" 하이라이트(그룹 내 max≥60 AND min≤40 휴리스틱 — **자동 판정 없음, 판단은 사람**). calibration-report 스킬 문서 갱신.

**테스트**: test_ws6 (4) + test_ws7 (4) + test_ws8 (3) 신규 — src 118 + dualdb 38 전체 통과.

### P-D: 문서화 + 완주 검증 — 2026-07-20

- DECISIONS 9-1(WS3 결정론 보정 = ML 게이트 비저촉)·9-2(divergence 기준 = 보정값)·9-3(등록 필터 규약) 기록.
- KNOWN_LIMITS: 3번 T-11 **상환** 표기 + 신규 한계 3건 정직 추가 (29 σ_w 근사 · 30 벤치마크 쌍대 극소 · 31 등급 사전 수동 큐레이션). MODEL_REGISTRY: T5 브리지·GBM 일간화 갱신.
- 검토 응답 매핑표 작성 (검토질문 → 워크스트림 → 구현 지점 — 내부 아카이브 보존).
- WS7 보강 1건: 스킬 경로 evidence의 스킴 없는 인용(`[source: cnbc.com/...]`) 추출 지원 — 실측 재파싱: nfp r1 primary 55% · corr10 r2 28% · soxx r2 17%.
- **완주 검증 실측**: `ai_fc ml` 실행 — 보정 반영 확인. raw→보정 변화폭: F1 t5 60→68%/gbm 75→80% (앙상블 74%) · F2 t5 47→52%/gbm 36→39% (앙상블 39→45%) · VIX25 t5 1→4%/gbm 42→51% (앙상블 27%). **corr10 divergence 18%p → 12%p로 축소 — 플래그 해소** (T-11이 divergence의 구조적 원인이었다는 스펙 §1 진단 실증). `sync --check` exit 0 · report(WS8/WS9 섹션) 생성 · src 118 + dualdb 38 통과.
