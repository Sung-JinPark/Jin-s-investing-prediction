# Codex → Claude Code UI 인수인계

작성일: 2026-07-30 KST · all-dark revision
대상: Jin's Investing Prediction Solution  
배포 URL: https://sung-jinpark.github.io/Jin-s-investing-prediction/  
작업 성격: **UI 표현 계층 전면 재구축, 데이터·예측 로직 불변**

---

## 1. 결론

기존 공개본의 아래 3단 상단 구조를 제거했다.

```text
74px 전체 너비 브랜드 헤더
84px 전체 너비 시장 스트립
61px 전체 너비 가로 메뉴
```

총 219px를 사용하던 구조를 다음 제품 shell로 교체했다.

```text
desktop  : 236px persistent product rail + compact live row + content stage
tablet   : 84px compact rail + compact live row + content stage
mobile   : 64px mobile header + accessible drawer + compact live row
```

메인 첫 화면은 “사이트 설명 + 여러 운영 카드”가 아니라 다음 순서의 시장 브리핑으로 바꿨다.

1. 현재 시장 판단
2. 데이터 기반 market thesis
3. 현재 stance
4. 핵심 예측 확률 3개

운영 KPI, Brier, 전체 판정 일정은 첫 화면에서 제거했다.  
시나리오 분포와 가까운 판정일 3건은 first fold 아래에 배치했다.

---

## 2. 변경 파일

### `src/ai_fc/dashboard_template.html`

실제 UI 구현 파일이다.

변경 영역:

- CSS token과 application shell
- desktop rail
- tablet compact rail
- mobile header/drawer
- compact market live row
- overview market briefing
- 데이터 기반 thesis helper
- route active state
- drawer keyboard/focus 동작
- chart palette
- risk palette
- analog overlay palette
- history chart palette
- subpage heading stage
- responsive layout

### `src/tests/test_dashboard.py`

다음 UI 회귀 계약을 추가했다.

- `.product-rail` 필수
- `.mobile-drawer` 필수
- `.overview-stage` 필수
- drawer `aria-expanded` 및 `setDrawer()` 필수
- 구형 `.site-header` 금지
- 구형 `--blue` token 금지

### `reports/md/codex_to_claude_ui_handoff_260730.md`

현재 문서다.

---

## 3. 보존한 영역

다음 파일·데이터·로직은 수정하지 않았다.

- `src/ai_fc/dashboard.py`
- DB 스키마
- 질문 registry
- forecast 원본
- calibration ledger
- scenario 확률과 경로
- analog 원자료
- 질문별 최신 확률
- forecast round
- SVG tooltip 로직
- 기간 조회
- 시점 조회
- 질문 검색/필터
- 질문 상세와 round 선택
- hash route
- `window.__DATA__`
- `window.__DATA_URL__`
- `<!--DATA-->`
- 자기완결 HTML 계약

UI 작업으로 forecast나 calibration 값을 수정하지 말 것.

---

## 4. 최종 DOM 구조

```html
<body>
  <div class="product-shell">
    <aside class="product-rail">
      <a class="rail-brand" href="#overview">...</a>
      <nav class="view-nav" id="nav">...</nav>
      <div class="rail-status">...</div>
    </aside>

    <header class="mobile-header">...</header>
    <div class="drawer-backdrop">...</div>
    <aside class="mobile-drawer">
      <nav class="view-nav" id="mobile-nav">...</nav>
    </aside>

    <div class="content-shell">
      <div class="market-strip" id="mktstrip"></div>
      <main class="app-shell" id="app"></main>
      <footer class="site-footer">...</footer>
    </div>
  </div>

  <div class="tip" id="tip"></div>
</body>
```

구형 구조를 다시 추가하지 말 것.

금지:

- `.site-header` 복원
- 전체 너비 84px market card strip 복원
- 가로 6개 탭 내비게이션 복원
- mobile에서 좁은 가로 탭 사용

---

## 5. 내비게이션

### desktop `>=1280px`

- rail: 236px
- 브랜드, 번호, 메뉴명 모두 표시
- 활성 메뉴 우측 lime indicator
- rail 하단:
  - LIVE DATA
  - phase
  - NASDAQ 값
  - 갱신 시각

### tablet `800px~1279px`

- rail: 84px
- 숫자 `01~06`만 표시
- 접근 가능한 링크 이름은 DOM에 그대로 남아 있음
- 활성 indicator 유지

### mobile `<800px`

- desktop rail 숨김
- 64px mobile header 표시
- `MENU` 버튼으로 drawer 개방
- drawer 너비: `min(86vw, 330px)`
- backdrop 클릭으로 닫힘
- `Escape`로 닫힘
- 열릴 때 close 버튼으로 focus 이동
- 닫힐 때 MENU 버튼으로 focus 복귀
- 열려 있는 동안 body scroll lock
- 메뉴 선택 후 drawer 닫힘

### route active 처리

`route()`에서 두 nav를 함께 갱신한다.

```js
document.querySelectorAll('.view-nav a[data-v]')
```

