"""V15-VOL 계약 상수·경로·로더 — 상수 아티팩트·판정 코드 핀 대조는 여기서 fail-closed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from ..timeseries_v13.contracts import CELL_ORDER, THETA_RV as V13_THETA_RV, canonical_hash, cell_specs, sha256_file
from ..timeseries_v13.features import PROB_CLIP as V13_PROB_CLIP

MODEL_ID = "event_probability.volatility_v15_vol_shadow"
MODEL_VERSION = 15
CONTRACT_ID = "timeseries_v15_vol"
PROBABILITY_SPACE = "research_volatility_v15_vol_shadow"   # V13 공간과 같은 사건, 별도 라벨 — 화면 결합 방지
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v15_vol.yaml")
CONSTANTS_RELATIVE = Path("data/timeseries_v15_vol/constants/v15_vol_constants.json")
PREREG_MDE_RELATIVE = Path("data/timeseries_v15_vol/prereg/design_reference_mde.json")
SHADOW_LEDGER_RELATIVE = Path("data/timeseries_v15_vol/ledgers/vol15_shadow.jsonl")
RESOLUTION_LEDGER_RELATIVE = Path("data/timeseries_v15_vol/ledgers/vol15_shadow_resolutions.jsonl")
APPROVALS_LEDGER_RELATIVE = Path("data/timeseries_v15_vol/ledgers/approvals.jsonl")
ARMING_LEDGER_RELATIVE = Path("data/timeseries_v15_vol/ledgers/arming.jsonl")
PACKAGE_RELATIVE = Path("src/ai_fc/timeseries_v15_vol")
ARMING_ENV = "V15_VOL_ARMING_CONTEXT"
ARMING_ENV_VALUE = "main_scheduled_ci"
CODE_PIN_FILES = ("contracts.py", "arms.py", "shadow.py", "resolve.py", "verdict.py")
ARMS = ("R1_platt", "R2_calm_jump", "R3_regime_mix")
R2_CELLS = ("vix25_h5", "vix30_h5")
BASELINES = ("climatology", "conditional_base_rate", "persistence_pb")
CALM_VIX_BELOW = 20.0
THETA_RV = 0.1694
PROB_CLIP = (1e-6, 1 - 1e-6)
BOOTSTRAP_SEED = 20261111
BOOTSTRAP_REPLICATES = 5000
NULL_DRAWS = 120
NULL_BOOT_B = 300
NULL_PASS_RATE_MAX = 0.10
MIN_BLOCK = 13
MIN_BLOCKS = 5
MIN_ORIGINS = 60
MIN_EVENTS_EACH = 20
MIN_EPISODES_EACH = 5
RESOLUTION_ABSENT_GRACE_SESSIONS = 10
PREFIX_SETTLE_SESSIONS = 20
FAMILY_SIZE = 20
ALPHA = 0.05

# V13 와 같은 값이어야 한다 — 다르면 import 시점에 실패(조용한 문턱 이동 차단).
assert THETA_RV == V13_THETA_RV, "V15 θ must equal the V13 frozen θ"
assert tuple(PROB_CLIP) == tuple(V13_PROB_CLIP), "V15 clip must equal the V13 clip"

# 핀 밖 V13 심볼 고정(리뷰 N10) — 셀 인덱스(RNG 시드)·지평(ℓ_h·offset)·정준 해시 규칙이 V13 쪽에서 바뀌면 import 실패.
PINNED_CELL_SPECS = (
    ("vix25_h5", "vix_touch", 25, 5), ("vix25_h21", "vix_touch", 25, 21), ("vix25_h63", "vix_touch", 25, 63),
    ("vix30_h5", "vix_touch", 30, 5), ("vix30_h21", "vix_touch", 30, 21), ("vix30_h63", "vix_touch", 30, 63),
    ("rv_h5", "rv_exceedance", 0.1694, 5), ("rv_h21", "rv_exceedance", 0.1694, 21),
    ("rv_h63", "rv_exceedance", 0.1694, 63),
)
PINNED_CANONICAL_PROBE = ({"probe": [1, 0.5, "x", None, True], "k": {"b": 2, "a": 1}},
                          "6a95a3fcdebe7cc6fecc8334fdcc581ead03483a82e14a1d647f263ec9bb8f45")
assert CELL_ORDER == tuple(spec[0] for spec in PINNED_CELL_SPECS), "V13 CELL_ORDER moved"
assert tuple((s["name"], s["target"], s.get("K", s.get("theta")), s["h"]) for s in cell_specs()) == PINNED_CELL_SPECS, \
    "V13 cell_specs moved"
assert canonical_hash(PINNED_CANONICAL_PROBE[0]) == PINNED_CANONICAL_PROBE[1], "canonical_hash rule moved"

__all__ = [
    "MODEL_ID", "MODEL_VERSION", "CONTRACT_ID", "PROBABILITY_SPACE", "CONTRACT_RELATIVE", "CONSTANTS_RELATIVE",
    "PREREG_MDE_RELATIVE", "SHADOW_LEDGER_RELATIVE", "RESOLUTION_LEDGER_RELATIVE", "APPROVALS_LEDGER_RELATIVE",
    "ARMING_LEDGER_RELATIVE", "PACKAGE_RELATIVE", "ARMING_ENV", "ARMING_ENV_VALUE", "CODE_PIN_FILES", "ARMS",
    "R2_CELLS", "BASELINES", "CALM_VIX_BELOW", "THETA_RV", "PROB_CLIP", "BOOTSTRAP_SEED", "BOOTSTRAP_REPLICATES",
    "NULL_DRAWS", "NULL_BOOT_B", "NULL_PASS_RATE_MAX", "MIN_BLOCK", "MIN_BLOCKS", "MIN_ORIGINS",
    "MIN_EVENTS_EACH", "MIN_EPISODES_EACH", "RESOLUTION_ABSENT_GRACE_SESSIONS", "PREFIX_SETTLE_SESSIONS",
    "FAMILY_SIZE", "ALPHA", "CELL_ORDER", "PINNED_CELL_SPECS", "PINNED_CANONICAL_PROBE", "TimeSeriesV15VolError", "canonical_hash", "cell_specs", "sha256_file",
    "load_contract_v15_vol", "contract_sha256", "load_constants", "code_pin_digests", "check_code_pins",
    "read_rows", "read_arming", "arming_row_hash_ok", "block_length", "family_pairs",
]


class TimeSeriesV15VolError(RuntimeError):
    """A V15-VOL invariant failed closed (contract, constants pin, code pin, arming, ledger)."""


def load_contract_v15_vol(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        raise TimeSeriesV15VolError("V15-VOL contract is missing")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_id") != CONTRACT_ID:
        raise TimeSeriesV15VolError("V15-VOL contract id mismatch")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV15VolError("V15-VOL contract model identity mismatch")
    return payload


def contract_sha256(root: Path) -> str:
    """계약 파일 바이트 sha256 — 원장 행의 정보 필드(row_contract_sha256: informational)."""
    return sha256_file(root / CONTRACT_RELATIVE)


def load_constants(root: Path, *, expected_sha256: str | None, expected_content_hash: str | None) -> dict[str, Any]:
    """동결 상수 아티팩트 — 파일 sha256 · content_hash · 모델 정체성 3자 대조. 하나라도 어긋나면 raise."""
    if not expected_sha256 or not expected_content_hash:
        raise TimeSeriesV15VolError("frozen constants are not pinned in the contract")
    path = root / CONSTANTS_RELATIVE
    if not path.is_file():
        raise TimeSeriesV15VolError("frozen constants artifact is missing")
    if sha256_file(path) != expected_sha256:
        raise TimeSeriesV15VolError("frozen constants sha256 mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    recorded = body.pop("content_hash", None)
    if recorded != expected_content_hash or canonical_hash(body) != expected_content_hash:
        raise TimeSeriesV15VolError("frozen constants content hash mismatch")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV15VolError("frozen constants model identity mismatch")
    r1 = (payload.get("R1") or {}).get("cells") or {}
    r3 = (payload.get("R3") or {}).get("cells") or {}
    if set(r1) != set(CELL_ORDER) or set(r3) != set(CELL_ORDER):
        raise TimeSeriesV15VolError("frozen constants cell set invalid")
    if tuple((payload.get("R2") or {}).get("cells") or ()) != R2_CELLS:
        raise TimeSeriesV15VolError("frozen constants R2 cell set invalid")
    return payload


def code_pin_digests(root: Path) -> dict[str, str]:
    """판정·채점 코드 5파일의 LF 정규화 바이트 sha256 (Windows CRLF 체크아웃과 CI LF 를 같게 본다)."""
    out: dict[str, str] = {}
    for name in CODE_PIN_FILES:
        path = root / PACKAGE_RELATIVE / name
        data = path.read_bytes() if path.is_file() else b""
        out[name] = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() if data else ""
    return out


def check_code_pins(root: Path, contract: dict[str, Any]) -> list[str]:
    """계약 verdict_code_sha256 과 다른 파일명 목록(빈 목록 = 통과). 계약값이 비어 있으면 ['unpinned']."""
    pins = contract.get("verdict_code_sha256") or {}
    expected = {name: pins.get((PACKAGE_RELATIVE / name).as_posix()) for name in CODE_PIN_FILES}
    if any(not value for value in expected.values()):
        return ["unpinned"]
    actual = code_pin_digests(root)
    return [name for name in CODE_PIN_FILES if actual.get(name) != expected[name]]


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def arming_row_hash_ok(row: dict[str, Any]) -> bool:
    body = {key: value for key, value in row.items() if key != "content_hash"}
    return canonical_hash(body) == row.get("content_hash")


def read_arming(root: Path) -> dict[str, Any] | None:
    """무장 원장 — 0행이면 None, 1행이면 그 행(해시 검사), 2행 이상이면 raise (effective_from 의 유일 원천)."""
    rows = read_rows(root / ARMING_LEDGER_RELATIVE)
    if not rows:
        return None
    if len(rows) > 1:
        raise TimeSeriesV15VolError(f"arming ledger must hold at most one row (found {len(rows)})")
    row = rows[0]
    if not arming_row_hash_ok(row):
        raise TimeSeriesV15VolError("arming row content hash mismatch")
    return row


def block_length(h: int) -> int:
    return max(MIN_BLOCK, int(h))


def family_pairs() -> list[tuple[str, str]]:
    """고정 가족 [(arm, cell)] — R1×9, R2×2, R3×9. Holm 동률 순서도 이것이다."""
    pairs = [("R1_platt", cell) for cell in CELL_ORDER]
    pairs += [("R2_calm_jump", cell) for cell in R2_CELLS]
    pairs += [("R3_regime_mix", cell) for cell in CELL_ORDER]
    assert len(pairs) == FAMILY_SIZE
    return pairs
