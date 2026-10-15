"""Persistence, source identity and deployment gates for daily display paths."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from ai_fc import dashboard, scenario
from ai_fc import scenario_daily_flow_artifact as artifact
from ai_fc.scenario_daily_flow import DailyFlowError


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def retained_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy only retained input; no durable source or ledger is ever written."""
    for relative in (scenario.LATEST_RELATIVE_PATH, scenario.CALENDAR_RELATIVE_PATH):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    source = json.loads((tmp_path / scenario.LATEST_RELATIVE_PATH).read_text(encoding="utf-8"))
    archive = tmp_path / scenario.ARCHIVE_RELATIVE_DIR / f"{source['asof']}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")

    def builder(snapshot: dict, calendar: dict | None = None) -> dict:
        return {
            "schema_version": 1, "version": "daily-flow-modal-medoid-v1", "status": "ok",
            "source_snapshot_id": snapshot["snapshot_id"],
            "source_snapshot_sha256": artifact.canonical_hash(snapshot),
            "input_sha256": artifact.canonical_hash({"model": snapshot["model"],
                "calendar": json.loads(json.dumps(calendar, default=str))}),
            "asof": snapshot["asof"], "anchor": snapshot["anchor"],
            "calendar_end": "2027-04-09", "default_end_index": 1,
            "dates": [snapshot["asof"], "2026-10-12"], "probability_unit": "fraction",
            "risk": {"probability_unit": "fraction", "cumulative_touch": [0.0, 0.02]},
            "scenarios": {"S1": {"status": "ok", "probability": 0.92,
                                   "probability_unit": "fraction", "selection": {"audit": "retained"},
                                   "member_path_index": 47,
                                   "values": [snapshot["anchor"], snapshot["anchor"] + 19]}},
            "shadow": {"passed": True, "checks": {"same_input": True}, "tolerance": "exact_serialized"},
        }

    # Mathematical validation is exercised by test_scenario_daily_flow.py. This
    # stub isolates immutable persistence and exact replay without another 20k run.
    monkeypatch.setattr(artifact, "build_daily_flow", builder)
    monkeypatch.setattr(artifact, "validate_daily_flow", lambda payload, source_snapshot=None: payload)
    return tmp_path


def test_build_is_source_bound_and_idempotent_without_mutating_history(retained_root: Path) -> None:
    inputs = {path: path.read_bytes() for path in retained_root.rglob("*") if path.is_file()}
    latest, payload, changed = artifact.build_artifact(retained_root)
    assert changed and payload["revision"] == 1 and payload["supersedes"] is None
    assert payload["source_snapshot_path"].startswith("data/scenarios/archive/")
    pointer = json.loads(latest.read_text(encoding="utf-8"))
    assert pointer["kind"] == "latest_reference" and "dates" not in pointer
    assert pointer["artifact_sha256"] == artifact.canonical_hash(payload)
    archive = retained_root / payload["archive_path"]
    original_bytes = archive.read_bytes()
    _, second, changed = artifact.build_artifact(retained_root)
    assert not changed and second == payload and archive.read_bytes() == original_bytes
    assert all(path.read_bytes() == contents for path, contents in inputs.items())
    assert artifact.verify_artifact(retained_root, replay=True)["ok"]


