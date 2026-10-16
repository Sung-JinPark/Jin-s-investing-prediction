# NASDAQ 일일 시황 연구 프리뷰

`#future/original`의 새 연구 패널은 전체 분포에서 전형적인 실제 경로 하나를
선택해 252개 미래 거래일과 기준 종가를 모두 그린다. 날짜별 정확한 중앙값,
50%/80% 분위 구간, 시황 미반영 중앙값, 고점 대비 낙폭을 함께 제공한다.
기존 S1 구조선과 그 과거 대조 기록은 명시적 비교 토글에서 보존한다.

## 모델과 표시 의미

- 기존 `quant.mc.gbm_paths`의 252세션·20,000개 경로와 seed42를 그대로 사용한다.
- 7개 축 × 5/21/63세션 반감기 상태를 무절편 ridge로 학습한다. 입력 중립값0을
  보존하며 기존 GBM의 `mean(log_return)-sigma²/2` 관례도 변경하지 않는다.
- 5/21/63세션 성숙 라벨에 가중치 .25/.50/.25를 적용한다. 스케일·family당30사건
  하한·정규화 선택은 각 학습 구간 안에서만 계산한다. 최소756개의 성숙한 전진
  원점이 필요하다. 반복된 주말 발행은 같은 원점의 새 독립 표본으로 세지 않는다.
- 월별 계수는 시간순 purge·embargo 검증과 63원점 블록 bootstrap200회로 동결한다.
  baseline/market-only/event-only/combined/FHS를 구분한다. 미적합 비교군은 결측이며
  baseline을 해당 모델 성과로 대신 표시하지 않는다.
- 시황의 추가 drift는63세션 이후0이고 그때 누적된 log-level 효과만 유지한다.
  새 모델이 사건별 변동성이나 극단손실을 학습했다고 설명하지 않는다.
- 대표경로는 종료수익률·최대낙폭·변동성·하락일·방향전환 순위가 중앙에 가까운
  실제 행이다. 표시를 위한 추가 굴곡·spline·주간 thinning은 없다. 날짜별 중앙값과
  실제 대표경로는 서로 다른 통계이다. 실제 하락 날짜를 맞혔다는 뜻이 아니다.
- 낙폭은 각 경로의 기준일 이후 running peak에 대한 `P/peak-1`이다. 중앙값 가격선의
  낙폭으로 전체 분포의 낙폭을 대신 계산하지 않는다. 확률 저장 단위는 fraction이다.

## 입력·운영

매일05:20UTC(14:20KST)에 공개 원천을 수집한 후 실제 수집 완료 시각을 발행
`as_of`로 고정한다. 휴장일은 새 사건만 반영하며 가짜 종가를 생성하지 않는다.
XNAS 요청 달력과 실제로 해결된 달력 이름·거래일·원문 해시를 보존한다.
수집 완료 시각을 workflow 전체의 고정 마감으로 넘긴다. 그 이후에 적합이 끝난
새 계수는 이번 마감에 소급 적용하지 않고 다음 적격 발행부터 사용한다.

새 원천은 FRED 공개CSV와 BLS/Fed/Anthropic/BIS/메모리 기업 공식 발표이다.
각 원천의 실패 상태를 보존하며, 임의의 감성점수를 가격효과로 바꾸지 않는다.
CXMT는 원천 약관 검토 필요 상태로 비활성 등록한다.

CSV의 과거 값은 현재 발행의 baseline 입력으로 사용할 수 있지만 과거 예측시점에
실제로 수집한 자료로 부르지 않는다. raw는 원문 전체를 보존하고 정규화 원장은
원천당 최근3,000개 관측을 선택한다. 동일 관측 재수집은 최초 capture를 유지하고
정정은 새 revision으로 추가한다. 학습은 불변 발행 상태와 이후 최초 채점 때
확인한 실제 관측만 사용하며, 그 결과도 이후에 덮어쓰지 않는다.

소표본·미지원 사건은 참고용으로 남기고 numerical coefficient는0이다.
수집 실패는 중립0이 아니다. 필수 종가·시간·단위·해시·신선도 오류는 발행HOLD다.
계수가 없으면 그래프는 시황 보정 미적용을 밝히고 종합점수는 산출 대기로 표시한다.
예측력은 계속 `not_established`이며 공식 예측/벤치마크/기존 시나리오 원장을 쓰지 않는다.

## 실행

기존 실행 환경의 `src` 디렉터리에서 사용한다. 새 의존성 설치나 키 연결은 필요하지 않다.

```powershell
python -m ai_fc market-context-collect
python -m ai_fc market-context-resolve
python -m ai_fc market-context-fit
python -m ai_fc market-context-build
python -m ai_fc market-context-verify --replay
```

명시 정정은 `market-context-build --supersedes <forecast-id>`를 사용한다.
하루의 기존 발행본과 기록을 보존하며, 동일 일자 재실행은 임의 새 발행을 만들지 않는다.

