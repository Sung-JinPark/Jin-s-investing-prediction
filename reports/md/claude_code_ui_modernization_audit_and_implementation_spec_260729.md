# Claude Code 실행 명세 — Jin's Investing Prediction Solution UI 전면 현대화

작성일: 2026-07-29 KST  
대상 공개본: https://sung-jinpark.github.io/Jin-s-investing-prediction/  
대상 로컬 산출물: `reports/dashboard.html`  
핵심 원칙: **DB·예측·시나리오·생성 파이프라인은 그대로 두고 표현 계층만 전면 재구축**

---

## 0. 이 문서의 성격

이 문서는 참고 아이디어 모음이 아니라 Claude Code가 그대로 실행해야 하는 구현 계약이다.

직전 작업은 색상과 일부 타이포그래피만 교체한 수준이었고, 기존의 작은 KPI 카드·균일한 흰색 패널·보고서형 표 구조가 유지됐다. 이번 목표는 단순 리컬러링이 아니다.

**화면의 정보 우선순위, 크기 체계, 섹션 구조, 내비게이션, 인터랙션, 차트 표현을 다시 설계해 현대적인 데이터 프로덕트로 보이게 만드는 작업**이다.

계획만 작성하지 말고 실제 코드 수정, 대시보드 재생성, 브라우저 검증, 스크린샷 비교까지 완료한다.

---

## 1. 실사 결과

### 1.1 공개 GitHub Pages 실사

2026-07-29에 아래 공개본을 1440×900 뷰포트에서 직접 확인했다.

`https://sung-jinpark.github.io/Jin-s-investing-prediction/`

확인된 장점:

- 상단을 어두운 배경으로 묶어 이전 로컬 산출물보다 브랜드 영역이 선명해졌다.
- 시장 스트립과 6개 화면 탭이 존재한다.
- 주간 시나리오와 혁신 사이클은 실제 SVG로 렌더링된다.
- 공개본 시장 전망의 두 SVG 실측 크기는 약 `1228×593`, `1240×460`이다.
- 해시 기반 화면 전환과 차트 tooltip 로직은 존재한다.

그러나 제품 인상을 떨어뜨리는 문제가 남아 있다.

| 항목 | 공개본 실측/관찰 | 문제 |
|---|---:|---|
| 메인 제목 | 46px, 한 줄 | 정보 제품의 중심이라기보다 보고서 섹션 제목처럼 보임 |
| 내비게이션 | `href` 없는 `<a>` 6개 | 실제 링크도 버튼도 아니며 키보드·접근성·제품감이 약함 |
| 활성 접근성 | `aria-current` 0개 | 현재 화면을 보조기술이 인식하지 못함 |
| 애니메이션 | `@keyframes` 0, `animation:` 0 | 화면이 바뀌어도 정적인 문서처럼 느껴짐 |
| 전환 선언 | 전체 CSS에서 3개 | hover 위주이며 화면 전환 리듬이 없음 |
| 화면 구조 | 동일한 직사각형과 표 반복 | 색을 빼면 기존 관리도구형 레이아웃과 큰 차이가 없음 |
| 예측 목록 | 헤딩 없이 필터와 표가 바로 등장 | 화면별 정체성과 시각적 계층이 없음 |
| 차트 패널 | 흰색 보고서 패널 | 그래프는 크지만 분석 도구의 몰입감이 약함 |
| 핵심 질문 | 요약에서 65/52/58 같은 최신 질문 확률이 대형 카드로 드러나지 않음 | 사용자가 가장 궁금한 값보다 운영 KPI가 우선됨 |

판단:

> 공개본은 색상과 상단 구조가 개선된 “정돈된 리포트”다. 아직 “현대적인 동적 예측 제품”은 아니다.

### 1.2 로컬 실제 산출물 실사

확인 파일:

- `reports/dashboard.html`
- 생성 시각: 2026-07-28 11:49 KST
- 파일 크기: 약 179KB

로컬 산출물은 공개본보다 이전 디자인이다.

