# Claude Code 실행 프롬프트 — Codex 메인 비주얼 완전 이식 + 사이드 내비게이션 재설계

작성일: 2026-07-30 KST  
대상 공개본: `https://sung-jinpark.github.io/Jin-s-investing-prediction/`  
핵심 수정 파일: `src/ai_fc/dashboard_template.html`  
생성 산출물: `reports/dashboard.html`

---

## 이 프롬프트를 Claude Code에 그대로 전달할 것

아래 지시는 참고안이 아니라 **구현·검수·완료 보고까지 포함한 실행 계약**이다.  
이 문서는 2026-07-29에 작성된 이전 UI 프롬프트보다 우선한다.

---

# 작업 목표

Jin's Investing Prediction Solution의 DB, 예측값, 시나리오, 차트 데이터, 해시 라우팅, 조회·필터 기능은 유지하되 **UI 표현 계층을 다시 재구축**하라.

이번 작업은 색상 몇 개를 교체하는 리스킨이 아니다.

현재 공개본은 Codex 레퍼런스의 큰 제목, 연두색, 어두운 예측 카드를 일부 옮겼지만 다음 문제가 남아 있다.

1. 기존 `헤더 → 시장 스트립 → 가로 메뉴 → 보고서 본문` 구조가 그대로 남아 있다.
2. 새 UI를 구식 메인페이지 위에 얹은 것처럼 보인다.
3. 첫 화면에서 무엇을 먼저 읽어야 하는지 불분명하다.
4. 화면별 색 역할이 통일되지 않았고 차트에 금색·보라·회색 계열이 뒤섞여 있다.
5. 가로 탭 메뉴 때문에 웹앱보다 리포트/관리자 페이지처럼 보인다.
6. 첫 화면 안에 핵심 카드 3개가 온전히 들어오지 않는다.

최종 결과는 다음 한 문장으로 설명되어야 한다.

> **검은 시장 브리핑 무대 위에 최신 시장 판단과 핵심 확률 3개가 크게 보이고, 좌측 제품 내비게이션으로 분석 도구를 전환하는 현대적인 예측 제품**

## Codex 레퍼런스 사용법

저장소 안의 아래 두 파일을 시각적 source of truth로 직접 읽고 작업하라.

- `codex-forecast-demo/app/globals.css`
- `codex-forecast-demo/app/page.tsx`

“Codex와 비슷하게” 자의적으로 해석하지 않는다. 아래 요소는 레퍼런스의 실제 수치와 구조를 가져와 현재 템플릿 방식으로 번역한다.

- `--ink`, `--ink-2`, `--ink-3`, `--paper`, `--mint`, `--coral`, `--teal` 색 토큰
- `clamp(40px, 6vw, 86px)` 계열의 큰 제목 스케일
- `clamp(72px, 7vw, 112px)` 계열의 확률 숫자 위계
- 하나의 dark grid를 선으로 나눈 3개 forecast card
- 직선적인 chart panel
- mono metadata와 system sans 본문의 조합
- radius를 거의 쓰지 않는 패널
- hover 시 4px 이내의 절제된 이동

단, 레퍼런스의 기존 전체 너비 header/market strip/horizontal nav 배치는 복사하지 않는다.  
이번 작업에서는 동일한 시각 언어를 **좌측 rail + full-height overview** 구조로 재조합한다.

---

# 1. 작업 시작 전 원칙

먼저 실제 저장소 상태를 확인하라.

```bash
git status --short
git branch --show-current
git log --oneline --all -10 -- src/ai_fc/dashboard_template.html
git log --oneline --all -10 -- reports/dashboard.html
```

주의:

- 작업자의 미커밋 변경을 삭제하거나 덮어쓰지 않는다.
- `git reset --hard`, 강제 checkout, 강제 pull을 하지 않는다.
- 공개 GitHub Pages가 로컬보다 최신이면 공개본을 만든 브랜치/커밋을 먼저 확인한다.
- 공개본의 최신 기능을 잃지 않은 상태에서 아래 설계를 적용한다.
- `reports/dashboard.html`을 직접 손으로 고치지 않는다.
- 템플릿을 수정한 뒤 기존 생성 절차로 산출물을 다시 만든다.
- 계획만 작성하고 멈추지 말고 실제 코드 수정과 검증까지 끝낸다.

---

# 2. 반드시 보존할 계약

## 2.1 데이터와 로직

아래는 변경하지 않는다.

