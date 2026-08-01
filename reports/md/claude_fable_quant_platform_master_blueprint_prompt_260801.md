# Claude Fable용 마스터 프롬프트 — Quant Intelligence Platform Grand Blueprint

이 파일 전체가 Claude Fable에게 전달할 작업 지시다. 요약하거나 일부만 발췌하지 말고
저장소 루트에서 그대로 실행한다.

---

## 역할

당신은 다음 다섯 역할을 동시에 수행하는 principal급 설계자다.

1. 금융시장 데이터 아키텍트
2. 확률 예측·시계열 계량 연구자
3. ML 평가·MLOps 책임자
4. 제품 정보설계·UI/UX 디자인 리드
5. 감사 가능성과 모델 리스크를 책임지는 독립 검증자

당신의 임무는 코드를 작성하는 것이 아니다. 현재 저장소를 정밀 감사하고 최신 공식 자료를
광범위하게 조사해, 이후 Codex가 작은 단위로 구현할 수 있는 **하나의 대형 설계서**를 만드는
것이다.

최종 산출 경로:

`reports/md/claude_fable_quant_platform_grand_blueprint_260801.md`

이 경로 외 파일을 수정·생성·삭제하지 않는다. Git commit·push도 하지 않는다.

---

## 최종 목표

Jin's Investing Prediction을 다음 상태로 발전시키는 실행 가능한 grand blueprint를 작성한다.

- 더 넓고 신뢰 가능한 데이터 레이어
- point-in-time·빈티지·lineage가 보장되는 데이터 구조
- 단순 기준선부터 엄격히 경쟁하는 시계열·확률 모델 체계
- 독립 표본과 proper scoring rule을 사용하는 평가·캘리브레이션 체계
- 시장 전망 변화가 왜 바뀌었는지 수치와 근거로 추적 가능한 의사결정 화면
- 최신 startup/product 수준의 세련된 UI·UX와 의미 있는 동적 상호작용
- static GitHub Pages 제약 안에서도 빠르고 접근 가능한 부가기능
- 자동 갱신·장애 복구·비용·보안·감사까지 포함한 운영 설계

“모델을 더 많이 넣는다”가 목표가 아니다. out-of-sample 정합성을 실제로 높일 가능성이 있는
최소 모델 집합과, 그 개선을 정직하게 판정할 검증 체계를 설계해야 한다.

---

## 필수 입력 — 순서대로 전부 읽기

### 1단계: 현재 상태 인수인계

1. `reports/md/codex_to_claude_fable_workspace_handoff_260801.md`
2. 루트 `CLAUDE.md`
3. 루트 `README.md`

### 2단계: 정본 운영·결정 문서

4. `docs/ARCHITECTURE.md`
5. `docs/DB_MAP.md`
6. `docs/KNOWN_LIMITS.md`
7. `docs/MODEL_REGISTRY.md`
8. `docs/DECISIONS.md`
9. `docs/P1_OPERATIONS.md`
10. `data/README.md`

### 3단계: 실제 스키마·파이프라인

11. `pyproject.toml`
12. `.github/workflows/*.yml`
13. `src/ai_fc/db/schema.sql`
14. `dualdb/schema.sql`
15. `src/ai_fc/config.py`
16. `src/ai_fc/cli.py`
17. `src/ai_fc/db/ingest.py`
18. `src/ai_fc/db/queries.py`
19. `src/ai_fc/orchestrator.py`
20. `src/ai_fc/reasoning_core.py`
21. `src/ai_fc/scenario.py`
22. `src/ai_fc/quant/`
23. `src/ai_fc/ml/`
24. `src/ai_fc/market/`
25. `dualdb/dualdb/ingest/`
26. `dualdb/dualdb/derive/`
27. `dualdb/dualdb/models/`
28. `dualdb/dualdb/export/context_bridge.py`

### 4단계: UI·read-model

29. `src/ai_fc/dashboard.py`
30. `src/ai_fc/dashboard_template.html`
31. `src/ai_fc/dashboard_parts/dashboard.css`
32. `src/ai_fc/dashboard_parts/dashboard.js`
33. `src/tests/test_dashboard.py`
34. `reports/md/codex_dashboard_scenario_change_intelligence_v7_blueprint_260801.md`
35. `reports/md/codex_dashboard_research_intelligence_v6_blueprint_260731.md`
36. `reports/md/codex_dashboard_decision_ergonomics_v5_blueprint_260731.md`
37. `reports/md/codex_dashboard_masterplan_v4_wide_scope_260731.md`
38. `reports/md/claude_to_codex_design_blueprint_260731.md`

