# Claude → Codex 설계 핸드오프 — 데이터·모델·캘리브레이션 백엔드 청사진

> 작성: Claude (Opus 4.8), 2026-07-31. 수신: Codex.
> 범위: **비-UI 백엔드**(데이터 축적·모델·채점·캘리브레이션·자동화)의 미완 설계 전량.
> UI/UX는 Codex가 이미 담당 중(`reports/md/codex_*` 계열) — 본 문서는 그 **반대편 절반**의 설계도다.
> 근거 문서: [CLAUDE.md](../../CLAUDE.md) · [docs/DB_MAP.md](../../docs/DB_MAP.md) · [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) ·
> [docs/KNOWN_LIMITS.md](../../docs/KNOWN_LIMITS.md) · [docs/MODEL_REGISTRY.md](../../docs/MODEL_REGISTRY.md) · [docs/DECISIONS.md](../../docs/DECISIONS.md).

---

## WS-0 · 절대 가드레일 (착수 전 필독 — 위반 시 작업 전체 무효)

이 시스템은 "정확도"보다 **정직성·불변성·캘리브레이션 무결성**이 상위 목표다. 아래는 협상 불가.

1. **불변성**: `forecasts/**`는 생성 후 수정·삭제 절대 금지(오타도 유지). `calibration/ledger.csv`·`benchmark_ledger.csv`·`data/ml_history/*.jsonl`은 **append-only**. 재예측은 새 파일(`r<N>`).
2. **LLM 백테스트 원천 금지**: 과거 질문으로 LLM 예측 능력 검증 제안이 나오면 **거부**하고 원칙5 인용. 예외는 **결정론 수치모델**(LPPL·GBM·DTW·k-NN)의 워크포워드뿐 — 산출은 base rate 참조이지 캘리브레이션 표본 아님(DECISIONS 8-6).
3. **데이터 무보간**: 결측은 결측으로. 월간 지수 부재 시 가짜 시계열 생성 금지(철도 광기 사례 = Tier-3 큐레이션 앵커만). 각 시대 생존편향·표본수(사이클당 n=1) 정직 고지.
4. **하드 게이트 (사용자만 전환)**:
   - ML 보정(isotonic/Platt) = 해소 **100+** 후. 앙상블 **가중** 학습 = 해소 **200+** 후. DL 가격예측 학습은 **영구 금지**.
   - 오픈웨이트(`src/ai_fc/ml`)는 **추론 전용** — 학습·가중치 갱신 금지. 결합은 고정 규칙(중앙값·불일치)만.
   - **P3 게이트(해소 50 + Brier<0.18) 전까지 edge 검출 활성화 금지**. market_implied/옵션 내재확률은 **기록·표시 전용**.
5. **출력 규약**: 확률 1% 단위 + 80% CI. 모든 사실주장 출처(URL·날짜). 미검증은 `[미검증]`. 반대증거(데블스) 섹션 없으면 예측 무효. 날짜 절대표기(YYYY-MM-DD), 시각 KST.
6. **git 위생**: 커밋/푸시는 **사용자 지시 시에만**. 푸시 전 `git fetch`(원격이 자주 선행 — 병렬 작업자 존재) + 비밀 스캔. **force-push·타인 작업 덮어쓰기 금지**. 충돌은 양쪽 보존 리베이스.
7. **비용**: 질문당 서브에이전트 1~4개. 예측 배치·팬아웃 **자동 실행 금지** — 제안 후 사용자 지시 대기. (로컬 수치모델 재계산은 예외.)

---

## 전체 우선순위 지도

```
[P0 병목]   WS-1 채점 회전율 엔진  ────────────► 시스템 1차 목표(캘리브레이션 증명)의 율속단계
[P1 정합도] WS-3 k-NN 다중시대 배선   WS-2 entity/event→digest 배선
[P2 폭]     WS-4 결측 차원(AAII·EDGAR)   WS-8 자동화·재예측 트리거
[P3 봉인]   WS-5 캘리브레이션 배관 활성화   WS-6 market/edge (게이트 전 대기)
[경계]      WS-7 UI 인터페이스 계약 (Codex UI ↔ 백엔드 read-model)
```

의존성: **WS-1이 모든 것의 선행** (해소 표본 없이는 WS-5 게이트가 영원히 안 열림). WS-3는 WS-2와 독립 병렬 가능.

---

## WS-1 · 채점 회전율 엔진 (P0 — 최우선)