- 상단 52px 앱바
- 1240px 고정 중심 폭
- 5px radius 흰색 카드 반복
- 26px KPI
- 17px 섹션 제목
- 4열 KPI 카드 → 2열 카드 → 일정 표의 전형적인 관리자 화면
- 모든 화면이 범용 `.card`에 의존
- 데이터는 풍부하지만 시각적 우선순위가 평평함

로컬 차트 자체는 존재한다.

- 시나리오 SVG: 약 `1160×560`
- 혁신 사이클 SVG: 약 `1160×430`

따라서 문제는 “그래프가 없음”이 아니라 **그래프를 포함한 전체 표현 계층이 오래된 보고서 문법에 갇혀 있음**이다.

### 1.3 공개본과 로컬 산출물의 동기화 차이

실사 시점 기준:

- 공개본 갱신 표시: 2026-07-29 07:33 KST
- 로컬 `reports/dashboard.html`: 2026-07-28 11:49 KST
- 로컬 `src/ai_fc/dashboard_template.html`: 2026-07-28 11:05 KST

즉 공개 Pages에는 로컬 현재 파일보다 새로운 변경이 반영됐을 가능성이 높다.

작업 시작 전에 반드시 아래를 확인한다.

```bash
git status --short
git log --oneline --all -10 -- src/ai_fc/dashboard_template.html
git log --oneline --all -10 -- reports/dashboard.html
```

주의:

- 작업자의 미커밋 변경을 삭제하거나 덮어쓰지 않는다.
- `git reset --hard`, 임의 checkout, 강제 pull을 하지 않는다.
- 공개본을 만든 더 최신 템플릿이 다른 브랜치에 있다면 그 변경을 보존한 상태에서 이 명세를 적용한다.
- `reports/dashboard.html`을 손으로 수정하지 않는다. 템플릿을 수정한 뒤 생성 명령으로 다시 만든다.

---

## 2. 기술적 결론과 권장 방안

### 선택안 A — 자기완결 HTML 유지 + 표현 계층 전면 재구축

이 방식을 채택한다.

이유:

- 현재 대시보드는 외부 의존성 없는 자기완결 HTML을 계약으로 가진다.
- 임베드 스냅샷과 `/api/data` 라이브 모드를 같은 템플릿이 처리한다.
- 기존 SVG 차트와 tooltip 로직이 이미 동작한다.
- DB와 Python read model을 건드리지 않고도 충분히 현대화할 수 있다.
- GitHub Pages 배포 구조를 유지할 수 있다.

수정 중심:

- `src/ai_fc/dashboard_template.html`

생성 산출물:

- `reports/dashboard.html`

선택적으로 강화할 테스트:

- `src/tests/test_dashboard.py`

변경 금지:

- `src/ai_fc/dashboard.py`의 read model, `SCENARIO`, DB 접근, 직렬화 로직
- 질문 레지스트리
- forecast 원장
- calibration·resolution 데이터
- DB 스키마

### 선택안 B — React/Next 등 별도 프런트엔드로 전환

이번 작업에서는 채택하지 않는다.

이유:

- 현재의 “외부 리소스 0, 파일 하나로 열림” 테스트 계약을 깨뜨린다.
- 빌드·배포 체계와 데이터 연결 방식을 불필요하게 확장한다.
- UI 개선보다 마이그레이션 비용이 커진다.

### 선택안 C — 기존 DOM 유지 + CSS만 교체

금지한다.

이유:

- 현재 문제의 원인은 색상이 아니라 `renderOverview()`부터 모든 화면이 동일한 `.card` 구조를 출력하는 데 있다.
- CSS만 바꾸면 여전히 4열 작은 KPI, 2열 작은 패널, 표 순서가 그대로 남는다.
- 직전 실패를 반복하게 된다.

---

## 3. 변경 불가 계약

아래는 UI 변경과 무관하게 반드시 그대로 유지한다.

### 3.1 데이터 계약

