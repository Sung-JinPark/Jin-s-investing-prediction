"""V14 조건부 전이 트랙 — 라이브 전진 경로 (V14-D10, 영수증 v14-approval:V14-D10:2026-10-28:r2 — r1 은 대체됨).

계약: data/contracts/multivariate_timeseries_v14_conditional.yaml (`live_pointer` · `frozen_coefficients` ·
`live_forward_gate`). 모형은 conditional_persistence_pb 하나 — 동결 계수(sha256 핀)만 읽고 재적합하지 않는다.
적합기·부트스트랩·귀무는 V13 공유 구현(ai_fc.timeseries_v13.features/scoring)을 import 한다(신규 구현 0).
봉인 V8/V2 패키지는 read-only 로만 import 한다. pandas 금지(numpy 만). tools/ 가 이 패키지를 import 하고 역방향은 없다.
모든 출력은 참고 의견이며 매매 신호가 아니다.
"""