### 5단계: 실제 산출·원장

39. `questions/registry.yaml`
40. `calibration/ledger.csv`
41. `calibration/benchmark_ledger.csv`
42. `data/ml_history/2026.jsonl`
43. `data/scenarios/nasdaq_latest.json`
44. `data/scenarios/archive/*.json`
45. `data/base_rates/*.md`
46. `dualdb/config.yaml`
47. `dualdb/data/seeds/*.csv`

모든 파일을 무작정 전문 복사하지 말고 필요한 사실을 추출하되, 선택한 instruction/정본 파일은
끝까지 읽는다. 문서 서술과 코드·실측이 충돌하면 반드시 충돌표를 만들고 판정 근거를 적는다.

---

## 라이브·Git 상태 확인

다음을 직접 확인한다.

- 라이브 URL: https://sung-jinpark.github.io/Jin-s-investing-prediction/
- GitHub: https://github.com/Sung-JinPark/Jin-s-investing-prediction
- 현재 `HEAD`, `origin/main`, live Pages의 시나리오 기준일
- 현재 브랜치와 다른 브랜치에만 존재하는 예측 기록
- Git에서 제외된 SQLite가 현재 branch source와 일치하는지

브라우저로 desktop·mobile을 직접 관찰하고 다음을 기록한다.

- 첫 5초에 읽히는 핵심 판단
- visual hierarchy와 정보 밀도
- hover·scroll·keyboard·mobile interaction
- motion이 정보를 설명하는지 장식인지
- 작은 글자·낮은 contrast·hit target·overflow
- 로딩·empty·stale·error 상태 표현
- 메뉴가 늘어날 때의 확장 한계

라이브와 로컬 소스가 다르면 둘을 섞어 서술하지 말고 각각의 commit/as-of를 적는다.

---

## 조사 규율

### 최신성

- 시장·제품·API·라이브러리·가격·라이선스는 2026-08-01 현재를 웹에서 재검증한다.
- 모든 변동 가능 사실에 `as of`와 직접 링크를 붙인다.
- 검색 결과 요약이 아니라 공식 문서·원 논문·공식 GitHub·규제기관·거래소를 우선한다.
- 사실, 출처가 지지하는 추론, 제안을 명시적으로 분리한다.

### 금융 데이터

- 동일 데이터라도 공식성, 지연, revision, point-in-time history, 라이선스, 비용, API 안정성이
  다르므로 “무료로 가져올 수 있다”만으로 채택하지 않는다.
- Yahoo 등 편의 소스는 fallback으로 평가하고 정본 후보와 교차검증 설계를 제시한다.
- 유료 소스는 무료 대안과 함께 비용 대비 개선 가능성을 제시한다.
- GitHub Pages에서 데이터를 재배포할 권리와 raw 저장 권리를 구분한다.

### 연구 방법

- 금융 시계열 기술 질문은 원 논문·공식 구현을 사용한다.
- 논문 벤치마크 성능을 이 저장소의 성능으로 전이하지 않는다.
- foundation model은 멋져 보인다는 이유로 채택하지 않는다. zero-shot baseline으로
  동일한 walk-forward 평가를 통과해야 한다.
- 작은 표본에서 통계적 유의성을 과장하지 않는다.

### 디자인

- 색상만 바꾸는 리스킨은 금지한다.
- 정보 구조, 공간 리듬, type scale, component hierarchy, motion behavior, state design까지 조사한다.
- 현재 Mistral-light/warm-neutral 방향을 존중하고 전체 테마 교체가 아닌 진화형 개선을 설계한다.
- Linear, Vercel, Mistral, Mercury, Koyfin, TradingView, Perplexity Finance 등은 형태를
  복제하지 말고 문제 해결 원리를 추출한다.

---

## 반드시 해결할 선결 결함

설계서의 Phase 0은 다음 문제를 코드·스키마·마이그레이션·테스트 수준으로 해결해야 한다.

### A. 브랜치/파생 DB 오염

- 현재 branch의 예측 본문보다 `db/index.db` forecast row가 7개 많다.
- 현재 branch JSONL의 market 최신은 7/19인데 DB는 7/28 레코드를 보유한다.
- `dualdb.sqlite`의 entity/event/era가 seed/config보다 뒤처져 있다.

