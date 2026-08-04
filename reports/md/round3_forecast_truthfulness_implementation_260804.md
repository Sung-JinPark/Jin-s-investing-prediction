# Round 3 날짜 재기준·경로 사실성·검증 커버리지·캘린더 구현 보고

작성일: 2026-08-04 KST

기준 커밋: `38ad84e`

## B. 시나리오 경로 사실성

- 기존 S1/S2/S3 굵은 선과 확률은 변경하지 않는다. 이 선은 각 시나리오 묶음의 주별 중앙 경로다.
- 같은 GBM 호출로 만든 일별 20,000경로에서 최대낙폭 분포와 5%·10% 조정 경험 비율을 계산한다.
- 실제 경로 표본은 각 묶음 종점의 25/50/75 백분위에 가장 가까운 경로를 선택하고, 동률이면 원본 path index가 낮은 경로를 고른다.
- `2026-08-03` 기존 경로·확률·일별 분위수와 재생성 결과의 일치를 확인한 뒤 `CORR-260804-012` revision으로 사실성 블록만 추가한다.
- UI는 굵은 중앙 경로와 얇은 회색 실제 경로를 함께 보여주며, 실제 경로 토글은 기본 ON이다.

`nasdaq-scenario:2026-08-03:r3` 결과:

| 묶음 | 경로 수 | 최대낙폭 중앙값 | 5% 이상 조정 경험 |
|---|---:|---:|---:|
| S1 | 16,702 | −12.7% | 100% |
| S2 | 302 | −12.5% | 100% |
| S3 | 2,996 | −16.4% | 100% |

이 문서는 A·E·D·C 단계 구현 결과와 최종 검증표를 같은 라운드에서 이어서 기록한다.

## A. 선택일 = 100 재기준 조회

- URL은 `#lookup=YYYY-MM-DD&mode=rebase|current`를 사용하며 기본값은 `rebase`다.
- 재기준 차트의 D 시점은 항상 100이다. D+h 값은 별도 재시뮬레이션이나 보간 없이 현재 스냅샷의 동일 h 거래일 분위수를 현재 anchor로 나눠 지수화한다.
- 선택일이 늦어질수록 마지막 산출일까지 남은 거래일만 표시한다. 실제 날짜와 `D+N주/개월` 상대 축을 함께 쓴다.
- 현재 원점 모드로 전환하면 기존 절대 수준 팬차트와 파란 조회 보조선을 그대로 볼 수 있다.
- 재기준 화면에는 “D일의 새 가격·변동성은 아직 반영되지 않았고 D일에 새 스냅샷이 계산된다”는 한계를 항상 표시한다.
- 독립 JavaScript 기하 테스트로 3개 선택일의 원점 100, 동일 h 분포 사용, 잔여 지평 축소를 검증했다.

## E. 지평별 검증 커버리지

- `band_calibration.csv`에 `horizon_trading_days`를 추가했다. 아직 데이터 행이 없던 승인 원장이므로 과거 행을 변형하지 않고 스키마를 확정했다.
- 한 종가가 확정되면 해당 날짜를 포함하는 과거 스냅샷 가운데 asof별 최신 revision을 모두 채점한다. 같은 `(실현일, origin_snapshot_id)`는 다시 쓰지 않는다.
- read-model은 1주·1개월·3개월·6개월·12개월 버킷별 표본 수와 p10–p90 적중 횟수를 제공한다.
- 버킷 표본이 60개 미만이면 적중률 숫자는 데이터와 화면 모두에서 숨기고 `축적 중 n/60`만 표시한다.
- 현재 원장은 0행이므로 모든 지평을 `미검증 구간 — 적중 기록 축적 중 (0일 · 0/60)`으로 표시한다. 6개월·12개월 버튼에도 같은 한계가 먼저 보인다.

## D. 12개월 이벤트 캘린더

- D0 계약은 연준 FOMC, BLS CPI, BLS 고용, BEA GDP, NVIDIA/기업 IR을 무료 공식 원천으로 등록한다. Yahoo 실적 캘린더는 사용하지 않는다.
- `data/calendar/events.csv`는 2026-08-07부터 2027-07-29까지 53건을 등록했다. 구성은 FOMC 8, CPI 12, 고용 12, GDP 12, 실적 9건이다.
- 기관·기업이 날짜를 공개한 19건은 `confirmed`, 2027 BLS/BEA 미공개 일정과 기업 발표 월 패턴 29건 및 연준이 명시한 2027 공식 잠정 일정 5건은 `estimated`다. 공식 페이지에 올라왔더라도 연준이 잠정이라고 명시한 2027 일정은 확정으로 과장하지 않았다.
- 일정 정정은 기존 행을 고치지 않고 새 행의 `supersedes`가 과거 event_id를 가리킨다. `superseded_by`는 read-model에서 파생하므로 이전 CSV 바이트를 수정하지 않는다.
- 차트 위 긴 일정 문자를 없애고 kind별 회색조 도형(◇ FOMC, □ CPI, ○ 고용, △ GDP, ⬡ 실적)으로 바꿨다. 추정 일정은 점선 테두리이며 키보드 포커스와 hover 제목을 제공한다.
- 조회 카드는 asof부터 선택일까지 kind·ticker별 등록 건수와 추정 건수를 요약한다. 일정과 분포 확률을 연결하지 않는다는 문구를 고정했다.

공식 근거: [Federal Reserve FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [BLS CPI schedule](https://www.bls.gov/schedule/news_release/cpi.htm), [BLS Employment Situation schedule](https://www.bls.gov/schedule/news_release/empsit.htm), [BEA release schedule](https://www.bea.gov/news/schedule), [NVIDIA IR](https://investor.nvidia.com/events-and-presentations/events-and-presentations/).

## C. DB 축적 감사와 공개 설명

- `scenario_band_calibration`의 중복 `timestamp_field`와 `planned` 강제값을 제거했다. writer는 작동하지만 아직 채점 가능한 실현 행이 0개이므로 `allow_empty_accumulating` 계약으로 0행을 숨기지 않은 채 accumulating 상태를 표시한다.
- 신규 `market_event_calendar`를 append_csv/event cadence 원장으로 등록했다. `path_realism`은 scenario snapshot 내부 필드이므로 별도 원장으로 중복 등록하지 않았다.
- 감사 전 기존 manifest의 10개 해시가 현재 Git HEAD blob과 달랐다. 각 대상의 working-tree SHA-256이 Git HEAD blob SHA-256과 정확히 일치함을 먼저 확인했고, 데이터 파일을 손대지 않은 채 manifest의 뒤처진 기준 해시만 현재 공개 HEAD에 동기화했다. 이 기준 보정 사실을 숨기지 않고 이 보고서에 남긴다.
- 신뢰 센터에 `데이터는 이렇게 쌓입니다` 카드를 추가했다. 파일 원본 → 화–토 확정값 → 원장 감사 → 월간 Parquet 연구팩 → 미축적 상태 공개의 5단계를 비전공자 문구로 설명하며, 원장 수와 상태는 감사 read-model에서 실시간으로 읽는다.

감사 명령 원문:

```text
ledger audit: accumulating=25 stalled=0 inactive=0 violation=0 planned=3
```
