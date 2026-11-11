"""V15 정합성 섀도 계약 r2 — 로더·규칙 잠금·영수증·봉인 무접촉 (spec_U3 §8 C1~C13).

상태 의존 값(mde.status·track_open·영수증 행 총수)은 실계약에 고정하지 않는다 — r3·철회 뒤에도 깨지지 않게.
실저장소에는 쓰지 않는다. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_fc.timeseries_v15 import contracts as c
from ai_fc.timeseries_v15.plan import plan_run
from v15_coherence_fixtures import ROOT, make_root

WORKFLOW = ROOT / ".github/workflows/v15-coherence-shadow.yml"


@pytest.fixture(scope="module")
def contract() -> dict:
    return c.load_contract_v15(ROOT)


def test_c1_real_contract_loads_and_mutations_are_rejected(contract: dict) -> None:
    assert contract["contract_id"] == "multivariate_timeseries_v15_coherence"
    assert not (ROOT / "data/contracts/multivariate_timeseries_v15_coherence.draft.yaml").exists()
    mutations = [
        ("contract_id", lambda d: d.update(contract_id="x")),
        ("model_version", lambda d: d.update(model_version=8)),
        ("status", lambda d: d.update(status="draft_prereg")),
        ("size", lambda d: d["verdict_rule"]["family"]["superiority"].update(size=15)),
        ("members", lambda d: d["verdict_rule"]["family"]["superiority"]["member_pairs"].pop()),
        ("margin", lambda d: d["verdict_rule"]["family"]["noninferiority"].update(margin_rel=0.02)),
        ("pruning", lambda d: d["verdict_rule"]["family"].update(affected_horizons_rule="design_replay")),
        ("B", lambda d: d["verdict_rule"]["bootstrap"].update(replicates=1000)),
        ("seed", lambda d: d["verdict_rule"]["bootstrap"].update(seed=1)),
        ("blocks", lambda d: d["verdict_rule"]["bootstrap"]["block_length_origins_by_horizon"].update({"63": 10})),
        ("min", lambda d: d["verdict_rule"]["minimum_matured_origins_by_horizon"].update({"63": 26})),
        ("deadline", lambda d: d["verdict_rule"]["verdict_cut"].update(deadline_cut_utc="2029-01-01T00:00:00Z")),
        ("verdict_hash", lambda d: d["verdict_rule"].update(frozen_verdict_code_hash="abc")),
        ("rejected", lambda d: d["rejected_arms"].pop("A6")),
        ("sealed", lambda d: d["fork"]["sealed_originals_unchanged"].update(v8_live_model_code_hash="0" * 64)),
        ("prohibition", lambda d: d["prohibitions"].update(automatic_verdict_append=False)),
        ("combination", lambda d: d["combination"].update(allowed=True)),
        ("rule_hash", lambda d: d["provenance"].update(rule_hash_r2="0" * 64)),
    ]
    raw = c.read_contract_raw(ROOT)
    for name, mutate in mutations:
        mutated = copy.deepcopy(raw)
        mutate(mutated)
        with pytest.raises(c.TimeSeriesV15ContractError):
            c.validate_contract_v15(ROOT, mutated)
        if name != "rule_hash":  # 규칙 잠금 없이도 개별 검증이 거부한다
            with pytest.raises(c.TimeSeriesV15ContractError):
                c.validate_contract_v15(ROOT, mutated, check_rule_hash=False)


def test_c2_state_independent_values(contract: dict) -> None:
    rule = contract["verdict_rule"]
    family = rule["family"]
    assert len(family["superiority"]["member_pairs"]) == 12 and family["superiority"]["size"] == 12
    assert {tuple(p) for p in family["superiority"]["member_pairs"]} == {
        (a, h) for a in ("A1", "A2", "A3", "A4") for h in (5, 21, 63)}
    assert family["noninferiority"]["member_pairs"] == [["A5", 5], ["A5", 21], ["A5", 63]]
    assert family["noninferiority"]["size"] == 3 and family["noninferiority"]["margin_rel"] == 0.01
    assert family["superiority"]["alpha"] == family["noninferiority"]["alpha"] == 0.05
    assert rule["verdict_cut"]["deadline_cut_utc"] == "2028-06-30T23:59:59Z"
    assert rule["bootstrap"]["block_length_origins_by_horizon"] == {"5": 2, "21": 5, "63": 13}
    assert rule["minimum_matured_origins_by_horizon"] == {"5": 26, "21": 26, "63": 39}
    assert rule["bootstrap"]["replicates"] == 5000 and rule["bootstrap"]["seed"] == 20261111
    assert contract["mde"]["replay_knowledge_cutoff"] == "2026-11-11T09:03:44Z"
    assert contract["live"]["catch_up_window_v8_origins"] == 2


def test_c3_rejected_arms_are_not_registered(contract: dict) -> None:
    assert {"A6", "A7", "A2b"} <= set(contract["rejected_arms"])
    assert set(contract["arms"]) == {"A0", "A1", "A2", "A3", "A4", "A5"}
    for arm in ("A6", "A7"):
        assert contract["rejected_arms"][arm]["status"] == "not_registered"


def test_c4_approval_receipts_one_per_decision(contract: dict) -> None:
    rows = [json.loads(line) for line in (ROOT / c.APPROVALS_LEDGER).read_text(encoding="utf-8").splitlines() if line]
    by_decision: dict[str, list[dict]] = {}
    for row in rows:
        by_decision.setdefault(row["decision_id"], []).append(row)
    upper = datetime(2026, 11, 11, 9, 3, 44, tzinfo=timezone.utc)
    for decision in c.DECISIONS:
        r1 = [row for row in by_decision.get(decision, []) if row["receipt_id"].endswith(":r1")]
        assert len(r1) == 1, decision
        row = r1[0]
        assert row["receipt_id"] == f"v15-approval:{decision}:2026-11-11:r1"
        for key in ("approved_at", "approver_role", "approval_text", "approval_form", "template_text",
                    "literal_template_match", "approval_basis", "approval_scope", "conditions",
                    "semantic_reference", "source", "timestamp_note", "revocation", "rule_hash_r2"):
            assert key in row, (decision, key)
        assert row["literal_template_match"] is False
        assert row["approval_form"] == "delegated_bundle_instruction"
        assert datetime.fromisoformat(row["approved_at"]) == upper  # 문자열이 아니라 순간 비교(§6 C1)
        assert row["approved_at"] == "2026-11-11T18:03:44+09:00"
        assert row["approval_text"] == "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜"
        assert "  " in row["approval_text"]  # 공백 2칸 원문
        assert row["template_text"].startswith(decision) and row["template_text"] != row["approval_text"]
        assert row["rule_hash_r2"] == contract["provenance"]["rule_hash_r2"]
        assert row["receipt_id"] in json.dumps(contract["decisions_resolved"], ensure_ascii=False)


def test_c5_sealed_originals_untouched() -> None:
    from ai_fc.timeseries_v8.contracts import model_code_hash, verify_v2_benchmark

    assert model_code_hash(ROOT) == "869418ccb6a7356761b489bd2e23262427b31b8446dcf2f2dcc17959a8206fde"
    verify_v2_benchmark(ROOT)


def test_c6_hashes_are_deterministic(contract: dict) -> None:
    assert c.frozen_hash(contract) == c.frozen_hash(copy.deepcopy(contract))
    assert c.rule_hash(contract) == c.rule_hash(copy.deepcopy(contract))
    assert re.fullmatch(r"[0-9a-f]{64}", c.frozen_hash(contract))


def test_c7_closed_track_plans_only_mde_and_identity(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    from v15_coherence_fixtures import v8_row, write_v8_rows

    write_v8_rows(root, [v8_row("2026-11-06", "2026-11-10T11:04:48+00:00")])
    calls: list = []

    def runner(args):
        calls.append(list(args))
        return "a" * 40

    now = datetime(2026, 11, 16, 3, 40, tzinfo=timezone.utc)
    for event, schedule, mode in (("schedule", "40 3 * * 1", "auto"), ("workflow_run", "", "auto"),
                                  ("workflow_dispatch", "", "a5_issue"), ("workflow_dispatch", "", "auto")):
        result = plan_run(root, event=event, schedule=schedule, mode=mode, now=now, git_runner=runner)
        assert result["track_open"] is False
        assert result["pending"] is False and result["a5_due"] is False and result["arms"] == []
        assert result["mde_due"] is False and result["identity_due"] is False
    result = plan_run(root, mode="mde_replay", now=now, git_runner=runner)
    assert result["mde_due"] is True and result["identity_due"] is True and result["pending"] is False


def test_c8_no_v14_module_string_in_v15_package_or_workflow() -> None:
    needle = "timeseries" + "_v14"
    for path in sorted((ROOT / "src/ai_fc/timeseries_v15").glob("*.py")):
        assert needle not in path.read_text(encoding="utf-8"), path.name
    assert needle not in WORKFLOW.read_text(encoding="utf-8")
    assert "timeseries" + "-v14" not in WORKFLOW.read_text(encoding="utf-8")


def test_c9_rule_hash_equals_r2_lock(contract: dict) -> None:
    assert c.rule_hash(contract) == contract["provenance"]["rule_hash_r2"]


def _set(d: dict, path: tuple[str, ...], value) -> None:
    node = d
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def test_c10_r3_allowlist_only(contract: dict) -> None:
    base = c.rule_hash(contract)
    allowed = copy.deepcopy(contract)
    _set(allowed, ("mde", "status"), "computed")
    _set(allowed, ("mde", "values_by_horizon"), {"5": 0.03, "21": 0.04, "63": 0.05})
    _set(allowed, ("mde", "per_arm"), {"A1": {"5": {"mde_rel_at_nmin": 0.03}}})
    _set(allowed, ("mde", "artifacts", "summary_sha256"), "e" * 64)
    _set(allowed, ("live", "first_origin_not_before"), "2026-11-20")
    _set(allowed, ("development_protocol", "track_open"), True)
    _set(allowed, ("gates", "armed"), True)
    allowed["provenance"]["revisions"].append("2026-11-2x r3 (허용 목록만)")
    assert c.rule_hash(allowed) == base
    # rule_hash 대상 블록마다 잎 하나를 바꾸면 해시가 바뀐다
    leaves = {
        "target": ("target", "label_basis"),
        "arms": ("arms", "A1", "formula"),
        "rejected_arms": ("rejected_arms", "A6", "reason"),
        "live": ("live", "catch_up_window_v8_origins"),
        "verdict_rule": ("verdict_rule", "verdict_deadline"),
        "mde": ("mde", "trials"),
        "data_policy": ("data_policy", "intraday_values"),
        "contamination": ("contamination", "designed_after_live_observation"),
        "promotion": ("promotion", "minimum_shadow_sessions"),
        "prohibitions": ("prohibitions", "dl_price_training"),
        "fork": ("fork", "frozen_kernel_code_hash"),
        "revision_control": ("revision_control", "any_other_change_after_r2"),
    }
    assert set(leaves) == set(c.FROZEN_KEYS)
    for block, path in leaves.items():
        changed = copy.deepcopy(contract)
        _set(changed, path, "changed-leaf")
        assert c.rule_hash(changed) != base, block


def test_c11_pruning_rule_abolished(contract: dict) -> None:
    family = contract["verdict_rule"]["family"]
    assert family["affected_horizons_rule"] == "abolished_r2"
    assert family["superiority"]["size"] == 12
    assert "affected_horizons" not in family
    text = (ROOT / c.CONTRACT_RELATIVE).read_text(encoding="utf-8")
    assert "구조적 동일 지평이 확인되면 등록 전에 빼고" not in text


def test_c12_code_hashes_match_frozen_pins(contract: dict) -> None:
    assert c.verdict_code_hash(ROOT) == contract["verdict_rule"]["frozen_verdict_code_hash"]
    assert c.kernel_code_hash(ROOT) == contract["fork"]["frozen_kernel_code_hash"]


def test_c13_kernel_hash_scope_excludes_research_layer() -> None:
    assert not [path for path in c.KERNEL_HASH_FILES if "mts_research" in path]
    for name in ("arms", "vol", "model", "backtest", "features", "labels", "calendar", "bundle"):
        text = (ROOT / f"src/ai_fc/timeseries_v15/{name}.py").read_text(encoding="utf-8")
        assert "mts_research" not in text.replace("mts_research.sessions", "").replace(
            "mts_research.v8_xnas_labels", ""), name
        assert "import ai_fc.mts_research" not in text and "from ai_fc.mts_research" not in text