설계 요구:

- source manifest와 HEAD/worktree fingerprint
- incremental sync 허용 조건
- staging→validate→atomic swap rebuild
- 삭제/축소/branch switch 의미
- read consumer fail-closed 기준
- CI에서 clean checkout rebuild와 cardinality 대조
- DB inventory 자동 생성 문서

### B. 확률 단위 오류

- `benchmark_ledger.csv`의 market probability 22.0/5.0과 Brier 484/25는 유효 범위를 벗어난다.

설계 요구:

- canonical `[0,1]` probability type
- source raw unit과 normalized unit 분리
- check constraints·typed schema·property test
- append-only 원장을 보존하는 correction ledger/migration view
- 모든 scoring output의 범위 불변식

### C. 표본 독립성

- 같은 FOMC 결과의 r1~r4가 게이트 표본을 네 번 늘린다.

설계 요구:

- forecast round, question, resolution event cluster 분리
- 모든 회차 점수와 gate 대표 점수 동시 보존
- effective sample size와 clustered uncertainty
- 고유 이벤트·기간·도메인 커버 기준
- 같은 outcome 반복으로 게이트를 통과하지 못하는 테스트

### D. point-in-time 누출

- 최종 수정 거시값을 과거에 알았던 값처럼 사용하는 위험이 있다.

설계 요구:

- observation time, available time, retrieved time, vintage interval
- release calendar와 market session/timezone
- ALFRED/BLS/BEA/SEC revision·accepted timestamp 처리
- as-of query semantics
- leakage sentinel dataset/test

이 네 문제가 해결되기 전 champion model·자동 edge·실보정 활성화를 제안하지 않는다.

---

## 필수 시장·DB 조사 범위

최소한 다음 source family를 조사하고 비교표를 작성한다.

### 가격·거래·변동성

- Nasdaq/공식 exchange data와 Data Link
- CBOE VIX·VVIX·term structure·options
- Yahoo fallback
- Treasury yield curve
- New York Fed SOFR·EFFR·repo volume
- FINRA margin/short interest 가능 범위
- CFTC Commitments of Traders

### 거시·유동성

- FRED와 ALFRED real-time period
- BLS API
- BEA API
- Federal Reserve releases
- Treasury
- New York Fed

### 기업·반도체·실적

- SEC EDGAR submissions/companyfacts/frames
- 10-K, 10-Q, 8-K, 20-F와 accepted time
- 기업 IR·공식 earnings release
- capex, inventory, gross margin, data-center revenue, foundry/equipment 지표
- ticker/CIK/entity 변경 이력

### 시장 기대·포지셔닝

- 옵션 risk-neutral distribution
- prediction market의 유동성·스프레드·settlement contract
- analyst consensus는 라이선스·비용·revision을 포함해 별도 평가
- ETF flow·breadth·concentration의 공식/유료 원천

각 source row에 다음 열을 포함한다.

`source_id`, `provider`, `dataset`, `official_tier`, `frequency`, `event_time`,
`publication_latency`, `revision_policy`, `vintage_available`, `history_start`, `coverage`,
`api_auth`, `rate_limit`, `license`, `raw_retention`, `public_redistribution`, `cost`,
`failure_modes`, `fallback`, `quality_checks`, `recommended_status`, `reason`.

최종적으로 `adopt now`, `shadow`, `manual`, `defer`, `reject` 중 하나를 판정한다.

---

## 필수 데이터 아키텍처 설계

다음 네 옵션을 ADR 형식으로 비교하고 하나를 권고한다.

1. 현재 SQLite-only 개선
2. SQLite + DuckDB
3. SQLite + partitioned Parquet + DuckDB
4. 서버형 PostgreSQL/warehouse

평가 기준:

- 현재 0.6M 안팎 시계열 규모와 향후 10배 성장
- 단일 writer·정적 Pages·Git 감사 모델
- point-in-time query와 walk-forward scan
- branch/worktree 안전성
- Windows·GitHub Actions 이식성
- dependency·운영 복잡도
- raw 보존·schema evolution·backfill
- 다중 프로세스 쓰기 제약
- 비용·복구·테스트

권고안에는 최소 다음이 포함되어야 한다.

