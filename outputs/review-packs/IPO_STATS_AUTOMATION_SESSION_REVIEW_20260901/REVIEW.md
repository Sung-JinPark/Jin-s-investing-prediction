# 세션 검토 문서 — IPO 참고통계 자동화 + SPX/GFDEBTN 통계 확장

- **작성**: 2026-09-01 (KST) · Claude Code 세션
- **기간**: 2026-08-31 ~ 2026-09-01
- **저장소**: Sung-JinPark/Jin-s-investing-prediction (origin/main)
- **배포**: https://sung-jinpark.github.io/Jin-s-investing-prediction/
- **지위**: 모든 산출물은 참고 통계·자동화 배관이다. 예측 파일·원장·게시 수치는 무수정 (CLAUDE.md 불변성 규칙 준수). LLM 추론 비용 발생 작업 없음 — 전부 결정론 코드.

---

## 0. 한눈에 보기 — PR·커밋 맵

| PR | 머지 커밋 | 내용 | 상태 |
|---|---|---|---|
| [#98](https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/98) | `5015b3d4` | EDGAR 424B4 격주 감시 + 통계 중분류 01~06 + 원장 등록 | 머지·배포 완료 |
| [#101](https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/101) | `1622c398` | (타 세션 작업) 차트 공시 '읽는 법' 블록 — 검증 후 대리 머지 | 머지·배포 완료 |
| [#102](https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/102) | — | (타 세션 작업) AI 빌드아웃 계측 — **red 상태 머지 차단**, 타 세션이 자체 해소 후 머지 | 관찰만 |
| [#118](https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/118) | `857837c5` | SPX/GFDEBTN 5년 창 비교 차트 + statistics-backfill.yml | 머지·배포 완료 |
| [#119](https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/119) | `dd7b5659` | SPX/GFDEBTN 1966~ 전 구간 레벨 차트 | 머지·배포 완료 |
| (직push) | `6fc25f49` | 로컬 FRED 키로 수동 통계 갱신 (기준 2026-08-31) | main 반영·배포 완료 |

#98 내부 커밋: `a3a1b435`(EDGAR 감시) · `d0f10896`(중분류 번호) · `222bbb2f`(원장 등록) · `443c932e`(인벤토리 지문).
#118 내부: `224902da`(차트) · `70d082dd`(백필 트리거) · `aa242b38`(CI 백필 데이터) · 외.
#119 내부: `24964c0d`(차트) · `e8bdbb3c`(CI 백필 데이터) · `ace28cf2`(CHANGELOG).

---

## 1. 작업 1 — IPO EDGAR 424B4 격주 감시 (PR #98)

### 1.1 배경과 목표

`data/statistics/ipo/ipo_comparison_v1.json`의 계약 블록이
`edgar_source_watch: discover_and_review_completed_424B4_events`를 **선언만 하고 구현이 없던** 구멍을 메웠다.
정적으로 만들어 둔 IPO 참고 통계의 갱신 소재(새 IPO 완료 공모)를 격주로 자동 발굴한다.

### 1.2 설계 경계 (가장 중요)

- **게시 수치 무접촉**: `ipo_comparison_v1.json`은 읽기 전용. 닷컴 과거 행은 인용 시점(vintage) 고정,
  현재 구간 행은 `current_era_rows_only_after_review` — 병합은 최종 투자설명서를 사람이 검토한 뒤 수동.
- **AI 소속 판정 안 함**: 키워드는 후보를 좁히는 힌트일 뿐. 자동화 범위는 "무엇을 검토해야 하는가"의 발굴까지.
- **주간 해시 감시 무손상**: 기존 `ipo_reference_batch`(Ritter 학술 원천 4종 해시 감시)와 완전 분리 —
  `statistics-refresh.yml`도 `reference_batch_status.json`의 `cadence: weekly`도 그대로.

### 1.3 구현

| 파일 | 내용 |
|---|---|
| `src/ai_fc/ipo_edgar_watch.py` (신규) | EDGAR full-text search로 424B4 발굴. `fetcher` 주입 시그니처(기존 배치 미러) → 테스트 밀폐 실행 |
| `.github/workflows/ipo-edgar-watch.yml` (신규) | 토 01:40 UTC cron + **짝수 ISO 주차 게이트** = 격주. concurrency `investing-data-writer`. 커밋 화이트리스트는 대기열 파일 하나 |
| `data/statistics/ipo/edgar_candidates.json` (신규 산출물) | 검토 대기열 (`ipo_edgar_424b4_candidates_v1`) |
| `src/tests/test_ipo_edgar_watch.py` (신규) | 10개 테스트, 전부 오프라인 |
| `src/ai_fc/cli.py` | `ipo-edgar-watch` 서브커맨드 |
| `data/contracts/ledger_registry.yaml` + `src/ai_fc/ledger_audit.py` | `ipo_edgar_candidates` 원장 등록 + `biweekly` 신선도 분기(17일) 신설 |

핵심 동작:
- 엔드포인트는 기억이 아니라 **실호출로 확인**:
  `efts.sec.gov/LATEST/search-index?q="<키워드>"&forms=424B4&dateRange=custom&startdt=&enddt=`
  — 페이지 100건, `from`이 오프셋 (2026-05~08 표본 total 129 → 2페이지 실측).
- AI 키워드 6종(artificial intelligence, machine learning, generative AI, large language model,
  deep learning, neural network)을 각각 질의해 accession 기준으로 합치고 `matched_keywords`에 기록.
- 검색 창은 `classification.reviewed_through` **다음 날**부터 — EDGAR `startdt`가 포함 경계라
  그대로 쓰면 이미 검토한 날을 재수집한다 (실측: 경계 수정 전 13건 → 후 11건).
- `already_in_cohort`: 발행인명을 법인 접미사 정규화 후 `ai_broad_cohort`와 대조.
  이미 반영된 발행인도 지우지 않고 표시만 — 대기열이 정직하게 남는다.
- SEC 공정접근 UA: `JinsInvestingIPOEdgarWatch/1.0 (91ssjj@gmail.com)` (사용자 지정 주소).

### 1.4 실측 결과 (2026-08-13 ~ 08-31 창)

AI 키워드 적중 424B4 **11건 전부 검토 대기** 적재. 예: SunScout Holding(SNSC, 반도체),
Lyntris(LYNX), Londian Wason(FOIL), Andersen Group, Republic Power 등.

### 1.5 명세 대비 의도적 이탈 2건 (사유 명기)

1. **주차 게이트 `10#` 진법 강제**: 원안 `[ $(( $(date -u +%V) % 2 )) -eq 0 ]`은
   `date +%V`가 `"08"`/`"09"`로 오면 bash 산술이 8진수로 읽어
   `value too great for base`로 **8·9주차에 워크플로가 죽는다** (실측 재현).
   `$(( 10#$week % 2 ))`로 수정, 07~10·35~36주차 검증.
2. **검색 창 시작 +1일**: 위 1.3의 포함 경계 문제.

### 1.6 원장 등록 (후속 커밋 `222bbb2f`)

`biweekly` cadence 분기가 `ledger_audit`에 없으면 어떤 staleness 조건에도 걸리지 않아
**격주 작성기가 죽어도 영원히 stalled로 잡히지 않는다.** 17일(=14일 주기 + 한 번 놓칠 여유,
weekly가 7일 주기에 10일을 주는 것과 같은 비율) 분기를 넣고 경계 테스트(14일 신선/17일 여유/18일 stalled)로 고정.

---

## 2. 작업 2 — 통계 비교 중분류 번호 01~06 (PR #98, `d0f10896`)

### 2.1 문제

대분류 03 통계 비교의 레일 중분류가 `02 IPO·상장 ~ 07 신용`으로 밀려 있었다.
원인: 레일에서 걸러지는 '전체'(`railHidden`) 항목이 번호 리터럴 `code:'01'`을 차지.

### 2.2 해법 — 번호를 다시 적지 않고 원인 제거

`MID_CATEGORIES` 레지스트리의 번호 리터럴 `code:'0N'` **22개를 전부 제거**하고,
**걸러낸 뒤 1부터 매기는** 단일 규칙 `midCategoryCode(index)`를 레일·명령 팔레트가 공유.
앞으로 어떤 hidden/비활성 항목도 01을 먹을 수 없다.

- 결과: `01 IPO·상장 / 02 유동성 / 03 금리 / 04 경기·물가 / 05 기업가치 / 06 신용`, 07 없음.
- 번호는 표시 라벨 전용 — `key`·`hash` 필터 키와 라우트 무접촉.
- 위치 정정: 지목된 `statistics_lab.py`가 아니라 `dashboard.js`가 번호 생성 지점이었다
  (`grep enumerate|02d|start=` 결과에 중분류 번호 생성부 부재 확인).
- 테스트 2종: 01~06 연속·07 부재 고정 + 번호가 다시 리터럴로 박히지 않는지 고정.

---

## 3. 작업 3 — SPX ÷ 연방부채(GFDEBTN) 통계 2종 (PR #118, #119)

### 3.1 분자 선택 (핵심 판단 — 검토 요망)

| 후보 | 판정 | 사유 |
|---|---|---|
| FRED `SP500` | ❌ | **라이선스상 최근 10년만 제공** → 닷컴 구간(1995~99) 비교 원천 불가 |
| Yahoo `^GSPC` | ❌ | 정책상 `market_data_aggregator` = 교차검증 전용, 공식 수치 입력 불가 |
| NYU 연간 수익률 | ❌ | 계약상 `insight_only_not_numeric_input` |
| **OECD `SPASTT01USM661N`** | ✅ | 미국 주가지수(S&P 계열 월평균, 2015=100), **1957~ 전 구간 공식 경로**. 기등록 한국 지수(`SPASTT01KRM661N`)와 같은 계열 |

시작=100 지수화 구조라 리베이스 기준(2015=100)은 결과에 영향 없음.
"S&P 500 종가가 아니라 OECD 월평균 대용"임은 두 차트 caveat에 명시.
분모 `GFDEBTN` = 재무부 분기말 연방부채 총액(1966~, Treasury Fiscal Service).
두 시리즈 모두 FRED 페이지에서 **실측 확인** (2026-08-31 기준 갱신 중, GFDEBTN 241개 관측).

### 3.2 차트 1 — 5년 창 비교 `spx_per_federal_debt` (#118)

기존 `nasdaq_per_m2`와 같은 구조 (유동성 카테고리, 시작=100, 닷컴 vs 현재).

| | 닷컴 (1995~99) | 현재 (2023~) |
|---|---|---|
| 시작 | 100 | 100 |
| 같은 36개월차 | **174** | **116** |
| 말기 | 199 (60개월) | — |

읽기: 닷컴은 주가가 연방부채의 2배 속도로 달렸으나, 지금은 연방부채($39.1조)가 주가 상승을 거의 따라잡는 중.

### 3.3 차트 2 — 1966~ 전 구간 레벨 `spx_per_federal_debt_full_history` (#119)

사용자 제시 TradingView SPX/GFDEBTN 뷰의 공식-원천 재현. 5년 창으로는 안 보이는
1968·2000 고점과 현재 위치를 60년 한 선으로 잇는다.

```
1966=100 기준
1968 고점 103 ──╲
                 ╲  (고점이 낮아지는 60년 하락 추세)
        2000 고점 73 ──╲
                        ╲
              2009 저점 ─── 현재 35 (회복 중)
```

- 수집 창을 GFDEBTN 원점 **1966-01-01로 소급** (`window_start`) — 기존 1995 시작 원장에 1966~1994 append.
- 분기 밀도 241개 관측 (분모가 분기 잔액 — 보간·연장 없음, 실제 관측만).
- **10년 연도 틱·고점 이벤트는 하드코딩이 아니라 데이터에서 파생** (argmax + 120개월 이상 이격 2위 고점).
- 렌더러(`dashboard.js`)에 `axis_note` 지원 1줄 — 5년 비교 고정 aria 문구 대신 차트 자체 축 설명.
- 결론 문구(자동 생성): "1966년을 100으로 두면 현재 35입니다. 1968년 고점 103·2000년 고점 73 대비 34% 수준…"

### 3.4 statistics-backfill.yml (신규 인프라)

새 FRED 시리즈의 원장 백필은 `FRED_API_KEY`가 (당시) CI 시크릿에만 있어 로컬 불가였다.
**실행한 브랜치에** 백필 커밋을 붙이는 워크플로를 신설 — main 무접촉, `statistics-refresh`와 같은
화이트리스트 가드. 이 구조 덕에 "코드+계약+데이터+재생성 스냅샷"이 한 PR에서 원자적으로 이동해
lineage 계약 테스트(스냅샷↔yaml 일치)가 어느 시점에도 깨지지 않는다.

**함정 실측**: `workflow_dispatch`는 기본 브랜치에 파일이 있어야 API 등록된다(404 실측).
브랜치 단계에서는 파일 안의 요청 스탬프를 바꿔 푸시하는 것이 실행 요청. 머지 후에는 dispatch 가능.

### 3.5 계약 정합

- `data/contracts/statistics_lab_v1.yaml`: 시리즈 스펙 2종 등록
- `data/contracts/website_data_lineage_v1.yaml`: 차트→원천 lineage 2행
- 차트 수 고정값 25→26→27 갱신 (테스트)

---

## 4. 작업 4 — FRED 키 로컬 경로 + 수동 갱신 (`6fc25f49`)

### 4.1 키 문제 발견·정정

사용자가 설정한 키가 **플레이스홀더 꺾쇠까지 포함**돼 저장돼 있었다 (`<키>`, len 34 = 32+2).
API 호출이 403 → 오류 URL의 `%3C...%3E`로 원인 특정 → 꺾쇠 제거 후 User 스코프 재설정.
**주의**: 정정 전 오류 메시지에 키가 1회 노출됨. 사용자 결정: 재발급 안 함 (무료 키, 저위험).

### 4.2 검증

- `GFDEBTN` 1966 소급 241행 수신 — FRED 페이지 실측(241 data points)과 정확히 일치
- 영수증 바이트에 키 미포함 (설계: `observations_public_url`은 키 없는 URL만 기록)

### 4.3 수동 갱신 실행 (주간 CI 비대기)

격리 worktree에서 로컬 키로 `statistics-refresh` + `official-data-workbook` 실행:
- 기준 **2026-08-31**, 차트 27개, 관측 52,019건, 원천 49
- CI와 동일 검증: 4스위트 **98 passed** · `security-check` clean · **커밋 파일 키 유출 0건**
  (1차 스캔이 `head` exit 코드 버그로 오탐 → 정확 재스캔 0건 확정)
- CI와 동일 화이트리스트로 4파일 커밋 → main 직push (봇 관례와 동일 경로) → pages 자동 배포
- 사후 `verify` = success

### 4.4 자동 업데이트 최종 상태

| 경로 | 상태 |
|---|---|
| CI 주간 갱신 (`statistics-refresh.yml`, 토 09:20 KST) | ✅ SPX/GFDEBTN 2종 포함 전 시리즈 |
| IPO EDGAR 격주 감시 (`ipo-edgar-watch.yml`, 짝수 주 토 10:40 KST) | ✅ |
| 브랜치 백필 (`statistics-backfill.yml`) | ✅ dispatch 가능 |
| 로컬 즉시 갱신 (`python -m ai_fc statistics-refresh`) | ✅ 키 정정으로 개통, 실증 완료 |

---

## 5. 병렬 세션 공존 기록 (검토 시 참고)

이 세션은 같은 워킹트리·같은 main을 쓰는 **다른 Claude 세션들과 병렬**로 진행됐다.
충돌 없이 끝내기 위해 쓴 규율과 실측 사례:

1. **모든 작업은 격리 worktree** (`worktrees/active/*`) — 공유 트리 HEAD·미커밋 파일 무접촉.
2. **PR #102 red 차단 사례**: 감시가 "MERGEABLE/CLEAN"을 알렸을 때 그대로 머지하지 않고
   격리 worktree에서 재검증 → 보호 스냅샷 불변성 테스트 실패 발견 (`1 failed, 968 passed`).
   GitHub `pr checks`의 "no checks reported"는 head 이동 직후의 착시였다.
   → 머지 보류, 타 세션이 자체 수정(`fix: relocate build-out artifacts…`) 후 스스로 머지. 개입 0.
3. **로컬 실패 ≠ 저장소 실패**: `test_dashboard` 4건 실패가 공유 트리의 **타 세션 미커밋 변경** 탓임을
   stash 재현으로 분리 (CI green으로 확증). 최초 보고를 PR 본문에서 정정.
4. **HEAD 탈취 사례**: 커밋과 푸시 사이 타 세션이 공유 트리 브랜치를 바꿔 첫 푸시가 옛 main을 올림
   → SHA 지정 푸시(`git push origin <sha>:refs/heads/<branch>`)로 복구.
5. **머지·삭제 체이닝 금지**: 머지가 실패해도 삭제는 실행돼 열린 PR의 head 브랜치를 지운 전례(타 세션 #88·#114)
   → 삭제는 `state=MERGED` 확인 후 별도 명령.
6. 위 규율은 메모리(`feedback-check-main-before-fixing`)에 영구 기록.

---

## 6. 함정·발견 대장 (재사용 가치)

| # | 발견 | 실측 근거 |
|---|---|---|
| 1 | bash `$(( 08 % 2 ))`는 8진수 파싱으로 죽는다 → `10#` 강제 | `value too great for base` 재현 |
| 2 | EDGAR `startdt`는 포함 경계 — reviewed_through 그대로 쓰면 재수집 | 13건→11건 |
| 3 | `www.sec.gov/Archives`는 일부 UA를 403 차단 — 기존 검증된 UA 문자열 재사용 | UA A/B 실측 |
| 4 | FRED `SP500`은 최근 10년만 — 장기 비교엔 OECD 시리즈가 공식 대안 | FRED 페이지 |
| 5 | `workflow_dispatch`는 기본 브랜치에 파일 필요 (404) — 브랜치 단계는 self-path push 트리거 | API 404 |
| 6 | 대시보드 스크린샷 rAF 함정 — 빈 캡처는 환경 탓, DOM(`read_page`/JS)으로 검증 | 기존 메모리 재확인 |
| 7 | FRED 봇 필터가 WebFetch 403 — 브라우저 팬으로 우회해 문서 확인 | NETWORK_RECOVERY 정합 |
| 8 | 쉘 파이프라인 `grep -rl … \| head && echo` 는 head가 항상 exit 0 → 오탐 | 키 스캔 1차 오탐 |

---

## 7. 검증 총괄

| 시점 | 결과 |
|---|---|
| #98 최종 | 전체 956 passed, 7 skipped + verify/refresh CI green |
| #101 머지 전 (새 main 위 머지 프리뷰) | 957 passed |
| #118 최종 (백필 후) | 990 passed + 게이트 5종 (sync/inventory/audit-ledgers/provider/security/verifier) |
| #119 최종 (백필 후) | **991 passed, 7 skipped** + 게이트 전부 |
| 수동 갱신 커밋 | 검증 4스위트 98 passed + security clean + 사후 verify success |
| 대시보드 실렌더 | 유동성 탭 카드 DOM 검증 (SVG 451×226·두 시대 선·결론/caveat 문구) |

배포는 각 머지 직후 pages build/deploy success 확인 — 최종 배포 시점 기준 배포 sha = main.

---

## 8. 남긴 것 / 후속 제안

1. **EDGAR 대기열 첫 검토**: `edgar_candidates.json`의 11건 중 AI 코호트 편입 후보를
   최종 투자설명서로 검토 → `ipo_comparison_v1.json` 현재 구간 행 갱신 + `reviewed_through` 전진.
   (자동화 범위 밖 — 계약상 사람 검토 필수)
2. **격주 감시 첫 자동 실행**: 다음 짝수 ISO 주차 토요일. Actions Summary에 후보 표+링크 출력됨.
3. **키 노출 잔여 리스크**: 사용자 결정으로 재발급 안 함. 마음이 바뀌면
   FRED 계정에서 재발급 후 `[Environment]::SetEnvironmentVariable('FRED_API_KEY','<새 키>','User')`
   (꺾쇠 없이) + CI 시크릿 동시 교체.
4. **`spx_per_federal_debt` 5년 비교의 현재 선**: 분모 분기 지연으로 최신 관측이 2026-01(Q1)에서 멈춤 —
   Q2 발표 시 주간 갱신이 자동 연장. 이는 "실제 관측만, 연장 없음" 원칙의 정상 동작.

---

## 9. 검토자 체크리스트

- [ ] EDGAR 감시가 게시 수치(`ipo_comparison_v1.json`)를 절대 쓰지 않는가 → `test_watch_writes_only_its_own_queue_and_never_the_published_reference`
- [ ] 격주 게이트가 8·9주차에도 사는가 → `ipo-edgar-watch.yml`의 `10#$week`
- [ ] OECD 분자 대용이 두 차트 caveat에 명시돼 있는가 → 대시보드 유동성 탭 카드 "이 수치의 한계"
- [ ] 전 구간 차트의 고점 이벤트가 데이터 파생인가 → `test_spx_debt_full_history_walks_from_the_first_observation_with_peak_events`
- [ ] 커밋된 어떤 파일에도 FRED 키가 없는가 → `security-check` + 본 문서 4.3
- [ ] 중분류 번호가 리터럴로 회귀하지 않았는가 → `test_mid_category_numbers_are_derived_after_filtering_not_hardcoded`
