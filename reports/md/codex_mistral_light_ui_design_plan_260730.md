# Mistral-inspired Light Intelligence UI 설계

작성일: 2026-07-30 KST
대상: Jin's Investing Prediction Solution
범위: UI, interaction, responsive, accessibility
불변: DB, forecast 원본, 질문 registry, calibration ledger, 확률·판정 로직

---

## 1. 직접 조사 결과

기준 사이트: https://mistral.ai/

1280×720 공개 화면을 직접 렌더링하고 pointer hover 전후, 하단 사례 카드, CTA 내부 구조를 확인했다.

### 시각 언어

- canvas: `rgb(251,251,248)`에 가까운 warm ivory
- typography: 거의 검정인 초대형 sans headline
- 구조: radius와 shadow보다 1px 회색 grid line으로 영역을 나눔
- signal color: orange, red, crimson, amber를 큰 pixel mosaic로 사용
- navigation: 48px segmented bar, 검정 CTA 한 개
- product proof: 장식 카드보다 실제 사례·뉴스·제품 화면을 크게 노출

### motion 실측

```text
hover utility 적용 요소  370개
transition 적용 요소      614개
CSS animation 요소          4개
hero interactive canvas     1개, 884×288
주요 transition             300ms ease
```

확인한 동작:

1. CTA에서 왼쪽 화살표가 들어오고 기존 오른쪽 화살표가 나간다.
2. CTA text도 같은 방향으로 약간 이동한다.
3. 뉴스·목록 row는 hover 시 전체 내용이 약 32px 옆으로 밀린다.
4. hero의 orange/red pixel field는 시간과 pointer 위치에 반응한다.
5. 고객 사례는 큰 가로 carousel이며, 한 viewport에 다음 카드 일부를 노출한다.
6. motion은 색 번쩍임이 아니라 위치·crop·arrow 교대에 집중한다.

---

## 2. 번역 원칙

Mistral을 복제하지 않고 prediction product 문법으로 번역한다.

| Mistral 요소 | 예측 제품 적용 |
|---|---|
| orange/red hero canvas | 확률 크기에 반응하는 signal mosaic |
| segmented top navigation | segmented light product rail |
| black CTA | command palette trigger |
| moving news rows | forecast/deadline row slide |
| large customer carousel | 핵심 forecast 3개 bento rail |
| pixel mascot/icon | 4×4 signal mark |
| ivory canvas | 전 route warm ivory workspace |

---

## 3. 디자인 시스템

### Palette

```css
--paper:       #fbfbf8;
--paper-2:     #f4f3ed;
--surface:     #ffffff;
--ink:         #11110f;
--ink-soft:    #2c2b27;
--muted:       #706f68;
--line:        #d9d8d1;
--line-strong: #b8b6ad;
--orange:      #ff4f17;
--amber:       #ff9d19;
--red:         #e30b17;
--crimson:     #c9002d;
--positive:    #147a55;
--teal:        #247d78;
```

규칙:

- 전체 화면의 85% 이상은 paper/surface 계열이다.
- 검정은 rail 일부가 아니라 headline, chart axis, primary CTA에 사용한다.
- orange/red는 브랜드 신호와 시나리오 데이터에만 사용한다.
- 상승·하락 변화량은 positive/red의 의미색을 유지한다.
- glow, glass blur, violet gradient는 제거한다.

### Geometry

- 기본 radius: 0~4px
- floating dialog만 14px
- card 구분: shadow보다 1px line
- section grid: 48px 단위의 약한 배경 grid
- rail: 208px desktop, 76px tablet
- intelligence bar: 48px

### Type

- hero: 56~88px, line-height .91
- subpage title: 44~76px
- probability: 74~104px mono
- label: 8~10px mono uppercase
- 본문: 13~17px

---

## 4. 화면 설계

### Overview

```text
┌──────── light segmented rail ────────┐
│ 48px intelligence bar                │
│                                      │
│ giant market thesis  │ stance signal │
│                      │ mosaic field  │
│──────────────────────────────────────│
│ priority forecast │ forecast │ forecast
└──────────────────────────────────────┘
```

- hero 문장은 검정, 핵심 확률 문장만 orange
- stance는 원형 glow가 아니라 정사각 signal gauge
- 4×4 mosaic cell의 크기·불투명도를 상승/조정 확률에 연결
- pointer 이동 시 cell마다 서로 다른 depth로 최대 18px 이동
- pointer leave 시 spring-like 420ms로 원위치

### Forecast cards

- 흰 surface, 검정 probability, orange/amber/crimson top band
- hover:
  - 카드 `translateY(-6px)`
  - pointer 방향으로 최대 1.2° tilt
  - title과 arrow `translateX(10px)`
  - sparkline draw 강조
  - pixel corner가 90° 회전
- touch와 reduced-motion에서는 tilt 없음

### Subpages

- hero panel의 glass와 glow 제거
- chart·table은 흰색 분석 surface
- chart grid와 axis는 회색, 시나리오는 orange/amber/crimson
- filter bar는 ivory segmented control
- table row hover는 orange left rail + content slide 8px
- detail probability는 원형 halo 대신 square segmented meter

### Command palette

- black scrim은 낮은 불투명도
- white dialog + black type
- active result는 orange strip
- row hover는 Mistral식 arrow exchange

---

## 5. Motion 시스템

### pointer

- `pointermove`는 `requestAnimationFrame`으로 한 frame에 한 번만 처리
- `pointer: fine`에서만 활성화
- 요소당 최대 변화:
  - mosaic: 18px
  - card tilt: 1.2deg
  - card lift: 6px
  - row slide: 10px

### scroll/entry

- route enter: 260ms opacity + 14px
- overview headline: line reveal 420ms
- forecast cards: 55ms stagger
- live indicator: 2.8s step pulse

### accessibility

`prefers-reduced-motion: reduce`:

- mosaic pointer listener 비활성
- tilt 비활성
- animation/transition 사실상 정지
- 정보와 hover affordance는 color/border로 유지

---

## 6. 구현 범위

수정:

- `src/ai_fc/dashboard_template.html`
- `src/tests/test_dashboard.py`
- `reports/md/codex_to_claude_ui_handoff_260730.md`

추가:

- `reports/md/codex_mistral_light_ui_design_plan_260730.md`

수정 금지:

- `src/ai_fc/dashboard.py`
- `forecasts/`
- `questions/`
- `calibration/`
- `.hashes`
- 확률·scenario path·판정 값

---

## 7. 완료 조건

- 모든 route가 warm light surface로 렌더링
- dark full-page section 0개
- hero signal mosaic가 실제 확률로 생성
- pointer mosaic와 forecast tilt 정상
- hover row slide와 arrow exchange 정상
- `prefers-reduced-motion` 계약 보존
- desktop/tablet/mobile document overflow 0
- 기존 chart, tooltip, search, range, as-of, detail 정상
- 전체 Python 테스트 통과
- 공개 GitHub Pages에서 최종 재검증