**문제**: 예측 39·질문 38 축적 vs **해소 6건**. P3 게이트는 해소 50을 요구. DB가 아니라 **채점 회전이 병목**(DB_MAP §4). 기한 도래 질문이 `resolve`되지 않으면 캘리브레이션 엔진이 영원히 안 돈다.

**현재 상태**:
- `python -m ai_fc due` — 기한 도래 스캔 동작. `resolve <qid> --draft`는 **가격 임계형만** 자동 초안(`resolver.draft_verdicts`). macro/earnings는 수동 판정.
- `resolve`는 다회차 **전량 채점**(투명), `research_status='failed'`는 대표 Brier(`v_brier_primary`)에서 제외.

**설계 (Codex 실행)**:
1. **반자동 판정 보조 확장** (`src/ai_fc/resolver.py`): 가격 임계형 외에 **결정론적으로 판정 가능한 유형** 초안 지원 추가 —
   - `earnings` EPS beat/miss: 컨센서스 vs 실적 수치가 있으면 판정(출처 2곳 대조 필수, WS-D 규약).
   - `macro` 이벤트(FOMC 인상/CPI 임계/NFP 임계): 공식 릴리스 수치 대조. **단, 최종 확정은 사람** — 초안만 생성(`--draft`), 원장 무기록.
   - 판정 불가 유형(주관적 서사)은 명시적으로 "판정불가" 반환.
2. **판정 이중화 자동 대조**: 1차(Yahoo/FRED) vs 2차(거래소/공식 릴리스) 수치 불일치 시 **판정 보류·기록**(KNOWN_LIMITS 25, resolve SKILL의 2차 출처 규약을 코드로 승격).
3. **`research_status='failed'` 태깅 규칙 코드화**: 현재 frontmatter 수동/CSV override. 리서치 전멸(웹서치 0 유효결과) 자동 감지 → frontmatter 태그 기준 문서화(AUDIT-260715 8-2c 준수, 예측 파일 무수정).
4. **due → resolve 큐 리포트**: `due`가 resolve 대상을 우선순위(기한 경과일)로 정렬한 큐를 출력. 사용자가 배치 승인.

**파일**: `src/ai_fc/resolver.py`, `src/ai_fc/cli.py`(due/resolve), `src/ai_fc/files.py`(frontmatter 파싱), 테스트 `src/tests/`.
**수용 기준**: 기한 도래 macro/earnings 질문에 `--draft` 초안 생성 + 2차 출처 대조 로그. 원장 기록은 여전히 사람 확정(`--yes`). 다회차 채점·failed 제외 회귀 테스트 통과.
**금지**: 자동 원장 기록(사람 확정 필수). 예측/질문 파일 수정. 판정기준 변경(변경 필요 시 질문 void + 신규).

---

## WS-2 · entity/event → 예측 digest 배선 (P1 정합도)

**문제**: 2026-07-31 entity 46·event 48로 6시대 채웠으나(DB_MAP §3 주석), **자동 예측 digest에 미배선** — 현재는 대시보드 타임라인·트윈 모델용 사료(史料)일 뿐. 정합도에 직접 기여 못 함.

**설계**:
1. `dualdb/dualdb/export/context_bridge.py`에 **현 사이클월(M+N) 근처 과거 시대 이벤트** 요약 추가 → `data/ml_history`(kind:context) run에 `event_context` 필드. 예: "현 AI M+42 ≈ 닷컴 1999-07(그린스펀 발언 후, 정점 8개월 전)·일본 M+42(1988 과열기)".
2. `src/ai_fc/base_rates.py`의 `ml_digest_with_meta`가 이 필드를 **원재료 라인**으로 주입 — "유사 사이클월의 과거 이벤트 맥락".
3. **매핑 확률 절대 금지**(R-4, base_rates.py L3-6): 이벤트는 서사 맥락이지 확률이 아니다. 준-앵커 경고 라벨 유지.

**파일**: `context_bridge.py`, `src/ai_fc/base_rates.py`, 테스트(주입 O + 매핑확률 미포함 검증).
**수용 기준**: `forecast <qid> --dry-run` 프롬프트 evidence에 이벤트 맥락 라인 포함, 매핑 확률 없음. is_twin=0 격리 유지(트윈 base rate 무변).
**금지**: event를 확률로 변환. is_twin=1 오염.

---

## WS-3 · k-NN 다중시대 배선 (P1 정합도 — 실제 갭)