- 디렉터리 구조
- 테이블·파일 naming convention
- source registry와 data contract
- bitemporal fact schema
- raw manifest와 content hash
- dataset snapshot/feature snapshot manifest
- schema version/migration
- partition key·file size·compression
- idempotency key
- quality status와 quarantine
- lineage graph
- retention/compaction
- disaster recovery
- branch-aware rebuild

SQLite와 DuckDB/Parquet를 병용한다면 어느 데이터가 어디에 속하는지 한 행씩 결정한다.

---

## 필수 수학·ML 연구 범위

모든 후보를 구현하라는 뜻이 아니다. 데이터 요구량과 검증 가능성을 비교해 최소 집합을
선정해야 한다.

### 1. 기준선

- random walk / drift
- historical unconditional base rate
- seasonal base rate
- empirical historical simulation
- stationary/moving block bootstrap
- 현재 GBM

기준선을 이기지 못하는 복잡한 모델은 채택하지 않는다.

### 2. 변동성·경로

- EWMA
- ARCH/GARCH
- EGARCH 또는 GJR-GARCH
- HAR-RV: intraday realized volatility 확보 가능할 때만
- stochastic volatility 또는 jump diffusion의 실익
- EVT peaks-over-threshold와 tail probability
- regime-conditioned bootstrap
- Hamilton Markov switching/HMM

### 3. 분포·옵션

- Breeden–Litzenberger risk-neutral density
- volatility smile/surface smoothing과 no-arbitrage constraints
- risk-neutral→physical measure 보정의 가능/불가능 경계
- barrier/path-touch probability와 discrete monitoring bias
- copula 또는 multivariate factor scenario의 필요성

### 4. foundation model

- 현재 Chronos-Bolt/Chronos-2/T5
- 최신 Amazon Chronos 계열
- Google TimesFM 최신 공개 버전
- covariate support, context length, quantile output, CPU/GPU 비용
- training-corpus leakage 가능성과 finance domain mismatch
- zero-shot shadow baseline으로서의 역할

### 5. 이벤트 확률 모델

- base-rate + evidence Bayes/log-odds update
- hierarchical Bayesian partial pooling
- dynamic logistic pooling 또는 Bayesian model averaging
- time-to-event survival/hazard model
- repeated forecast trajectory scoring
- domain/question difficulty adjustment
- logical constraints: subset, monotonic threshold, mutually exclusive/exhaustive sum
- constrained optimization/isotonic reconciliation

### 6. 불확실성

- bootstrap interval
- Bayesian posterior predictive interval
- adaptive conformal inference
- quantile calibration와 quantile crossing 방지
- distribution shift 시 coverage 모니터링

각 후보마다 다음 템플릿을 채운다.

| 항목 | 내용 |
|---|---|
| 목표 변수 | 무엇을 예측하는가 |
| 확률 공간 | physical/risk-neutral/event/terminal/path |
| 데이터 최소량 | 필요한 history·frequency·independent events |
| point-in-time 요구 | 누출 방지 방식 |
| 기준선 | 무엇과 비교하는가 |
| 평가 | loss·coverage·walk-forward |
| 계산비용 | 로컬/CI 가능성 |
| 실패 조건 | 기각 기준 |
| 현 프로젝트 지위 | adopt/shadow/defer/reject |

---

## 필수 평가·캘리브레이션 설계

### event probability

- Brier score
- log score
- Murphy reliability/resolution/uncertainty decomposition
- calibration/reliability curve와 불확실성 band
- sharpness
- baseline skill score
- repeated-round trajectory metric
- unique event clustered score

### price/distribution forecast

- MAE/RMSE는 보조
- pinball loss
- CRPS
- interval coverage와 interval width
- PIT/rank histogram
- tail exceedance calibration
- direction·barrier score는 사전 정의된 경우만

### validation protocol

- expanding-window walk-forward
- rolling-window sensitivity
- purge/embargo가 필요한 label overlap 정의
- 모든 scaler·feature·threshold를 train window 안에서만 fit
- release/vintage availability cut
- frozen dataset manifest
- minimum evaluation horizon과 regime coverage
- naïve baseline 대비 성능
- Diebold–Mariano는 표본이 충분할 때만
- multiple testing/selection bias 통제
- champion/challenger 승격·강등·rollback 기준

`한 번의 backtest 수익률` 또는 `한 기간 RMSE`로 채택하지 않는다. 평가 결과의
confidence interval과 표본 한계를 함께 설계한다.

### 게이트 재설계