- DB 스키마와 DB 파일
- 질문 ID
- 최신 확률과 과거 forecast round
- scenario 확률·경로·밴드·이벤트
- analog context와 overlay 원자료
- calibration, resolution, Brier 데이터
- `window.__DATA__`
- `window.__DATA_URL__`
- `<!--DATA-->`
- 임베드 데이터와 `/api/data` 라이브 데이터 양쪽 지원
- 기존 해시 라우트
  - `#overview`
  - `#flow`
  - `#ask`
  - `#questions`
  - `#asof`
  - `#track`
  - 질문 상세 화면
- 질문 검색, 도메인 필터, 상태 필터
- 기간 조회
- 시점 조회
- 질문 상세 round 선택
- SVG 차트와 tooltip

`src/ai_fc/dashboard.py`의 read model과 직렬화 로직은 UI 구현에 꼭 필요한 사유가 없는 한 수정하지 않는다.

## 2.2 자기완결 HTML

현재 저장소 테스트가 요구하는 자기완결 HTML 계약을 유지한다.

- 외부 CDN 금지
- 외부 폰트 요청 금지
- 외부 JS/CSS 번들 금지
- `<link>` 의존성 추가 금지
- 프레임워크 마이그레이션 금지
- GitHub Pages에서 정적 산출물만으로 동작해야 함

React/Next로 이전하지 않는다.  
Codex 레퍼런스의 디자인 원리와 구조를 **현재 자기완결 HTML/CSS/JS에 이식**한다.

---

# 3. 2026-07-30 공개본 실사 결과

공개본을 1440×900에서 직접 확인한 결과는 다음과 같다.

| 항목 | 현재 공개본 실측 | 판정 |
|---|---:|---|
| 사이트 헤더 | 높이 74px | 별도 행을 차지함 |
| 시장 스트립 | 높이 84px | 별도 행을 차지함 |
| 가로 내비게이션 | 높이 61px | 별도 행을 차지함 |
| 본문 시작 | y=219px | 첫 화면 세로 공간 24%를 사용 전에 소모 |
| 실제 hero 콘텐츠 시작 | y≈323px | 메인 판단이 지나치게 늦게 등장 |
| 메인 H1 | 86px, 893×170 | 크기는 충분하나 위치와 문구가 문제 |
| stance 카드 | 331×270, y=334 | 방향은 좋지만 본문과 분리되어 보임 |
| 핵심 예측 그리드 | y=688px | 900px 화면에서 하단이 잘림 |
| 핵심 예측 카드 | 각 높이 약 360px | 첫 화면에 온전히 보이지 않음 |
| overview 전체 높이 | 약 1,943px | 첫 화면 이후 보고서 블록이 길게 이어짐 |
| 화면 진입 모션 | 1개 | loader 외 제품 모션은 매우 제한적 |
| 시장 전망 1번 SVG | 약 1,235×596 | 그래프는 실제로 존재하며 크기도 충분 |
| 시장 전망 2번 SVG | 약 1,240×460 | 문제는 그래프 부재가 아니라 표현 통일성 |

현재 첫 화면의 구조적 문제는 다음과 같다.

```text
74px  브랜드 헤더
84px  시장 데이터 스트립
61px  가로 메뉴
104px 상단 여백
281px 제목/설명/stance
84px  섹션 간격
360px 핵심 예측 카드
```

이 구조에서는 카드가 첫 화면에 들어올 수 없다.

또한 현재 메인 문구인

> 시장 이벤트를 확률로 읽고, 결과로 검증한다

는 브랜드 소개 문구에 가깝다. 사용자가 첫 화면에서 원하는 것은 사이트 설명이 아니라 **현재 시장 판단과 최신 확률**이다.

---

# 4. 채택할 정보 구조

## 4.1 데스크톱: 좌측 고정 제품 레일

기존의 아래 세 영역을 제거한다.

- 전체 너비 `site-header`
- 전체 너비 `market-strip`
- 전체 너비 `view-nav`

세 기능을 좌측 내비게이션과 메인 상단의 얇은 live row로 재배치한다.

