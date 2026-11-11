"""V15-VOL 계약·영수증·이름·금지 문자열·가족 크기·코드 핀·무장 상태 (명세 U5 §8.1). 저장소 쓰기 0."""

from __future__ import annotations

import ast
import json
import re
from datetime import date, datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

from ai_fc.timeseries_v15_vol import contracts as C
from ai_fc.timeseries_v15_vol.resolve import _xnas_session_offset
from v15_vol_fixtures import ROOT, make_root, protected_hashes

CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v15_vol.yaml"
V13_CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v13_vol.yaml"
PACKAGE = ROOT / "src/ai_fc/timeseries_v15_vol"
WORKFLOW = ROOT / ".github/workflows/v15-vol-shadow.yml"
TOOL = ROOT / "tools/v15_vol_freeze_constants.py"
INSTRUCTION = "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜"
INSTRUCTED_UPPER = datetime(2026, 11, 11, 9, 3, 44, tzinfo=timezone.utc)
FORBIDDEN = ("timeseries" + "_v14", "timeseries" + "-v14")  # 이 파일 자체가 검사 대상이 될 수 있어 쪼갠다

PROTECTED_GLOBS = (
    ".github/workflows/timeseries*.yml",
    "tools/*timeseries*",
    "tools/*scenario*",
    "tools/*v6*",
    "src/tests/test_multivariate_timeseries*.py",
)
TRACK_FILES = (
    "data/contracts/multivariate_timeseries_v15_vol.yaml",
    "src/ai_fc/timeseries_v15_vol/__init__.py",
    "src/ai_fc/timeseries_v15_vol/contracts.py",
    "src/ai_fc/timeseries_v15_vol/arms.py",
    "src/ai_fc/timeseries_v15_vol/design_fit.py",
    "src/ai_fc/timeseries_v15_vol/shadow.py",
    "src/ai_fc/timeseries_v15_vol/resolve.py",
    "src/ai_fc/timeseries_v15_vol/verdict.py",
    "tools/v15_vol_freeze_constants.py",
    "data/timeseries_v15_vol/constants/v15_vol_constants.json",
    "data/timeseries_v15_vol/prereg/design_reference_mde.json",
    "data/timeseries_v15_vol/ledgers/approvals.jsonl",
    "data/timeseries_v15_vol/ledgers/arming.jsonl",
    "data/timeseries_v15_vol/ledgers/vol15_shadow.jsonl",
    "data/timeseries_v15_vol/ledgers/vol15_shadow_resolutions.jsonl",
    ".github/workflows/v15-vol-shadow.yml",
    "docs/research/mts_upgrade/v15_vol_prereg_20261111.md",
    "src/tests/test_timeseries_v15_vol_contract.py",
    "src/tests/test_timeseries_v15_vol_arms.py",
    "src/tests/test_timeseries_v15_vol_shadow.py",
    "src/tests/test_timeseries_v15_vol_resolve.py",
    "src/tests/test_timeseries_v15_vol_verdict.py",
    "src/tests/test_v15_vol_workflow.py",
    "src/tests/v15_vol_fixtures.py",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(C.ARMING_ENV, raising=False)
    before = protected_hashes()
    yield
    assert protected_hashes() == before, "실저장소 V13/V15 파일이 바뀌었다"


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_contract_identity_and_status() -> None:
    contract = C.load_contract_v15_vol(ROOT)
    assert contract["contract_id"] == "timeseries_v15_vol"
    assert contract["model_id"] == C.MODEL_ID and contract["model_version"] == 15
    assert contract["status"] == "live_shadow_prereg"


def test_family_is_twenty_fixed_pairs() -> None:
    pairs = C.family_pairs()
    assert len(pairs) == 20
    arms = [arm for arm, _ in pairs]
    assert arms.count("R1_platt") == 9 and arms.count("R2_calm_jump") == 2 and arms.count("R3_regime_mix") == 9
    assert [c for a, c in pairs if a == "R2_calm_jump"] == ["vix25_h5", "vix30_h5"]
    assert _contract()["verdict_rule"]["family"]["pairs"] == 20


def test_parent_pin_equals_v13_contract() -> None:
    parent = _contract()["parent_v13"]
    v13 = yaml.safe_load(V13_CONTRACT.read_text(encoding="utf-8"))["frozen_coefficients"]
    assert parent["coefficients_sha256"] == v13["sha256"]
    assert parent["coefficients_content_hash"] == v13["content_hash"]
    assert parent["finalist_id"] == v13["finalist_id"]


def test_constants_pin() -> None:
    pin = _contract()["frozen_constants"]
    path = ROOT / pin["path"]
    assert C.sha256_file(path) == pin["sha256"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = {k: v for k, v in payload.items() if k != "content_hash"}
    assert C.canonical_hash(body) == pin["content_hash"] == payload["content_hash"]
    C.load_constants(ROOT, expected_sha256=pin["sha256"], expected_content_hash=pin["content_hash"])
    assert C.sha256_file(ROOT / pin["mde_reference"]) == pin["mde_reference_sha256"]


def test_armed_state_shape_and_arming_row() -> None:
    contract = _contract()
    protocol, gates, live = contract["development_protocol"], contract["gates"], contract["live_shadow"]
    assert live["effective_from"] is None, "effective_from 은 계약에 두지 않는다 — 무장 원장이 정본"
    assert live["effective_from_rule"]
    assert live["arming_ledger"] == C.ARMING_LEDGER_RELATIVE.as_posix()
    if gates["armed"] is True:
        assert re.fullmatch(r"[0-9a-f]{8,40}", str(protocol["prereg_commit"])), protocol["prereg_commit"]
        assert live["armed_at"]
        for value in contract["verdict_code_sha256"].values():
            assert re.fullmatch(r"[0-9a-f]{64}", str(value))
    else:
        assert protocol["prereg_commit"] is None and live["armed_at"] is None   # 커밋 A 상태
    arming_path = ROOT / C.ARMING_LEDGER_RELATIVE
    if arming_path.is_file():
        rows = [json.loads(line) for line in arming_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(rows) == 1
        row = rows[0]
        assert C.arming_row_hash_ok(row)
        observed = datetime.fromisoformat(row["armed_observed_at"]).astimezone(timezone.utc).date()
        assert row["effective_from"] == _xnas_session_offset(observed, 1).isoformat()
        assert row["effective_from"] > "2026-11-11"
        # 리뷰 N2: 커밋 B(prereg_commit·armed_at) 뒤의 CI 실행만 무장행을 쓴다.
        assert row["prereg_commit"] == protocol["prereg_commit"]
        assert datetime.fromisoformat(row["armed_observed_at"]) >= datetime.fromisoformat(str(live["armed_at"]))
        assert str(row["github_run_id"]).strip() and str(row["github_sha"]).strip()


def test_approval_receipts_delegated_form() -> None:
    rows = [json.loads(line) for line in (ROOT / C.APPROVALS_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert len(rows) == 2
    assert [r["receipt_id"] for r in rows] == _contract()["approvals"]["receipts"]
    assert [r["decision_id"] for r in rows] == ["V15VOL-D1", "V15VOL-D2"]
    for row in rows:
        assert row["literal_template_match"] is False
        assert row["approval_form"] == "delegated_bundle_instruction"
        assert row["approval_text"] == INSTRUCTION          # 공백 2칸 포함 원문
        assert row["template_text"].startswith(row["decision_id"]) and row["template_text"].endswith("승인")
        approved = datetime.fromisoformat(row["approved_at"])
        assert approved.tzinfo is not None and approved <= INSTRUCTED_UPPER
        assert approved == INSTRUCTED_UPPER                  # 도구 기록 상한 그대로(합성 금지)
        assert row["approval_scope"]["irreversible_resources"]["holdout"] == 0
    assert _contract()["approvals"]["receipt_form"] == "delegated_bundle_instruction"


def test_track_file_names_avoid_protected_globs() -> None:
    hits = {path: [g for g in PROTECTED_GLOBS if fnmatchcase(path, g)] for path in TRACK_FILES}
    assert {k: v for k, v in hits.items() if v} == {}
    assert [g for g in PROTECTED_GLOBS if fnmatchcase(".github/workflows/timeseries-v13-vol-live.yml", g)]


def test_no_v14_module_string_in_track_code() -> None:
    targets = sorted(PACKAGE.rglob("*.py")) + [TOOL, WORKFLOW]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN:
            assert forbidden not in text, path.name


def test_prohibitions_and_promotion() -> None:
    contract = _contract()
    assert contract["prohibitions"] and all(v is True for v in contract["prohibitions"].values())
    assert contract["promotion"]["automatic"] is False
    assert contract["promotion"]["display_tiers_allowed"] == ["t0_internal"]
    assert contract["promotion"]["wiring"] == "forbidden"


def _write_targets(tree: ast.AST) -> list[str]:
    """쓰기 호출(open 'w'/'a', write_text, append_unique)의 경로 인자 표현식 소스."""
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else "")
        if name == "append_unique" and len(node.args) >= 2:
            out.append(ast.unparse(node.args[1]))
        elif name in ("write_text", "write_bytes") and isinstance(func, ast.Attribute):
            out.append(ast.unparse(func.value))
        elif name == "open":
            modes = [a for a in node.args[1:2]] + [k.value for k in node.keywords if k.arg == "mode"]
            if any(isinstance(m, ast.Constant) and any(ch in str(m.value) for ch in "wa+") for m in modes):
                out.append(ast.unparse(node.args[0]) if node.args else ast.unparse(func))
    return out


def test_v15_package_writes_only_v15_ledgers() -> None:
    allowed = {"C.SHADOW_LEDGER_RELATIVE", "C.RESOLUTION_LEDGER_RELATIVE", "C.ARMING_LEDGER_RELATIVE"}
    for path in sorted(PACKAGE.glob("*.py")):
        targets = _write_targets(ast.parse(path.read_text(encoding="utf-8")))
        assert set(targets) <= allowed, (path.name, targets)


def _imports(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(("." * node.level) + (node.module or ""))
            names += [a.name for a in node.names]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "design_fit" in node.value:
            names.append("str:" + node.value)
    return names


def test_live_modules_do_not_import_design_fit() -> None:
    for name in ("arms.py", "shadow.py", "resolve.py", "verdict.py"):
        imports = _imports(ast.parse((PACKAGE / name).read_text(encoding="utf-8")))
        assert not any("design_fit" in item for item in imports), (name, imports)


def test_code_pins_match_contract_and_are_lf_normalized(tmp_path: Path) -> None:
    contract = _contract()
    digests = C.code_pin_digests(ROOT)
    expected = {name: contract["verdict_code_sha256"][f"src/ai_fc/timeseries_v15_vol/{name}"] for name in C.CODE_PIN_FILES}
    assert digests == expected
    assert C.check_code_pins(ROOT, contract) == []
    root = make_root(tmp_path)
    target = root / "src/ai_fc/timeseries_v15_vol/arms.py"
    target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert C.code_pin_digests(root) == digests


def test_v14_overlap_disclosure_and_no_v14_reference() -> None:
    overlap = _contract()["v14_overlap"]
    for key in ("identical_conditioning", "decision", "not_v14", "pre_observation_of_v14_live", "thin_estimate"):
        assert overlap.get(key), key
    assert "v14" not in C.MODEL_ID and "v14" not in C.PROBABILITY_SPACE
    v14_path = "data/" + "timeseries" + "_v14"
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert v14_path not in node.value, path.name
        assert not any("v14" in item for item in _imports(tree)), path.name


def test_termination_not_acknowledged_at_prereg() -> None:
    assert _contract()["parent_v13"]["termination_acknowledged"] is None


def test_research_layer_boundary() -> None:
    """생산 패키지는 연구 계층을 import 하지 않고 그 데이터 경로 문자열도 갖지 않는다(통합 계획 I7)."""
    research = "mts" + "_research"
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(research in item for item in _imports(tree)), path.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert f"data/{research}/" not in node.value, path.name


def test_live_shadow_never_reads_archive() -> None:
    for name in ("arms.py", "shadow.py", "resolve.py"):
        text = (PACKAGE / name).read_text(encoding="utf-8")
        assert "read_market_observations" not in text, name


def test_instructed_upper_bound_literal() -> None:
    assert _contract()["approvals"]["instructed_at_upper_bound"] == "2026-11-11T09:03:44Z"
    assert date.fromisoformat(_contract()["drafted"]) == date(2026, 11, 11)
