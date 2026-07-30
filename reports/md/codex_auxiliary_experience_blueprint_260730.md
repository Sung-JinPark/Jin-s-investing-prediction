# Jin's Investing 부가기능·경험 확장 블루프린트

작성일: 2026-07-30 KST
대상: `Jin's Investing Prediction Solution`
범위: 부가기능, 탐색, 개인화, 공유, 데이터 신뢰성, 접근성, 미세 인터랙션
제외: 신규 예측 기능, AI 채팅, 모델 변경, DB schema 변경, 외부 데이터 수집

---

## 0. 결론

현재 사이트의 핵심 디자인은 이미 충분히 강하다. 다음 개편은 새 화면과 카드를 계속 추가하는 방식이 아니라,
기존 command palette를 중심으로 다음 다섯 기능을 하나의 `Workspace Utility System`으로 묶는 것이 가장
효율적이다.

1. Command Center 2.0 — 검색 + 작업 + 고정 항목 + 최근 항목
2. Data Status Drawer — 데이터 생성 시각·범위·신뢰 상태
3. Share / Print — 현재 화면 깊은 링크 공유와 보고서 출력
4. Focus / Density — 발표용 집중 모드와 정보 밀도 설정
5. Favorites / Recents — 별도 계정 없이 브라우저에만 저장

이 다섯 기능은 새 예측을 만들지 않는다. 이미 있는 콘텐츠를 더 빨리 찾고, 확인하고, 공유하고, 읽기 좋게
만드는 제품 기능이다.

---

## 1. 설계 원칙

### 1.1 유지할 것

- warm ivory canvas
- black typography
- orange / amber / crimson signal palette
- 208px segmented product rail
- 48px market strip
- 현재 hash routing
- vanilla HTML / CSS / JavaScript
- 단일 자기완결 dashboard HTML
- keyboard-first command palette
- reduced-motion 지원

### 1.2 추가하지 않을 것

- 새로운 예측·추천·매매 기능
- AI 질의 입력창 또는 챗봇
- 로그인·계정·서버 저장
- 실시간 알림 서버
- 외부 뉴스 feed
- 여러 색상 theme
- drag-and-drop dashboard builder
- 외부 UI library, icon package, web font, analytics SDK

### 1.3 품질 기준

기능은 다음 질문을 모두 통과할 때만 추가한다.

1. 현재 데이터만으로 동작하는가?
2. 사용자가 2회 이상 반복할 행동을 줄이는가?
3. 첫 화면의 시각적 힘을 약화시키지 않는가?
4. 모바일에서도 별도 기능 복제 없이 동작하는가?
5. 외부 네트워크 없이 저장된 HTML에서도 동작하는가?

---

## 2. 벤치마크 조사

### 2.1 직접 화면 조사

