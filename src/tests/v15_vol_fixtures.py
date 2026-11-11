"""V15-VOL 테스트 공용 픽스처 — 실제 저장소에서 필요한 파일만 tmp_path 로 복사한다(실저장소 쓰기 0).

모든 V15 테스트는 V15_VOL_ARMING_CONTEXT 를 지우고 시작한다(워크플로 verify step 이 이 변수를 설정한 채 pytest 를 돌린다).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[2]

V13_FILES = (
    "data/contracts/multivariate_timeseries_v13_vol.yaml",
    "data/timeseries_v13/vol/champion_coefficients.json",
    "data/timeseries_v13/ledgers/vol_live.jsonl",
    "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl",
)
V15_FILES = (
    "data/contracts/multivariate_timeseries_v15_vol.yaml",
    "data/timeseries_v15_vol/constants/v15_vol_constants.json",
    "data/timeseries_v15_vol/prereg/design_reference_mde.json",
    "data/timeseries_v15_vol/ledgers/approvals.jsonl",
)
PACKAGE = "src/ai_fc/timeseries_v15_vol"
CODE_FILES = ("__init__.py", "contracts.py", "arms.py", "shadow.py", "resolve.py", "verdict.py")

PROTECTED_REAL = (
    "data/timeseries_v13/ledgers/vol_live.jsonl",
    "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl",
    "data/timeseries_v13/vol/champion_coefficients.json",
    "data/contracts/multivariate_timeseries_v13_vol.yaml",
    "data/contracts/multivariate_timeseries_v15_vol.yaml",
    "data/timeseries_v15_vol/constants/v15_vol_constants.json",
    "data/timeseries_v15_vol/ledgers/approvals.jsonl",
    "data/timeseries_v15_vol/ledgers/arming.jsonl",
    "data/timeseries_v15_vol/ledgers/vol15_shadow.jsonl",
    "data/timeseries_v15_vol/ledgers/vol15_shadow_resolutions.jsonl",
)

CONTRACT = "data/contracts/multivariate_timeseries_v15_vol.yaml"
V13_LIVE = "data/timeseries_v13/ledgers/vol_live.jsonl"
V13_RES = "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl"
V15_SHADOW = "data/timeseries_v15_vol/ledgers/vol15_shadow.jsonl"
V15_RES = "data/timeseries_v15_vol/ledgers/vol15_shadow_resolutions.jsonl"
ARMING = "data/timeseries_v15_vol/ledgers/arming.jsonl"


def protected_hashes() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for relative in PROTECTED_REAL:
        path = ROOT / relative
        out[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return out


def make_root(tmp_path: Path, *, v13_ledgers: bool = True) -> Path:
    root = tmp_path / "repo"
    files = list(V15_FILES) + [f for f in V13_FILES if v13_ledgers or "ledgers" not in f]
    for relative in files:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    for name in CODE_FILES:
        target = root / PACKAGE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / PACKAGE / name, target)
    return root


def load_contract(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / CONTRACT).read_text(encoding="utf-8"))


def write_contract(root: Path, payload: dict[str, Any]) -> None:
    (root / CONTRACT).write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def edit_contract(root: Path, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    payload = load_contract(root)
    mutate(payload)
    write_contract(root, payload)
    return payload


# tmp 기본 armed_at 은 과거 V13 원장 구간(2026-09~)에 무장행을 둘 수 있게 이르게 둔다 — verify 는
# armed_observed_at >= armed_at 을 요구한다(리뷰 N2). 실계약의 armed_at 은 커밋 B 시각이다.
TMP_ARMED_AT = "2026-08-01T00:00:00+09:00"
TMP_PREREG = "0123abcd"


def arm(root: Path, *, prereg_commit: str = TMP_PREREG, armed_at: str = TMP_ARMED_AT) -> dict[str, Any]:
    """tmp 계약을 커밋 B 상태로 — armed·prereg_commit·armed_at, 코드 핀이 비어 있으면 tmp 코드로 채운다."""
    from ai_fc.timeseries_v15_vol import contracts as C

    digests = C.code_pin_digests(root)

    def _mutate(payload: dict[str, Any]) -> None:
        payload["gates"]["armed"] = True
        payload["development_protocol"]["prereg_commit"] = prereg_commit
        payload["live_shadow"]["armed_at"] = armed_at
        pins = payload.get("verdict_code_sha256") or {}
        for name in C.CODE_PIN_FILES:
            key = f"{C.PACKAGE_RELATIVE.as_posix()}/{name}"
            if not pins.get(key):
                pins[key] = digests[name]
        payload["verdict_code_sha256"] = pins

    return edit_contract(root, _mutate)


def write_arming(root: Path, *, effective_from: str = "2026-10-01",
                 armed_observed_at: str | None = None, prereg_commit: str = TMP_PREREG) -> dict[str, Any]:
    """tmp 무장행 — effective_from 은 armed_observed_at 다음 XNAS 세션과 일치하게 만든다."""
    from ai_fc.timeseries_v15_vol import contracts as C
    from ai_fc.timeseries_v15_vol.resolve import _xnas_session_offset
    from datetime import date

    if armed_observed_at is None:
        prior = _xnas_session_offset(date.fromisoformat(effective_from), -1)
        armed_observed_at = f"{prior.isoformat()}T11:25:00+00:00"
    row = {"schema_version": 1, "kind": "v15_vol_arming", "armed_observed_at": armed_observed_at,
           "effective_from": effective_from, "contract_sha256": C.contract_sha256(root),
           "prereg_commit": prereg_commit, "github_run_id": "1", "github_sha": "f" * 40}
    row["content_hash"] = C.canonical_hash(row)
    path = root / ARMING
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return row


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                            for r in rows), encoding="utf-8")


def file_hashes(root: Path, relatives: tuple[str, ...]) -> dict[str, str | None]:
    return {r: (hashlib.sha256((root / r).read_bytes()).hexdigest() if (root / r).is_file() else None)
            for r in relatives}