- `window.__DATA__`
- `window.__DATA_URL__`
- `<!--DATA-->`
- `DATA.meta`
- `DATA.scenario`
- `DATA.analog_context`
- `DATA.questions`
- `DATA.forecast_history`
- `DATA.resolutions`
- `DATA.ml_runs`
- `DATA.market_runs`
- `DATA.calibration`
- `DATA.due`

### 3.2 의미 계약

- 질문별 최신 확률
- 질문별 라운드 이력
- 마감일과 상태
- 시나리오 경로와 확률
- 이벤트와 위험도
- 과거 혁신 사이클
- ML·시장 내재확률
- Brier와 calibration
- as-of 재구성 의미

`65%`, `52%`, `58%`는 서로 다른 질문의 최신 확률이다. 이를 합계 100%인 시나리오 가중치로 해석하거나 `S1/S2/S3`에 대입하지 않는다.

### 3.3 배포·보안 계약

기존 테스트의 다음 조건을 유지한다.

- 외부 CDN 없음
- `<link>` 기반 외부 스타일시트 없음
- 외부 스크립트 없음
- 외부 폰트 로드 없음
- 자기완결 HTML
- 서버는 읽기 전용
- POST 405

Geist 느낌이 필요하면 외부 폰트를 불러오지 말고 아래처럼 시스템 폰트 우선순위를 사용한다.

```css
--sans: Geist, Inter, system-ui, -apple-system, "Segoe UI",
  "Apple SD Gothic Neo", "Malgun Gothic", Roboto, Arial, sans-serif;
```

---

## 4. 디자인 목표

### 한 문장 목표

> “운영 현황을 카드로 나열한 관리자 페이지”를 “큰 시장 판단과 확률을 중심으로 탐색하는 현대적 예측 제품”으로 바꾼다.

### 색을 제거해도 보여야 하는 차이

새 화면을 흑백으로 바꿔도 다음 변화가 명확해야 한다.

- 제목이 훨씬 크다.
- 핵심 질문 확률이 운영 KPI보다 먼저 보인다.
- 섹션마다 폭과 구성이 다르다.
- 밝은 편집 영역과 어두운 분석 영역이 교차한다.
- 차트가 화면의 주역이다.
- 상세 화면은 좌측 라운드 내비게이션과 본문 분석으로 구분된다.

흑백 비교에서 기존 화면과 차이가 사라지면 실패다.

---

## 5. 화면 골격

### 5.1 공통 데스크톱 골격

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ BRAND / P1 / LIVE / 데이터 시각                                         │ 74px
├─────────────┬─────────────┬─────────────┬─────────────┬────────────────┤
│ NASDAQ      │ ATH 대비    │ -10% 선     │ BREADTH     │ REGIME         │ 84px
├──────────────────────────────────────────────────────────────────────────┤
│ 01 요약 │ 02 시장 전망 │ 03 기간 │ 04 질문 │ 05 시점 │ 06 적중        │ 61px
└──────────────────────────────────────────────────────────────────────────┘

max-width 1540px의 화면별 콘텐츠
```

변경 사항:

- `.appbar`와 `.mktstrip`을 별개의 작은 카드로 보이지 않게 하나의 dark shell로 묶는다.
- 시장 스트립의 외곽 radius·shadow를 제거한다.
- 현재처럼 `.wrap` 안의 작은 카드로 시장 스트립을 넣지 않는다.
- 내비게이션은 실제 `<a href="#overview">` 또는 `<button type="button">`로 만든다.
- 현재 화면에는 `aria-current="page"`를 부여한다.

### 5.2 요약 화면

```text
┌──────────────────────────────────────┬───────────────────────────────┐
│ EYEBROW                              │ 현재 분포/검증 상태            │
│ 시장 판단을 설명하는 2~3줄 대형 H1  │ 상승 경로 66%                 │
│ 데이터 기준과 주의 문구              │ 조정·횡보 34%                 │
└──────────────────────────────────────┴───────────────────────────────┘

┌──────────────────────┬──────────────────────┬──────────────────────┐
│ 65%                  │ 52%                  │ 58%                  │
│ 질문 제목            │ 질문 제목            │ 질문 제목            │
│ 직전 대비 / 갱신시각 │ 직전 대비 / 갱신시각 │ 직전 대비 / 갱신시각 │
└──────────────────────┴──────────────────────┴──────────────────────┘

