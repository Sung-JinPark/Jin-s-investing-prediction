from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ai_fc.scenario_v4_shadow import load_shadow, load_shadow_state


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "src/ai_fc/dashboard_parts/dashboard.js"


def _view_model_helper() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"function buildScenarioChartViewModel\([\s\S]+?\n}\nfunction diagnosticPanelMarkup",
        source,
    )
    assert match, "state-driven scenario view-model helper must remain standalone"
    return match.group(0).removesuffix("\nfunction diagnosticPanelMarkup")


def _node_view_model(candidate_state: dict) -> dict:
    candidate = {
        "candidate_id": "legacy_gbm_actual_member_v1",
        "status": "shadow_only",
        "promotion_state": "not_eligible_diagnostic_baseline",
        "model_identity": {"family": "legacy_gbm"},
        "source": {
            "asof": "2026-08-03",
            "snapshot_id": "source-r8",
            "snapshot_sha256": "abc123",
        },
        "reproducibility": {"canonical_payload_sha256": "def456"},
        "official_weights": {"values": {"S1": 0.83, "S2": 0.02, "S3": 0.15}},
        "candidate_implied_weights": {
            "values": {"S1": 0.8351, "S2": 0.0151, "S3": 0.1498}
        },
        "week_dates": ["2026-08-03", "2026-08-10"],
        "representatives": {},
        "scenario_distributions": {
            "S1": {"sample_count": 16702, "blocked_quantiles": {}},
            "S2": {
                "sample_count": 302,
                "blocked_quantiles": {
                    "p25_p75": "insufficient_conditional_sample_n_302_lt_500"
                },
            },
            "S3": {"sample_count": 2996, "blocked_quantiles": {}},
        },
        "unconditional_distribution": {},
        "diagnostics": {"sample_gates": {"representative_and_p50": 200}},
        "year_slices": {},
    }
    program = (
        _view_model_helper()
        + "\nconsole.log(JSON.stringify(buildScenarioChartViewModel("
        + json.dumps(
            {
                "mode": "legacy_actual_member_diagnostic",
                "official": {},
                "candidate": candidate,
                "candidateState": candidate_state,
            }
        )
        + ")));"
    )
    completed = subprocess.run(
        ["node", "-e", program],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def test_dashboard_defaults_to_official_and_diagnostic_is_explicit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "let sc=officialScenario,shadowActive=false" in source
    assert "data-flow-diagnostic-view hidden" in source
    assert "data-flow-v4-shadow" in source


def test_diagnostic_view_model_has_one_consistent_candidate_identity() -> None:
    view = _node_view_model({"status": "shadow_only", "display_allowed": True})
    assert view["candidateId"] == "legacy_gbm_actual_member_v1"
    assert view["family"] == "legacy_gbm"
    assert view["title"] == "LEGACY GBM ACTUAL-MEMBER · SHADOW DIAGNOSTIC"
    assert view["subtitle"] == "NOT RCFHS · NOT OFFICIAL · NOT CHAMPION"
    assert view["supportsStructuralBaseline"] is False
    assert view["supportsLookup"] is False
    assert view["sourceStatus"] == "shadow_only"


def test_stale_source_disables_diagnostic_view_model() -> None:
    view = _node_view_model(
        {
            "status": "stale_source",
            "display_allowed": False,
            "reason": "source snapshot_sha256 mismatch",
        }
    )
    assert view["displayAllowed"] is False
    assert view["status"] == "stale_source"
    assert view["warnings"] == ["source snapshot_sha256 mismatch"]


def test_dashboard_uses_conditional_small_multiples_and_separate_unconditional_panel() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    artifact = json.loads(
        (ROOT / "data/scenarios/shadow/legacy_gbm_actual_member_v1_latest.json")
        .read_text(encoding="utf-8")
    )
    assert "data-diagnostic-chart=\"${key}\"" in source
    assert "Legacy joint unconditional distribution" in source
    assert "data-diagnostic-unconditional-chart" in source
    assert artifact["scenario_distributions"]["S2"]["available_quantiles"] == ["p50"]
    assert artifact["scenario_distributions"]["S1"]["available_quantiles"] == [
        "p05", "p10", "p25", "p50", "p75", "p90", "p95"
    ]
    assert artifact["scenario_distributions"]["S3"]["available_quantiles"] == [
        "p05", "p10", "p25", "p50", "p75", "p90", "p95"
    ]


def test_diagnostic_never_uses_old_rcfhs_or_official_label() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "RCFHS-SB v1 official" not in source
    assert "RCFHS-SB v1 shadow" not in source
    assert "NOT RCFHS · NOT OFFICIAL · NOT CHAMPION" in source
    assert "Legacy GBM diagnostic · shadow active" in source


def test_diagnostic_has_no_structural_baseline_or_duplicate_path_layer() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"function diagnosticPanelMarkup\([\s\S]+?\n}\nfunction diagnosticPathD",
        source,
    )
    assert match
    diagnostic_markup = match.group(0)
    assert "data-flow-baseline" not in diagnostic_markup
    assert "structural_forecast" not in diagnostic_markup
    assert "data-representative" in source
    assert "data-overview-representative" in source


