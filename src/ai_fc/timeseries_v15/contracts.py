"""V15 정합성 섀도 계약 로더·해시·경로 — 오케스트레이션(kernel 밖).

- `frozen_hash`  = 행마다 기록하는 계약 지문(canonical_hash, 대상 FROZEN_KEYS).
- `rule_hash`    = 결과 전 잠금 — FROZEN_KEYS 에서 r3 허용 목록(R3_RULE_ALLOWLIST)을 뺀 해시.
                   r2 커밋 값이 계약 provenance.rule_hash_r2·영수증 5행·DECISIONS 에 같다.
- `kernel_code_hash` = 길이접두 sha256(V8 model_code_hash 형식) — V15 kernel 8파일 + 봉인 import 원본.
- `verdict_code_hash` = verdict.py 한 파일, `mde_code_hash` = mde.py + verdict.py.
모든 verb 는 `load_contract_v15` 를 거친다 — 규칙이 바뀐 계약으로는 아무것도 실행되지 않는다.
참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from ai_fc.timeseries_v8.contracts import _normalize, canonical_hash

MODEL_ID = "shadow.mf_dfm_varx_coherence_v15"
MODEL_VERSION = 15
CONTRACT_ID = "multivariate_timeseries_v15_coherence"
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v15_coherence.yaml")
STORE_RELATIVE = Path("data/timeseries_v15")
LEDGERS_RELATIVE = STORE_RELATIVE / "ledgers"
PREREG_RELATIVE = STORE_RELATIVE / "prereg"
SHADOW_LEDGER = LEDGERS_RELATIVE / "shadow_forecasts.jsonl"
ISSUANCE_LEDGER = LEDGERS_RELATIVE / "issuance_forecasts.jsonl"
RESOLUTION_LEDGER = LEDGERS_RELATIVE / "shadow_resolutions.jsonl"
ATTEMPTS_LEDGER = LEDGERS_RELATIVE / "attempts.jsonl"
APPROVALS_LEDGER = LEDGERS_RELATIVE / "approvals.jsonl"
VERDICTS_LEDGER = LEDGERS_RELATIVE / "verdicts.jsonl"
FORK_PATCH_RELATIVE = PREREG_RELATIVE / "fork_patch_v1.json"
MDE_SUMMARY_RELATIVE = PREREG_RELATIVE / "mde_v1.json"
STATUS_RELATIVE = STORE_RELATIVE / "derived" / "v15_shadow_status.json"
V8_SHADOW_LEDGER = Path("data/timeseries_v8/ledgers/shadow_forecasts.jsonl")

PACKAGE = "src/ai_fc/timeseries_v15"
KERNEL_FILES = tuple(f"{PACKAGE}/{name}.py" for name in (
    "arms", "vol", "model", "backtest", "features", "labels", "calendar", "bundle",
))
IMPORTED_UNCHANGED = (
    "src/ai_fc/timeseries_v2/model.py",
    "src/ai_fc/timeseries_v2/backtest.py",
    "src/ai_fc/timeseries_v2/dfm_cache.py",
    "src/ai_fc/timeseries_v2/market_archive.py",
    "src/ai_fc/timeseries_v2/contracts.py",
    "src/ai_fc/timeseries/model.py",
    "src/ai_fc/timeseries/backtest.py",
    "src/ai_fc/timeseries_v8/model.py",
    "src/ai_fc/timeseries_v8/contracts.py",
    "src/ai_fc/timeseries_v8/pipeline.py",
)
KERNEL_HASH_FILES = KERNEL_FILES + IMPORTED_UNCHANGED
VERDICT_FILES = (f"{PACKAGE}/verdict.py",)
MDE_CODE_FILES = (f"{PACKAGE}/mde.py", f"{PACKAGE}/verdict.py")
PIPELINE_FILES = tuple(f"{PACKAGE}/{name}.py" for name in ("__init__", "contracts", "pipeline", "plan"))
FORKED = (
    ("src/ai_fc/timeseries_v8/model.py", f"{PACKAGE}/model.py"),
    ("src/ai_fc/timeseries_v8/backtest.py", f"{PACKAGE}/backtest.py"),
    ("src/ai_fc/timeseries_v2/features.py", f"{PACKAGE}/features.py"),
)

FROZEN_KEYS = (
    "target", "arms", "rejected_arms", "live", "verdict_rule", "mde", "data_policy",
    "contamination", "promotion", "prohibitions", "fork", "revision_control",
)
# rule_hash 밖(r3 가 채우는 값) — 이 밖의 rule 대상 변경은 새 계약(revision_control)
R3_RULE_ALLOWLIST = (
    ("mde", "status"),
    ("mde", "values_by_horizon"),
    ("mde", "per_arm"),
    ("mde", "artifacts", "summary_sha256"),
    ("live", "first_origin_not_before"),
)
DECISIONS = ("V15-D0", "V15-D1", "V15-D2", "V15-D3", "V15-D4")
APPROVAL_TEXT = "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜"
APPROVED_AT_INSTANT_UTC = "2026-11-11T09:03:44+00:00"
V8_LIVE_MODEL_CODE_HASH = "869418ccb6a7356761b489bd2e23262427b31b8446dcf2f2dcc17959a8206fde"
NOTICE = "참고 의견, 매매 신호 아님"
_HEX64 = re.compile(r"[0-9a-f]{64}")


class TimeSeriesV15ContractError(ValueError):
    """V15 사전등록·잠금·핀 위반 — fail-closed."""


class TimeSeriesV15DataError(ValueError):
    """V15 입력 데이터 전제 위반(XNAS 내부 결측 등) — fail-closed."""


# ── 해시 ────────────────────────────────────────────────────────────────────


def length_prefixed_hash(root: Path, relatives: tuple[str, ...] | list[str]) -> str:
    """V8 contracts.model_code_hash 와 같은 형식(경로·본문 길이접두 sha256)."""
    digest = hashlib.sha256()
    for relative in relatives:
        path = root / relative
        if not path.is_file():
            raise TimeSeriesV15ContractError(f"V15 해시 대상 파일 없음: {relative}")
        encoded = Path(relative).as_posix().encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        body = path.read_bytes()
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def kernel_code_hash(root: Path) -> str:
    return length_prefixed_hash(root, KERNEL_HASH_FILES)


def verdict_code_hash(root: Path) -> str:
    return length_prefixed_hash(root, VERDICT_FILES)


def mde_code_hash(root: Path) -> str:
    return length_prefixed_hash(root, MDE_CODE_FILES)


def pipeline_code_hash(root: Path) -> str:
    return length_prefixed_hash(root, PIPELINE_FILES)


def frozen_coordinates(contract: dict[str, Any]) -> dict[str, Any]:
    return {key: contract.get(key) for key in FROZEN_KEYS}


def frozen_hash(contract: dict[str, Any]) -> str:
    return canonical_hash(frozen_coordinates(contract))


def rule_coordinates(contract: dict[str, Any]) -> dict[str, Any]:
    coordinates = copy.deepcopy(frozen_coordinates(contract))
    for path in R3_RULE_ALLOWLIST:
        node: Any = coordinates
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return coordinates


def rule_hash(contract: dict[str, Any]) -> str:
    return canonical_hash(rule_coordinates(contract))


# ── 로더 ────────────────────────────────────────────────────────────────────


def read_contract_raw(root: Path) -> dict[str, Any]:
    payload = _normalize(yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise TimeSeriesV15ContractError("V15 계약이 매핑이 아니다")
    return payload


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TimeSeriesV15ContractError(message)


def validate_contract_v15(root: Path, contract: dict[str, Any], *, check_rule_hash: bool = True) -> dict[str, Any]:
    from . import verdict as verdict_rules
    from ai_fc.timeseries_v8.contracts import model_code_hash as v8_model_code_hash

    _require(contract.get("contract_id") == CONTRACT_ID, "V15 contract_id 불일치")
    _require(contract.get("model_id") == MODEL_ID, "V15 model_id 불일치")
    _require(contract.get("model_version") == MODEL_VERSION, "V15 model_version 불일치")
    _require(contract.get("status") in {"prereg"}, f"V15 status 는 prereg 여야 한다: {contract.get('status')!r}")
    rule = contract.get("verdict_rule") or {}
    family = rule.get("family") or {}
    _require(family.get("affected_horizons_rule") == "abolished_r2", "affected_horizons_rule 는 abolished_r2 여야 한다")
    superiority = family.get("superiority") or {}
    _require(superiority.get("size") == 12, "우월성 가족 크기는 12 로 고정")
    _require([tuple(item) for item in superiority.get("member_pairs") or []]
             == [tuple(item) for item in verdict_rules.SUPERIORITY_FAMILY], "우월성 가족 구성원 불일치")
    _require(superiority.get("correction") == "holm" and superiority.get("alpha") == 0.05, "우월성 Holm·α 불일치")
    ni = family.get("noninferiority") or {}
    _require(ni.get("size") == 3, "비열등 가족 크기는 3")
    _require([tuple(item) for item in ni.get("member_pairs") or []]
             == [tuple(item) for item in verdict_rules.NONINFERIORITY_FAMILY], "비열등 가족 구성원 불일치")
    _require(ni.get("margin_rel") == verdict_rules.NI_MARGIN, "δ_NI 는 +0.01")
    _require(ni.get("correction") == "holm" and ni.get("alpha") == 0.05, "비열등 Holm·α 불일치")
    bootstrap = rule.get("bootstrap") or {}
    _require(bootstrap.get("replicates") == verdict_rules.REPLICATES, "B=5000 이어야 한다")
    _require(bootstrap.get("seed") == verdict_rules.BOOTSTRAP_SEED, "seed 20261111 이어야 한다")
    _require({int(k): int(v) for k, v in (bootstrap.get("block_length_origins_by_horizon") or {}).items()}
             == verdict_rules.BLOCK_LENGTH, "블록 길이 {5:2,21:5,63:13} 이어야 한다")
    _require(int(bootstrap.get("distinct_resample_floor", 0)) == verdict_rules.DISTINCT_FLOOR, "distinct floor 1000")
    _require({int(k): int(v) for k, v in (rule.get("minimum_matured_origins_by_horizon") or {}).items()}
             == verdict_rules.MIN_ORIGINS, "최소 원점 {5:26,21:26,63:39} 이어야 한다")
    cut = rule.get("verdict_cut") or {}
    _require(cut.get("deadline_cut_utc") == verdict_rules.DEADLINE_CUT_UTC, "마감 컷 2028-06-30T23:59:59Z")
    _require(cut.get("families_independent") is True, "가족별 T* 는 독립이어야 한다")
    _require(bool(_HEX64.fullmatch(str(rule.get("frozen_verdict_code_hash") or ""))),
             "frozen_verdict_code_hash 는 64자 hex")
    rejected = contract.get("rejected_arms") or {}
    _require({"A6", "A7"} <= set(rejected), "rejected_arms 에 A6·A7 가 있어야 한다")
    arms = contract.get("arms") or {}
    _require(set(arms) == {"A0", "A1", "A2", "A3", "A4", "A5"}, "등록 팔은 A0~A5 정확히")
    fork = contract.get("fork") or {}
    _require(fork.get("exists") is True, "r2 포크는 존재해야 한다")
    _require(bool(_HEX64.fullmatch(str(fork.get("frozen_kernel_code_hash") or ""))),
             "frozen_kernel_code_hash 는 64자 hex")
    sealed = (fork.get("sealed_originals_unchanged") or {}).get("v8_live_model_code_hash")
    _require(sealed == V8_LIVE_MODEL_CODE_HASH, "봉인 V8 model_code_hash 핀 불일치")
    _require(v8_model_code_hash(root) == sealed, "봉인 V8 코드가 바뀌었다(model_code_hash 불일치)")
    prohibitions = contract.get("prohibitions") or {}
    _require(bool(prohibitions) and all(value is True for value in prohibitions.values()),
             "prohibitions 의 모든 키는 true")
    for key in ("mutate_v15_kernel_after_freeze", "automatic_verdict_append", "retro_catch_up_beyond_window",
                "rule_change_after_r2_outside_allowlist", "verdict_on_pairs_after_cut"):
        _require(prohibitions.get(key) is True, f"금지 조항 누락: {key}")
    combination = contract.get("combination") or {}
    _require(combination.get("allowed") is False, "결합은 금지(combination.allowed false)")
    mde = contract.get("mde") or {}
    _require(mde.get("replay_knowledge_cutoff") == "2026-11-11T09:03:44Z", "MDE replay_knowledge_cutoff 고정 리터럴")
    _require(str(mde.get("design_truncation")) == "2014-12-31", "MDE 설계창 절단 2014-12-31")
    live = contract.get("live") or {}
    _require(int(live.get("catch_up_window_v8_origins", 0)) == 2, "따라잡기 창은 2원점")
    if check_rule_hash:
        recorded = (contract.get("provenance") or {}).get("rule_hash_r2")
        _require(bool(_HEX64.fullmatch(str(recorded or ""))), "provenance.rule_hash_r2 가 없다")
        _require(rule_hash(contract) == recorded,
                 "rule_hash(contract) != provenance.rule_hash_r2 — r3 허용 목록 밖 규칙 변경(새 계약 필요)")
    errors = track_open_precondition_errors(root, contract)
    _require(not errors, "track_open true 의 r3 전제 미충족 — " + "; ".join(errors))
    return contract


def track_open_precondition_errors(root: Path, contract: dict[str, Any]) -> list[str]:
    """계약 `mde.must_be_filled_before: track_open`·`gates.armed_requires` 의 기계화.

    track_open 이 true 면 — 첫 원점 날짜 기입(규칙 헬퍼 값), mde.status computed, mde_v1.json 존재·sha256 핀 일치,
    가장 최근 A0 라이브 identity 시도 PASS, gates.armed true. 하나라도 빠지면 로더가 거부한다(라이브 계산 0).
    track_open false 면 빈 목록.
    """
    if not track_open(contract):
        return []
    errors: list[str] = []
    first = (contract.get("live") or {}).get("first_origin_not_before")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(first or "")):
        errors.append("live.first_origin_not_before 가 날짜(YYYY-MM-DD)가 아니다")
    mde = contract.get("mde") or {}
    if mde.get("status") != "computed":
        errors.append("mde.status 가 computed 가 아니다")
    summary = root / MDE_SUMMARY_RELATIVE
    pinned = str(((mde.get("artifacts") or {}).get("summary_sha256")) or "")
    if not summary.is_file():
        errors.append(f"{MDE_SUMMARY_RELATIVE.as_posix()} 가 없다")
    elif not _HEX64.fullmatch(pinned) or hashlib.sha256(summary.read_bytes()).hexdigest() != pinned:
        errors.append("mde.artifacts.summary_sha256 가 mde_v1.json 과 맞지 않는다")
    from .pipeline import latest_identity_status  # 지연 import — pipeline 이 이 모듈을 import 한다

    if latest_identity_status(root) != "PASS":
        errors.append("가장 최근 a0_live_identity 시도가 PASS 가 아니다")
    if (contract.get("gates") or {}).get("armed") is not True:
        errors.append("gates.armed 가 true 가 아니다")
    return errors


def load_contract_v15(root: Path, *, check_rule_hash: bool = True) -> dict[str, Any]:
    return validate_contract_v15(root, read_contract_raw(root), check_rule_hash=check_rule_hash)


def track_open(contract: dict[str, Any]) -> bool:
    return (contract.get("development_protocol") or {}).get("track_open") is True


def assert_track_open(contract: dict[str, Any]) -> None:
    if not track_open(contract):
        raise TimeSeriesV15ContractError(
            "V15 track_open 이 false 다 — 라이브 평가 금지(r3 전: MDE 재생·A0 identity 시도만 허용)"
        )
