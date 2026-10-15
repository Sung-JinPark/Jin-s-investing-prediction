# NASDAQ 6개월 일별 연구 프리뷰

`#timeseries/daily`는 기존 V8과 독립된 `daily6m_v1` 연구 모델을 표시한다. 위에는 실제 종가와 일별 중앙값·50%/80% 분위 구간, 아래에는 **전 거래일 종가보다 오를 확률**을 표시한다. 두 그래프는 같은 날짜를 선택한다. 1·3·6개월 전환은 하나의 발행본을 자르며 다시 예측하지 않는다.

## 수치의 의미

- 같은 20,000개 다변량 공동 경로에서 가격 분위수와 상승확률을 계산한다. 첫날은 기준 종가, 이후는 각 경로의 직전 종가와 비교한다. 중앙선의 변화로 확률을 만들지 않는다.
- expanding/rolling 2,520세션 앙상블은 50:50이다. 기존 V2 적합·잔차 선택·시뮬레이션을 읽기 전용으로 재사용한다. 성장·물가 상태와 발표 경과일 외생 입력은 발행 당시 값으로 고정한다.
- 만기는 기준 날짜에서 달력상 6개월 뒤다. 실제 마지막 XNAS 거래일과 달력 종료일을 별도로 보존한다. 휴일에 값을 만들지 않는다.
- 표시하는 다섯 점선은 마지막 지수 순위의 10/25/50/75/90%에 가까운 실제 경로이다. 확률 계산은 전체 경로를 사용한다.
- 범위는 각 날짜의 분포이며 전체 경로를 계속 담는 동시 신뢰구간이나 검증된 적중률이 아니다.

## 시점·검증 계약

발행 시각 `as_of`와 기준 종가 날짜 `anchor_date`를 분리한다. 과거 추론·학습의 원천 자료는 공개 시점·빈티지·캡처 시점을 각각 보존한 native ALFRED 사실이다. NASDAQ/VIX는 실제 XNAS 세션별 값이 필요하며 금리·금리차·달러는 명시적으로 마지막 가용 수준을 유지한다. 기존 논리 입력을 유지하되 VIX는 VIXCLS, 금리차는 native T10Y2Y를 사용한다. DTWEXB→DTWEXBGS의 전환일과 차분 경계를 계약에 기록한다.

최신 기준일에 native 입력이 아직 공개되지 않은 경우에는 별도 등록한 공식 입력을 `captured_forward`로 연결할 수 있다. 이미 사용할 수 있는 native 값이 우선하며, 이 경로는 과거 native 관측이나 동결 모형의 입력을 교체하지 않는다. 사용한 경우 발행 계보에 `native_alfred_vintages_plus_official_captured_tail`을 남긴다.

| 공식 입력 | 연결 범위와 검증 |
|---|---|
| Nasdaq Composite `COMP` | 최근 30일 공식 이력과 native 값이 최소 5세션 정확히 일치해야 한다. 직전 native 종가, 지수 정체성, 완료 세션 날짜와 `Closed`/`After-Hours` 상태를 확인하며 최신 완료 XNAS 세션 한 점만 허용한다. |
| CBOE VIX | 최신 완료 XNAS 세션 한 점을 `VIX`에서 논리 입력 `VIXCLS`로 연결한다. 기존 V2에 보존된 검증된 공식 VIX도 읽기 전용 대안으로 유지한다. |
| 미국 Treasury 2년물 `DGS2` | 마지막 가용 native 뒤부터 현재 기준일까지 최대 5 XNAS 세션의 실제 발표 행만 연결한다. native와 겹치는 최소 5개 값이 정확히 일치해야 한다. Treasury 휴일에는 마지막 알려진 수준을 명시적으로 유지하며 가상 관측 행을 만들지 않는다. 필요한 정상 발표일 값이 빠지면 HOLD다. |

Nasdaq·VIX의 중간 세션 결측을 이 경로로 채우지 않는다. Treasury의 짧은 연결 구간도 해당일 실제 원문이 모두 있어야 하며 과거 native 이력을 재구성하는 용도로 쓰지 않는다. 금리 원단위 `percent`는 연율 4.82가 4.82%라는 뜻이며 확률의 fraction 단위와 구분한다.

각 행의 원문 SHA256·관측 ID·영수증·단위·등록된 HTTPS 요청/응답 경로를 재검증한다. `available_at`과 `vintage_start`는 응답을 실제로 받은 완료 시각으로 두고 발행 시각을 넘지 않아야 한다. 뒤늦게 수집한 공식 행을 과거 발행 시점으로 소급하거나 native로 부르지 않는다. CBOE의 리디렉션은 계약에 적힌 `cdn.cboe.com`에서 `cdn-api.cboe.com`의 동일 전체 경로로 향하는 한 방향만 허용하고 실제 응답 URI도 영수증에 보존한다. 그 밖의 호스트·경로 변경은 허용하지 않는다. 신선도 한도와 발행 직전 재검사는 그대로 적용한다.

