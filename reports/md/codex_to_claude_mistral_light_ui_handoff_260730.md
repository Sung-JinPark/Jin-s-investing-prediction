# Codex → Claude Code: Mistral Light UI 인수인계

작성일: 2026-07-30 KST  
대상: Jin's Investing Prediction Solution  
상태: 구현 및 브라우저 검증 완료

> 이 문서는 이전 `Signal Glass` 다크 UI 인수인계를 대체한다. 앞으로 UI를 수정할 때는 이 문서와
> `codex_mistral_light_ui_design_plan_260730.md`를 현재 기준으로 사용한다.

## 1. 이번 변경의 목적

기존 DB, 질문, 예측 확률, 캘리브레이션, 차트 계산 로직은 유지하면서 화면만 Mistral AI의 시각 언어를
참고한 밝은 분석 제품으로 재설계했다. 복제보다는 다음 원리를 투자 예측 대시보드 문법으로 번역했다.

- warm ivory 캔버스와 흰색 데이터 surface
- 거대한 검정 타이포그래피와 orange/red 신호색
- 둥근 glass card 대신 1px 격자와 직선형 product rail
- probability를 보여 주는 4×4 signal mosaic
- 카드·행·CTA가 pointer 위치에 반응하는 짧고 명확한 motion

## 2. 소스 범위

- UI와 interaction: `src/ai_fc/dashboard_template.html`
- UI 계약 테스트: `src/tests/test_dashboard.py`
- 상세 설계 근거: `reports/md/codex_mistral_light_ui_design_plan_260730.md`

DB schema, ingest, forecast registry, read model, chart 산식은 변경하지 않았다.

## 3. 현재 디자인 토큰

```css
--paper: #fbfbf8;
--surface: #fff;
--ink: #11110f;
--muted: #77746d;
--line: rgba(17,17,15,.14);
--orange: #ff4f17;
--amber: #ff9d19;
--crimson: #c9002d;
--teal: #247d78;
```

### Typography refinement

- display: `Segoe UI Variable Display` / `SF Pro Display` 우선 native variable stack
- body: `Segoe UI Variable Text` / `SF Pro Text` 우선 native variable stack
- 한국어 fallback: `Apple SD Gothic Neo` → `Noto Sans KR` → `Malgun Gothic`
- 숫자·라벨: 기존 monospace stack 유지
- overview headline: desktop `clamp(52px, 4.7vw, 72px)`, mobile `clamp(42px, 10.8vw, 52px)`
- headline tracking: `-.055em` desktop, `-.05em` mobile
- headline line-height: `.97` desktop, `.98` mobile

외부 폰트를 로드하지 않는다. 저장된 report HTML도 동일하게 보이는 자기완결 원칙을 지키면서 각 운영체제의
가장 정교한 native variable font를 사용한다.

색상 역할을 임의로 바꾸지 않는다.

- orange: 주 시나리오, 상승 신호, 현재 선택
- amber: 보조 시나리오와 중립 강조
- crimson: 하방 위험과 경고
- teal: 비교 계열과 역사적 reference
- black: navigation active state와 최상위 판단

## 4. 핵심 interaction

### Signal mosaic

`signalMosaic(prob)`가 16개 셀의 활성 개수와 색을 확률에서 계산한다.  
`bindDynamicMotion(root)`가 pointer 위치에 따라 각 셀을 서로 다른 depth로 이동·회전시킨다.

### Forecast card

fine pointer 환경에서 카드가 아주 작게 tilt되고, pointer 위치를 따라 radial spot이 이동한다.
동시에 제목이 오른쪽으로 이동하고 진입 화살표가 나타난다. `pointerleave` 시 원상복구된다.

### Rows와 navigation

표 행은 hover 시 orange inset 신호와 짧은 수평 이동을 사용한다. 활성 메뉴는 검정 면과 orange bar로
명확하게 구분한다.

### 접근성

- `prefers-reduced-motion: reduce`에서는 transform과 animation을 제거한다.
- coarse pointer에서는 JS tilt/mosaic motion을 바인딩하지 않는다.
- command palette, mobile drawer, navigation의 기존 keyboard와 ARIA 계약을 유지한다.

## 5. 반응형 구조

- desktop: 208px segmented product rail + 48px market strip
- tablet: 76px compact rail
- mobile: 64px header + 330px 이하 drawer

390×844에서 가로 넘침 없이 hero, stance mosaic, drawer가 동작하는 것을 확인했다.

## 6. 후속 수정 규칙

1. 검정 전체 배경, violet ambient glow, glass blur panel을 다시 도입하지 않는다.
2. 카드 radius를 키워 일반적인 SaaS template처럼 만들지 않는다.
3. motion은 300ms 안팎의 위치·화살표·crop 변화에 집중한다.
4. 확률과 차트 색을 장식용 색과 혼용하지 않는다.
5. 새 화면은 ivory canvas, white surface, black type, signal color 체계를 그대로 따른다.
6. UI를 바꾼 뒤 desktop 전체 route, detail, command palette, 390px drawer, reduced-motion 계약을 다시 검증한다.

## 7. 검증 결과

- overview, flow, ask, questions, asof, track: 가로 overflow 0
- desktop 1280×720: light surface와 chart rendering 확인
- mobile 390×844: rail 숨김, mobile header 노출, drawer open/close 확인
- command palette: white surface, 검색 input focus, 결과 렌더링 확인
- signal mosaic: depth별 transform 확인
- forecast card: pointer 기반 tilt, shadow, title shift, arrow reveal 확인
