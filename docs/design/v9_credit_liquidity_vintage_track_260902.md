# V9 신용·유동성 vintage 수집 트랙 — 설계서 (2026-09-02)

- 승인 근거: 사용자 지시 2026-09-02 ("다음단계 까지 설계 후 진행해") — G3 보고의 권고안
  V9-D5(a) "blocked 피처 ALFRED vintage 수집 트랙 개시"에 대한 진행 지시. DECISIONS V9-D5 기록.
- 선행 근거: `docs/design/v9_gate_autoloop_260901.md` §1(피처군), G0 정찰 보고(수집 부재 실측),
  `reports/md/bank_credit_layer_contract_260805.md`(은행 신용 레이어 선행 계약 — 규율 승계).
- 지위: 데이터 수집 트랙. 모델·게이트·원장 무접촉. 산출물은 reference/PIT 원천 데이터.

## 1. 목표와 실측 근거

V9 G2가 실측으로 보여준 것: 현재 저장소의 유일한 즉시 적격 신규 피처(M2SL)는 무효익이며,
02 설계서가 노린 **신용/여신·MMF 채널의 시리즈는 수집 자체가 안 되어 있다**. 이 트랙은 그
병목을 푼다 — ALFRED 네이티브 vintage 실측(2026-09-02, 공식 API)으로 확정한 수집 대상:

| 시리즈 | 첫 vintage | vintage 수 | 설계창(2007–2014) PIT | 채널 |
|---|---|---|---|---|
| **TOTCI** (주간 C&I 대출) | 1996-12-06 | 1,550 | **완전 적격** | 기업 신용 사이클 |
| **TOTLL** (주간 총여신) | 1996-12-06 | 1,551 | **완전 적격** | 은행 신용 총량 |
| **WRMFNS** (주간 소매 MMF) | 2002-10-31 | 1,021 | **완전 적격** | 대기자금 |

**제외 (온셋 부족 — conditionally_registered 유지·수집 보류)**: 예금 DPSACBW027SBOG(2012-08) →
예대율 파생 불가, VXNCLS(2014-04), MMMFFAQ027S(2013-06), NFCI(2011-05).
**금지 승계**: 폐지 시리즈 WRMFSL 참조 0, 주간·분기 격자 혼합 금지, 판정 문구 렌더 금지.

## 2. 수집 경로 — V1 정본 ALFRED 레인 확장 (recon 판정 승계)

- **로스터**: `data/contracts/multivariate_timeseries_v1.yaml` `sources.financial_optional`에
  3계열 추가. `load_contract`는 로스터를 핀하지 않으므로(브리지·그리드만 fail-closed) 통과하고,
  `registered_series()`가 일일 refresh에 자동 편입한다. V1 모델은 피처를 하드코딩하므로 무영향.
- **최초 백필**: refresh의 증분 창(전 시리즈 공용 max retrieved_at−7일)은 과거 이력을 못
  가져온다 → 신규 CLI `timeseries-collect-series --series TOTCI,TOTLL,WRMFNS`가
  `collect_alfred(series_ids=…)`를 기본 전체 창(expanding_start=1996-01-01)으로 1회 호출.
- **실행**: 키는 CI 시크릿 전용 관례(12-6) → `statistics-backfill.yml` 패턴의
  `.github/workflows/timeseries-vintage-backfill.yml`이 **실행 브랜치에** 수집·커밋.
  체인: collect-series → timeseries-fit → timeseries-forecast → timeseries-verify
  (계약 해시 변경 후 forecast 재기록 전의 verify는 "stale" FAIL이므로 순서 필수).
- **예상되는 정상 WARN**: 백필 후 verify의 `upstream_backfill` 분류·source_backfill_audit 행
  추가는 설계된 동작(ok=true 유지) — 침묵시키려 재적합하지 않는다.
- **커밋 경로 가드**: `data/timeseries/**` + `docs/generated/inventory.generated.md`만 허용.

## 3. 거버넌스 (선행 계약과의 정합)

- **Board 원생산자 조항(은행 계약 §1·§4.1) 미적용 결정** — BEA 선례(DECISIONS 2026-08-31)
  형식으로 기록: Fed Board H.8/H.6 공식 다운로드에는 **first-release vintage 이력이 없다**
  (current vintage만 제공) → PIT 요건(available_at ≤ origin, first-release 불변 객체)을
  충족하는 유일한 기계적 경로는 ALFRED 네이티브 vintage이며, 12-6이 FRED 공식 API를 유일
  준수 자동수집 경로로 확정했다. 긴장은 소멸이 아니라 명시 인수.
- **approved 상속 아님**: `fred_market_signals: approved`(current-vintage 레인)를 상속하는 것이
  아니라, 이미 `vintage_observation` 역할로 등록된 **alfred 레인**(V1 정본 스토어가 8년째
  사용)에 시리즈를 추가하는 것이다. `fred_market_signals.yaml`의 "historical current-vintage
  rows are not valid for backtests" 조항이 오히려 이 트랙의 필요성을 계약으로 뒷받침한다.
- **KNOWN_LIMITS 34 고지**: FRED 약관의 AI/ML 문언·store/cache 조항 vs PIT 아카이브 커밋
  긴장은 미해결(소유자·법률 판단 영역)이며, 본 트랙은 기존 V1 스토어 관행(NFCI 91만 행 등)의
  연장선에서 그 부피를 늘린다. 소유자 고지 사항.
- **루프 격리**: 수집은 키가 배선된 CI 워크플로 전용 — V9 게이트 루프는 시크릿 로드 금지
  헌법을 유지하고 커밋된 파케이만 읽는다.

## 4. 피처 승격 절차 (수집 ≠ 등록)

수집 완료 후 별도 사전등록 개정 커밋으로만:
1. V9 계약 blocked → registered 승격 (F2_totci_credit·F3_totll_credit·F4_wrmfns_mmf),
   research_grids feature_sets 확장(단독 ablation: [F2]·[F3]·[F4] 개별 + 통과 조합),
   preregistered_first_experiments에 V9_E2~E4 추가.
2. `timeseries_v9/contracts.py` registered 집합·`pipeline.py` FEATURE_BUILDERS 동기 개정.
3. 각 피처: first-release 정렬·PIT 강제 테스트·상관 |ρ|>0.85 기각 후 design 실행 (예산 잔여 22/24).
4. E0 대비 쌍대 개선이 없으면 M2SL과 같은 기준으로 무효익 기록 — HOLD가 정답이라는
   원칙 유지 (02 설계서 §0).

## 5. 진행 순서 (이 세션)

1. 본 설계서 + 로스터 확장 + CLI + 백필 워크플로 + DECISIONS V9-D5 + 테스트 + inventory → PR
2. PR 브랜치에서 backfill dispatch → 브랜치에 vintage 데이터 커밋 → CI green 확인 → 머지
3. main pull 후 파케이에서 3계열 first-release 깊이 재실측(수집 검증)
4. 피처 사전등록 개정(§4) + V9_E2~E4 design 실행은 수집 검증 후 후속 (예산·시간 허용 시)