질문 상세 `#q/<id>`에서는 `예측 목록`을 활성 메뉴로 표시한다.

모든 route는 실제 hash link다.

```text
#overview
#flow
#ask
#questions
#asof
#track
#q/<question-id>
```

현재 화면에는 `aria-current="page"`가 적용된다.

---

## 6. overview 첫 화면

### render 구조

`renderOverview()`는 다음 계층을 만든다.

```text
.overview-page
├─ .overview-stage
│  └─ .stage-inner
│     ├─ .overview-hero
│     │  ├─ .overview-copy
│     │  └─ .stance-card
│     └─ .forecast-grid
└─ .overview-lower-inner
   └─ .overview-lower
      ├─ 시나리오 분포
      └─ 가까운 판정일 3건
```

### market thesis

고정 마케팅 문구를 제거했다.

새 helper:

```js
marketThesis(upProb, rangeProb)
```

`data.scenario.paths`로 deterministic 문장을 만든다.

현재 데이터:

```text
상승 경로 = S1 50 + S2 16 = 66
조정·횡보 = S3 34
```

현재 표시 문구:

```text
단기 조정 위험은 남아 있지만,
연말 상승 경로가 66%로 우세합니다.
```

중요:

- 새 AI 호출 없음
- 질문별 확률과 scenario 확률 합산 없음
- scenario 데이터만으로 문장 결정
- 데이터 값이 바뀌면 문장도 자동 변경

### 핵심 forecast card

기존 `FEATURE_QIDS` 계약을 유지한다.

```text
nasdaq-corr10-augoct-2026
nasdaq-eoy-above-jul9-2026
nasdaq-ath-eoy-2026
```

표현:

- 하나의 dark grid
- 3열
- probability 72~96px
- bar는 모두 lime
- 상승 delta lime
- 하락 delta coral
- card 배경색은 통일
- hover는 최대 `translateY(-4px)`

기존처럼 카드마다 coral/teal/lime bar를 임의로 할당하지 않는다.

---

## 7. 색상 체계

source of truth:

```css
--ink: #06100d;
--ink-2: #0b1714;
--ink-3: #10231d;
--white: #ffffff;
--lime: #bcff71;
--lime-deep: #98dc55;
--teal: #57d4c8;
--coral: #ff8066;
--slate: #94a3b8;
--muted: rgba(255,255,255,.48);
```

역할:

| 의미 | 색 |
|---|---|
| 브랜드, active, 상승 우세 | lime |
| 비교 경로, 보조 모델 | teal |
| 하락, 위험, 오차 | coral |
| 과거 참조, 중립 | slate 또는 white alpha |
| 최상위 배경 | ink |
| 카드·표·필터 surface | ink-2 |
| 입력·표 머리글·내부 surface | ink-3 |

전체 제품은 **all-dark**다. `paper`, 흰 카드, 밝은 표 배경은 사용하지 않는다. 화면 구분은 밝기 반전이 아니라 `ink → ink-2 → ink-3`, 1px white-alpha border, 여백으로 만든다. 강조 색은 의미가 있는 데이터에만 쓴다.

삭제한 색 체계:

- 제품 강조용 blue
- risk amber/gold
- analog purple/pink/gold rainbow
- history chart gold

---

## 8. 차트 변경

차트 데이터와 tooltip은 유지했다.

### scenario

```text
S1 상승·ATH 돌파 = lime
S2 상승·ATH 미달 = teal
S3 조정·횡보 = coral
과거 유사 사이클 = slate dashed
```

### risk strip

```text
저 = teal
중 = slate
고 = coral
```

기존 중간 위험 amber를 제거했다.

### analog overlay

`ERA_META`를 다음 방식으로 통일했다.

```text
AI 현재       lime, 3px
닷컴 1996     teal, 2px
일본 1989     coral, 2px dashed
나머지 시대   white alpha + 서로 다른 dash
```

시대를 rainbow 색으로 구분하지 않는다.  
색, 굵기, dash를 함께 사용한다.

### 질문 상세 history

```text
AI 예측       lime
모델 앙상블   teal
시장 반영     slate
```

기존 시장 반영 gold를 제거했다.

---

## 9. subpage

다음 화면 기능은 그대로다.

- 시장 전망
- 기간 조회
- 예측 목록
- 시점 조회
- 적중 이력
- 질문 상세

공통 `.page-heading`을 dark editorial stage로 바꿨다.

특징:

- lime eyebrow
- 44~78px H1
- white title
- white alpha description
- `word-break: keep-all`

한글 단어가 `시 / 장`, `확 / 률`처럼 음절 중간에서 끊기던 현상을 방지했다.

예측 목록은 다음 흐름을 유지한다.

```text
dark page heading
→ search/filter command bar
→ forecast table
```

---

## 10. 반응형 실측

공개본과 동일한 embedded read model로 실제 브라우저 렌더를 검사했다.

### 1440×900