현재 P2/P3를 무단 변경하지 말고, 다음을 병기하는 개선안을 제안한다.

- forecast row 수
- unique resolution event 수
- effective sample size
- 최소 도메인/기간/regime cover
- primary vs all
- model별 paired sample
- 데이터 품질 pass 비율
- calibration uncertainty

기존 게이트와 새 proposed gate의 호환·migration·사용자 승인 지점을 명시한다.

---

## 필수 모델 운영 설계

다음을 machine-readable하게 만드는 방안을 설계한다.

- model ID/version
- code commit
- dataset snapshot
- feature schema
- hyperparameters/seed
- train/eval windows
- dependency/runtime
- artifact hash
- scores by horizon/domain/regime
- limitations
- lifecycle: baseline/candidate/shadow/champion/demoted/retired
- owner·approval·created_at

모델 run, forecast artifact, UI read-model 사이 lineage를 Mermaid로 그린다.

### ensemble 규칙

- 현재 고정 중앙값을 baseline으로 보존한다.
- 학습 가중은 200+ 게이트 전 활성화하지 않는다.
- gate 전에는 동일가중·median·trimmed mean·log-odds pool을 shadow 비교할 수 있다.
- 서로 다른 확률 공간을 결합하지 않는다.
- 모델 상관·중복·regime dependency를 평가한다.
- ensemble이 개별 최선 모델보다 나쁘면 자동 기각한다.

---

## 필수 자동화·운영 설계

다음 job graph를 설계한다.

1. source discovery/calendar
2. fetch raw
3. validate/quarantine
4. normalize/vintage
5. derive features
6. snapshot dataset
7. run baselines
8. run shadow candidates
9. evaluate/compare
10. generate scenario/read-model
11. build/test Pages
12. commit/publish
13. freshness/incident report

각 job에 다음을 적는다.

- trigger/cadence/timezone
- dependency
- idempotency key
- timeout/retry/backoff
- rate/cost budget
- output/manifest
- stale threshold
- fail-soft/fail-closed
- backfill policy
- commit policy
- alert severity
- rollback/recovery

자동으로 LLM forecast를 대량 실행하거나 resolve 원장을 확정하지 않는다. 비용이 발생하는 예측과
최종 해소는 인간 승인 경계를 유지한다.

---

## 필수 UI/UX grand blueprint

### 제품 원칙

- 첫 화면은 “지금 무엇이 바뀌었고 무엇을 확인해야 하는가”에 답한다.
- 모델 복잡도를 뽐내지 말고 판단 순서를 돕는다.
- 숫자, 단위, 기준일, 비교 시점, 확률 공간, fresh/stale를 같은 시각 언어로 표현한다.
- 원인 추정과 관측 사실을 구분한다.
- 기능이 늘어도 주 메뉴는 5~6개를 넘기지 않고 progressive disclosure를 사용한다.

### 벤치마크할 제품

최소 다음을 실제로 보고 원리를 추출한다.

- Mistral AI / Le Chat: 밝은 neutral, editorial scale, expressive motion
- Linear 2026: 차분한 chrome, hierarchy, consistent headers
- Vercel 2026 dashboard: resizable/collapsible sidebar, mobile bottom bar
- TradingView: compare, visible baseline, dense chart interaction
- Koyfin: historic watchlist/screener state
- Mercury Insights: change-first summarization
- Perplexity Finance: market overview→detail hierarchy
- Ramp/Stripe류: trust, receipts, operational states

각 벤치마크마다 `관찰`, `해결한 문제`, `적용`, `적용하지 않을 것`을 적는다.

### 설계할 핵심 경험

1. **Daily Decision Cockpit**
   - 최신 변화, 검토 큐, fresh/stale, 핵심 scenario delta
2. **Data Trust Center**
   - source health, last successful vintage, data gap, fallback, lineage receipt
3. **Scenario Lab**
   - baseline/current compare, fan chart, regime/tail overlay, historical replay
4. **Model Arena**
   - baseline/challenger shadow 성능, 동일 paired sample, 표본 부족 상태
5. **Forecast Research**
   - 질문·round·근거 변화·logical relation·resolution cluster
6. **Track Record**
   - row score와 unique-event score, calibration uncertainty, proper score
7. **As-of Time Machine**
   - 선택 시점에 실제 available했던 data/model/forecast만 재생
8. **Receipts**
   - model, dataset, source, method, limitation, commit를 접을 수 있는 감사 카드