┌──────────────────────────────────────┬───────────────────────────────┐
│ 연말 시나리오 분포                   │ 다가오는 판정일               │
└──────────────────────────────────────┴───────────────────────────────┘

┌────────────┬────────────┬────────────┬────────────┬─────────────────┐
│ 질문 수    │ 라운드 수  │ 해결 표본  │ Brier      │ P2 게이트       │
└────────────┴────────────┴────────────┴────────────┴─────────────────┘
```

핵심:

- 운영 KPI 4개를 첫 콘텐츠로 두지 않는다.
- 최신 핵심 질문 3개를 `DATA.questions`와 `DATA.forecast_history`에서 읽어 대형 카드로 배치한다.
- UI 선택용 질문 ID만 상수로 두고 확률은 절대 하드코딩하지 않는다.

권장 UI 선택 ID:

```js
const FEATURE_QIDS = [
  "nasdaq-corr10-augoct-2026",
  "nasdaq-eoy-above-jul9-2026",
  "nasdaq-ath-eoy-2026",
];
```

각 카드:

- 확률 숫자 `clamp(72px, 7vw, 112px)`
- 최소 높이 330–360px
- hover 시 `translateY(-4px)`
- 직전 라운드 대비 `%p` 계산
- 클릭 시 기존 질문 상세 hash로 이동
- 라운드 수와 최신 시각 표시

우측 stance 패널은 새 예측을 만들지 않는다. 기존 시나리오에서 다음처럼 도출해 표현한다.

```js
const upProb = DATA.scenario.paths.S1.prob + DATA.scenario.paths.S2.prob;
const rangeProb = DATA.scenario.paths.S3.prob;
```

표현 예:

- `연말 상승 경로 66%`
- `조정·횡보 34%`
- `시나리오 기준일 2026-07-14`

질문별 확률과 시나리오 확률이 다른 데이터라는 설명을 함께 표시한다.

### 5.3 시장 전망 화면

```text
대형 화면 제목 + 시나리오 빈티지

┌──────────────────────────────────────────────────────────────────────────┐
│ DARK ANALYSIS PANEL                                                      │
│ 2026년 말까지 주간 시나리오 — 전체 폭, 실제 SVG 500px 이상              │
│                                                                          │
│ 이벤트 리본                                                             │
│ 위험도 스트립                                                           │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│ DARK ANALYSIS PANEL                                                      │
│ 혁신 사이클 비교 — 전체 폭, 로그 축, 실제 SVG 430px 이상                │
│ context KPI 4개                                                         │
└──────────────────────────────────────────────────────────────────────────┘
```

필수 변경:

- 두 그래프를 흰색 `.card` 안에 넣지 않는다.
- 차트 패널 배경을 `--ink-2`로 하고 축·grid·tooltip을 dark theme에 맞춘다.
- S1 lime, S2 teal, S3 coral, analog slate로 시각 우선순위를 분명히 한다.
- 아날로그는 dashed line으로 유지한다.
- AI 현재 계열은 역사 계열보다 굵게 표시한다.
- 이벤트 라벨을 차트 내부 상단에 겹쳐 놓기보다 별도 이벤트 리본으로 분리한다.
- 위험도는 텍스트 칸 반복이 아니라 얇고 연속된 strip으로 보이게 한다.
- tooltip은 어두운 floating panel로 유지하되 padding과 대비를 강화한다.

차트 데이터 배열과 좌표 계산 의미는 바꾸지 않는다.

### 5.4 기간 조회

구조:

1. 대형 화면 제목
2. 8월·9월·10월·11월·연말 프리셋
3. 시작일·종료일 입력
4. 선택 기간의 S1/S2/S3 수익률 대형 숫자 3개
5. dark chart panel
6. 기간 내 이벤트와 해결 예정 질문 2열

동작:

- 프리셋 선택 시 날짜가 실제로 변한다.
- 날짜 변경 시 기존 보간 로직으로 차트가 다시 그려진다.
- 수익률 숫자와 질문 목록이 함께 변한다.

### 5.5 예측 목록

현재 공개본처럼 필터와 표만 바로 보여주지 않는다.

필수 구조:

- `QUESTION REGISTRY` eyebrow
- “예측 질문과 모든 라운드를 탐색합니다” 수준의 대형 화면 제목
- 우측 결과 개수
- 넓은 검색 필드
- 도메인·테마·상태 필터
- 표

표는 유지하되 다음을 개선한다.

- 행 높이 58–68px
- 질문 제목과 ID를 두 줄 계층으로 구분
- 최신 확률은 mono 18–22px
- hover 배경 변화
- `tabindex="0"`과 Enter 처리
- 상태 chip의 의미 있는 색
- 모바일 가로 스크롤

### 5.6 질문 상세

```text
뒤로가기

