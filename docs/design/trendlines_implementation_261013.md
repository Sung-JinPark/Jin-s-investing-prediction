# 미래탐색 상·하방 추세선 v1

미래탐색의 마지막 카테고리에서 SK하이닉스·SOXX·나스닥종합·S&P500·BTC/USD·다우·Solactive Magnificent Seven Equal Weighted PR를 각각 보여준다. 기본은 SK하이닉스, 단기 63세션, 선형 가격축이다. 예측 확률이나 기존 공식 모델의 결과를 변경하는 기능이 아니다.

## 원천과 초기 상태

7개 대상에 승인된 무료 OHLC 정본이 아직 없으므로 최초 배포는 모두 **미산출**이다. 무료 조회와 공개 사이트 표시 권한을 구분하며, 소스 정책은 기본 거부다. 종가를 고저가로 합성하거나 NASDAQSOX를 SOXX ETF, MAGS를 공식 M7 지수로 바꾸지 않는다. 가상 READY 검수 화면은 `검토용 가상 입력`으로 구분한다.

자산 식별·통화·단위·달력·일봉 종료 시각·분할 조정 기준은 registry에 선언한다. 신규 데이터는 승인된 동일 원천의 portable raw capture/inbox 계약을 통과해야 한다. 새 공급원의 자동 수집·공개 표시 권한과 식별자를 확인하고 해당 원천의 수집기를 별도로 연결하기 전에는 실제 가격을 만들지 않는다. 현재 batch가 네트워크 없이 수행하는 일은 승인된 입력 묶음의 보존·재생, 원장 검수, 상태 갱신이다.

공식 무료 후보 조사 근거: [KRX Open API](https://openapi.krx.co.kr/contents/OPP/MAIN/main/index.cmd), [금융위 주식시세](https://www.data.go.kr/data/15094808/openapi.do), [Coinbase candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles), [Coinbase 시장 자료 조건](https://www.coinbase.com/legal/market_data), [Solactive M7 공식 식별](https://www.solactive.com/indices/?index=DE000SL0KSZ2). 무료라는 이유만으로 이 원천들을 활성화하지 않았다.

## 계산과 계보

계산 창은 63/252/756세션, 피벗 좌·우 확인은 3/5/10세션, 앵커 최소 간격은 10/20/60세션이다. 확정 시점은 오른쪽 확인 봉의 완료와 사용 자료의 실제 availability를 모두 만족해야 한다. 과거 자료 최초 취득으로 재구성한 결과는 실제 당시 발행 이벤트로 기록하지 않는다.

ATR14 단순평균을 사용한다. 접촉 허용폭은 `max(검증된 tick, 0.25 ATR, 선가격 0.1%)`, 이탈 허용폭은 `max(검증된 tick, 0.5 ATR, 선가격 0.25%)`다. 두 접촉은 후보, 세 피벗 이상 접촉은 `3회 이상 접촉선`이다. 이탈·재진입은 각각 확정 종가 2개로 확인하며 결측 봉은 연속성을 끊는다. 미래 연장은 주식·지수 21거래일, BTC 30일이다.

원본 → receipt → bar revision → pivot → line → event → snapshot을 해시로 연결한다. 정정은 supersedes를 가진 새 revision, 새 앵커 선택은 새 line ID다. 원본과 이전 결과를 삭제하지 않는다. 동일 의미 재실행에는 날짜만 바뀐 새 공개본을 만들지 않는다. writer lock과 atomic latest pointer를 사용한다.

승인된 receipt의 가격 검증에 실패한 자료도 quarantine 원문·영수증과 append-only rejection 원장으로 영구 보존한다. 취득 시각·당시 원천 정책·원문 SHA·거절 이유를 연결하여 임시 capture artifact가 없어도 재검수할 수 있다. 격리 자료는 수치 입력으로 사용할 수 없다.

## 실행·배포

기존 환경에서 실행한다. 의존성 변경은 없다.

```powershell
python -m ai_fc trendlines-refresh --capture-only --out .tmp/trendlines-capture
python -m ai_fc trendlines-refresh --bundle .tmp/trendlines-capture
python -m ai_fc trendlines-verify --replay
python -m ai_fc trendlines-latest
```

새 workflow는 매일 KST 07:17·09:17·16:17에 실행한다. capture artifact를 각 push 시도마다 최신 main에 재생하고, 원장·선 재검산 후 허용 경로만 커밋한다. 의미 변화가 있을 때만 Pages를 dispatch한다. 초기 미산출은 자료 상태이며 추세선 생성 성공으로 집계하지 않는다.

화면 경로는 `#future/trendlines/<asset-id>`, 읽기 API는 `/api/trendlines/<asset-id>`다. static sidecar와 API는 동일 JSON을 사용한다. 요약 16KiB·상세 256KiB의 실바이트 해시와 snapshot identity를 확인한다. 기존 시나리오 fetch 실패에 새 화면이 종속되지 않는다.

## 검수와 복구

원본·계보·PIT·OHLC·분할·시장 달력, 피벗 확인 지연, 이탈·재진입, 독립 재산술, revision와 멱등성, sidecar 변조, 모바일·데스크톱을 검수한다. `tools/audit_trendlines_release.py`는 운영 SQLite/WAL을 임시 사본에서 검사하고 공식 raw·관측 계보와 기존 보호 경로 불변성을 확인한다. 기존 DB의 혼합 공급원 OHLC 결함은 기록하며 이 기능에서 수정하지 않는다.

코드·환경·자료 실패를 따로 보고한다. 롤백은 UI·workflow 코드와 공개 선택 포인터를 되돌리고 원본·정정·이벤트 원장은 보존한다.

출시 감사의 `ok`는 감사 실행·물리 DB·원본 계보·보호 경로 검사를 뜻한다. 기존 데이터 품질은 별도 `legacy_data_clean`으로 보고한다. 구 DB의 OHLC 위반 228건과 기존 benchmark fraction 범위 위반 2건은 원문을 보존하고 감사 결과에 남겼다.