def test_same_asof_new_display_version_appends_supersedes(retained_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, first, _ = artifact.build_artifact(retained_root)
    old_path = retained_root / first["archive_path"]
    old_bytes = old_path.read_bytes()
    builder = artifact.build_daily_flow

    def changed_version(*args, **kwargs):
        result = builder(*args, **kwargs)
        result["version"] = "daily-flow-modal-medoid-v2"
        return result

    monkeypatch.setattr(artifact, "build_daily_flow", changed_version)
    _, revised, _ = artifact.build_artifact(retained_root)
    assert revised["revision"] == 2 and revised["supersedes"] == first["artifact_id"]
    assert revised["revision_reason"] == "derived_display_contract_revision"
    assert revised["model_content_sha256"] != first["model_content_sha256"]
    assert old_path.read_bytes() == old_bytes
    assert len(list((retained_root / artifact.ARCHIVE_RELATIVE_DIR).glob("*.json"))) == 2
    assert artifact.verify_artifact(retained_root)["ok"]


def test_tampered_archive_is_rejected_and_not_rewritten(retained_root: Path) -> None:
    _, payload, _ = artifact.build_artifact(retained_root)
    archive = retained_root / payload["archive_path"]
    corrupt = deepcopy(payload)
    corrupt["scenarios"]["S1"]["values"][-1] += 100
    archive.write_text(json.dumps(corrupt), encoding="utf-8")
    corrupt_bytes = archive.read_bytes()
    result = artifact.verify_artifact(retained_root)
    assert not result["ok"] and "archive hash mismatch" in result["errors"][0]
    with pytest.raises(DailyFlowError, match="content hash mismatch"):
        artifact.build_artifact(retained_root)
    assert archive.read_bytes() == corrupt_bytes


def test_source_revision_closes_display_and_source_archive_tamper_fails_verification(retained_root: Path) -> None:
    _, payload, _ = artifact.build_artifact(retained_root)
    latest_source = retained_root / scenario.LATEST_RELATIVE_PATH
    source = json.loads(latest_source.read_text(encoding="utf-8"))
    source["revision"] = 2
    source["snapshot_id"] = "nasdaq-scenario:2026-10-09:r2"
    latest_source.write_text(json.dumps(source), encoding="utf-8")
    closed = artifact.load_daily_flow(retained_root, source)
    assert closed["status"] == "unavailable" and "snapshot hash mismatch" in closed["reason"]
    # An earlier derivative remains reproducible against its retained source.
    assert artifact.verify_artifact(retained_root)["ok"]
    retained_source = retained_root / payload["source_snapshot_path"]
    retained_source.write_text(json.dumps(source), encoding="utf-8")
    assert not artifact.verify_artifact(retained_root)["ok"]


def test_exact_replay_mismatch_is_a_failure_and_verification_is_read_only(retained_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact.build_artifact(retained_root)
    before = {path: path.read_bytes() for path in retained_root.rglob("*") if path.is_file()}
    builder = artifact.build_daily_flow

    def different_member(*args, **kwargs):
        result = builder(*args, **kwargs)
        result["scenarios"]["S1"]["member_path_index"] += 1
        return result

    monkeypatch.setattr(artifact, "build_daily_flow", different_member)
    result = artifact.verify_artifact(retained_root, replay=True)
    assert not result["ok"] and "exact deterministic replay mismatch" in result["errors"][0]
    assert artifact.verify_artifact(retained_root, replay=False)["ok"]
    assert all(path.read_bytes() == contents for path, contents in before.items())


def test_replay_accepts_machine_epsilon_but_rejects_material_price_change(retained_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, payload, _ = artifact.build_artifact(retained_root)
    assert payload["model_content_hash_algorithm"] == artifact.MODEL_HASH_ALGORITHM
    builder = artifact.build_daily_flow
    delta = 1e-10

    def platform_float_difference(*args, **kwargs):
        result = builder(*args, **kwargs)
        result["scenarios"]["S1"]["values"][-1] += delta
        return result

    monkeypatch.setattr(artifact, "build_daily_flow", platform_float_difference)
    accepted = artifact.verify_artifact(retained_root)
    assert accepted["ok"]
    assert accepted["replay_tolerances"]["representative_and_band_price_absolute"] == 1e-8
    delta = 1e-3
    assert not artifact.verify_artifact(retained_root)["ok"]


def test_replay_fraction_tolerance_is_stricter_than_semantic_hash_precision(retained_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact.build_artifact(retained_root)
    builder = artifact.build_daily_flow

    def changed_probability(*args, **kwargs):
        result = builder(*args, **kwargs)
        result["scenarios"]["S1"]["probability"] += 1e-10
        return result

    monkeypatch.setattr(artifact, "build_daily_flow", changed_probability)
    assert not artifact.verify_artifact(retained_root)["ok"]


def test_one_ulp_hash_boundary_replays_and_reuses_immutable_archive(retained_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = artifact.build_daily_flow

    def rounding_boundary(*args, **kwargs):
        result = builder(*args, **kwargs)
        row = result["scenarios"]["S1"]
        row["values"][-1] = math.nextafter(27385.170000005, -math.inf)
        row["conditional_bands"] = {name: list(row["values"]) for name in ("p10", "p25", "p50", "p75", "p90")}
        return result

    monkeypatch.setattr(artifact, "build_daily_flow", rounding_boundary)
    _, original, _ = artifact.build_artifact(retained_root)
    archive = retained_root / original["archive_path"]
    before = archive.read_bytes()

    def next_platform(*args, **kwargs):
        result = rounding_boundary(*args, **kwargs)
        row = result["scenarios"]["S1"]
        row["values"] = [math.nextafter(value, math.inf) for value in row["values"]]
        row["conditional_bands"] = {
            key: [math.nextafter(value, math.inf) for value in values]
            for key, values in row["conditional_bands"].items()
        }
        return result

    source = json.loads((retained_root / scenario.LATEST_RELATIVE_PATH).read_text(encoding="utf-8"))
    changed = next_platform(source, calendar=scenario.load_calendar_contract(retained_root))
    assert artifact._model_hash(changed) != original["model_content_sha256"]
    monkeypatch.setattr(artifact, "build_daily_flow", next_platform)
    result = artifact.verify_artifact(retained_root)
    assert result["ok"] and result["replay_quantized_hash_matches"] is False
    _, repeated, written = artifact.build_artifact(retained_root)
    assert not written and repeated == original and archive.read_bytes() == before
    assert len(list((retained_root / artifact.ARCHIVE_RELATIVE_DIR).glob("*.json"))) == 1


def test_price_diagnostics_use_price_tolerance_without_relaxing_fraction_metrics() -> None:
    original = {"selection": {"metrics": {"terminal": 27385.17, "direction_change_rate": .41},
        "display_shadow": {"point_deltas": [11000.0], "maximum_absolute_delta": 11000.0}}}
    replayed = deepcopy(original)
    replayed["selection"]["metrics"]["terminal"] = math.nextafter(27385.17, math.inf)
    replayed["selection"]["display_shadow"]["point_deltas"][0] = math.nextafter(11000.0, math.inf)
    replayed["selection"]["display_shadow"]["maximum_absolute_delta"] = math.nextafter(11000.0, math.inf)
    assert artifact._replay_matches(original, replayed)
    replayed["selection"]["metrics"]["direction_change_rate"] += 1e-10
    assert not artifact._replay_matches(original, replayed)
    replayed = deepcopy(original)
    replayed["selection"]["display_shadow"]["maximum_absolute_delta"] += 1e-7
    assert not artifact._replay_matches(original, replayed)


def test_shadow_failure_never_publishes_a_pointer(retained_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = artifact.build_daily_flow

    def failed_shadow(*args, **kwargs):
        result = builder(*args, **kwargs)
        result["shadow"]["passed"] = False
        return result

    monkeypatch.setattr(artifact, "build_daily_flow", failed_shadow)
    with pytest.raises(DailyFlowError, match="shadow validation is blocked"):
        artifact.build_artifact(retained_root)
    assert not (retained_root / artifact.LATEST_RELATIVE_PATH).exists()


def test_missing_daily_artifact_is_explicitly_unavailable(retained_root: Path) -> None:
    source = json.loads((retained_root / scenario.LATEST_RELATIVE_PATH).read_text(encoding="utf-8"))
    assert artifact.load_daily_flow(retained_root, source)["status"] == "unavailable"


def test_daily_paths_defer_with_identity_and_missing_paths_stay_inline(retained_root: Path) -> None:
    _, payload, _ = artifact.build_artifact(retained_root)
    model = {"daily_flow": payload, "era_analog": {"status": "empty"}}
    original = deepcopy(model)
    base, daily = dashboard.split_daily_flow(model)
    assert model == original
    assert "dates" not in base["daily_flow"]
    assert base["daily_flow"]["deferred_paths"]["required"]
    assert base["daily_flow"]["deferred_paths"]["url"] == "daily_flow.json"
    assert daily["data"]["daily_flow"]["dates"] == payload["dates"]
    assert daily["semantic_reference"] == base["daily_flow"]["semantic_reference"]
    again, redundant = dashboard.split_daily_flow(base)
    assert again == base and redundant is None
    closed = {"status": "unavailable", "reason": "no matching derivative"}
    base, daily = dashboard.split_daily_flow({"daily_flow": closed})
    assert base["daily_flow"] == closed and daily is None


def test_daily_dashboard_projection_keeps_exact_paths_and_references_full_audit(retained_root: Path) -> None:
    _, payload, _ = artifact.build_artifact(retained_root)
    source = json.loads((retained_root / scenario.LATEST_RELATIVE_PATH).read_text(encoding="utf-8"))
    projected = artifact.dashboard_projection(retained_root, source)
    assert projected["display_projection_version"] == "daily_flow_chart_projection_v1"
    assert projected["audit_artifact_path"] == payload["archive_path"]
    assert projected["semantic_reference"] == payload["semantic_reference"]
    assert projected["scenarios"]["S1"]["values"] == payload["scenarios"]["S1"]["values"]
    assert "selection" not in projected["scenarios"]["S1"]
    assert payload["scenarios"]["S1"]["selection"] == {"audit": "retained"}


def test_daily_route_has_an_independent_fixed_budget() -> None:
    huge = {"daily_flow": {"dates": ["2026-10-09"], "audit": "x" * dashboard.DAILY_FLOW_BUDGET_BYTES}}
    with pytest.raises(ValueError, match="daily flow budget exceeded"):
        dashboard.split_daily_flow(huge)
    assert dashboard.FUTURE_PATHS_BUDGET_BYTES == 240_000


def test_real_forecast_bodies_round_trip_losslessly_with_extended_dictionary() -> None:
    import frontmatter
    import re
    import subprocess

    encoded = dashboard._forecast_bodies(ROOT)
    assert encoded
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    dictionary = re.search(r"const BODY_DICTIONARY=\[(.*?)\];", script, re.S)
    decoder = re.search(r"function decodeForecastBody\(text\)\{[^\n]+", script)
    assert dictionary is not None and decoder is not None
    # Run the shipped browser decoder once for every production-encoded body.
    # Binary stdin preserves exact newlines on Windows as well as Linux.
    program = "const BODY_DICTIONARY=[" + dictionary.group(1) + "];\n" + decoder.group(0)
    program += "\nconst rows=JSON.parse(require('fs').readFileSync(0,'utf8'));"
    program += "\nprocess.stdout.write(JSON.stringify(rows.map(row=>({...row,body:decodeForecastBody(row.body)}))));"
    rows = [{"source_uri": row["source_uri"], "body": row["body"]} for row in encoded.values()]
    restored = subprocess.run(
        ["node", "-e", program],
        input=json.dumps(rows, ensure_ascii=False).encode("utf-8"),
        check=True, capture_output=True,
    )
    decoded = json.loads(restored.stdout)
    assert len(decoded) == len(rows)
    assert [row["source_uri"] for row in decoded] == [row["source_uri"] for row in rows]
    for row in decoded:
        original = frontmatter.load(str(ROOT / row["source_uri"])).content.strip()
        assert row["body"] == original, row["source_uri"]
    # These origin/main token identities predate the appended dictionary entries.
    assert dashboard.FORECAST_BODY_DICTIONARY[58:64] == (
        "가이던스", "컨센서스", "서프라이즈", "미검증", "조건부", "인상")


def test_pages_writes_daily_sidecar_and_inline_summary(retained_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact.build_artifact(retained_root)
    source = json.loads((retained_root / scenario.LATEST_RELATIVE_PATH).read_text(encoding="utf-8"))
    projected = artifact.dashboard_projection(retained_root, source)
    model = {"scenario": source, "daily_flow": projected}
    monkeypatch.setattr(dashboard, "build_read_model", lambda *args, **kwargs: model)
    monkeypatch.setattr(dashboard, "render_html", lambda *args, **kwargs: "<html></html>")
    monkeypatch.setattr(dashboard, "_write_og_image", lambda *args: None)
    out = retained_root / "_site_test"
    dashboard.write_pages(None, out, retained_root)
    base = json.loads((out / "data.json").read_text(encoding="utf-8"))
    daily = json.loads((out / "daily_flow.json").read_text(encoding="utf-8"))
    assert "dates" not in base["daily_flow"]
    assert base["daily_flow"]["deferred_paths"]["url"] == "daily_flow.json"
    assert daily["data"]["daily_flow"] == projected
    assert daily["semantic_reference"] == base["daily_flow"]["semantic_reference"]


@pytest.mark.parametrize("workflow", ["pages.yml", "verify.yml"])
def test_deployment_and_rehearsal_require_daily_build_and_replay_before_dashboard(workflow: str) -> None:
    document = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    job = document["jobs"]["build" if workflow == "pages.yml" else "verify"]
    steps = job["steps"]
    daily_index = next(index for index, step in enumerate(steps)
                       if "scenario-daily-flow-build" in step.get("run", ""))
    daily_step = steps[daily_index]
    assert "scenario-daily-flow-verify --replay" in daily_step["run"]
    assert not daily_step.get("continue-on-error", False)
    build_index = next(index for index, step in enumerate(steps)
                       if "dashboard --pages-out" in step.get("run", ""))
    assert daily_index <= build_index
    all_commands = "\n".join(step.get("run", "") for step in steps)
    assert all_commands.index("scenario-daily-flow-build") < all_commands.index("scenario-daily-flow-verify --replay")
    assert all_commands.index("scenario-daily-flow-verify --replay") < all_commands.index("dashboard --pages-out")
    assert "sync --rebuild" in all_commands[all_commands.index("scenario-daily-flow-verify --replay"):]
    assert "git add" not in all_commands