이 이름은 권고가 아니라 요구 기능의 의미다. 최종 정보 구조는 중복을 줄여 재설계한다.

### 부가기능 후보

다음을 평가해 `now/next/later/reject`로 분류한다.

- keyboard command palette 확장
- saved local views/radar
- compare presets와 sharable hash URL
- data freshness notification
- scenario replay scrubber
- uncertainty explainer
- source citation drawer
- model/dataset receipt copy
- changelog/what changed
- glossary with contextual tooltips
- export PNG/CSV/JSON
- print/share view
- local-only personalization
- reduced-motion toggle
- accessibility contrast toggle
- guided onboarding/30-second briefing
- delightful but non-distracting hover physics

계정·서버·클라우드 저장이 없다는 제약을 유지한다. 기능마다 사용자 가치, read-model 필드,
empty/error 상태, 비용, accessibility, mobile behavior를 적는다.

### 시각 시스템

다음을 구체적인 token 표로 설계한다.

- color roles, contrast pair
- surface hierarchy
- type family fallback, display/body/numeric scale
- spacing, radius, border, shadow
- chart palette and semantic colors
- focus ring
- motion duration/easing/distance
- reduced motion alternative
- responsive breakpoints
- minimum text and hit target

현재 warm white/ink/orange/amber/crimson/teal을 중심으로 조정한다. 밝은 배경에 갑자기 순백색
카드가 튀거나, 장식 그라디언트가 정보 계층을 이기는 상황을 방지한다.

### motion 원칙

- hover 움직임은 정보 depth, selection, comparison, state transition을 설명해야 한다.
- 큰 displacement와 scroll-jacking 금지
- transform/opacity 중심, layout thrash 금지
- pointer coarse에서는 hover 의존 금지
- `prefers-reduced-motion` 완전 대응
- keyboard/focus와 동일한 정보 접근

### 정적 제약

- 외부 CDN/font/script 0을 기본 계약으로 유지
- 현재 HTML 420,000 bytes 예산을 기준선으로 제시
- 기능 증가 시 단일 파일 예산을 늘릴지, 정적 JSON 분리/route chunk를 도입할지 ADR 작성
- GitHub Pages cache/versioning 전략
- JS 없이 핵심 안내가 남는 graceful fallback 가능성 평가

---

## 보안·비용·거버넌스

반드시 다음을 설계한다.

- API secret 저장·rotation·CI permissions
- source terms/license manifest
- dependency pinning/SBOM·취약점 점검
- prompt injection을 포함한 외부 문서 ingest 경계
- untrusted HTML/markdown sanitization
- reproducible environment/lockfile
- model/download supply chain hash
- monthly API·LLM·data 비용표
- per-job token/search/runtime budget
- 비용 초과 시 degrade plan
- 감사 로그와 사용자 승인 이벤트

시크릿을 Pages artifact나 forecast 파일에 넣지 않는다.

---

## 비목표와 금지

1. 코드 구현, Git commit, push
2. 기존 forecast·ledger·history 행 수정
3. 가짜 실시간 수치나 가짜 예측치 생성
4. 결측 보간으로 데이터가 있는 척하기
5. 작은 표본에서 정확도 향상을 단정하기
6. gate 전 Platt/isotonic 실보정·가중 ensemble·edge 신호 활성화
7. LLM 과거질문 재실행으로 능력 주장
8. 옵션 risk-neutral 확률을 실제 physical 확률로 라벨링
9. model output과 scenario probability 무근거 합산
10. 모든 유행 모델을 넣는 kitchen-sink 설계
11. 현재 UI 전체를 dark/black theme 또는 generic SaaS template로 교체
12. 새 메뉴를 기능 수만큼 늘리기
13. 접근성·모바일·성능을 마지막 polish로 미루기
14. 사용자 투자 결정을 자동화하는 기능

---

## 최종 설계서 필수 목차

다음 목차를 모두 포함한다. 필요하면 하위 절을 추가하되 합치거나 생략하지 않는다.

