# Startup Benchmark → Product UI Upgrade Plan

작성일: 2026-07-30 KST
대상: Jin's Investing Prediction Solution
작업 범위: UI·interaction·responsive 표현 계층
불변 범위: DB, 질문 registry, forecast 원본, calibration ledger, 예측·판정 로직

---

## 1. 결론

다음 개편의 목표는 “검정색 대시보드”를 “시장 판단을 빠르게 읽고 깊게 탐색하는 prediction product”로 바꾸는 것이다.

디자인 방향의 이름은 **Signal Glass / Market Intelligence OS**다.

핵심 변화:

1. 순수 검정 면의 반복을 줄이고 deep forest 3단계 위에 mint·teal·restrained violet 광원을 얹는다.
2. 모든 영역을 1px 사각 테두리로 나누던 방식을 줄이고, 여백·표면 명도·blur·soft shadow로 깊이를 만든다.
3. 첫 화면의 예측 카드에 실제 회차 데이터를 사용한 mini sparkline을 추가한다.
4. 고정 market strip을 반투명 intelligence bar로 바꾸고 `Ctrl/⌘+K` 빠른 이동을 제공한다.
5. forecast card를 동일한 사각형 3개가 아니라 우선순위가 드러나는 bento composition으로 바꾼다.
6. table·filter·detail은 marketing card가 아니라 조용한 product workspace처럼 정리한다.
7. motion은 진입·hover·live pulse에만 사용하고, `prefers-reduced-motion`을 유지한다.

---

## 2. 벤치마크 범위

2026-07-30 기준 공개 홈페이지와 공개 제품 소개 화면을 직접 확인했다.