```text
┌────────────────┬────────────────────────────────────────────────────┐
│ PRODUCT RAIL   │ LIVE / UPDATE / NASDAQ / DRAWDOWN / BREADTH       │
│                ├────────────────────────────────────────────────────┤
│ Brand          │                                                    │
│                │  현재 시장 판단                                   │
│ 01 Overview    │  단기 조정 위험은 남아 있지만,                    │
│ 02 Outlook     │  연말 상승 경로가 66%로 우세합니다.               │
│ 03 Period      │                                      Stance block  │
│ 04 Forecasts   │                                                    │
│ 05 As-of       ├────────────────────────────────────────────────────┤
│ 06 Track       │  57%                 63%                62%         │
│                │  Forecast 01         Forecast 02        Forecast 03 │
│ Data live      │                                                    │
└────────────────┴────────────────────────────────────────────────────┘
```

### 너비 규칙

- `>= 1280px`: rail 너비 `236px`
- `800px ~ 1279px`: rail 너비 `84px`
- `< 800px`: 고정 rail을 숨기고 mobile drawer 사용

### rail 디자인

- 배경: `--ink-2`
- 우측 경계: `1px solid --dark-line`
- 상단: 브랜드 마크, `JIN'S / PREDICTION`
- 중단: 6개 실제 링크
- 하단: LIVE 상태, 갱신 시각, 데이터 기준일
- 활성 메뉴:
  - 좌측 또는 우측에 `3px --lime` indicator
  - 텍스트 `--white`
  - 번호 `--lime`
  - 배경 `rgba(255,255,255,.045)`
- 비활성 메뉴:
  - 텍스트 `rgba(255,255,255,.52)`
  - 번호 `rgba(255,255,255,.28)`
- hover 시 `translateX(3px)` 이내의 짧은 반응만 사용
- 아이콘 라이브러리를 새로 넣지 않는다.
- 메뉴는 장식 아이콘 대신 `01`~`06` 숫자와 명확한 레이블을 사용한다.

### rail 동작

- 넓은 데스크톱에서는 레이블을 항상 표시한다.
- 800~1279px에서는 숫자 중심 compact rail로 줄인다.
- compact rail 항목에 `title`만 의존하지 말고 접근 가능한 이름을 유지한다.
- 현재 route 링크에 `aria-current="page"`를 적용한다.
- 각 메뉴는 실제 `href="#overview"` 형태의 링크로 만든다.
- 클릭뿐 아니라 브라우저 뒤로/앞으로와 직접 hash 진입도 정상 동작해야 한다.

## 4.2 모바일: 상단 바 + drawer

390px 화면에서 6개 메뉴를 하단에 억지로 모두 넣지 않는다.

- 64px 상단 바
- 왼쪽 브랜드
- 오른쪽 실제 `<button>`인 `MENU`
- 누르면 화면 왼쪽에서 drawer가 열린다.
- drawer 너비: `min(86vw, 330px)`
- backdrop 제공
- `Escape`로 닫힘
- 메뉴 선택 후 닫힘
- 열릴 때 첫 메뉴 또는 닫기 버튼으로 focus 이동
- 닫힐 때 menu 버튼으로 focus 복귀
- drawer가 열렸을 때 배경 스크롤 잠금
- 모바일에서도 01~06 번호 체계를 그대로 사용

---

# 5. 메인 첫 화면 재설계

## 5.1 첫 화면의 역할

첫 화면은 “사이트 사용 설명서”가 아니라 **오늘의 시장 브리핑**이어야 한다.

첫 화면에 허용되는 내용:

1. 브랜드와 LIVE 갱신 상태
2. 현재 NASDAQ 핵심 수치
3. 데이터가 말하는 한 문장 시장 판단
4. 시장 stance
5. 핵심 예측 확률 3개
6. 다음 분석 화면으로 이동하는 명확한 action

첫 화면에서 제거할 내용:

- 진행 중 예측 총 개수
- 기록된 round 총 개수
- 해결 표본 수
- Brier
- 검증 진행률
- 6개 전체 판정 일정
- 장문의 방법론 설명
- “투자 자문이 아니다” 문구의 반복
- 전체 시나리오 표
- 검색/필터/운영 도구

위 항목을 삭제하라는 뜻이 아니다. overview의 lower fold 또는 `#track`, `#questions`에 배치하라.  
단, **1440×900의 첫 화면에는 보이지 않게** 한다.

## 5.2 hero 배경

overview의 첫 `100dvh`는 완전한 dark stage로 만든다.

```css
.overview-stage {
  min-height: 100dvh;
  color: var(--white);
  background:
    radial-gradient(circle at 78% 14%, rgba(188,255,113,.11), transparent 34%),
    radial-gradient(circle at 55% 90%, rgba(87,212,200,.055), transparent 35%),
    var(--ink);
}
```