DFM 캐시는 원본 해시·입력 해시·native 추정 지위·기존 수치 런타임을 확인한다. 캐시 cutoff를 실제 생성 시각으로 바꾸어 부르지 않는다. 실제 availability가 없는 캐시는 로컬 materialization 시각을 보수적인 acquisition 하한으로 기록하므로, 이를 앞서는 과거 발행 요청은 거부한다.

예측 발행 전 입력·신선도 검사와 append 직전 검사를 모두 수행한다. 같은 지평·입력·seed의 V8 원시 공동 경로 커널 비교, 재현성, 경로 재집계, 독립 FHS 경로 비교를 기록한다. 기존 V8의 보정된 종료점은 새로운 native 입력과 보정 상태가 비교 가능하지 않으면 **비교 불가 사유**를 남긴다. V8 봉인 성적을 이 모델에 승계하지 않는다.

현재 충분한 strict-PIT 과거 평가창과 전진 성능은 확립되지 않았다. 모든 숫자에 `predictive_validation=not_established`를 유지한다. 공식 예측·벤치마크·시나리오 원장은 쓰지 않는다.

## 실행과 저장

기존 실행 환경에서 `src` 디렉터리를 기준으로 사용한다.

```powershell
python -m ai_fc timeseries-daily6m-forecast
python -m ai_fc timeseries-daily6m-resolve
python -m ai_fc timeseries-daily6m-latest
python -m ai_fc timeseries-daily6m-verify
```

새 원장·불변 run 요약은 `data/timeseries_daily6m`에 저장된다. 주간 실행은 ISO 주 단위로 중복을 막는다. 명시적 정정은 `--supersedes <forecast-id>`로 새 revision을 추가하며 원본을 보존한다. 전진 채점은 장이 끝나고 해당 관측이 공개된 뒤에만 추가한다. 첫 발행 전 HOLD도 현재의 입력 신선도·거부 사유를 숫자 없이 공개한다.

## 공식 입력의 별도 5분 수집

`daily6m-sources-refresh`는 UTC 매시 4·9·14분부터 59분까지 5분 간격으로 위 세 원천을 확인한다. GitHub 예약과 원천 발표 지연 때문에 5분 내 반영을 보장하지는 않는다. 기존 30분 native 입력 수집과 일일 전체 수집·DFM 작업은 그대로 유지한다. 장중 미완료 시세나 아직 발표되지 않은 완료 세션은 대기 사유로 남기며 새 관측으로 만들지 않는다. 통신·스키마·원문 검증 실패와 이 대기 상태를 구분한다.

수집 단계는 원장에 쓰지 않고 공개 원문과 영수증을 가진 불변 묶음을 만든다. 발행 단계는 최신 main의 임시 체크아웃에서 원문을 다시 파싱하고 해시·시각·단위·중복을 검사한다. 다른 writer가 먼저 저장하면 새 main에서 같은 묶음을 최대 3회 재생하며 강제 푸시나 기존 행 수정은 하지 않는다. 수집에 일부 실패가 있어도 독립적으로 검증된 행은 보존하고 실패를 보고한다. 단순한 재수집 시각 변화는 새 관측으로 세지 않는다.

소스 저장 경로는 `data/timeseries_daily6m/raw`, `source_receipts.jsonl`, `source_observations.jsonl`뿐이다. 관측 정정은 `supersedes`로 연결한 새 행이다. 기존 native 원문·사실·V2 원장·동결 모형·봉인 성적·공식 예측 및 벤치마크 원장은 쓰지 않는다. 원시 자료는 웹 배포 대상이 아니며 source registry의 이용 조건도 유지한다.

실제 새 값이나 정정이 저장됐을 때만 별도 `timeseries-daily6m` 작업을 호출한다. 동일 응답이면 커밋·모델 실행·배포를 만들지 않는다. 호출된 작업은 입력/PIT/신선도 검사를 다시 수행하며, **기준 세션의 ISO 주당 발행본 하나**를 유지한다. 5분 수집이 예측을 5분마다 새로 발행한다는 뜻은 아니다. 기존 발행본의 해소·표시 게이트 갱신과 성공한 변경의 Pages 배포 연쇄는 유지한다.

이 공식 실시간 입력은 현재 예측과 표시를 위한 자료다. 실제 결과의 Brier·구간 포함 여부는 계속 별도로 공개된 native NASDAQ 결과로 채점한다. `captured_forward` 시세를 native 결과로 사용하거나 기존 점수를 다시 쓰지 않는다. 연구 지위와 `predictive_validation=not_established`도 유지한다.

운영 계약은 [공식 입력 계약](../../data/contracts/daily6m_official_sources_v1.yaml)과 [6개월 모델 계약](../../data/contracts/timeseries_daily6m_v1.yaml)에 있다. 기존 실행 환경에서 수동 점검할 때는 다음 명령을 사용한다. `--root`는 적용할 별도 체크아웃을 지정한다.

