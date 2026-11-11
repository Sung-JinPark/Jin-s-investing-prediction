"""daily6m v2 contract pins, v1 byte-identity pins and repository wiring (read only)."""
from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

from ai_fc.timeseries_daily6m import contracts as v1C
from ai_fc.timeseries_daily6m_v2 import contracts as C

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/daily6m-v2-shadow.yml"
FORBIDDEN = "timeseries" + "_v14"
NEW_PATHS = (
    "data/contracts/timeseries_daily6m_v2.yaml",
    "data/timeseries_daily6m_v2/prereg/design_constants_v1.json",
    "data/timeseries_daily6m_v2/prereg/design_report_v1.json",
    "data/timeseries_daily6m_v2/ledgers/approvals.jsonl",
    "src/ai_fc/timeseries_daily6m_v2/__init__.py",
    "src/ai_fc/timeseries_daily6m_v2/contracts.py",
    "src/ai_fc/timeseries_daily6m_v2/kernel.py",
    "src/ai_fc/timeseries_daily6m_v2/model.py",
    "src/ai_fc/timeseries_daily6m_v2/design.py",
    "src/ai_fc/timeseries_daily6m_v2/pipeline.py",
    "src/ai_fc/timeseries_daily6m_v2/scorecard.py",
    "tools/check_daily6m_v2_pending.py",
    "tools/publish_daily6m_v2_shadow.py",
    ".github/workflows/daily6m-v2-shadow.yml",
    "src/tests/test_daily6m_v2_kernel.py",
    "src/tests/test_daily6m_v2_model.py",
    "src/tests/test_daily6m_v2_pipeline.py",
    "src/tests/test_daily6m_v2_scorecard.py",
    "src/tests/test_daily6m_v2_contract_wiring.py",
    "src/tests/test_daily6m_v2_publication.py",
    "docs/research/mts_upgrade/daily6m_v2_prereg_20261111.md",
)


def test_contract_loads_and_constants_hash_is_pinned():
    contract = C.load_contract(ROOT)
    constants = C.load_constants(ROOT, contract)
    assert C.canonical_hash(constants) == contract["design_constants"]["canonical_hash"]
    assert constants["long_run_rule"]["registered"] == "slow_ewma_0.996"
    assert constants["persistence_by_column"]["nasdaq_return"] == 0.98708


def test_v1_is_byte_identical_pin():
    # Any PR that deliberately changes the v1 hash updates this pin in the same commit; the v2 contract's
    # parent.model_code_hash_at_registration keeps the registration-time value (it is never rewritten).
    assert v1C.model_code_hash(ROOT) == "c3fe06c1fbe3b0862e299f8eeb0a2018f8f35940f2fe12be06366905b2fda539"
    assert v1C.frozen_hash(v1C.load_contract(ROOT)) == "53f023f79829778c37bfc460698ff5e2224894b9ec7ecfd03f2d18fddeeb83dc"


def test_code_hash_sets_do_not_cross():
    assert "timeseries_daily6m_v2" not in inspect.getsource(v1C.model_code_hash)
    assert not any("timeseries_daily6m/" in path or "daily6m_sources" in path for path in C.CODE_PATHS)


def test_contract_loader_compares_whole_evaluation_blocks(tmp_path):
    """Review N4: labels, timing, p value, secondary metrics and the h21 promotion n are all matched."""
    import copy
    import pytest
    base = yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    edits = (
        lambda c: c["evaluation"]["labels"].__setitem__("inferior", "ci90_lower_ge_0"),
        lambda c: c["evaluation"]["verdict_timing"].__setitem__("h1_p_values", "frozen_at_owner_choice"),
        lambda c: c["evaluation"]["metrics"].__setitem__("secondary", ["coverage80_raw"]),
        lambda c: c["evaluation"].__setitem__("p_value", "two_sided"),
        lambda c: c["evaluation"]["inference_sample"].__setitem__("representative_run", "latest"),
        lambda c: c["publication"]["promotion"].__setitem__("requires", ["owner_decision"]),
    )
    target = tmp_path / C.CONTRACT_RELATIVE
    target.parent.mkdir(parents=True)
    for edit in edits:
        contract = copy.deepcopy(base)
        edit(contract)
        target.write_text(yaml.safe_dump(contract, allow_unicode=True), encoding="utf-8")
        with pytest.raises(C.Daily6mV2ContractError):
            C.load_contract(tmp_path)
    assert C.THRESHOLDS[21] == 30 and "h21_thinned_n30_ci90_lower_le_0" in base["publication"]["promotion"]["requires"]