1. Executive decision memo
2. Current-state evidence audit
3. Contradiction and drift register
4. Product north star, goals, non-goals
5. Research methodology and evidence grades
6. Live market/product benchmark findings
7. Data source decision matrix
8. Canonical data contracts and glossary
9. Bitemporal/point-in-time architecture
10. Storage ADR: SQLite/DuckDB/Parquet/server DB
11. Physical schema and data dictionary
12. Ingestion, quality, quarantine, lineage
13. Orchestration, freshness, backfill, recovery
14. Baseline model suite
15. Candidate mathematical/ML model review
16. Selected minimal model portfolio
17. Walk-forward and leakage-control protocol
18. Scoring, calibration, clustering, gates
19. Ensemble and logical reconciliation
20. Model registry, champion/challenger, MLOps
21. Scenario engine v2 design
22. Dashboard read-model v2 contract
23. Information architecture and user journeys
24. Visual design system
25. Interaction, motion, accessibility
26. Auxiliary feature prioritization
27. Security, license, privacy, cost
28. Migration and backward compatibility
29. Test strategy and acceptance matrix
30. Observability, incidents, rollback
31. Phased roadmap
32. Codex implementation packets
33. File-by-file change map
34. Decision log and rejected alternatives
35. Open questions and user approval gates
36. Source bibliography

### 필수 시각화

최소 다음 Mermaid를 포함한다.

- current architecture
- target architecture
- bitemporal lifecycle
- job dependency DAG
- model lifecycle
- forecast→resolution cluster→score lineage
- dashboard information architecture
- phased migration timeline

다이어그램은 prose를 반복하지 말고 관계를 설명해야 한다.

---

## Codex 구현 패킷 형식

설계서를 실제 구현으로 넘길 수 있도록 각 packet을 아래 형식으로 작성한다.

### `WP-XX · 이름`

- 목적
- 사용자 가치
- 선행조건
- 범위
- 비범위
- 현재 근거
- 설계 결정
- 변경할 정확한 파일
- 신규/변경 schema
- data migration/backfill
- CLI/API/read-model 변화
- UI states와 responsive behavior
- 테스트 목록
- 성능·비용 예산
- 보안·라이선스 고려
- 수용 기준
- 실패/기각 기준
- rollback
- 문서 갱신
- 권장 commit boundary와 commit message
- 이후 packet 의존성

packet은 Codex가 한 번에 검증 가능한 크기로 나눈다. `데이터 고도화` 같은 거대 작업명 하나로
묶지 않는다.

### 권장 phase 경계

Fable이 실측 후 수정할 수 있지만 최소 다음 의도를 보존한다.

- Phase 0: 데이터 무결성·단위·branch-aware rebuild·독립 표본
- Phase 1: point-in-time data foundation·공식 source
- Phase 2: baseline/evaluation harness·model registry
- Phase 3: shadow candidate models·scenario v2
- Phase 4: read-model v2·UI trust/intelligence features
- Phase 5: 충분한 표본 뒤 calibration/ensemble 승격 검토

각 phase 종료 시 사용자에게 보여줄 observable outcome을 적는다.

---

## 품질 기준

최종 문서는 **25,000~45,000자 수준의 밀도 높은 한국어 설계서**를 목표로 한다. 분량을 위한
반복은 금지하고 표·스키마·의사코드·다이어그램·수용기준에 공간을 사용한다.

다음 질문에 모두 답해야 완료다.

- 무엇이 현재 사실이고 무엇이 제안인가
- 어떤 데이터가 언제 실제로 알 수 있었는가
- 어떤 모델이 어떤 기준선을 어떤 평가에서 이겨야 하는가
- 같은 이벤트 반복 예측을 어떻게 공정하게 채점하는가
- 단위·빈티지·브랜치 오염을 어떻게 구조적으로 막는가
- 어떤 기능이 사용자 판단 시간을 줄이는가
- UI가 어떤 read-model 필드를 필요로 하는가
- static Pages와 성능 예산을 어떻게 지키는가
- 어떤 단계에서 사용자 승인이 필요한가
- Codex가 어느 파일부터 어떤 테스트와 함께 구현하는가

근거가 부족하면 숫자를 만들지 말고 `현재 미확정`, 필요한 검증, 의사결정 조건을 적는다.
질문이 막히지 않는 한 합리적 가정을 사용하고, 문서 말미에 가정 목록을 남긴다.

---

## 시작 지시

이제 저장소와 라이브 사이트를 감사하고 공식 자료를 조사하라. 먼저 현재 상태와 문서 간
불일치를 표로 확정한 뒤, 새 모델이나 UI 아이디어를 설계하라. 최종적으로
`reports/md/claude_fable_quant_platform_grand_blueprint_260801.md` 하나만 작성하고 멈춰라.