| 제품 | 확인한 강점 | 이번 작업에 적용 | 적용하지 않을 것 |
|---|---|---|---|
| [Linear](https://linear.app/homepage) | fixed navigation, muted inactive state, 넓어진 vertical rhythm, 실제 product UI가 hero의 증거 역할 | 조용한 rail, 약한 divider, predictable action 위치 | 회색 일변도의 개발도구 미학 |
| [Vercel](https://vercel.com/home) | 매우 적은 색으로 강한 hierarchy, sticky header, grid composition | top intelligence bar, 간결한 layout axis | black/white만 사용하는 극단적 무채색 |
| [Ramp](https://ramp.com/) | 한 문장 hero, finance 신뢰감, lime을 action에만 사용 | 숫자·판단 우선, accent 절제 | 밝은 white marketing surface |
| [Mercury](https://mercury.com/) | 금융 제품에 따뜻한 색과 illustration을 사용, 복잡한 기능을 부드럽게 설명 | deep forest에 warm/frosted tone 추가 | 외부 이미지·장식 illustration |
| [Stripe](https://stripe.com/) | 강한 brand color를 atmosphere로 사용하고 CTA hierarchy를 분명히 함 | violet은 ambient/system accent에만 사용 | 데이터 의미와 brand gradient 혼용 |
| [Clay](https://www.clay.com/) | 88px hero type, rounded product blocks, green과 warm neutral 조합 | 큰 판단 문장, 더 유연한 radius scale | 지나친 bubble UI와 marketing copy |
| [Retool](https://retool.com/) | dark canvas 위에 실제 product mosaic, warm off-white type, command/search 진입점 | product evidence, command palette, warm-white text | 과도한 drop shadow와 많은 CTA |
| [Attio](https://attio.com/) | product simulation 자체가 hero visual, 복잡한 정보를 정교한 rounded layer로 표현 | 실제 forecast history를 mini visual로 사용 | 데모 애니메이션의 과밀함 |
| [Raycast](https://www.raycast.com/) | 거의 검정인 배경에서도 제한된 glow와 단순한 headline으로 인상 형성 | glow는 1~2개 광원만, 빠른 키보드 탐색 | red/purple glow를 전 화면에 반복 |
| [Brex](https://www.brex.com/) | finance 문맥의 deep navy, white, 단일 orange accent | 위험·경고는 coral 한 색으로 명확히 유지 | 금융 사이트의 전형적인 CTA 랜딩 구조 |

참고한 Linear의 최신 interface refresh 원칙:

- action 위치를 화면마다 예측 가능하게 유지
- inactive text와 border 대비를 낮춤
- vertical padding을 늘려 기능 밀도를 안정화
- 시각적 분리를 강한 선이 아니라 surface 차이로 처리

출처: [A calmer interface for a product in motion](https://linear.app/now/behind-the-latest-design-refresh)

---

## 3. 현재 공개본 진단

1280×720 실측:

```text
rail width          236px
hero H1 width       약 558px
hero H1 size        약 67px
forecast card top   약 492px
forecast card h     286px
rounded elements    6개
horizontal overflow 0
```

장점:

- 첫 화면의 판단 문장이 분명하다.
- all-dark tone이 모든 route에서 일관된다.
- sidebar와 hash route가 안정적이다.
- 데이터·차트 기능이 이미 충분하다.

개선할 점:

- 236px rail과 좁은 hero copy 때문에 1280px에서 첫 화면이 답답하다.
- 모든 panel이 같은 1px 직사각형이라 중요도 차이가 약하다.
- forecast card가 동일한 크기·표현이라 우선순위가 보이지 않는다.
- 확률 값 외에는 live product라는 증거가 부족하다.
- 검정–초록 두 색의 반복으로 premium depth가 약하다.
- filter/table/detail이 기능적으로는 좋지만 정적인 report처럼 보인다.
- 빠른 탐색이 mouse 중심이다.

---

## 4. 확정 디자인 시스템

### 4.1 Palette

```css
--night:       #030a08;  /* 최상위 canvas */
--ink:         #06100d;  /* page */
--ink-2:       #0b1714;  /* primary surface */
--ink-3:       #10231d;  /* raised/input surface */
--glass:       rgba(12, 27, 23, .72);
--glass-strong:rgba(16, 35, 29, .88);
--lime:        #bcff71;  /* 상승·active·primary data */
--teal:        #57d4c8;  /* 비교·secondary data */
--coral:       #ff8066;  /* 하락·위험·오차 */
--violet:      #a99bff;  /* system/ambient only */
--white-warm:  #f4f7f2;
```

규칙:

- violet은 차트 데이터에 사용하지 않는다.
- lime은 모든 장식에 뿌리지 않고 active·확률·상승에만 쓴다.
- 밝은 paper/white surface는 재도입하지 않는다.
- 배경 광원은 한 viewport 안에서 최대 2개다.

### 4.2 Surface

| level | 용도 | 표현 |
|---|---|---|
| canvas | body·page | night/ink + subtle grid |
| glass | rail·topbar·floating control | alpha surface + 18~24px blur |
| primary | forecast·panel·chart | ink-2 + soft highlight + 18~26px radius |
| raised | input·table header·tag | ink-3 + 10~14px radius |

1px border는 모든 면을 감싸는 기본값이 아니다. 필요한 면에만 `rgba(255,255,255,.08~.12)`를 사용한다.

### 4.3 Typography

- hero 판단: 52~78px, line-height 0.95~1.0
- subpage title: 42~68px
- data number: mono 56~92px
- body: 13~16px
- metadata: mono 8~10px
- warm white를 기본 본문으로 사용하고 pure white는 headline과 숫자에만 쓴다.

### 4.4 Radius / shadow

```text
control  10~12px
card     18~22px
hero     26~30px
drawer   0 24px 24px 0
```

shadow는 아래 두 계열만 사용한다.

```css
0 24px 70px rgba(0,0,0,.24)
inset 0 1px rgba(255,255,255,.04)
```

---

## 5. 화면별 설계

### 5.1 Product rail

- desktop rail 236px → 220px
- alpha glass와 background glow 사용
- active route를 직사각형이 아니라 14px pill + 작은 luminous indicator로 표시
- 숫자 `01~06`은 유지하되 대비를 낮춤
- navigation 아래 `빠른 이동  Ctrl/⌘ K` 버튼 추가
- live status는 bottom card 한 개로 묶음

### 5.2 Intelligence bar

- 기존 48px market strip을 62px sticky glass bar로 전환
- 중요한 값만 white/lime/coral
- label은 더 작게, divider 대비는 더 약하게
- desktop 우측에 command trigger
- mobile은 기존처럼 핵심 3개만 보이되 가로 overflow 없음

### 5.3 Overview hero

- hero의 좌우 폭을 넓히기 위해 rail과 stage padding 축소
- 배경에 CSS grid + mint/violet aurora 사용
- stance card는 `signal halo`를 포함한 rounded glass object로 전환
- 상승 경로 확률을 conic ring으로 시각화
- 문장과 확률의 의미 관계는 기존 deterministic logic 그대로 유지

### 5.4 Forecast bento

- 3개 동일 칸 → `1.16fr / .92fr / .92fr`
- 각 카드 210~236px 높이
- 첫 카드는 priority signal로 한 단계 강하게
- 실제 `forecast_history`로 mini sparkline 생성
- 확률, 변화량, deadline, round를 한 화면에서 읽음
- hover는 translateY 최대 4px + border glow만

### 5.5 Overview lower

- scenario와 deadline panel을 24px rounded glass로 전환
- scenario bar의 색 의미는 유지
- section 간 배경 반전 없이 같은 canvas 위 depth만 변경

### 5.6 Subpage hero

- 1px 직사각형 page-heading → 28px atmospheric header
- title size를 화면 폭에 맞게 축소해 첫 기능 영역을 더 빨리 노출
- heading stat은 inner glass object로 유지

### 5.7 Filter / table

- filter bar는 rounded glass, desktop에서 sticky
- input/select는 12px radius
- table shell은 20px radius
- table header는 sticky raised surface
- row hover는 약한 highlight만 사용
- status는 dot + pill로 표현

### 5.8 Chart / detail

- chart panel 24px radius, inner glow
- chart canvas 뒤에 아주 약한 gradient field 추가
- detail probability orb를 conic probability ring으로 변경
- round sidebar와 reasoning panel을 동일 surface system으로 통합

### 5.9 Command palette

단축키:

```text
Ctrl/⌘ + K  열기
/           입력창에 focus가 없을 때 열기
Escape      닫기
Enter       선택 route/question 이동
```

결과:

- 6개 main route
- question title 검색
- 최대 10개 결과
- keyboard focus return
- `role="dialog"`, `aria-modal`, label 제공

---

## 6. Motion 원칙

사용:

- route enter 220ms
- hero atmospheric drift 14~18s
- live dot pulse 2.4s
- forecast card stagger 40~80ms
- hover 160~220ms

금지:

- 계속 움직이는 chart
- 숫자 count-up으로 실제 값을 오인하게 하는 연출
- parallax
- cursor trail
- 과도한 glass blur

`prefers-reduced-motion: reduce`에서는 모두 사실상 정지한다.

---

## 7. Responsive 기준

### 1440×900

- 220px rail
- hero + stance + forecast card 3개 전체가 첫 viewport 안
- forecast grid bottom 목표 `<= 860px`

### 1024×768

- 82px compact rail
- hero 1열
- forecast card 3개는 3열 유지하되 210px 안팎
- 가로 overflow 0

### 390×844

- 64px glass mobile header
- drawer `min(86vw, 330px)`
- forecast card 1열
- command palette width `calc(100vw - 24px)`
- table만 자체 가로 scroll 허용, document overflow 0
- Escape·focus return 유지

---

## 8. 구현 파일

수정:

- `src/ai_fc/dashboard_template.html`
- `src/tests/test_dashboard.py`
- `reports/md/codex_to_claude_ui_handoff_260730.md`

추가:

- `reports/md/codex_startup_benchmark_design_plan_260730.md`

수정 금지:

- `src/ai_fc/dashboard.py`
- `forecasts/`
- `questions/`
- `calibration/`
- `data/`
- `.hashes`
- SQLite 파생 DB

---

## 9. 완료 조건

기능:

- 6개 route와 question detail 정상
- 모든 기존 chart·filter·range query 정상
- command palette mouse/keyboard 정상
- drawer Escape·focus return 정상

표현:

- 밝은 paper surface 0
- document horizontal overflow 0
- 첫 화면에 판단·stance·핵심 예측 3개 노출
- mini sparkline이 실제 history에서 생성
- violet이 data series에 사용되지 않음
- desktop/tablet/mobile tone 일치

검증:

- JavaScript syntax check
- `src/tests/test_dashboard.py`
- 1440×900
- 1024×768
- 390×844
- 공개 GitHub Pages 7개 route bright-surface audit

배포:

- 관련 파일만 commit
- `main` push
- GitHub `verify` success
- GitHub `pages` success
- 공개 URL 재확인
