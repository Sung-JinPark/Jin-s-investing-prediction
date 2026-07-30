# Jin's Investing — Experience Layer V2 Blueprint

작성일: 2026-07-30 KST

대상: `Jin's Investing Prediction Solution`

목표: 새로운 예측 로직이나 외부 데이터 없이, 기존 분석을 더 빠르게 이해하고 더 즐겁게 탐색하도록 만든다.

---

## 1. 이번 개선의 판단 기준

현재 사이트는 다음 단계까지 이미 도달했다.

- Mistral 계열의 warm ivory, black, orange 조합
- 제품형 좌측 rail
- Command Center
- 고정 화면, 최근 화면, 공유, 데이터 상태
- focus mode, density, shortcut, print
- 카드 tilt, pointer spotlight, signal mosaic

따라서 이번 작업은 메뉴나 카드 수를 늘리는 방식이 아니라 다음 질문에 답해야 한다.

1. 첫 방문자가 30초 안에 오늘의 핵심을 이해할 수 있는가?
2. 긴 분석 화면에서 지금 어디를 읽는지 알 수 있는가?
3. 상세 화면을 열지 않고도 다음 행동을 판단할 수 있는가?
4. 사용자가 자기 생각을 사이트 안에 남길 수 있는가?
5. 동적 효과가 장식이 아니라 피드백으로 작동하는가?

---

## 2. 벤치마크 리서치

### 2.1 Linear — Contextual command와 invisible detail

참조:

- https://linear.app/now/invisible-details
- https://linear.app/changelog/2019-10-07-contextual-command-menu
- https://linear.app/docs/favorites

확인한 패턴:

- 동일 행동을 mouse와 keyboard 양쪽에서 실행
- 현재 문맥에 맞는 action만 노출
- 자주 쓰는 화면은 favorites로 승격
- peek와 command menu가 동시에 충돌하지 않도록 제어
- 빠른 조작을 가르치는 shortcut hint

적용점:

- Quick Peek는 command, drawer, briefing이 열리면 즉시 닫는다.
- briefing과 note action을 Command Center에도 등록한다.
- hover뿐 아니라 keyboard focus에서도 동일 정보를 제공한다.

### 2.2 Attio — Workspace navigation과 개인화

참조:

- https://attio.com/help/reference/productivity-collaborating/navigating-your-workspace

확인한 패턴:

- sidebar, search, quick action이 하나의 workspace 구조로 연결
- `/`, `Cmd/Ctrl K`, `?`가 서로 다른 목적을 명확히 담당
- 개인이 자주 쓰는 정보에 빠르게 다시 접근

적용점:

- 새 기능을 새 top-level 메뉴로 만들지 않는다.
- briefing, note, motion preference는 기존 utility와 command에 흡수한다.
- state는 device-local로 제한한다.

### 2.3 Koyfin — Custom dashboard와 shareable insight

참조:

- https://www.koyfin.com/features/custom-dashboards/
- https://www.koyfin.com/help/topic/functionality/
- https://www.koyfin.com/help/my-dashboards-groups/

확인한 패턴:

- 한 화면에서 필요한 정보만 밀도 있게 정리
- 사용자가 자기 방식으로 dashboard를 구성
- chart와 insight를 쉽게 공유
- 관련 widget끼리 문맥을 공유

적용점:

- 화면별 note를 저장해 사용자의 research context를 유지한다.
- section navigator는 현재 route 안의 의미 있는 분석 block만 보여준다.
- 기존 share 기능과 note copy를 연결한다.

### 2.4 TradingView — Watchlist, notes, workspace continuity

참조:

- https://www.tradingview.com/support/solutions/43000745825-mastering-the-tradingview-watchlists/
- https://www.tradingview.com/support/solutions/43000520149-introduction-to-tradingview-alerts/
- https://www.tradingview.com/support/solutions/43000673888-tradingview-desktop-releases-and-release-notes/

확인한 패턴:

- asset detail을 열지 않고 watchlist에서 핵심 지표 확인
- symbol별 note
- tab별 workspace 상태 기억
- 기능이 많아져도 최소 표시 모드를 제공

적용점:

- Quick Peek는 probability, 변화, deadline, driver만 보여준다.
- note는 route 또는 question hash별로 분리한다.
- motion preference도 density처럼 기억한다.

제외:

- 실시간 alert, notification permission, 외부 가격 API

### 2.5 Notion — Peek와 hover table of contents

참조:

- https://www.notion.com/en-gb/help/intro-to-databases
- https://www.notion.com/en-gb/help/columns-headings-and-dividers

확인한 패턴:

- 항목은 우선 peek로 열어 navigation cost를 줄임
- 긴 문서는 오른쪽 table of contents가 현재 위치를 따라감
- 목차는 평소 작게 있다가 hover 시 확장

적용점:

- 데스크톱 우측에 compact section navigator 배치
- active section과 전체 scroll progress 표시
- forecast/deadline 항목은 비모달 Quick Peek 제공

### 2.6 Wise — Snappy, fluid, intuitive motion

참조:

- https://wise.design/foundations/motion-system

확인한 패턴:

- 빠르지만 과잉 반응하지 않는 snappy motion
- 자연스러운 무게와 방향
- 숫자 변화는 즉각적인 feedback으로 사용
- motion sickness를 유발하는 반복 효과 배제

적용점:

- 180–420ms 안에서 끝나는 one-shot motion
- 무한 loop와 flash 추가 금지
- number roll은 route 진입 때 한 번만 실행
- 사용자가 motion을 reduced로 고정할 수 있게 한다.

### 2.7 Vercel — Interactive tour와 interface discipline

참조:

- https://vercel.com/blog/designing-the-vercel-virtual-product-tour
- https://vercel.com/design/guidelines
- https://vercel.com/blog/improving-the-accessibility-of-our-nextjs-site

확인한 패턴:

- 복잡한 제품을 짧은 interactive tour로 체험
- keyboard everywhere
- 명확한 focus, focus move/return, 44px mobile target
- CSS motion 우선, reduced-motion 존중
- 큰 WebGL 효과도 정보 전달을 방해하지 않도록 제한

적용점:

- 3-step Guided Briefing
- 자동 재생하지 않고 사용자가 다음 장을 결정
- Arrow, Escape, Tab 지원
- CSS transition 우선, dependency 0

### 2.8 Mistral — 큰 장면과 반응형 오브젝트

참조:

- https://mistral.ai/

실제 화면에서 확인한 패턴:

- 첫 화면은 하나의 큰 메시지와 큰 시각 장면으로 구성
- 화면 이동과 hover에 맞춰 큰 오브젝트가 반응
- 요소가 많아도 강조색 수는 제한

적용점:

- hero를 다시 쪼개지 않는다.
- Guided Briefing을 별도 큰 scene으로 만든다.
- 기존 orange/amber/crimson만 사용한다.

---

## 3. 최종 구현 범위

### P0 — Guided Briefing

기존 데이터를 세 장의 큰 scene으로 재구성한다.

1. Market stance
   - 현재 thesis
   - 상승 경로와 조정·횡보 비중
   - signal mosaic
2. Featured forecast
   - 대표 질문
   - 현재 probability
   - 직전 회차 대비 변화
3. Next decision
   - 가장 가까운 판정일
   - 해당 질문 probability
   - 상세 화면 바로가기

진입:

- overview hero의 `3 STEP BRIEFING` 버튼
- Command Center
- utility drawer
- `Shift + B`

동작:

- modal full scene
- Previous / Next / Done
- Left / Right arrow
- Escape close
- focus trap과 focus return
- mobile full-screen
- auto-play 없음

### P0 — Smart Section Navigator

각 route의 의미 있는 section을 자동 추출한다.

대상:

- overview stage
- page heading
- chart panel
- analysis panel
- 일반 panel
- table shell
- metric/track summary

규칙:

- 최대 7개
- 중첩 block은 상위 의미 단위 우선
- 제목은 `h1`, `h2`, `aria-label` 순
- 오른쪽 fixed navigator
- active item은 orange
- progress line은 전체 문서 scroll과 동기화
- hover/focus 시 label 확장
- 1050px 이하에서는 navigator를 숨기고 3px progress bar만 유지

### P0 — Quick Peek

`data-q`가 있는 forecast와 deadline 항목에 non-modal preview를 붙인다.

표시:

- title
- domain / round
- current probability
- latest delta
- deadline
- driver 최대 2개

동작:

- fine pointer hover 220ms
- keyboard focus 즉시
- pointer leave, blur, scroll, route change에 close
- command, utility, shortcut, briefing과 동시에 표시하지 않음
- touch에서는 비활성
- `role="tooltip"`과 `aria-describedby`

### P1 — Local Research Note

현재 hash별 device-local note를 제공한다.

규칙:

- 최대 700자
- utility drawer에서 편집
- 입력 즉시 local save
- `현재 기기에 저장됨` 상태
- 글자 수 표시
- note copy
- Command Center에서 `현재 화면 메모`
- `Shift + N`

저장 구조:

```json
{
  "version": 1,
  "density": "comfortable",
  "motion": "adaptive",
  "pins": [],
  "recent": [],
  "notes": {
    "#overview": "..."
  }
}
```

보존:

- 기존 `jin-investing-ui-v1` key 유지
- 기존 사용자 state와 호환
- 존재하는 route/question note만 유지
- 최대 20개 note

### P1 — Motion Engine 2.0

추가:

- section scroll reveal
- route 진입 number roll
- section navigator progress
- briefing scene transition
- compact surface spotlight

motion preference:

- `Adaptive`: OS `prefers-reduced-motion` 준수
- `Reduced`: 사용자 설정으로 모든 transform/count/reveal 축소

금지:

- 무한 ticker
- 자동 carousel
- flashing
- 배경 전체를 따라다니는 cursor
- finance data를 늦게 읽게 만드는 긴 count-up

---

## 4. 화면 구조

### Desktop

```text
┌──────── rail ────────┬──────── market strip ─────────────────────┐
│ nav                  │ 3px route progress                        │
│ command              ├────────────────────────────────────────────┤
│ utilities            │                                            │
│ data status          │  existing route content        section map │
│                      │                                 01 ━ label  │
│                      │                                 02 ━ label  │
│                      │                                 03 ━ label  │
└──────────────────────┴────────────────────────────────────────────┘

Guided Briefing
┌───────────────────────────────────────────────────────────────────┐
│ BRIEFING 01/03                                      CLOSE          │
│                                                                   │
│ very large statement             responsive signal object         │
│                                                                   │
│ PREVIOUS                                      NEXT →              │
└───────────────────────────────────────────────────────────────────┘
```

### Mobile

```text
┌─────────────────────────────────┐
│ header                          │
│ 3px route progress              │
├─────────────────────────────────┤
│ existing route content          │
│                                 │
└─────────────────────────────────┘

Briefing은 full-screen이고 controls는 safe-area 위에 고정한다.
Quick Peek과 section map은 표시하지 않는다.
```

---

## 5. Visual system

기존 token을 유지한다.

- Canvas: `#fbfbf8`
- Surface: `#ffffff`
- Text: `#11110f`
- Primary action: `#ff4f17`
- Secondary signal: `#ff9d19`
- Risk: `#c9002d`
- Grid/line: `#d9d8d1`

새 요소:

- Briefing background: paper grid + black/orange geometric block
- Peek: white surface, black 1px border, 10px offset shadow
- Section map: white translucent surface, black line, orange active
- Progress: orange → amber gradient
- Note: paper textarea, monospace metadata

radius는 기존 Mistral revision과 맞춰 `0–2px`를 기본으로 한다.

---

## 6. Interaction timing

| Interaction | Duration | Curve |
|---|---:|---|
| Briefing open | 240ms | cubic-bezier(.2,.8,.2,1) |
| Briefing step | 180ms | ease-out |
| Section reveal | 360ms | cubic-bezier(.2,.8,.2,1) |
| Peek open | 160ms | ease-out |
| Number roll | 420ms max | ease-out |
| Progress | 80ms | linear |

모든 motion은 opacity와 transform 중심으로 구현한다.

---

## 7. 상태와 충돌 규칙

동시에 열릴 수 있는 modal은 하나다.

```text
Command
Utility
Shortcut
Briefing
Mobile Drawer
```

하나를 열면 나머지를 닫는다.

Quick Peek은 modal이 아니지만 위 레이어 중 하나라도 열리면 닫는다.

Focus mode와 Briefing:

- briefing은 focus mode 위에서도 열 수 있다.
- briefing close 후 이전 focus로 복귀한다.

Route change:

- peek close
- briefing close
- section observer cleanup
- 새 section map 재구축
- scroll progress reset

---

## 8. 접근성

- briefing `role="dialog"`, `aria-modal="true"`
- title은 `aria-labelledby`
- step 변화는 `aria-live="polite"`
- focus open/return
- Tab focus trap
- Arrow key는 editing target에서 무시
- section map button에 전체 section title 제공
- Quick Peek은 tooltip
- note textarea는 label과 max length 제공
- mobile hit target 44px 이상
- reduced-motion OS와 local preference 모두 존중
- CSS가 없는 상태에서도 기존 hash navigation 유지