def test_gating_code_hash_scope():
    # B2: the run gate covers only files that can change a forecast number; orchestration is a diagnostic
    assert set(C.CODE_PATHS) == set(C.NUMERICAL_CODE_PATHS) == {
        "src/ai_fc/timeseries_daily6m_v2/kernel.py", "src/ai_fc/timeseries_daily6m_v2/model.py",
        "src/ai_fc/timeseries/model.py", "src/ai_fc/timeseries/backtest.py", "src/ai_fc/timeseries_v2/model.py"}
    assert set(C.ORCHESTRATION_CODE_PATHS) == {
        "src/ai_fc/timeseries_daily6m_v2/contracts.py", "src/ai_fc/timeseries_daily6m_v2/pipeline.py",
        "src/ai_fc/timeseries_daily6m_v2/scorecard.py"}


def test_workflow_triggers_and_registration():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = workflow[True]
    assert on["workflow_run"] == {"workflows": ["timeseries-daily6m"], "types": ["completed"]}
    assert {"cron": "52 */3 * * *"} in on["schedule"]
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in text and "|| true" not in text
    assert all(step.get("with", {}).get("include-hidden-files") is True
               for step in workflow["jobs"]["shadow"]["steps"] if "upload-artifact" in str(step.get("uses", "")))
    verify = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    ops = (ROOT / ".github/workflows/ops-failure-alert.yml").read_text(encoding="utf-8")
    pages = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert '"daily6m-v2-shadow"' in verify
    assert "- daily6m-v2-shadow" in ops
    assert "daily6m-v2-shadow" not in pages   # no site display (D9/D12)
    pending = (ROOT / "tools/check_daily6m_v2_pending.py").read_text(encoding="utf-8")
    assert "America/New_York" in pending and "time(16, 0)" in pending and "36" not in pending


def test_no_v14_string_in_cli_workflow_or_package():
    texts = [(ROOT / "src/ai_fc/cli.py").read_text(encoding="utf-8"), WORKFLOW.read_text(encoding="utf-8")]
    texts += [path.read_text(encoding="utf-8") for path in (ROOT / "src/ai_fc/timeseries_daily6m_v2").glob("*.py")]
    assert all(FORBIDDEN not in text for text in texts)


def test_new_paths_avoid_protected_globs():
    from ai_fc.timeseries_v7.protection import GLOB_SPECS
    protected = [pattern for _, pattern in GLOB_SPECS] + [".github/workflows/timeseries*.yml", "tools/*timeseries*",
                                                           "tools/*scenario*", "tools/*v6*", "src/tests/test_multivariate_timeseries*.py"]
    for path in NEW_PATHS:
        assert (ROOT / path).exists(), path
        assert not [pattern for pattern in protected if fnmatchcase(path, pattern)], path


def test_ledger_registry_lists_seven_v2_entries():
    registry = yaml.safe_load((ROOT / "data/contracts/ledger_registry.yaml").read_text(encoding="utf-8"))
    entries = registry["ledgers"] if isinstance(registry, dict) else registry
    ids = {row["id"]: row for row in entries}
    expected = {"timeseries_daily6m_v2_forecasts", "timeseries_daily6m_v2_resolutions", "timeseries_daily6m_v2_verdicts",
                "timeseries_daily6m_v2_runs", "timeseries_daily6m_v2_approvals", "timeseries_daily6m_v2_prereg",
                "timeseries_daily6m_v2_scorecard"}
    assert expected <= set(ids)
    assert ids["timeseries_daily6m_v2_verdicts"]["path"] == "data/timeseries_daily6m_v2/ledgers/verdicts.jsonl"
    assert ids["timeseries_daily6m_v2_verdicts"]["cadence"] == "event"


