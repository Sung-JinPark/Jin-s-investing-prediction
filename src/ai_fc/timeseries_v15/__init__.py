"""V15 정합성 섀도 트랙 (multivariate_timeseries_v15_coherence) — 동결 V8 를 대체하지 않는 후속 섀도.

동결 V8 와 같은 원점·같은 입력 스냅숏에서 결함 축마다 단일 변경 팔(A1~A5)을 V8 비트 동일
대조군(A0)과 xnas_v1 라벨로 쌍대 CRPS 비교한다. 봉인 V2/V8 코드는 0바이트 변경 — 바뀌는 3파일만
포크(model·backtest·features), 나머지는 import. 판정 규칙은 rule_hash_r2 로 결과 전에 잠갔다.
화면 없음(publication.site_surface none). 모든 출력은 참고 의견, 매매 신호 아님.
"""

from .arms import ARMS, SEED_MODEL_ID, SEED_MODEL_VERSION, ArmSpec
from .contracts import MODEL_ID, MODEL_VERSION, load_contract_v15

__all__ = [
    "ARMS", "ArmSpec", "MODEL_ID", "MODEL_VERSION", "SEED_MODEL_ID", "SEED_MODEL_VERSION",
    "load_contract_v15",
]