그라디언트는 분위기만 만들고 눈에 띄는 “오로라 배경”처럼 과장하지 않는다.  
카드마다 서로 다른 화려한 그라디언트를 넣지 않는다.

## 5.3 live row

기존 84px 시장 스트립을 42~48px의 compact live row로 바꾼다.

표시 우선순위:

1. `NASDAQ 26,107`
2. `ATH 대비 -3.6%`
3. `200DMA 상회 79.2%`
4. `경기 국면 확장`
5. `UPDATED 2026-07-30 00:20 KST`

desktop에서는 한 줄, compact rail/tablet에서는 필요한 경우 두 줄로 줄일 수 있다.

- label: 9~10px mono
- value: 13~15px mono
- positive/healthy: lime 또는 white
- drawdown/risk: coral
- 경계선: `--dark-line`
- 별도 커다란 카드 5개로 만들지 않는다.

## 5.4 시장 판단 H1

고정된 마케팅 문구 대신 데이터 기반 문장을 보여라.

현재 scenario 데이터처럼 상승 경로 합계가 조정·횡보보다 크면 예:

> 단기 조정 위험은 남아 있지만, 연말 상승 경로가 66%로 우세합니다.

중립이면 예:

> 상승과 조정 경로가 맞서며, 핵심 이벤트 전까지 변동성 우위입니다.

하락 경로가 우세하면 예:

> 방어 경로가 우세해졌고, 지지선 확인 전까지 위험 관리가 먼저입니다.

구현 원칙:

- 새 AI 호출을 추가하지 않는다.
- `data.scenario.paths`의 확률을 이용한 순수 deterministic helper로 생성한다.
- 실제 데이터가 문장을 결정해야 한다.
- 확률은 반올림 규칙을 현재 데이터 표현과 맞춘다.
- 시나리오 확률과 개별 질문 확률을 합산하지 않는다.
- 문장 아래에 “시나리오 확률과 질문별 확률은 별도”라는 짧은 설명을 1회만 둔다.

desktop H1:

```css
font-size: clamp(58px, 5.7vw, 86px);
line-height: .96;
letter-spacing: -.064em;
font-weight: 680;
max-width: 920px;
```

H1은 최대 2~3줄이다.  
문장 폭과 줄바꿈을 직접 검수하라.

## 5.5 stance block

현재 dark stance card의 개념은 유지하되 hero 안에 자연스럽게 통합한다.

표시 예:

```text
CURRENT STANCE
변동성 경계
중기 상승 우세
상승 경로 66 / 조정·횡보 34
```

- 폭: 280~320px
- 높이: 200~230px
- 배경: `--ink-2`
- border: `--dark-line`
- radius: `0` 또는 최대 `2px`
- 상태 배지는 lime, coral 두 색만 사용
- 길고 방어적인 설명 문단은 제거
- 수치 근거를 한 줄로 명시

## 5.6 핵심 예측 카드 3개

현재의 큰 확률 카드 방향은 유지하되 첫 화면에 완전히 보이도록 높이와 hero 배치를 조정한다.

desktop 기준:

- 3열
- 카드 높이 `280~310px`
- 확률 `clamp(68px, 6.2vw, 96px)`
- 카드 간 외곽 gap을 만들기보다 하나의 dark grid 안에서 선으로 분할
- 카드 hover `translateY(-4px)`
- hover 배경 `rgba(255,255,255,.045)`
- title은 2줄 이내
- domain, round, delta, deadline은 mono micro text
- 확률 바는 4px
- 카드 전체가 질문 상세로 이동하는 실제 button 또는 link

색 역할:

- 확률 숫자: white
- 확률 bar: lime
- 상승 delta: lime
- 하락 delta: coral
- secondary signal: teal
- 나머지 metadata: white alpha

`tone-0`, `tone-1`, `tone-2` 때문에 카드마다 무관한 색을 칠하지 않는다.  
세 카드의 배경은 같은 제품 표면이어야 한다.

## 5.7 1440×900 강제 배치 기준

1440×900에서 다음이 모두 보여야 한다.

- rail 전체
- compact live row
- eyebrow
- H1 전체
- stance 전체
- 핵심 예측 카드 3개 전체
- 카드 하단 deadline/delta

첫 카드 grid의 bottom은 `y <= 880px`이어야 한다.

현재처럼 card grid가 `y=688`에서 시작해 화면 아래로 잘리는 상태는 실패다.

이를 위해:

- 상단 전체 너비 3단 구조를 제거한다.
- hero 내부 padding을 36~52px 범위로 관리한다.
- page heading bottom margin을 기존 84px 수준으로 두지 않는다.
- 카드 높이를 360px에서 약 295px로 조정한다.
- 불필요한 description 줄을 제거한다.

---

# 6. overview lower fold

첫 화면 아래에는 필요한 내용만 두 단계로 배치한다.

## 6.1 첫 번째 lower section

2열 비대칭 editorial layout:

- 왼쪽 2/3: 연말 시나리오 분포
- 오른쪽 1/3: 가장 가까운 판정일 3건만

“다가오는 판정일 6건” 전체 목록은 `#questions` 또는 펼침 동작으로 이동한다.

## 6.2 운영 지표

다음 수치는 overview 하단에서 별도 `model quality` 섹션으로 묶거나 `#track`으로 이동한다.

- 진행 중 예측
- 기록된 round
- 해결 표본
- Brier
- 검증 진행

작은 KPI 카드 5개를 첫 화면에 반복하지 않는다.

## 6.3 반복 설명 정리

- 면책 문구는 footer에 한 번
- scenario와 질문 확률이 다르다는 설명은 해당 영역에 한 번
- 생성 시각은 live row와 rail footer 중 시각적으로 중복되지 않게 처리
- “정보 제공 목적” 문구를 각 패널마다 반복하지 않는다.

---

# 7. 나머지 화면 디자인

## 7.1 공통 page stage

`#flow`, `#ask`, `#questions`, `#asof`, `#track`도 동일한 제품 shell을 사용한다.

각 화면 상단:

- dark background
- 9~10px eyebrow
- 48~72px 화면 제목
- 한 줄 설명
- 필요할 때만 우측 live stat

도구/표가 필요한 화면은 상단 dark stage 아래에 paper workspace를 둔다.

이 패턴으로 “어떤 화면은 새 UI, 어떤 화면은 구식 흰색 보고서”인 단절을 없앤다.

## 7.2 시장 전망 `#flow`

차트는 이미 존재한다. 다시 만드는 것이 아니라 표현을 통일한다.

- 페이지 전체 분석 영역: dark
- chart panel: `--ink-2`
- panel title: 36~48px
- 첫 SVG 높이: 520~600px
- 두 번째 SVG 높이: 430~480px
- 축, grid, tooltip, legend를 동일 토큰으로 통일
- 시나리오 확률 legend는 차트 상단에 크게 정렬
- 이벤트 타임라인과 risk strip도 같은 색 역할 사용

현재 차트에서 제거할 색 불일치:

- 금색/amber
- 보라색
- 탁한 분홍색
- 임의의 pastel analog 색
- 별도 제품 색처럼 보이는 blue

시나리오 색:

| 의미 | 색 |
|---|---|
| 상승·ATH 돌파 | `--lime` |
| 상승·ATH 미달 | `--teal` |
| 조정·횡보 | `--coral` |
| 과거 유사 경로 | `--slate`, dashed |
| ATH/임계 reference | white alpha |

analog overlay는 rainbow palette를 사용하지 않는다.

| series | 표현 |
|---|---|
| AI 현재 | lime, 3px |
| 가장 가까운 비교 시대 | teal, 2px |
| 대표 위험 비교 시대 | coral, 2px dashed |
| 나머지 시대 | white alpha 0.68 / 0.52 / 0.38 / 0.25 + 서로 다른 dash |

색뿐 아니라 line width와 dash로도 구분한다.

risk strip:

- low: teal
- mid: slate/white alpha
- high: coral

## 7.3 기간 조회 `#ask`

- 상단은 dark page hero
- 날짜 입력과 preset은 하나의 command bar
- 결과 핵심 수익률 3개는 큰 수치로
- 이벤트는 작은 운영 표가 아니라 timeline/list
- empty state도 제품 언어로 작성

## 7.4 예측 목록 `#questions`

- dark heading 영역 아래 paper workspace
- 검색창을 가장 먼저
- filter select는 한 줄 command bar
- 결과 개수를 command bar 오른쪽에 표시
- desktop은 표 유지 가능
- 표 row hover와 focus 상태를 명확히
- 확률을 가장 강한 열로
- 질문 제목, 확률, deadline, status의 우선순위를 분명히
- mobile에서는 표를 억지로 축소하지 말고 row card/list로 전환

## 7.5 시점 조회 `#asof`

- 선택 날짜를 상단의 큰 context control로
- 핵심 확률과 model/market 차이를 큰 수치로
- 모든 항목을 동일 크기 작은 카드로 만들지 않는다.