┌─────────────────────────────────────────────┬────────────────────────────┐
│ 질문 제목 대형 H1                          │ 최신 확률 원형/대형 블록   │
│ domain · status · deadline · drivers        │ 65%                        │
└─────────────────────────────────────────────┴────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│ AI · ML · 시장 확률 비교 차트                                            │
└──────────────────────────────────────────────────────────────────────────┘

┌───────────────────┬──────────────────────────────────────────────────────┐
│ R1 / R2 / R3      │ 선택 회차 KPI 4개                                   │
│ 확률·날짜         │ 예측 근거 원문                                      │
└───────────────────┴──────────────────────────────────────────────────────┘
```

현재처럼 회차 버튼을 본문 상단에 작게 나열하지 않는다.

- 데스크톱: 좌측 라운드 rail
- 모바일: 가로 라운드 selector
- 회차 클릭 시 확률·CI·시장 내재·출처·본문이 실제로 갱신
- 상세 차트는 기존 `drawHistory()` 데이터를 그대로 사용

### 5.7 시점 조회

- 대형 화면 제목
- 기준일을 별도 dark control block으로 강조
- AI·ML·시장 확률 표
- AI−시장 edge를 부호와 색으로 구분
- 선택 날짜 이후 데이터가 배제된다는 설명
- 날짜 변경 시 결과 개수도 갱신

### 5.8 적중 이력

첫 줄:

- 해결 표본
- Brier
- Reliability
- Resolution

이후:

- 누적 Brier 추이
- calibration curve
- 해결 이력
- 도메인별 점수

표본 2개라는 제한을 작게 숨기지 말고, “아직 성능 판단에 이르다”는 상태 메시지를 명확히 표시한다.

---

## 6. 레이아웃·타이포그래피 명세

### 6.1 핵심 수치

```css
:root {
  --page-max: 1540px;
  --ink: #06100d;
  --ink-2: #0b1714;
  --ink-3: #10231d;
  --paper: #eef2ec;
  --white: #ffffff;
  --lime: #bcff71;
  --lime-deep: #5b8f2e;
  --coral: #ff8066;
  --teal: #57d4c8;
  --blue: #83a9ff;
  --muted: #718079;
  --line: rgba(7, 17, 15, 0.14);
  --dark-line: rgba(255, 255, 255, 0.13);
}
```

색상은 참고값이다. 합격 여부는 색상이 아니라 구조로 판단한다.

### 6.2 크기 체계

| 요소 | 데스크톱 |
|---|---:|
| 화면 H1 | `clamp(44px, 6vw, 86px)` |
| H2 | `clamp(28px, 3vw, 44px)` |
| 핵심 확률 | `clamp(72px, 7vw, 112px)` |
| 일반 KPI | 28–36px |
| 본문 | 14–18px |
| eyebrow | 9–10px |
| 공통 콘텐츠 폭 | 최대 1540px |
| 주간 시나리오 차트 | 500–560px |
| 혁신 사이클 차트 | 430–500px |

### 6.3 카드·경계

- 범용 `.card` 하나로 모든 UI를 만들지 않는다.
- radius는 0–2px 중심으로 사용한다.
- shadow는 제거하거나 거의 보이지 않게 한다.
- 구조는 경계선, 배경 대비, 여백으로 구분한다.
- dark panel 안에서는 흰색 테두리 `rgba(255,255,255,.10~.14)` 사용.

---

## 7. 동적 인터랙션 명세

현재 구현은 기술적으로 해시 전환이 있지만 시각적 전환이 없다.

### 7.1 화면 진입

라우팅 후 새 화면 root에 `.view-enter`를 붙인다.

```css
.view-enter {
  opacity: 0;
  transform: translateY(10px);
}