```powershell
python -m ai_fc timeseries-daily6m-sources-capture --out .tmp/daily6m-capture --report .tmp/daily6m-capture-report.json
python -m ai_fc timeseries-daily6m-sources-apply --bundle .tmp/daily6m-capture --report .tmp/daily6m-apply-report.json
```

## 해소·배포와 검토

결과 정정도 기존 `resolutions` 원장에 추가한다. 해당일 또는 직전 거래일의 native 종가·공개 시각·빈티지·원천 해시가 바뀌면 현재 결과를 `supersedes`로 연결한 정정 행을 만들고 원본 결과를 보존한다. 같은 원천 값을 다시 캡처한 시각만 바뀐 경우에는 결과를 추가하지 않는다. 두 종가의 원천 ID·SHA256·빈티지·공개 및 캡처 시각을 각 행에 보존하며, append 전과 검증 시 보존된 native 원본 관측에 정확히 연결한다. 원본 관측 청크의 경로·해시·행 수도 검증하고, Parquet에서 최신 정정으로 대체된 이전 관측은 불변 원본 청크에서 확인한다. 검증은 불변 예측의 날짜·직전 거래일·확률과 실제 결과·Brier 점수·80% 구간 포함 여부를 재계산한다. 아직 공개되지 않은 종가는 기다리며, 더 나중 종가가 존재하는 구간의 결측은 오류로 거부한다.

기존 V2 원천 수집은 화–토 08:20 UTC(17:20 KST)에 예약한다. 2026년 10월 1–10일의 보존된 공식 자료 캡처 8회가 모두 07–08시 UTC에 직전 완료 거래일을 포함했다는 기록에 맞춘 운영 시각이며, 공개 CSV의 발행 시각 보장은 아니다. 동결 모형·봉인 평가 좌표와 주간·월간 UTC 요일 조건은 바꾸지 않는다. 새 워크플로는 main의 수집 완료 후 연쇄 실행하며, 화–토 09:20 UTC(18:20 KST)에 추가 예약 실행한다. native ALFRED의 보수적인 뉴욕 공개 시각과 늦은 원천 체크포인트를 기다리며, 모든 실행에서 공개 시점·신선도 검사를 다시 수행한다. 예측 자체는 주 1회이며 이후 실행은 같은 발행본을 보존하고 성숙 결과·표시 게이트를 갱신한다. 새 연구 원장을 등록된 원장 감사에도 포함한다.

전체 경로는 `outputs/timeseries_daily6m/paths`의 선택적 로컬 NPZ 산출물로 보존하며 워크플로가 별도 artifact로 업로드한다. 존재하는 경로는 해시·shape·일별 통계·표본을 재검증한다. fresh checkout에 없는 과거 경로는 `missing_optional_path_artifacts`로 보고하며 전체 경로 replay가 완료된 것처럼 표현하지 않는다. JSON 원장과 불변 run은 항상 검증한다.

정적 웹은 `timeseries_daily.json`, 서버는 읽기 전용 `/api/timeseries-daily`를 사용한다. 본문에는 상태·발행 ID·기준일·해시만 먼저 싣고 상세는 일별 탭 진입 시 받는다. 파일은 128KiB 이하이며 실제 UTF-8 파일 해시와 발행 메타데이터를 확인한다. 실패·HOLD에 기존 모델 숫자로 전환하지 않는다.

## 로컬 화면 검토

실제 자료·원장을 쓰지 않는 가상 입력 프리뷰를 생성한다. 설치 작업은 수행하지 않는다.

```powershell
python tools/preview_timeseries_daily6m.py --capture
```

`outputs/timeseries_daily6m_preview/index.html`과 모바일·데스크톱 PNG, 브라우저 검사 JSON을 만든다. 페이지에는 **검토용 가상 입력 · 실제 시장 전망이 아님**을 표시한다. 모델의 실제 적합 및 20,000개 경로 생성, 기간 전환, 경로 토글, 키보드·마우스·터치와 가로 넘침을 검사한다.

직접 파일로 열 수 있는 fixture 전용 `standalone.html`도 함께 생성한다. 실제 배포는 발행 메타데이터와 파일 해시를 확인하는 별도 사이드카 방식을 유지한다.

초기 검토인 2026-10-12에는 최신 native 자료가 NASDAQ·금리차 10월 9일, 단기금리·VIX 10월 8일, 달러 10월 2일까지여서 신선도 조건으로 HOLD였다. 이 기록은 현재 발행 상태를 뜻하지 않는다. 현재 상태와 거부 사유는 최신 발행 검사 결과로 판단한다. 최초 공동 학습 이전 native 소스 결측은 감사 가능한 warmup 목록으로 보존하며, 이후 학습 구간의 일별 결측은 계속 발행을 차단한다. 입력 갱신과 비교 검사가 통과한 발행본부터 연구 프리뷰를 표시한다.