## 7.6 적중 이력 `#track`

- 상단에 resolved 수와 Brier를 큰 수치로
- calibration은 chart/panel 중심
- domain skill과 resolution history는 하단
- lime은 잘 맞은 값/활성 모델
- coral은 error/risk
- teal은 comparator
- blue를 calibration 기본색으로 쓰지 않는다.

## 7.7 질문 상세

- back action은 rail route와 충돌하지 않게 유지
- 확률 orb는 유지 가능하나 색은 lime/white로 통일
- round 선택은 본문 안의 secondary rail
- reasoning body는 paper surface
- model metadata는 dark strip
- 질문 상세에서도 메인 product rail은 유지

---

# 8. 단일 색상 시스템

다음 토큰을 source of truth로 사용한다.

```css
:root {
  --ink: #06100d;
  --ink-2: #0b1714;
  --ink-3: #10231d;
  --paper: #eef2ec;
  --white: #ffffff;
  --lime: #bcff71;
  --lime-deep: #5b8f2e;
  --teal: #57d4c8;
  --coral: #ff8066;
  --slate: #94a3b8;
  --muted: #718079;
  --line: rgba(7,17,15,.14);
  --dark-line: rgba(255,255,255,.13);
}
```

역할을 바꾸지 않는다.

| 역할 | 허용 색 |
|---|---|
| 브랜드/활성/상승 우세 | lime |
| 비교 경로/보조 신호 | teal |
| 하락/위험/오차 | coral |
| 과거 참조/중립 | slate 또는 white alpha |
| 본문 dark | ink 계열 |
| 상세 읽기 영역 | paper/white |

금지:

- `#1d5fd0` 같은 기존 dashboard blue
- `#0f8a4c` 같은 다른 녹색
- `#cf2f2a` 같은 다른 빨강
- 새로운 purple/amber/pink palette
- chart마다 제각각인 임의 색
- lime 위에 또 다른 green을 섞는 것
- light 화면에서 높은 채도의 장식색을 넓게 칠하는 것

특히 “연두색 헤더 + 파란 차트 + 금색 위험도 + 보라 analog”처럼 서로 다른 제품에서 가져온 듯한 색 조합은 실패다.

---

# 9. 타이포그래피와 표면

외부 폰트를 요청하지 않는다.

```css
--sans: system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
--mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
```

크기:

| 요소 | desktop |
|---|---:|
| overview H1 | 58~86px |
| subpage H1 | 48~72px |
| 주요 확률 | 68~96px |
| panel H2 | 32~48px |
| body | 15~18px |
| card title | 14~17px |
| metadata | 9~11px |

원칙:

- 큰 제목의 행간은 0.94~1.02
- 한글 제목 letter-spacing은 약 `-.05em`
- 숫자는 mono
- 지나치게 얇은 font weight 금지
- metadata를 모두 대문자 영어로 도배하지 않는다.
- radius는 `0~3px`
- 둥근 SaaS 카드, pill 남발, 과한 그림자 금지
- 경계와 명암으로 계층을 만든다.

---

# 10. 모션과 상호작용

사이트가 정적 보고서처럼 느껴지지 않게 하되 과장하지 않는다.

## route transition

- 180~240ms
- opacity `0 → 1`
- translateY `10px → 0`
- route 변경마다 새 content stage에 적용

## rail

- compact/expanded 전환이 있다면 200~240ms
- active indicator 이동 180ms
- hover translation 최대 3px

## forecast card

- hover `translateY(-4px)`
- background transition 160ms
- focus-visible 상태는 hover보다 명확

## chart

- 초기 path draw animation은 500~700ms 이내
- tooltip은 즉시 읽을 수 있어야 함
- data point를 과도하게 튕기거나 pulse시키지 않는다.

## reduced motion

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
  }
}
```

loader 회전만 추가하고 “모션 구현 완료”라고 보고하면 실패다.

---

# 11. 구현 구조 지시

`dashboard_template.html` 안에서 표현 계층을 실제로 재구성한다.

권장 공통 구조:

```html
<body>
  <div class="product-shell">
    <aside class="product-rail">...</aside>
    <header class="mobile-header">...</header>
    <div class="mobile-drawer">...</div>
    <main id="app" class="product-main">...</main>
  </div>
  <div class="tip">...</div>
  <!--DATA-->