.view-enter.is-ready {
  opacity: 1;
  transform: translateY(0);
  transition: opacity 220ms ease, transform 220ms ease;
}
```

렌더 직후 한 프레임 뒤 `.is-ready`를 추가한다.

```js
requestAnimationFrame(() => root.classList.add("is-ready"));
```

### 7.2 내비게이션

권장 마크업:

```html
<nav id="nav" aria-label="대시보드 화면">
  <a href="#overview" data-v="overview"><span>01</span>요약</a>
  <a href="#flow" data-v="flow"><span>02</span>시장 전망</a>
  ...
</nav>
```

라우팅 시:

- active class
- `aria-current="page"`
- 다른 항목의 `aria-current` 제거
- URL hash 유지

### 7.3 카드와 표

- 핵심 확률 카드 hover: 배경 변화 + `translateY(-4px)`
- 일반 표 행 hover: 밝은 surface 변화
- 클릭 가능한 행: 키보드 Enter 지원
- 모든 focus 상태를 `:focus-visible`로 표시

### 7.4 차트

- 기존 tooltip 동작 유지
- pointer 이동 시 crosshair와 값 표시
- 범례는 모바일에서 wrap
- `mouseleave` 시 tooltip 제거
- 화면 재진입 시 SVG 중복 생성 금지

### 7.5 모션 제한

```css
@media (prefers-reduced-motion: reduce) {
  .view-enter,
  .view-enter.is-ready,
  .feature-card {
    transition: none;
    transform: none;
  }
}
```

과도한 숫자 카운트업, 배경 파티클, 무한 애니메이션은 사용하지 않는다.

---

## 8. 코드 구조 변경 명세

### 8.1 `dashboard_template.html`

#### CSS

현재 CSS를 덧칠하지 말고 다음 구조로 재편한다.

```text
tokens
reset/base
dark application shell
market strip
navigation
page heading / hero
overview feature cards
light panels
dark analysis panels
charts / events / risk strip
filters / tables
question detail
track record
footer
responsive
reduced motion
```

현재의 문제:

- `.card`
- `.g4`
- `.g3`
- `.g2`
- `.section-h`
- 다수의 inline `style="margin-top:..."` 

이 조합이 모든 화면을 같은 관리도구처럼 만든다.

조치:

- 화면별 semantic class를 추가한다.
- inline style을 제거하고 클래스화한다.
- `.card`는 보조 surface에만 제한한다.
- 핵심 영역에는 `.feature-grid`, `.analysis-panel`, `.metric-ribbon`, `.detail-layout` 등 별도 구조를 사용한다.

#### 공통 helper 추가

권장 helper:

```js
function pageHeading({ eyebrow, title, description, aside = "" }) {}
function metricRibbon(items) {}
function featureQuestions() {}
function viewRoot(className = "") {}
function mountView(node) {}
function setActiveNav(view) {}
function latestDelta(qid) {}
```

목적:

- 반복 문자열 제거
- 화면별 heading 누락 방지
- UI 구조를 데이터 계산과 분리

### 8.2 기존 함수별 작업

| 함수 | 작업 |
|---|---|
| `route()` | 접근 가능한 nav 상태, view enter 전환, scroll top |
| `renderHeaderStrip()` | 카드형 strip 제거, dark full-width metric strip |
| `renderOverview()` | 완전 재작성. Hero + 핵심 질문 3개 + 비대칭 하단 |
| `renderFlow()` | dark full-width chart panel과 이벤트/risk 분리 |
| `renderAnalogOverlay()` | context KPI + dark overlay panel |
| `drawFlow()` | 데이터 계산 유지, dark theme 축·grid·label 적용 |
| `drawOverlay()` | 데이터 계산 유지, AI 강조와 역사 계열 톤 조절 |
| `renderAsk()` | query bar + 수익률 3개 + chart + 2열 일정 |
| `drawDaily()` | 데이터 계산 유지, dark chart theme |
| `renderQuestions()` | page heading, 결과 수, 검색/필터, 행 접근성 |
| `renderDetail()` | Hero + probability block + round rail + reasoning |
| `drawHistory()` | 실제 너비 확대, AI/ML/시장 시각 구분 |
| `renderAsof()` | page heading + date control + comparison table |
| `renderTrack()` | KPI ribbon + calibration/해결/도메인 2열 |

### 8.3 `dashboard.py`

수정하지 않는다.

허용되지 않는 변경:

- `SCENARIO` 수정
- `build_read_model()` 키 변경
- DB 쿼리 변경
- 데이터 가공 의미 변경
- 임의 확률 추가
- 시나리오 기준일 변경

### 8.4 `reports/dashboard.html`

직접 편집하지 않는다.

생성:

```bash
cd src
python -m ai_fc dashboard
```

### 8.5 테스트

기존 테스트를 유지하고, 필요하면 `src/tests/test_dashboard.py`에 아래 UI 계약을 추가한다.

- `<h1` 존재
- `href="#overview"` 등 6개 실제 hash link 존재
- `aria-current` 처리 코드 존재
- `prefers-reduced-motion` 존재
- `view-enter` 존재
- `feature-grid` 존재
- `analysis-panel` 존재
- 두 SVG 생성 함수 유지
- 외부 리소스 금지 테스트 통과

---

## 9. 데이터 보존 검증

### 9.1 변경 파일 제한

최종 diff에서 다음 파일은 변경이 없어야 한다.

```text
src/ai_fc/dashboard.py
questions/**
forecasts/**
calibration/**
db/**
data/**
```

허용 파일:

```text
src/ai_fc/dashboard_template.html
src/tests/test_dashboard.py          # UI 계약 강화 시
reports/dashboard.html               # 생성 산출물
reports/ui-audit/**                  # 스크린샷을 저장할 경우
```

### 9.2 임베드 데이터 비교

변경 전 `reports/dashboard.html`의 `window.__DATA__` JSON을 별도 임시 파일로 추출한다.

변경 후 동일 DB 상태에서 다시 생성하고 비교한다.

허용 차이:

- `meta.generated`

불허 차이:

- 질문 수
- 질문 ID
- 최신 확률
- 라운드 수
- 시나리오 경로
- 시나리오 확률
- 이벤트
- 위험도
- resolution
- calibration

### 9.3 질문 확률 검증

특히 아래 질문의 값은 데이터에서 읽어 표시한다.

- `nasdaq-corr10-augoct-2026`
- `nasdaq-eoy-above-jul9-2026`
- `nasdaq-ath-eoy-2026`

값을 HTML/JS에 직접 쓰지 않는다.

---

## 10. 반응형 명세

### 1440px

- max 1540px 레이아웃 사용
- Hero 2열
- 핵심 확률 카드 3열
- chart 전체 폭
- detail round rail 190–220px

### 768px

- Hero 1열
- feature card 1열 또는 2열
- 시장 스트립 3+2 재배치
- chart 높이 390px 이상

### 390px

- H1 최소 42px
- 확률 숫자 최소 68px
- 시장 스트립 2열
- nav 가로 스크롤
- 차트 숨김 금지
- chart 최소 높이 320px
- 표 가로 스크롤
- reasoning 본문 가독성 유지
- body 전체의 원치 않는 가로 넘침 금지

---

## 11. 브라우저 검수 절차

### 11.1 실행

스냅샷:

```bash
cd src
python -m ai_fc dashboard
```

라이브 검수:

```bash
cd src
python -m ai_fc dashboard --serve --host 127.0.0.1 --port 8899
```

### 11.2 화면별 확인

6개 화면을 전부 클릭한다.

1. 요약
2. 시장 전망
3. 기간 조회
4. 예측 목록
5. 시점 조회
6. 적중 이력

질문 상세 화면도 최소 1개 연다.

### 11.3 기능 확인

- 시장 전망에 크기 0이 아닌 SVG 2개
- 모든 시나리오 계열 존재
- 모든 혁신 사이클 계열 존재
- tooltip 작동
- 기간 프리셋 클릭 시 날짜와 차트 변동
- 검색어 입력 시 결과 수 변동
- 도메인·상태 필터 작동
- 질문 상세 라운드 전환 작동
- as-of 날짜 변경 시 결과 변동
- 적중 이력 수치와 해결 이력 표시
- 콘솔 error 0개

### 11.4 시각 확인

아래 해상도로 모든 주요 화면을 확인한다.

- 1440×900
- 768×1024
- 390×844

필수 스크린샷:

- 기존 요약 / 신규 요약
- 기존 시장 전망 / 신규 시장 전망
- 신규 질문 상세
- 신규 모바일 요약

---

## 12. 합격 기준

모두 충족해야 완료다.

1. 색을 빼도 기존 화면과 구조가 명확히 다르다.
2. 첫 화면에서 운영 KPI보다 시장 판단과 핵심 질문 확률이 먼저 보인다.
3. H1은 데스크톱에서 최소 56px 이상으로 실제 렌더된다.
4. 핵심 질문 확률은 최소 72px 이상으로 실제 렌더된다.
5. 주간 시나리오 SVG 높이는 500px 이상이다.
6. 혁신 사이클 SVG 높이는 430px 이상이다.
7. 6개 화면에 각각 대형 heading과 고유 레이아웃이 있다.
8. 모든 화면을 범용 `.card` 반복으로 만들지 않았다.
9. 화면 전환에 짧은 enter transition이 있다.
10. nav는 실제 링크 또는 버튼이며 키보드로 조작된다.
11. active nav에 `aria-current="page"`가 있다.
12. `prefers-reduced-motion`을 지원한다.
13. 390px에서 핵심 정보와 차트를 숨기지 않는다.
14. 외부 CDN·폰트·스크립트가 없다.
15. DB·예측·시나리오 데이터 diff가 없다.
16. 기존 대시보드 테스트가 모두 통과한다.
17. 브라우저 콘솔 error가 0개다.

---

## 13. 즉시 실패로 처리할 결과

- 색상 팔레트만 변경
- `.card`의 radius와 shadow만 변경
- 기존 4열 KPI 구조 유지
- 예측 목록에 heading 없이 필터와 표만 표시
- 핵심 질문 확률을 작은 글자로 표시
- 그래프를 흰색 보고서 카드에 그대로 유지
- 가짜 수치나 새 예측 문구 추가
- 시나리오와 질문 확률 혼합
- 외부 UI 라이브러리나 CDN 추가
- 모바일에서 차트 숨김
- 버튼처럼 보이지만 실제 `<a href>`/`button`이 아닌 요소 사용
- 스크린샷 없이 “현대화 완료” 보고
- `reports/dashboard.html`만 직접 편집

---

## 14. 완료 보고 형식

Claude Code는 완료 후 아래 형식으로만 보고한다.

```text
1. 구조적으로 재작성한 화면
2. 새로 구현한 동적 인터랙션
3. 실제 SVG 크기와 계열 수
4. 접근성 변경
5. 1440/768/390 검수 결과
6. 데이터 보존 비교 결과
7. 테스트 결과
8. 콘솔 오류 결과
9. 수정 파일 목록
10. 전/후 스크린샷 경로
```

“색상을 Codex 스타일로 바꿨다”는 설명은 완료 보고로 인정하지 않는다.

최종 결과는 **큰 제목, 큰 확률, 넓은 차트, 비대칭 섹션, 실제로 반응하는 화면 전환**을 가진 현대적 데이터 제품이어야 한다.

