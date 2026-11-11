"""U7 — V8 공식 채점 basis = 원장 grid 유지 선언(해시 고정) 테스트.

쓰기는 tmp 사본에만. 실저장소는 읽기만 한다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ai_fc.mts_research import label_basis as LB
from ai_fc.mts_research import v8_xnas_labels as X

ROOT = Path(__file__).resolve().parents[2]
INSTRUCTION = "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜"


def _copy_basis(tmp_path: Path) -> Path:
    dest = tmp_path / LB.LABEL_BASIS_RELATIVE
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / LB.LABEL_BASIS_RELATIVE, dest)
    return dest


def test_label_basis_file_is_hash_pinned(tmp_path: Path) -> None:
    payload, status = LB.load_pinned_label_basis(ROOT)
    assert status == "ok"
    assert payload is not None and payload["basis_set_id"] == "v8_official_label_basis_v1"

    dest = _copy_basis(tmp_path)
    assert LB.load_pinned_label_basis(tmp_path)[1] == "ok"
    raw = dest.read_bytes()
    # 값 1바이트 변경(같은 길이) — 해시 불일치로 fail-closed
    changed = raw.replace(b'"registered_on": "2026-11-11"', b'"registered_on": "2026-11-12"')
    assert changed != raw
    dest.write_bytes(changed)
    assert LB.load_pinned_label_basis(tmp_path) == (None, "label_basis_hash_mismatch")

    dest.write_bytes(b"{not json")
    assert LB.load_pinned_label_basis(tmp_path) == (None, "label_basis_hash_mismatch")

    dest.unlink()
    assert LB.load_pinned_label_basis(tmp_path) == (None, "label_basis_file_missing")


def test_official_basis_is_grid_and_diagnostic_rows_are_excluded() -> None:
    payload, status = LB.load_pinned_label_basis(ROOT)
    assert status == "ok"
    assert payload["official_basis"]["label_basis"] == X.GRID_BASIS == LB.OFFICIAL_BASIS
    diag = payload["diagnostic_bases"]
    assert [d["label_basis"] for d in diag] == [X.LABEL_BASIS]
    assert diag[0]["scoring_excluded"] is True and diag[0]["display_only"] is True
    ledger = ROOT / diag[0]["ledger"]
    assert ledger.is_file()
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows, "진단 원장이 비어 있다"
    for row in rows:
        assert row["scoring_excluded"] is True
        assert row["label_basis"] == X.LABEL_BASIS
    assert (ROOT / payload["official_basis"]["ledger"]).is_file()
    assert (ROOT / diag[0]["prereg"]).is_file()


def test_v8_frozen_coordinates_unchanged() -> None:
    import hashlib

    from ai_fc.timeseries_v8.contracts import frozen_hash, load_contract_v8

    payload, _ = LB.load_pinned_label_basis(ROOT)
    official = payload["official_basis"]
    contract = load_contract_v8(ROOT)
    assert frozen_hash(contract).startswith(official["frozen_coordinates_hash_prefix"])
    assert official["frozen_coordinates_hash_prefix"] == "7c56ee4eaa569782"
    digest = hashlib.sha256((ROOT / official["frozen_contract"]).read_bytes()).hexdigest()
    assert digest == official["contract_file_sha256_at_registration"]


def test_thresholds_label_bases_agree() -> None:
    thresholds = json.loads(
        (ROOT / "data/mts_research/contracts/coherence_monitor_thresholds_v1.json").read_text(encoding="utf-8"))
    payload, _ = LB.load_pinned_label_basis(ROOT)
    live = thresholds["v8_live"]
    assert live["label_bases"] == [payload["official_basis"]["label_basis"],
                                   payload["diagnostic_bases"][0]["label_basis"]]
    assert live["label_basis_mixing"] == "prohibited"
    assert any("결합하지 않는다" in p for p in payload["prohibitions"])


def test_approval_block_quotes_instruction_verbatim() -> None:
    payload, _ = LB.load_pinned_label_basis(ROOT)
    approval = payload["approval"]
    assert approval["approval_text"] == INSTRUCTION
    assert "  " in approval["approval_text"]  # 공백 2칸 원문
    assert approval["approval_form"] == "delegated_bundle_instruction"
    assert approval["literal_template_match"] is False
    assert approval["template_text"].strip() and approval["template_text"] != INSTRUCTION
    assert approval["instructed_at_upper_bound"] == "2026-11-11T09:03:44Z"
    assert payload["notice"] == "참고 의견, 매매 신호 아님"


def test_u1_display_contract_references_label_basis_loader() -> None:
    path = ROOT / "data/mts_research/contracts/mts_display_diagnostics_v1.yaml"
    if not path.is_file():
        pytest.skip("U1 표시 진단 계약이 아직 없다(병합 순서)")
    import yaml

    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    assert contract.get("label_basis_source") == LB.LABEL_BASIS_RELATIVE.as_posix()
    # 재선언 금지 — basis 선언 키(official_basis·diagnostic_bases)를 따로 두지 않는다
    assert "official_basis" not in contract
    assert "diagnostic_bases" not in contract
    assert "V13-D16" in text