</body>
```

권장 helper:

```text
renderProductRail(activeView, data)
renderMobileNavigation(activeView, data)
renderLiveRow(data)
renderPageStage({ eyebrow, title, description, aside })
getScenarioWeights(data)
getMarketThesis(data)
renderForecastFeatureGrid(data)
setActiveRoute(hash)
openMobileDrawer()
closeMobileDrawer()
```

중요:

- 기존 `renderOverview()` 안에 CSS만 덧붙이지 않는다.
- 상단 3단 DOM을 그대로 둔 채 `position: fixed`만 적용하지 않는다.
- 제품 shell 자체를 새 구조로 만든다.
- 화면별 렌더 함수가 같은 page stage와 token을 공유하게 한다.
- 반복 inline style을 줄이고 class/token으로 통일한다.
- scenario 원본에 저장된 임의 color를 UI에 그대로 신뢰하지 말고 의미 기반 color mapper를 둔다.
- analog도 series key 기반의 deterministic style mapper를 둔다.

---

# 12. 반응형 명세

## 1440×900

- 236px rail
- 첫 화면 카드 3개 전체 표시
- 가로 navigation bar 없음
- H1 최소 58px
- main content가 rail 아래로 들어가지 않음
- 차트가 1,100px 이상의 실사용 폭을 확보

## 1024×768

- 84px compact rail
- H1 50~68px
- 예측 카드는 3열 또는 2+1로 합리적으로 재배치
- 가로 스크롤 없음
- chart legend가 차트를 침범하지 않음

## 768px

- rail 대신 mobile header/drawer
- 예측 카드 1열 또는 가로 snap list 중 하나를 선택
- 메뉴 열기/닫기와 route 이동 검증
- 표는 responsive list 전환 준비

## 390×844

- viewport 가로 overflow 0
- H1 40~52px
- stance는 H1 아래
- 카드 title 잘림 없음
- drawer가 화면 밖에 잔여 픽셀로 보이지 않음
- touch target 최소 44px
- SVG 내부 텍스트가 완전히 겹치면 mobile용 축 label 축약 적용

---

# 13. 접근성 계약

- nav에 정확한 `aria-label`
- 현재 링크에 `aria-current="page"`
- drawer button에 `aria-expanded`, `aria-controls`
- drawer 자체에 적절한 role/label
- `Escape` 지원
- 모든 forecast card 키보드 실행 가능
- 표 row를 클릭 가능하게 만들 경우 Enter/Space 지원
- input/select에는 실제 label 연결
- focus-visible outline 제공
- 색만으로 상승/하락/active를 구분하지 않음
- decorative element에는 `aria-hidden="true"`
- tooltip 정보가 hover만으로 독점되지 않도록 기본 legend/label 유지

---

# 14. 생성과 테스트

저장소의 기존 명령을 먼저 확인한 뒤 실행한다.

최소 확인:

```bash
python -m pytest src/tests/test_dashboard.py
```

프로젝트에 더 적합한 생성 명령과 전체 테스트가 있으면 함께 실행한다.

반드시 확인할 것:

1. `dashboard_template.html` 수정
2. `reports/dashboard.html` 재생성
3. 자기완결 HTML 테스트 통과
4. 임베드 모드 렌더 성공
5. 가능하면 라이브 `/api/data` 모드 렌더 성공
6. 여섯 hash route 전환 성공
7. 브라우저 back/forward 성공
8. 질문 상세 진입/복귀 성공
9. 차트 tooltip 성공
10. 검색/필터/기간/시점 control 성공
11. 모바일 drawer 키보드 동작 성공

DB/예측값이 바뀌지 않았음을 검증하라.

- 변경 전후 `window.__DATA__`의 질문 ID 집합 비교
- 각 질문 latest probability 비교
- forecast round 수 비교
- scenario path probability와 end 값 비교
- calibration/resolution 수 비교

UI 작업으로 데이터 값이 달라지면 실패다.

---

# 15. 브라우저 시각 검수

반드시 실제 산출물을 브라우저에서 아래 viewport로 확인한다.

- 1440×900
- 1024×768
- 390×844

각 크기에서 최소 캡처:

1. overview 첫 화면
2. `#flow` 첫 차트
3. `#questions`
4. mobile drawer 열린 상태

1440×900 overview에서 bounding box를 확인하라.

