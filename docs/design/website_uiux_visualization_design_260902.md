# 웹사이트 UI/UX 가시화 설계서 — 직관적 이해를 위한 개선 (2026-09-02)

- 지위: 상세 UI/UX 설계서 (PROMPT 요청 2). 구현 착수는 사용자 승인 후 별도.
- 근거: dashboard.js(3,166줄)·dashboard.css(1,269줄)·라이브 사이트·페이로드 예산 실측
  (워크플로 ui-measure 에이전트, 2026-09-02). 초안 대비 변경은 §8.

## 0. 불변 제약 + 실측 예산

- fail-closed 표시·참고 의견 배지·확률 1% 단위·판정 문구 금지·정적 스택(라이브러리 0) 유지.
- **임베드 예산(ADR-002)**: `DASHBOARD_RAW_BUDGET_BYTES = 1,572,864B`, 현재 사용
  1,025,465B → **여유 547KB(34.8%)**. 신규 JS/CSS는 이 안에서 (dashboard.js 375KB·css 233KB).
- **statistics.json 예산: 96.3% 사용(여유 4.5KB)** — 통계 쪽 신규 데이터 필드는 사실상 0.
  본 설계는 통계 개선을 **기존 필드 재사용만**으로 구성한다 (예산 상향은 별도 결정).
- 브레이크포인트 실측 티어: 1279/1050/980/900/**799(데스크톱↔모바일 경계)**/760/620/359.
- 차트 확대 모달: 컨테이너가 `.timeseries-chart`·`.statistics-chart`류이고 내부에 svg가
  있으면 `enhanceChartZoom`이 자동 부착 — 신규 차트는 클래스 재사용으로 공짜 획득.

## 1. 시계열 페이지 — "분포를 그림으로"

### 1-1. v8 분포 밴드 차트 (path 탭 활성화) [최우선]

**데이터 실측**: v8 payload는 63일 경로가 아니라 **4노드 스냅샷**(horizons 1/5/21/63의
band_index{p10,p25,p75,p90}+median_index) + anchor. 기존 `timeseriesPathSvg`는
`path{history_index≥2, dates[63], p10..p90[63]}` 계약이라 그대로 못 쓴다.

**설계 결정: 신규 `timeseriesV8BandSvg` (기존 함수 무수정)** —
- 좌 25%: 과거 63세션 실적선. **공급 경로**: `build_projection`에
  `history{dates[], index[]}` 추가 — 이미 anchor 산출에 쓰는
  `read_market_observations`에서 NASDAQCOM 최근 63세션을 추출(디스플레이 계층 결합이라
  봉인 무접촉; `validate_latest`의 HOLD 숫자 금지와 무충돌 — visible에만 첨부).
  read_model_contract의 v8 가드에 history 필드 허용 추가 + "HOLD면 부재" 검사.
- 우 75%: 세션 축 0→63에 4개 **실측 노드**(1·5·21·63)를 마커(원)로 강조, 노드 사이는
  선형 보간 **점선** 밴드 2겹(p10–p90 연한, p25–p75 진한) + p50 중앙선.
  캡션 필수: "◦ 표시가 실측 분위수 — 사이 구간은 선형 보간(참고용)". 보간을 실측처럼
  보이게 하지 않는 것이 이 차트의 정직성 핵심.
- 노드 위 상승확률 마커(예: 63d "▲72%"), viewBox 1200×500·로그축·기존 ts-* CSS 재사용,
  컨테이너 `.timeseries-chart`(확대 모달 자동).
- TS_TABS의 path 탭을 v8에서 enabled로 승격(`enabled=['summary','path']`).

### 1-2. 게이트 상태 위젯 [데이터 보강 1건 필요]

- **실측**: `gate{sealed_gate_pass, operational_pass, reasons[], sealed_run_id}`는 카드
  payload에 생존. `operational.freshness[]`(그룹별 age/limit)는 **투영에서 탈락** →
  `build_projection`에 `freshness_summary`(그룹·age_hours·limit_hours·status 5행) 추가.