**문제**: `derived_daily`는 **6시대** 있으나, `model_run`의 knn_analog는 여전히 **dotcom-only z**(`n_dotcom_samples=108`, params `"standardize":"dotcom-only z"`). 계획서 1-B의 "다중시대 이웃 풀"이 **모델에 반영 안 됨** — 이게 정합도의 진짜 미배선 갭.

**설계**:
1. `dualdb/dualdb/models/knn_analog.py` 이웃 풀을 **config 아날로그 5시대**(dotcom+japan1989+niftyfifty1972+crypto2021+biotech2015)의 월말 벡터로 확장. z-표준화는 **풀 전체 기준**(전부 과거 → 누출 없음).
2. **상태벡터 차원 추가**(데이터 존재): 현 5차원 + **CAPE z**(`valuation_monthly.cape`) + **HY z**(`macro_daily.BAMLH0A0HYM2`). R-4의 "밸류·크레딧 결측" 2개 해소.
3. **백색화는 미적용 유지**(R-4 영구 결정) — 차원 추가 시 상호상관 미백색화 한계 재고지.
4. 표본 라벨 갱신: "n=1 사이클" → "다중 사이클 풀(각 사이클 여전히 자기상관)".

**파일**: `dualdb/dualdb/models/knn_analog.py`, `dualdb/dualdb/models/__init__` 또는 러너, `model_run` 산출 검증, 테스트(다중시대 이웃 선택 확인).
**수용 기준**: `python -m dualdb models` 후 model_run의 knn 이웃이 **닷컴 외 시대에서도 선택**됨. caveats에 풀 구성·차원 추가·미백색화 명기.
**금지**: 백색화 도입(별도 검증 라운드 필요). 미래 데이터 표준화 포함(누출). 이웃+지평이 각 시대 창을 넘으면 None(외삽 금지) 유지.

---

## WS-4 · 결측 차원·데이터 폭 (P2)

**문제**: `sentiment_weekly` 0행(AAII 심리 = k-NN 3번째 결측 차원, R-4), `fundamentals_annual` 0행, `cycle_compare` 0행(폐기 후보).

**설계**:
1. **AAII 심리**(KNOWN_LIMITS 28): 사이트 구조상 자동 파싱 부적합 → 사용자가 `dualdb/data/raw/manual/`에 CSV 투입 시 **파서 추가**. 투입 전엔 결측 유지(보간 금지). 확보 시 k-NN 3번째 차원으로.
2. **fundamentals_annual**: EDGAR 재무(무키). 착수 시 트윈 종목 우선. 죽은 회사 데이터 부재는 생존자 표본 규칙으로 방어(KNOWN_LIMITS 14).
3. **cycle_compare 폐기 공식화**: `alignment` long-format이 대체함(KNOWN_LIMITS 24 계열). 스키마에서 deprecated 주석 + 참조 코드 제거 or 뷰 대체.
4. **철도 광기(railway1845)**: 무료 월간 지수 부재 → **Tier-3 큐레이션 앵커 유지**(context_bridge `CURATED_DEEP`). Campbell·Turner 데이터셋을 사용자가 제공하면 오버레이 선 승격, 아니면 현상 유지.

**파일**: `dualdb/dualdb/ingest/`(신규 파서), `dualdb/schema.sql`, `dualdb/dualdb/models/knn_analog.py`(AAII 차원).
**수용 기준**: 파서는 데이터 있을 때만 적재, 없으면 no-op(결측 유지). 스키마 멱등.
**금지**: 심리·재무 데이터 추정/보간. 철도 월간 경로 조작.

---

## WS-5 · 캘리브레이션 배관 활성화 (P3 — 게이트 전 대기)

**문제**: 배관은 **구조 준비 완료, 활성화 대기**(ARCHITECTURE §4). 트리거는 전부 해소 표본 게이트 → **WS-1 선행 필수**.

**설계 (게이트 도달 시 사용자 승인 후에만)**:
| 항목 | 트리거 게이트 | 위치 |
|---|---|---|
| K=3~6 실행 중앙값 활성 | P2(해소 30+, Brier<0.20) | `AI_FC_REASONING_RUNS`(현 기본 1) |
| Platt/extremize 실보정 | 해소 100+ | `shadow_extremized` 섀도열로 사전 검증 중 |
| 앙상블 가중 학습 | 해소 200+ | 현재 고정 중앙값만 |
| 모델 출력 상관행렬(수렴=중복 검사) | ml_history 8~12주 축적 | WorldQuant 중복기각 관례 |
| divergence 명확화 질문 자동생성(supervisor-lite) | 표시→목록 첨부, 실행 사람 | AIA supervisor |