```text
rail width       236px
H1 font          75.6px
H1 bottom        y=412
stance bottom    y=472
forecast top     y=518
forecast bottom  y=817
forecast cards   3
horizontal overflow 없음
```

기존 공개본:

```text
forecast top     y≈688
forecast bottom  y≈1049
```

따라서 핵심 카드 3개가 첫 화면 안에 완전히 들어온다.

### 1024×768

```text
compact rail     84px
forecast top     y=500
forecast bottom  y=750
card height      248px
horizontal overflow 없음
```

### 390×844

```text
desktop rail     hidden
mobile header    64px
drawer width     330px
drawer x         0 when open
menu label       6개 모두 표시
Escape close     정상
focus return     menu-open
horizontal overflow 0
```

---

## 11. 검증 결과

### JavaScript

템플릿의 `<script>`를 추출해 Node syntax check를 통과했다.

```text
node --check
exit 0
```

### Python

```text
src/tests/test_dashboard.py
7 passed
```

### browser

검증 화면:

- overview 1440×900
- overview 1024×768
- overview 390×844
- mobile drawer open/close
- market flow
- questions

시장 전망:

```text
SVG 2개
첫 SVG  1000×483
둘째 SVG 1240×460
console error 0
active nav = 02 시장 전망
```

---

## 12. 데이터 검증과 로컬 DB 주의

UI 검수에는 Claude Code 메인 작업트리에서 생성된 기존 embedded model을 그대로 사용했다.

검수 model:

```text
questions   38
forecasts   21
resolved     2
```

현재 Codex 작업트리에 이전 브랜치에서 만들어진 파생 SQLite가 남아 있으면 단순 `dashboard` 생성 시 이전 forecast가 섞일 수 있다.

원칙:

- DB는 파생 인덱스다.
- 원본은 `forecasts/`, `questions/`, `calibration/`, `data/`다.
- 배포 CI는 clean checkout 후 `sync --rebuild`를 실행한다.
- 로컬 파생 DB를 이유로 forecast 원본이나 `.hashes`를 수정하지 않는다.
- UI 확인만 필요하면 clean main 작업트리 또는 기존 embedded model을 사용한다.

GitHub Pages workflow:

```text
checkout
→ dependency install
→ sync --rebuild
→ dashboard --pages-out ../_site
→ deploy
```

따라서 UI 커밋은 `src/ai_fc/dashboard_template.html` 변경만으로 Pages 재배포를 트리거한다.

---

## 13. 향후 Claude Code 작업 규칙

### UI 수정 시

1. `dashboard_template.html`을 수정한다.
2. `dashboard.py` read model은 UI 편의 때문에 바꾸지 않는다.
3. desktop rail과 mobile nav 항목을 같이 관리한다.
4. 새 route 추가 시 두 nav의 `data-v`를 같이 추가한다.
5. `route()`의 detail → questions active 처리를 보존한다.
6. chart 색은 `CHART_COL`, `ERA_META`의 의미 체계를 따른다.
7. `--blue`나 amber를 다시 제품 강조색으로 추가하지 않는다.
8. 첫 화면에 Brier/round/표본 KPI를 다시 넣지 않는다.
9. overview forecast grid bottom을 1440×900에서 880px 이하로 유지한다.
10. mobile drawer의 Escape와 focus return을 검사한다.

### 데이터 업데이트 시

UI 작업과 분리한다.

- forecast 추가는 새 immutable 파일
- ledger append-only
- 질문 기준 변경 금지
- UI 커밋에 예측값 변경을 섞지 않음

### 완료 전 필수 확인

```bash
python -m pytest src/tests/test_dashboard.py -q
```

그리고 다음 viewport를 실제 렌더한다.

```text
1440×900
1024×768
390×844
```

---

## 14. 되돌리지 말아야 할 핵심 판단

이번 UI의 중심 판단은 다음과 같다.

> 여섯 화면은 보고서 탭이 아니라 하나의 예측 제품 안에 있는 도구다.

따라서:

- 메뉴는 persistent rail
- 첫 화면은 market briefing
- 운영 도구는 route 뒤
- chart는 dark analysis surface
- table·filter·detail은 ink-2/ink-3 data workspace
- 색은 lime/teal/coral/slate 역할 기반

다음 회귀는 금지한다.

- `--paper` 토큰 재도입
- `background:#fff` 카드·표·입력
- overview 아래에서 갑자기 밝아지는 section
- 다크 배경에서 명도가 낮은 `SCEN_DEEP` 시나리오 색

“기능이 보이게만” 만들기 위해 다시 작은 카드와 가로 탭을 쌓으면 이전 구식 dashboard로 회귀한다.

첫 화면의 성공 기준은 장식의 양이 아니라 다음 질문에 3초 안에 답하는 것이다.

```text
지금 시장 판단은 무엇인가?
상승/조정 시나리오의 무게는 얼마인가?
핵심 예측 확률 3개는 무엇인가?
더 자세한 분석은 어디서 여는가?
```

현재 구조는 이 네 질문을 순서대로 답하도록 설계되어 있다.