- visible 시: 히어로 아래 2배지 — `봉인 평가 PASS`(툴팁: run id·원점 1,011) ·
  `운영 신선도 OK`(툴팁: 5그룹 중 최악 age/limit).
- **HOLD 시(v5 폴백·v8 hold 공통)**: 현 pending 카드는 사유를 안 보여준다. v8 hold의
  `gate.reasons[]`를 pending 카드에 리스트로 노출 — "왜 숫자가 없는지"가 설계임을 전달.
  (v5 폴백에는 operational_gate.reasons가 이미 있으나 미표시 — 같은 컴포넌트로 처리.)

### 1-3. 용어 즉석 설명 [기존 자산 확장]

- **실측**: `plainTerm`+`UI_TERMS` 고객용 용어 사전이 이미 존재. 신규 구축이 아니라
  **항목 추가**: p10–p90("100번 중 80번은 이 안"), 상승 가능성, CRPS 개선("오차 점수가
  기준 모델보다 얼마나 작은가"), 적중률, 참고 의견. 시계열·통계 카드의 해당 라벨에
  `<abbr title>` 적용 (모바일은 탭 시 1줄 팝오버 — CSS만).

## 2. 통계 페이지 — "한눈 요약 → 상세"

### 2-1. 접근 경보 히트 스트립 [신규 데이터 0바이트]

- **실측**: `approach_alert{status: ok|watch|alert|reached, proximity_percent,
  boundary_label…}`가 이미 7개 차트에 부착(`signal_semantics:
  'display_convention_not_trade_signal'` 명시 포함). 상단 필터 아래에 이 7개를
  1행 스트립으로 요약: 상태 아이콘(●)+차트명, 클릭 시 해당 카드 스크롤.
  statistics.json 추가 필드 0 — 예산 4.5KB 제약 준수.
- 스트립 캡션: "경계 접근 표시는 표시 관행이며 매매 신호가 아닙니다"(기존 semantics 문구).
- 미부착 20개 차트로의 확대는 **범위 밖**(경계값은 데이터 파생이어야 — 별도 결정).

### 2-2. 카드 정보 위계 [실측으로 절반 기각]

- **실측**: caveat는 이미 `details.chart-method.statistics-caveat`로 **접힘 구현 완료**,
  conclusion도 `.statistics-now`로 카드 하단 노출 중 — 초안 B-2의 절반은 기구현.
- 남는 개선 2건만: ① conclusion 1줄을 카드 **head 옆 요약**으로 복제(스크롤 없이 결론
  인지), ② `details` 요약 라벨을 "주의사항"→"주의 N건 · 첫 문장 미리보기"로.

### 2-3. 두 시대 색 문법 통일 [감사 후 소폭]

- 실측상 닷컴=적색계(#c70039·#8d2943)·현재=청록계(#28756a)가 대체로 일관 — 전 27차트
  색상표 감사 후 예외만 교정, 전역 범례 1회 승격(카드별 반복 제거는 카드 자립성 훼손이
  없는 범위에서 — 필터로 단독 카테고리 볼 때 범례 실종 방지 위해 스트립에 고정).

## 3. 전역

- 3-1. 오늘(overview)에 시스템 상태 3칸: 원장 예측 N·해소 N·다음 재예측 — DATA에 이미
  있는 calibration/due 요약 재사용 (data.json 예산 여유 확인 후, 없으면 기존 필드만).
- 3-2. 지연 로드 정직화: `ensureStatistics`/`ensureFuturePaths` 실패 시 현 동작 실측 후
  "불러오지 못했습니다 — 새로고침" 카드로 통일 (조용한 빈 화면 금지).
- 3-3. 모바일: 799px 경계는 견고(전용 블록 실측). 620px 티어(21개 미디어쿼리 — 최다)의
  시계열 카드 4열→2열 낙하를 실기기 스크린샷으로 검증, p10–p90 라벨 줄바꿈 확인.

## 4. 구현 순서 (작은 PR 단위, 각각 독립 배포 가능)

1. **PR-U1** 게이트 위젯 + HOLD 사유 노출 (`build_projection` freshness_summary +
   read_model_contract 가드 + JS) — 데이터·가드·렌더 한 묶음.
2. **PR-U2** v8 밴드 차트 (history 공급 + `timeseriesV8BandSvg` + path 탭 활성).
3. **PR-U3** 용어 사전 확장 + abbr 적용.
4. **PR-U4** 통계 히트 스트립 (JS만).
5. **PR-U5** 카드 위계 2건 + 색 감사 교정.
6. **PR-U6** 전역(상태 3칸·로딩·모바일 미세조정).

## 5. 각 단계 검증 방법

- 마크업 계약 테스트: v8 카드 선례(`test_v8_card_returns_use_two_decimal_precision`)처럼
  템플릿 문자열 단정 — 위젯 존재·보간 캡션 문구·스트립 semantics 문구.
- read-model 가드: freshness_summary/history는 visible에만, HOLD면 부재 (기존
  "not visible ⇒ no numbers" 패턴 확장).
- 브라우저 검증: 각 PR 머지 → pages → 라이브 스크린샷 (hidden 패널 rAF 함정 주의 —
  탭 활성 상태에서 촬영). 620px·375px 모바일 에뮬레이션 포함.
- 예산 게이트: 빌드가 임베드 예산 초과 시 실패하므로 CI가 자동 감시 (statistics.json
  0바이트 원칙은 코드리뷰로).

## 6. 명시적 비범위 (이번 설계에서 하지 않는 것)

- 통계 신규 데이터 필드(예산 4.5KB) · 차트 라이브러리 도입 · 신규 라우트 ·
  approach-alert 미부착 차트로의 경보 확대 · v2/v5 렌더 경로 수정.

## 7. 사용자 결정 대기

| # | 질문 | 선택지 (권고 굵게) |
|---|---|---|
| UX-D1 | 구현 착수 승인 | (a) **PR-U1~U3 우선 착수** (b) 전체 (c) 보류 |
| UX-D2 | statistics.json 예산 상향(향후 통계 확장 대비) | (a) 상향 (b) **현행 유지(이번 설계는 0바이트)** |
| UX-D3 | caveat 접힘 유지 vs 첫 문장 상시 노출 | (a) **첫 문장 상시 노출(공시 후퇴 방지)** (b) 현행 |

## 8. 초안(DRAFT_B) 대비 달라진 점과 근거

1. **fan chart를 '63일 경로 재사용'에서 '4노드 신규 SVG'로 재설계** — v8 payload가 4노드
   스냅샷임을 실측(경로 아님). 보간을 실측처럼 그리는 대신 실측 노드 강조 + 보간 점선 +
   캡션으로 정직성 확보. `timeseriesPathSvg` 재사용안 폐기.
2. **과거 실적선의 정확한 공급 경로 확정** — `build_projection`+`read_market_observations`
   (디스플레이 계층, 봉인 무접촉)로 명시. latest 포인터에 넣는 안은 HOLD 숫자 금지
   검증과의 관계 때문에 배제.
3. **게이트 위젯에 데이터 보강 1건이 필요함을 발견** — freshness가 투영에서 탈락함을 라인
   실측. 초안은 "데이터 이미 있음"으로 오판했다.
4. **초안 B-2(caveat 접힘) 절반 기각** — 이미 `details`로 구현돼 있음을 실측. 남는 것만 유지.
5. **히트 스트립을 '3단 위치 요약'에서 'approach_alert 7종 재사용'으로 교체** — 신규 판정
   로직 금지 원칙 + statistics.json 예산 96.3% 실측이 결정적. 초안의 전 차트 확대안은
   비범위로 명시.
6. **예산 수치의 구체화** — 임베드 34.8% 여유·statistics.json 4.5KB 여유를 실측해 설계
   전체를 "통계 데이터 0바이트" 제약 아래 재구성.
7. **용어 설명을 신규 구축이 아니라 기존 UI_TERMS 확장으로** — 사전 실존 실측.