def test_publisher_allow_list():
    import importlib.util
    spec = importlib.util.spec_from_file_location("v2publisher", ROOT / "tools/publish_daily6m_v2_shadow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = "data/timeseries_daily6m_v2/"
    assert module.allowed(store + "ledgers/verdicts.jsonl") and store + "ledgers/verdicts.jsonl" in module.LEDGERS
    assert not module.allowed(store + "ledgers/approvals.jsonl")
    assert not module.allowed(store + "prereg/design_constants_v1.json")
    assert not module.allowed("data/timeseries_daily6m/ledgers/forecasts.jsonl")


def test_contract_rules_and_v8_precedent_runs_exist():
    contract = C.load_contract(ROOT)
    evaluation = contract["evaluation"]
    assert evaluation["family"] == list(C.FAMILY) and evaluation["bootstrap"]["kind"] == "iid"
    assert evaluation["verdict_timing"]["one_row_per_kind"] is True
    assert contract["model"]["lead_width_multiplier"] == C.LEAD_MULTIPLIER_REJECTED
    runs = contract["model"]["variance_term_structure"]["mechanism_precedent"]["dev_runs"]
    assert len(runs) == 2 and all((ROOT / f"data/timeseries_v8/runs/dev_{run}.json").is_file() for run in runs)
    assert contract["publication"]["site_display"] == "none"


def test_approval_receipt_form():
    rows = [json.loads(line) for line in (ROOT / C.APPROVAL_LEDGER).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["literal_template_match"] is False and row["approval_form"] == "delegated_bundle_instruction"
    assert row["approval_text"] == "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜"
    instant = datetime.fromisoformat(row["approved_at"]).astimezone(timezone.utc)
    assert instant == datetime(2026, 11, 11, 9, 3, 44, tzinfo=timezone.utc)


def test_pending_tool_decisions(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("v2pending", ROOT / "tools/check_daily6m_v2_pending.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    v1 = tmp_path / "data/timeseries_daily6m"
    (v1 / "ledgers").mkdir(parents=True)
    (v1 / "runs").mkdir()
    (v1 / "runs/a.json").write_text(json.dumps({"dates": ["2026-11-13", "2026-11-16"]}), encoding="utf-8")
    (v1 / "ledgers/forecasts.jsonl").write_text(json.dumps({"forecast_id": "a", "supersedes": None,
                                                            "run_path": "data/timeseries_daily6m/runs/a.json"}) + "\n", encoding="utf-8")
    before = module.decide(tmp_path, datetime(2026, 11, 13, 20, 59, tzinfo=timezone.utc))   # 15:59 New York
    after = module.decide(tmp_path, datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc))     # 16:00 New York
    assert before["forecast"] is True and before["work"] is True and after["forecast"] is False
    v2 = tmp_path / "data/timeseries_daily6m_v2/ledgers"
    v2.mkdir(parents=True)
    (v2 / "forecasts.jsonl").write_text(json.dumps({"paired_v1_forecast_id": "a"}) + "\n", encoding="utf-8")
    (v1 / "ledgers/resolutions.jsonl").write_text(json.dumps({"resolution_id": "a:2026-11-13", "forecast_id": "a", "supersedes": None}) + "\n",
                                                  encoding="utf-8")
    paired = module.decide(tmp_path, datetime(2026, 11, 14, tzinfo=timezone.utc))
    assert paired["forecast"] is False and paired["resolve"] is True and paired["work"] is True
    (v2 / "resolutions.jsonl").write_text(json.dumps({"v1_resolution_id": "a:2026-11-13"}) + "\n", encoding="utf-8")
    assert module.decide(tmp_path, datetime(2026, 11, 14, tzinfo=timezone.utc))["work"] is False