def test_active_candidate_loader_is_fresh_and_dashboard_safe() -> None:
    candidate = load_shadow(ROOT)
    state = load_shadow_state(ROOT)
    assert candidate is not None
    assert candidate["candidate_id"] == "legacy_gbm_actual_member_v1"
    assert state == {
        "status": "shadow_only",
        "display_allowed": True,
        "reason": None,
        "candidate_id": "legacy_gbm_actual_member_v1",
    }


def test_toggle_updates_all_model_dependent_copy() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "officialFlowView.hidden=shadowActive" in source
    assert "diagnosticFlowView.hidden=!shadowActive" in source
    assert "flow-page-eyebrow" in source
    assert "flow-page-title" in source
    assert "flow-page-lede" in source
    assert "sc=shadowScenario" not in source


def test_dashboard_renders_s1_and_s3_allowed_bands() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    artifact = json.loads(
        (ROOT / "data/scenarios/shadow/legacy_gbm_actual_member_v1_latest.json")
        .read_text(encoding="utf-8")
    )
    assert "band('p10','p90'" in source
    assert "band('p25','p75'" in source
    for key in ("S1", "S3"):
        assert artifact["scenario_distributions"][key]["available_quantiles"] == [
            "p05", "p10", "p25", "p50", "p75", "p90", "p95"
        ]


def test_dashboard_does_not_use_unconditional_fan_as_scenario_fan() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"function drawDiagnosticPanels\([\s\S]+?\n}\nfunction renderFlow",
        source,
    )
    assert match
    helper = match.group(0)
    assert "distribution:distributions[key]" in helper
    assert "distribution:vm.unconditionalDistribution" in helper


def test_dashboard_displays_official_weights_as_comparison_only() -> None:
    view = _node_view_model({"status": "shadow_only", "display_allowed": True})
    source = SCRIPT.read_text(encoding="utf-8")
    assert view["officialWeights"] == {"S1": 0.83, "S2": 0.02, "S3": 0.15}
    assert "official ${num(official)}% · reproduced ${num(implied)}%" in source
    assert "official weight는 비교값" in source


def test_dashboard_d100_comparison_uses_actual_members() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "representatives[key]?.weekly_values" in source
    assert "100*Number(value)/first" in source
    assert "data-overview-representative" in source


def test_dashboard_accessibility_labels_match_active_candidate() -> None:
    view = _node_view_model({"status": "shadow_only", "display_allowed": True})
    source = SCRIPT.read_text(encoding="utf-8")
    assert view["candidateId"] in view["accessibilityText"]
    assert "shadow diagnostic" in view["accessibilityText"]
    assert 'aria-label="${esc(vm.accessibilityText)}"' in source