---

## 9. 성능·자기완결 원칙

- dependency 0
- external resource 0
- API 0
- DB/schema 변경 0
- canvas/WebGL 0
- IntersectionObserver 재사용
- scroll handler는 requestAnimationFrame throttle
- pointermove는 fine pointer에서만
- route change마다 observer와 handler cleanup
- local note는 최대 20개 × 700자

---

## 10. 구현 순서

### Phase A — Shell

- route progress
- section navigator shell
- quick peek shell
- briefing dialog shell
- CSS와 responsive states

### Phase B — Data and state

- motion preference
- note sanitization
- note editor
- briefing scene model
- command and shortcut actions

### Phase C — Dynamic bindings

- section extraction
- IntersectionObserver
- scroll progress
- reveal
- number roll
- Quick Peek position and lifecycle

### Phase D — QA

- 6 routes + question detail
- modal exclusivity
- keyboard-only
- reduced motion
- desktop 1280×720
- mobile CSS contract
- print contract
- self-contained contract
- complete Python test suite

---

## 11. Acceptance criteria

### Guided Briefing

- [x] 기존 DATA만 사용한 3개 scene
- [x] hero, command, utility, shortcut에서 진입
- [x] prev/next/done과 arrow key
- [x] focus trap, Escape, focus return
- [x] mobile full-screen

### Navigation

- [x] route마다 2–7개 section 자동 구성
- [x] active section이 scroll에 따라 변경
- [x] click 시 section 이동
- [x] progress가 0–100%로 동기화
- [x] route change cleanup

### Quick Peek

- [x] hover와 keyboard focus
- [x] 핵심 6개 필드 표시
- [x] modal/scroll/route에서 close
- [x] touch hidden

### Notes

- [x] hash별 700자 local note
- [x] autosave와 char count
- [x] note copy
- [x] 기존 state migration 없이 호환

### Motion

- [x] reveal과 number roll은 one-shot
- [x] Adaptive/Reduced 선택
- [x] OS reduced-motion 준수
- [x] 반복 flash와 auto-play 없음

### 품질

- [x] 외부 resource와 dependency 0
- [x] runtime error 0
- [x] duplicate ID 0
- [x] unnamed button 0
- [x] JavaScript syntax 통과
- [x] 전체 test suite 통과

---

## 12. 의도적으로 제외하는 기능

- 새로운 예측 질문
- 실시간 market API
- notification/alert
- account/login/cloud sync
- social feed/news
- dark theme
- chart drag editing
- sound
- confetti/gamification
- WebGL/3D library
- auto-advancing carousel

이 기능들은 현재 사이트의 목적보다 유지보수와 주의 분산 비용이 크다.

---

## 13. 최종 결론

이번 버전의 핵심은 “더 많은 페이지”가 아니라 “기존 페이지가 사용자에게 반응하는 방식”이다.

Guided Briefing은 첫 이해 시간을 줄이고, Section Navigator는 긴 분석의 방향을 잡아준다. Quick Peek은 navigation 비용을 낮추고, Local Note는 사이트를 개인 research workspace로 바꾼다. Motion Engine은 이 모든 행동을 짧고 명확하게 연결한다.

이 다섯 기능이 현재 디자인을 해치지 않으면서 체감 고도화를 가장 크게 만드는 조합이다.

---

## 14. 구현 결과

2026-07-30 기준으로 P0/P1 전체 범위를 구현했다.

- Guided Briefing 3 scene
- route-aware Smart Section Navigator
- scroll progress
- hover/focus Quick Peek
- hash별 Local Research Note
- Adaptive/Reduced Motion
- section reveal과 one-shot number roll
- Command Center, utility drawer, keyboard shortcut 통합

검증:

- 대시보드 계약 테스트 `8 passed`
- 사용자 로컬 전용 예측 파일을 제외한 작업 폴더 테스트 `139 passed`
- 동일 변경을 깨끗한 Git 기준 상태에 적용한 전체 테스트 `140 passed`
- inline JavaScript syntax 통과
- 실제 1280×720 Pages 산출물에서 briefing, arrow navigation, focus return, section map, scroll progress, note persistence, motion preference 확인
- runtime error 0
- duplicate ID 0
- unnamed button 0

데이터와 예측 로직:

- DB/schema 변경 없음
- 질문/확률/시나리오 계산 변경 없음
- 외부 API와 외부 resource 추가 없음