**수용 기준**: 각 항목은 게이트 판정(`v_gate_status`) 통과 + 사용자 승인 **둘 다** 충족 전 비활성. 섀도열은 게이트 전에도 계산·표시 가능(활성 아님).
**금지**: 게이트 전 활성화. 게이트를 코드로 우회. shadow를 실확률로 승격.

---

## WS-6 · market_implied / edge (P3 봉인 — 기록만)

**설계**: `src/ai_fc/market`(Kalshi·Polymarket·CBOE 옵션 BL)은 값을 채우되 **P3 게이트 전까지 기록·표시 전용**. 옵션 내재확률은 항상 risk-neutral 측도 + 프록시 가정 병기(KNOWN_LIMITS 6·7). rN과의 괴리 15%p+는 `due`에 divergence **표시만** — 자동 재예측 금지.
**금지**: P3 전 edge 시그널 발행. 실전 자금 결정의 단독 근거 제시.

---

## WS-7 · UI ↔ 백엔드 인터페이스 계약 (경계 — Codex UI와 접점)

Codex UI가 소비하는 백엔드 계약. 백엔드 변경 시 **깨지 않도록** 유지:
- **read-model 스키마**(`dashboard.build_read_model`): 키 `meta·scenario·questions·forecast_history·resolutions·ml_runs·market_runs·calibration·due` 불변. 추가는 OK, 삭제·개명은 UI 조율 필요.
- **임베드/페치 이중 모드**: `window.__DATA__`(Pages 정적) / `/api/data`(--serve 읽기전용). 서버는 POST 405.
- **자기완결**: 외부 CDN/폰트/스크립트 0(테스트 `test_template_self_contained` 강제).
- **오버레이 계약**: `analog_context.overlay`는 8시대 시작월=100 정규화(overlay_start·OVERLAY_MONTHS). ERA_META/ERA_START 정합.
- **미결 결정(사용자 몫)**: 대시보드 **라이트 vs 다크** 방향 — 원격이 Mistral 라이트로 전환, 이전 all-dark와 상충. Codex는 사용자 확정 전 한쪽으로 고정하지 말 것.

**금지**: read-model 키 삭제로 UI 파괴. `reports/dashboard.html`은 gitignore(빌드 산출) — 소스는 `dashboard_template.html`.

---

## WS-8 · 자동화·재예측 트리거 (P2)

**설계**: 정기 재예측(registry `schedule`) + 이벤트 트리거 재예측. 주간 예약 태스크는 **앱 실행 중에만 발화**(KNOWN_LIMITS 19) — 이 한계 명시. `due`의 stale(14일 무예측)이 최후 방어.
**금지**: 예측 배치 자동 실행(비용 가드레일 — 제안 후 지시 대기). divergence 자동 재예측(판단은 사람).

---

## 비-목표 (명시적 금지 — 하지 말 것)

1. DL 가격예측 모델 **학습** (검증된 능력은 이벤트 확률화 — 설계서 §02).
2. LLM으로 과거 질문 백테스트.
3. `forecasts/**` 사후 수정, 원장 행 수정.
4. 결측 데이터 보간·가짜 시계열.
5. 게이트 전 edge/ML보정/가중학습 활성화.
6. 사용자 하드룰(VIX 25+, 드로다운) 대체 — 시스템은 **조기경보**지 대체 아님.
7. Brier 무능 도메인(>0.22) 시그널 발행.

---

## 착수 순서 권고 (Codex)

1. **WS-1** 먼저 — 병목. 해소 표본이 늘어야 나머지 게이트가 의미를 가짐.
2. 병렬로 **WS-3**(k-NN 다중시대) + **WS-2**(event 배선) — 정합도 직접 기여, 서로 독립.
3. **WS-4** 데이터 폭 — AAII 확보는 사용자 투입 의존.
4. **WS-5/6**는 게이트 도달 + 사용자 승인 전까지 **설계·섀도만**.
5. 각 워크스트림 완료 시: 테스트 통과 → `docs/` 정본 갱신(DECISIONS/KNOWN_LIMITS/MODEL_REGISTRY) → 사용자에게 커밋 승인 요청.

**검증 공통**: `cd dualdb && python -m pytest -q`(v4.1 Pearson 0.899 유지 필수) · `cd src && python -m pytest -q` · `python -m ai_fc sync --check`(드리프트 없음). 푸시 전 `git fetch` + 비밀 스캔.