```js
const hero = document.querySelector(".overview-stage").getBoundingClientRect();
const rail = document.querySelector(".product-rail").getBoundingClientRect();
const grid = document.querySelector(".forecast-grid").getBoundingClientRect();
const h1 = document.querySelector("h1").getBoundingClientRect();

console.table({
  heroBottom: hero.bottom,
  railWidth: rail.width,
  h1Top: h1.top,
  h1Bottom: h1.bottom,
  gridTop: grid.top,
  gridBottom: grid.bottom
});
```

합격 목표:

- `rail.width` 약 236
- `hero.bottom` 약 900
- `grid.bottom <= 880`
- forecast 카드 3개 모두 viewport 안
- 기존 74+84+61px 전체 너비 stack 없음

---

# 16. 합격 기준

아래를 모두 만족해야 완료다.

## 구조

- 좌측 제품 rail이 실제로 구현됨
- 기존 가로 탭 내비게이션 제거
- 모바일 drawer 구현
- 첫 화면이 dark full-height market briefing으로 바뀜
- 첫 화면에서 핵심 예측 3개가 온전히 보임
- 운영 KPI와 전체 일정이 첫 화면에서 제거됨

## 시각

- shell, chart, active state의 색이 동일 token 체계
- blue/amber/purple가 제품 강조색으로 남지 않음
- H1이 generic 소개 문구가 아니라 데이터 기반 시장 판단
- 카드가 구식 dashboard tile처럼 반복되지 않음
- 첫 화면이 “새 UI를 예전 페이지 위에 얹은 모습”이 아님

## 기능

- 모든 기존 화면과 데이터 기능 유지
- 실제 링크와 `aria-current`
- back/forward 가능
- chart와 tooltip 유지
- mobile menu 접근성 동작
- reduced motion 지원

## 품질

- 1440×900, 1024×768, 390×844 시각 검수
- 테스트 통과
- 데이터 불변 검증
- 공개용 `reports/dashboard.html` 재생성

---

# 17. 즉시 실패로 처리할 결과

다음 중 하나라도 해당하면 작업을 완료로 보고하지 않는다.

- 색상만 바꿈
- 현재 horizontal nav를 그대로 둠
- 기존 header/market strip/nav 3단을 유지함
- 모든 메뉴를 작은 pill로 만듦
- 첫 화면에서 forecast card가 다시 잘림
- H1을 “시장 이벤트를 확률로 읽는다” 같은 마케팅 문구로 유지
- overview 첫 화면에 Brier/표본/round KPI를 다시 넣음
- 차트 색은 기존 blue/purple/amber 그대로 둠
- 외부 폰트나 CDN을 추가
- DB·예측값을 수정
- `reports/dashboard.html`만 직접 수정
- React/Next로 옮김
- mobile에서 6개 메뉴를 좁은 가로 탭으로 유지
- 스크린샷 없이 “현대화 완료”라고 보고
- 테스트 실패를 숨김

---

# 18. 완료 보고 형식

완료 후 아래 형식으로 보고하라.

```text
1. 변경 파일
2. 제거한 기존 구조
3. 새 rail/mobile drawer 구조
4. overview 첫 화면 변경
5. 화면별 색 통일 내용
6. 보존한 데이터·기능
7. 실행한 생성/테스트 명령과 결과
8. 1440×900 실측값
9. 1024×768 및 390×844 검수 결과
10. 남은 제약 또는 후속 작업
```

“세련되게 수정했다” 같은 추상 표현으로 끝내지 말고, 실제 DOM 구조·측정값·테스트 결과로 설명하라.

---

# 최종 디자인 판단

이 사이트에는 상단 가로 메뉴보다 **좌측 고정 제품 rail**이 적합하다.

이유:

- 예측·시장 전망·기간 조회·목록·시점 조회·적중 이력은 서로 다른 도구 화면이다.
- 여섯 화면을 가로 탭으로 놓으면 보고서의 장처럼 보인다.
- rail은 웹앱의 지속적인 정보 구조를 만들고 본문에 더 많은 세로 공간을 준다.
- 현재 219px를 차지하는 상단 stack을 제거하면 핵심 예측 카드가 첫 화면에 들어온다.
- rail 하단에 갱신 상태를 두면 브랜드, 내비게이션, 데이터 상태가 한 축으로 정리된다.

따라서 구현 방향은 아래로 고정한다.

> **desktop persistent rail + tablet compact rail + mobile accessible drawer + overview 100dvh dark briefing**

이 구조 위에서 Codex 레퍼런스의 큰 제목, 고대비 확률, 절제된 lime, 직선적 패널, 넓은 여백을 일관되게 사용하라.