| 서비스 | 확인한 패턴 | 채택 판단 |
|---|---|---|
| [Linear](https://linear.app/) | 고정 navigation, 검색 가능한 command system, favorites, recent context, shortcut help | command palette를 기능 허브로 확장 |
| [Raycast](https://www.raycast.com/) | 모든 작업을 검색 가능한 action으로 통합, quick action, keyboard 중심 | 화면 버튼을 늘리지 않고 action registry 사용 |
| [Attio](https://attio.com/) | 넓은 여백, 얇은 경계, 실제 product chrome을 큰 visual로 사용, context action | 현재 light grid 유지, utility panel도 product UI처럼 설계 |
| [Stripe](https://stripe.com/) | live metric, 문장 내 색상 위계, 강한 정보 계층, 즉시 실행 CTA | 데이터 상태를 장식이 아니라 신뢰 신호로 사용 |
| [Koyfin](https://www.koyfin.com/features/watchlists/) | watchlist, custom view, share, 사용 빈도 기반 navigation | 계정 없는 local favorites와 pinned views로 축소 적용 |
| [TradingView](https://www.tradingview.com/features/) | quick search, saved layout, share/export, watchlist, contextual side tools | focus mode, deep link share, print/export만 선별 적용 |

### 2.2 공식 기능 문서 조사

| 서비스 | 공식 패턴 | 본 사이트 적용 |
|---|---|---|
| [Linear personalized sidebar](https://linear.app/changelog/2024-12-18-personalized-sidebar) | 중요 항목 고정, 불필요한 항목 숨김, 기본 view 지정 | 최대 8개의 local pin, command palette 상단 노출 |
| [Linear shortcut help](https://linear.app/changelog/2021-03-25-keyboard-shortcuts-help) | `?`로 검색 가능한 shortcut help | `?` shortcut sheet |
| [Raycast Quicklinks](https://www.raycast.com/core-features/quicklinks) | action과 목적지를 하나의 검색 목록으로 통합 | share, focus, density, status를 command action으로 등록 |
| [Koyfin customizable navigation](https://www.koyfin.com/help/release-notes/customizable-left-navigation/) | favorite, collapse, reorder, 자동 저장 | drag/reorder는 제외하고 pin만 적용 |
| [Koyfin watchlists](https://www.koyfin.com/features/watchlists/) | custom view, share, note, reusable configuration | local pin, share link, density preference |
| [TradingView watchlists](https://www.tradingview.com/support/solutions/43000745825-mastering-the-tradingview-watchlists/) | favorite list, summary, notes, details | alert와 note는 제외하고 favorites만 적용 |
| [Notion sidebar](https://www.notion.com/help/navigate-with-the-sidebar) | favorites, collapsible section, flexible sidebar | command palette에 collapsible pin/recent group |
| [Notion export](https://www.notion.com/help/export-your-content) | 공유 가능한 출력과 데이터 소유권 | browser print 기반 PDF 출력 |
| [Arc features](https://resources.arc.net/hc/en-us/categories/16435255982103-Features) | favorites, peek, split, spaces, quick lookup | peek/split은 제외, favorite와 focus만 적용 |

### 2.3 벤치마크에서 의도적으로 버릴 요소

- Linear/Raycast의 all-dark visual
- TradingView의 과도한 toolbar 밀도
- Stripe의 대형 gradient hero
- Koyfin의 복잡한 column configuration
- Notion의 중첩 sidebar tree
- Arc의 다중 workspace 개념

기능 원리는 가져오되 현재 Mistral-inspired light system의 톤과 정보 구조는 바꾸지 않는다.

---

## 3. 현 사이트 기능 공백

현재 보유:

- 6개 route navigation
- command palette
- 질문 검색·필터
- mobile drawer
- hash deep link
- chart hover tooltip
- pointer motion
- reduced-motion

현재 부재:

- 즐겨찾기·고정 항목
- 최근 본 화면·질문
- 현재 화면 공유
- 보고서 출력 mode
- 데이터 freshness 상세
- 사용자 정보 밀도 설정
- 발표용 focus mode
- shortcut help
- action 완료 feedback toast
- 개인 설정 저장

핵심 공백은 콘텐츠가 아니라 `workspace memory`와 `utility feedback`이다.

---

## 4. 우선순위 매트릭스

| 기능 | 사용자 가치 | 구현량 | 유지비 | 결정 |
|---|---:|---:|---:|---|
| Command Center 2.0 | 매우 높음 | 낮음 | 낮음 | P0 |
| Share / Copy deep link | 높음 | 낮음 | 낮음 | P0 |
| Data Status Drawer | 높음 | 중간 | 낮음 | P0 |
| Favorites / Recents | 높음 | 중간 | 낮음 | P0 |
| Focus mode | 중간 | 낮음 | 낮음 | P1 |
| Comfortable / Compact density | 중간 | 낮음 | 낮음 | P1 |
| Shortcut help | 중간 | 낮음 | 낮음 | P1 |
| Print / Save PDF | 중간 | 중간 | 낮음 | P1 |
| Optional welcome tour | 낮음 | 중간 | 중간 | P2 보류 |
| Multi-theme | 낮음 | 높음 | 높음 | 제외 |
| Alerts | 높음 | 매우 높음 | 매우 높음 | 제외 |
| News feed | 중간 | 매우 높음 | 매우 높음 | 제외 |
| 자유형 dashboard builder | 중간 | 매우 높음 | 매우 높음 | 제외 |

---

## 5. 정보 구조

새 route를 만들지 않는다.

```text
Product shell
├─ Product rail
│  ├─ Existing navigation
│  ├─ Command trigger
│  ├─ Utility strip
│  │  ├─ Pin current
│  │  ├─ Share current
│  │  └─ View controls
│  └─ Data status card → Status drawer
├─ Market strip
├─ Current route
├─ Command Center 2.0
├─ Status / View drawer
├─ Shortcut sheet
└─ Toast region
```

Command Center group 순서:

```text
작업
  현재 화면 고정
  링크 복사
  데이터 상태
  집중 모드
  보기 밀도
  인쇄 / PDF

고정
  사용자가 고정한 route 또는 질문

최근
  최근 방문한 route 또는 질문

화면
  기존 6개 route

예측 질문
  기존 질문 검색 결과
```

검색어가 있으면 모든 group을 통합 검색하고, 검색어가 없으면 위 순서를 유지한다.

---

## 6. Desktop 블루프린트

```text
┌──────── PRODUCT RAIL ────────┬──────────── MARKET STRIP ───────────────────────────┐
│ BRAND                         │ NASDAQ  ATH  −10%  BREADTH  REGIME     [⌘K COMMAND] │
├───────────────────────────────┼──────────────────────────────────────────────────────┤
│ 01 오늘의 판단               │                                                      │
│ 02 시장 전망                 │              CURRENT ROUTE                           │
│ 03 기간 조회                 │                                                      │
│ 04 예측 목록                 │                                                      │
│ 05 시점 조회                 │                                                      │
│ 06 적중 이력                 │                                                      │
│                               │                                                      │
│ [빠른 이동          ⌘K]      │                                                      │
│ [☆ PIN][↗ SHARE][≡ VIEW]     │                                                      │
│                               │                                                      │
│ ┌ DATA STATUS ─────────────┐ │                                                      │
│ │ ● CURRENT          P1    │ │                                                      │
│ │ Snapshot 08:08 KST       │ │                                                      │
│ └──────────────────────────┘ │                                                      │
└───────────────────────────────┴──────────────────────────────────────────────────────┘
```

### Utility drawer

```text
                              ┌──────── WORKSPACE ─────────┐
                              │ DATA STATUS        CURRENT │
                              │ generated  08:08 KST       │
                              │ questions  38              │
                              │ active     21              │
                              │ resolved    2              │
                              ├─────────────────────────────┤
                              │ VIEW                        │
                              │ density  [Comfort][Compact] │
                              │ focus    [Enter focus]      │
                              ├─────────────────────────────┤
                              │ OUTPUT                      │
                              │ Copy link                   │
                              │ Share                       │
                              │ Print / Save PDF            │
                              └─────────────────────────────┘
```

Drawer width: `min(390px, 100vw)`
Desktop: 오른쪽에서 진입
Mobile: 아래에서 올라오는 bottom sheet
새로운 full page modal을 만들지 않는다.

---

## 7. Mobile 블루프린트

기존 상단 `Search + Menu`는 유지한다. 새 bottom navigation은 추가하지 않는다.

```text
┌──────────────────────────────────┐
│ JIN'S / PREDICTION      [⌕][MENU]│
├──────────────────────────────────┤
│ compact market strip             │
├──────────────────────────────────┤
│ current route                    │
└──────────────────────────────────┘

MENU drawer bottom
┌──────────────────────────────────┐
│ [☆ 고정] [↗ 공유] [≡ 보기]      │
│ DATA STATUS · CURRENT            │
└──────────────────────────────────┘
```

모바일에서 utility drawer는:

- 화면 높이 최대 `78dvh`
- 상단 drag handle은 시각 요소로만 사용
- 실제 닫기는 close button, scrim, Escape로 제공
- safe-area inset 적용

---

## 8. 기능 상세 명세

### 8.1 Command Center 2.0

기존 command palette를 다시 만들지 않고 `commandCatalog()`를 action registry로 확장한다.

각 item schema:

```js
{
  id: "share-current",
  group: "작업",
  title: "현재 화면 링크 복사",
  hint: "현재 hash를 포함한 링크",
  keywords: ["share", "copy", "link", "공유"],
  run: () => shareCurrentView()
}
```

요구 동작:

- action과 navigation을 같은 결과 목록에서 탐색
- Enter 실행
- ArrowUp / ArrowDown 이동
- action 실행 후 palette 닫기
- 성공·실패 toast 제공
- 검색 결과 최대 12개
- 고정 8개, 최근 6개 제한

### 8.2 Favorites / Recents

저장 단위:

```js
{ hash: "#flow", title: "시장 전망", type: "route" }
{ hash: "#q/...", title: "NVDA ...", type: "question" }
```

규칙:

- 최대 pin 8개
- 최대 recent 6개
- 중복은 최근 시각만 갱신
- 존재하지 않는 hash는 자동 제거
- 현재 화면이 고정됐으면 `☆`가 `★`로 변경
- 계정 동기화는 하지 않음

### 8.3 Data Status Drawer

새 API 없이 현재 `DATA`에서 다음만 파생한다.

- `DATA.meta.generated`
- 등록 질문 수
- 진행 중 질문 수
- 해결 질문 수
- forecast round 총수
- model run / market run 수
- calibration sample 수

freshness:

```text
0–24h     CURRENT   orange
24–72h   AGING     amber
72h+      STALE     crimson
```

`LIVE DATA`라는 표현은 실제 streaming으로 오해될 수 있으므로 `DATA STATUS` 또는 `SNAPSHOT`으로 교체한다.

### 8.4 Share

우선순위:

1. `navigator.share` 지원 시 native share
2. `navigator.clipboard.writeText`
3. 임시 textarea copy fallback

공유 URL은 현재 pathname, query, hash를 보존한다.

제공 action:

- 현재 화면 링크 복사
- native share
- 현재 핵심 문구 복사

### 8.5 Focus mode

Focus mode:

- product rail 숨김
- market strip 숨김
- content margin 제거
- chart와 table 폭 확장
- 우측 상단에 작은 `EXIT FOCUS` pill
- `Escape`로 종료

Focus mode는 다음 방문까지 유지하지 않는다. 실수로 고립되는 것을 막기 위해 `sessionStorage`만 사용한다.

### 8.6 Density

두 단계만 제공한다.

```text
Comfortable  현재 간격 유지
Compact      table row, panel padding, card min-height 약 12–16% 축소
```

세 단계 이상은 불필요하다. density는 `localStorage`에 저장한다.

### 8.7 Shortcut help

`?`로 열고 `Escape`로 닫는다.

```text
⌘/Ctrl K   빠른 이동
/          검색
?          단축키
Shift P    현재 화면 고정
Shift S    공유
Shift F    집중 모드
Escape     닫기 / 집중 모드 종료
```

입력 요소에 focus된 동안 single-key shortcut은 실행하지 않는다.

### 8.8 Print / Save PDF

브라우저의 `window.print()`를 사용한다.

print CSS:

- rail, market strip, command, utility control 숨김
- body background white
- current route만 출력
- chart와 table page-break 보호
- URL·갱신 시각·면책 문구 표시
- ink 절약을 위해 grid opacity 축소

별도 PDF library는 추가하지 않는다.

### 8.9 Toast

화면 오른쪽 아래, 모바일은 하단 safe area 위.

상태:

- success: `링크를 복사했습니다`
- info: `집중 모드를 켰습니다`
- warning: `이 환경에서는 공유를 지원하지 않습니다`

한 번에 하나만 표시하며 2.4초 후 사라진다. `aria-live="polite"`를 사용한다.

---

## 9. 시각 디자인

새 색상을 만들지 않는다.

```text
action primary     #11110f
action signal      #ff4f17
warning            #ff9d19
danger / stale     #c9002d
surface            #ffffff
canvas             #fbfbf8
line               기존 --line
```

### Component geometry

| 요소 | 규격 |
|---|---|
| rail utility button | 40–44px height, square corner |
| utility drawer | 390px max width, 1px border |
| drawer section | 20–24px padding |
| toast | max 320px, black surface, orange leading rule |
| shortcut key | 24px min height, 2px radius 이하 |
| pin indicator | filled black star 또는 orange 3px marker |

### Motion

| 동작 | 시간 | easing |
|---|---:|---|
| drawer open | 240ms | cubic-bezier(.2,.8,.2,1) |
| scrim | 180ms | ease |
| toast enter | 180ms | ease-out |
| pin state | 160ms | ease |
| focus layout | 280ms | cubic-bezier(.2,.8,.2,1) |

`prefers-reduced-motion`에서는 opacity 외 transform을 제거한다.

---

## 10. 상태 저장 설계

하나의 key만 사용한다.

```js
const UI_KEY = "jin-investing-ui-v1";

{
  version: 1,
  density: "comfortable",
  pins: [],
  recent: []
}
```

원칙:

- 저장 실패 시 조용히 default state 사용
- user data나 질문 메모를 저장하지 않음
- 4KB 미만 유지
- schema version이 다르면 safe migration 또는 reset
- focus mode는 `sessionStorage`

---

## 11. 구현 구조

새 framework나 파일 분할 없이 기존 template에 최소 확장한다.

### HTML

```text
#utility-layer
#shortcut-layer
#toast-region
```

### JavaScript

```text
loadUIState()
saveUIState()
recordRecent()
toggleCurrentPin()
shareCurrentView()
setFocusMode()
setDensity()
renderUtilityPanel()
showToast()
printCurrentView()
```

기존 함수 재사용:

```text
commandCatalog()
renderCommandResults()
setCommand()
setDrawer()
route()
renderHeaderStrip()
```

### CSS

```text
.rail-utilities
.utility-layer / .utility-panel
.shortcut-layer / .shortcut-sheet
.toast-region / .toast
body.focus-mode
body.density-compact
@media print
```

---

## 12. 토큰·코드 효율 전략

### 작업 범위

수정 파일을 세 개로 제한한다.

1. `src/ai_fc/dashboard_template.html`
2. `src/tests/test_dashboard.py`
3. 이 blueprint 또는 handoff 문서

### 구현 예산

```text
HTML 추가       25–40 lines
CSS 추가        90–130 lines
JavaScript 추가 140–190 lines
test 추가       15–25 lines
외부 dependency 0
새 route        0
DB/API 변경     0
```

### 토큰 낭비 방지

- 이미 있는 command palette를 재사용
- desktop/mobile에 같은 state와 action registry 사용
- icon package 대신 문자·CSS shape 사용
- 설정 panel과 data status panel을 하나의 drawer로 통합
- favorites와 recents를 같은 item schema로 처리
- share와 copy를 하나의 함수에서 capability detection
- 기능별 별도 modal 대신 generic layer 사용
- 1차 구현 후 실제 브라우저에서 한 번에 전체 route 검증

---

## 13. 단계별 실행 계획

### Phase A — Foundation

- UI state loader
- toast
- generic utility layer
- keyboard shortcut registry

완료 조건:

- storage 차단 환경에서도 오류 없음
- Escape와 focus return 정상

### Phase B — Core utilities

- Command Center 2.0
- pins
- recents
- share / copy
- Data Status Drawer

완료 조건:

- 새 route 없이 모든 action 실행
- pin/recent가 새로고침 후 유지

### Phase C — View controls

- focus mode
- density
- print CSS
- mobile drawer utility row

완료 조건:

- 390px 가로 overflow 0
- print preview에서 chrome 숨김

### Phase D — Polish and QA

- hover / pressed / toast motion
- reduced-motion
- keyboard-only flow
- desktop 1280×720
- mobile 390×844
- 6 routes + detail + command + utility drawer
- 전체 test suite

---

## 14. Acceptance criteria

### 기능

- [x] 현재 화면을 한 번에 고정/해제할 수 있다.
- [x] 최근 방문 6개가 command palette에 표시된다.
- [x] 현재 화면의 deep link를 복사·공유할 수 있다.
- [x] 데이터 갱신 시각과 snapshot 범위를 확인할 수 있다.
- [x] focus와 density를 선택할 수 있다.
- [x] `?` shortcut help가 동작한다.
- [x] print/PDF에서 navigation chrome이 제거된다.

### 디자인

- [x] 첫 화면 hero의 크기와 위치가 변하지 않는다.
- [x] rail에 새 텍스트 메뉴를 추가하지 않는다.
- [x] utility UI가 ivory/white/black/orange 체계를 유지한다.
- [x] floating bubble을 남발하지 않는다.
- [x] drawer와 modal은 동시에 하나만 열린다.

### 접근성

- [x] 모든 utility action에 accessible name이 있다.
- [x] dialog open 시 focus 이동, close 시 focus 복귀
- [x] Escape 동작
- [x] `aria-live` toast
- [x] keyboard-only 실행
- [x] reduced-motion
- [x] 44px mobile target

### 성능·자기완결

- [x] 외부 resource 0
- [x] library 0
- [x] local state 4KB 미만
- [x] HTML 저장 후 기능 유지
- [x] JavaScript syntax 및 전체 test 통과

---

## 15. 권장 최종 실행 범위

다음 구현에서는 P0와 P1을 한 번에 적용하되 welcome tour는 제외한다.

```text
IN
  Command Center 2.0
  Favorites / Recents
  Data Status Drawer
  Share / Copy link
  Focus mode
  Density
  Shortcut help
  Print / Save PDF
  Toast feedback
  Mobile utility row

OUT
  onboarding tour
  alerts
  news
  account sync
  dark theme
  new prediction features
```

이 범위가 기능성, 세련미, 자기완결성, 구현 토큰 효율의 균형점이다.

---

## 16. 구현 결과

2026-07-30 기준으로 위 P0/P1 범위를 `src/ai_fc/dashboard_template.html`에 반영했다.

- 기존 read-model, 예측 질문, DB schema, route는 변경하지 않았다.
- `jin-investing-ui-v1` 하나에 고정 화면 최대 8개, 최근 화면 최대 6개, density만 저장한다.
- focus mode는 탭 세션에만 유지한다.
- Command Center는 작업·고정·최근·화면·예측 질문을 통합 검색한다.
- utility drawer와 shortcut sheet는 focus 이동/복귀, Escape, focus trap을 포함한다.
- Web Share 미지원 환경은 링크 복사로 내려간다.
- print CSS에서는 rail, mobile header, market strip, modal, toast를 제거한다.
- 외부 라이브러리와 외부 resource는 추가하지 않았다.

검증:

- 대시보드 계약 테스트 `8 passed`
- 전체 테스트 `140 passed`
- inline JavaScript syntax 검사 통과
- 로컬 GitHub Pages 산출물에서 Command Center, 고정/해제, toast, data status, density, shortcut sheet, focus mode를 실제 브라우저로 확인
- 런타임 console error 0, 중복 ID 0, 이름 없는 button 0