JSON 발행본·원장·원문은 `data/market_context`, 선택적 전체 NPZ 경로는
`outputs/market_context/paths`에 저장한다. full-path 파일이 없어도 동결 입력으로
`--replay`할 수 있으며 실제 파일 누락과 재생성 성공을 구분해 보고한다.
화면 데이터는 별도 SHA256 검증 사이드카 `market_context.json` 또는 읽기 전용
`/api/market-context`에서 가져온다. API는 원장이나 파일을 수정하지 않는다.

## 검증

저장소 루트의 PowerShell에서 표적 테스트를 실행한다.

```powershell
$contextTests = @(rg --files src/tests | Where-Object { $_ -match 'test_market_context.*\.py$' })
python -m pytest @contextTests -q
```

`python tools/preview_market_context.py --capture`는 가상 입력만 사용해
데스크톱/모바일 화면과 검증 결과를 `outputs/market_context_preview`에 생성한다.
실제 자료·공식 원장을 쓰지 않는다.

성과 평가는 선택 대표선의 오차 대신 실제 공동 분포의 CRPS/WIS·포함률·낙폭·터치
확률로 수행한다. 21세션 CRPS2% 개선, 성숙PIT252원점·비중첩12블록,
의존성을 보존한 단측95% 비교, 보조 지평 악화/포함률 검사를 사전등록했다.
63세션을 승격 근거로 사용하면 비중첩8블록이 추가로 필요하다.
기준 통과도 자동 승격을 의미하지 않는다. 기존 봉인 성적을 승계하지 않는다.

## V1 동결과 코드 변경

V1의 수치 알고리즘과 선택·평가 규칙은 계약값으로 동결한다. 계약 파일의 숫자만
바꾸어 다른 규칙으로 실행할 수 없으며, 변경은 새 계약·모델 버전과 shadow 검증을
필요로 한다. 수치 코드 또는 계약 해시가 바뀌면 기존 발행본과 계수는 재사용·재현
검증을 통과시키지 않고 HOLD한다. 과거 발행본·원장은 그대로 보존하며, 과거
재현과 만기 채점에는 해당 발행 당시의 코드·계약 runtime을 보존해 사용해야 한다.
다른 코드로 계산한 결과를 과거 발행의 성공적인 replay로 표시하지 않는다.
발행본과 계수에는 Python·NumPy·SciPy·거래소 달력 라이브러리 버전도 기록한다.

## 구현 검증 결과 · 2026-10-15

| 검사 | 결과 |
|---|---|
| 최종 시황·대시보드·계약·workflow·inventory 표적 묶음 | 245 passed |
| 전체 `src/tests` | 1,546 passed / 7 skipped / 6 failed |
| DualDB 전체, 읽기 전용 백업으로 만든 임시 DB에서 실행 | 53 passed / 1 failed |
| 신규 소스·테스트 Ruff / `git diff --check` | 통과 |
| 1280px·390px 브라우저 검증 | 253점, 기간 전환, 날짜 선택, 터치·키보드, S1 토글 통과 |
| 실제 신규 원장 무결성·replay 검사 | 통과, 수치 발행 0건·만기 채점 0건 |

전체 묶음의 실패는 신규 기능의 코드 실패와 구분한다. V5.2 세 건은 작업 시작 때부터
수정돼 있던 `data/ml_history/2026.jsonl`과 기존 후보 봉인 해시의 불일치이고,
셸 테스트 세 건은 이 Windows 환경에 `/bin/bash`가 없는 환경 문제다. DualDB 한 건은
기존 IXIC 자료의 최신일이 2026-08-12여서 신선도 조건을 만족하지 못한 자료 문제다.
이 검사들을 통과시키려고 과거 데이터·봉인 해시를 바꾸지 않았다.
별도 전역 원장 감사에도 기존 cross-asset archive 두 파일과 IPO 영수증 네 파일의
해시 불일치가 남아 있다. 해당 파일과 감사 기준 역시 변경하지 않았다.

실제 공개 수집본은 원문 영수증29개, 관측22,137개, 원본 사건19개다. 사건은
13개 사실 그룹으로 구분되며 SK hynix 재게시6건은 추가 충격에서 제외한다.
NASDAQ의 비거래일 오류1건은 원문과 거절 원장에 보존했다. BLS RSS의 HTTP403은
수집 실패로 표시한다. 2026-10-15T01:38:24Z 발행 시도의 최신 수집 종가는
2026-10-13이어서 `stale_or_missing_index_anchor` HOLD가 맞다.
성숙한 전진 학습 원점도 아직0개이므로 계수·종합점수는 산출 대기이며 예측력은
`not_established`다. 현재 수집한 과거 CSV를 과거 PIT 예측 성과로 사용하지 않는다.

가상 자료 화면은 `outputs/market_context_preview/market_context__1280.png`와
`market_context__390.png`에 있으며 실제 시장 전망이 아니라는 표식을 포함한다.
검사 로그·JUnit·원장 검증 결과는 로컬 `outputs/market_context_checks/`에 보존했다.
일일 GitHub workflow와 Pages 연결은 구현했으며 원격 배포는 수행하지 않았다.
