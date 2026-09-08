"""V13-VOL 변동성 이벤트 확률 트랙 — 비봉인 패키지.

계약: data/contracts/multivariate_timeseries_v13_vol.yaml. 봉인 V8/V2 패키지는 read-only 로만 import 한다
(market_archive.read_market_observations · timeseries_v8.contracts.canonical_hash · timeseries_v8.artifact.append_unique).
pandas 금지 — pages 빌드 환경에는 numpy 만 있다. tools/ 가 이 패키지를 import 하고 역방향은 없다.
"""
