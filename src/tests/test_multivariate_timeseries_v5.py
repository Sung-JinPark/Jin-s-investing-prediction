from __future__ import annotations

import gzip
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from ai_fc.read_model_contract import validate as validate_read_model
from ai_fc.timeseries_v5.artifact import validate_latest
from ai_fc.timeseries_v5.contracts import MODEL_ID, PROBABILITY_SPACE, load_contract
from ai_fc.timeseries_v5.evaluation import evaluate
from ai_fc.timeseries_v5.features import _align_available
from ai_fc.timeseries_v5.identifiers import content_hash
from ai_fc.timeseries_v5.lineage import ParsedObservation, RawReceipt, build_versions, make_outcome, verify_lineage
from ai_fc.timeseries_v5.market_calendar import market_feature_is_eligible, missing_completed_sessions, session_records
from ai_fc.timeseries_v5.models import FROZEN_SPECS, QUANTILE_LEVELS, DirectDistributionModel
from ai_fc.timeseries_v5.pipeline import _apply_quantile_calibration, _select_weight, train_v5
from ai_fc.timeseries_v5.sources import SOURCE_REGISTRY, parse_body, sanitized_uri
from ai_fc.timeseries_v5.storage.local_store import LocalControlPlane
from ai_fc.timeseries_v5.storage.object_store import LocalObjectStore


ROOT = Path(__file__).resolve().parents[2]


def _receipt(name: str, moment: datetime) -> RawReceipt:
    return RawReceipt(receipt_id=f"receipt-{name}", run_id="run", source_id="test", raw_sha256=name * 64, raw_uri=f"raw/{name}.gz", source_uri="https://example.test/data", request_fingerprint="f" * 64, retrieved_at=moment, http_status=200, content_type="text/csv")


def test_v5_contract_keeps_model_probability_and_gate_frozen() -> None:
    contract = load_contract(ROOT)
    assert contract["model_id"] == MODEL_ID
    assert contract["probability_space"] == PROBABILITY_SPACE
    assert contract["probability_unit"] == "fraction"
    assert contract["target"]["horizons_sessions"] == [1, 5, 21, 63]
    assert contract["research_gate"]["long_horizon_mean_crps_improvement_min"] == .02
    assert contract["promotion"]["automatic_promotion"] is False


def test_raw_store_is_content_addressed_and_control_plane_is_append_only(tmp_path: Path) -> None:
    objects = LocalObjectStore(tmp_path); body = b"date,value\n2026-01-01,1\n"
    first = objects.put_raw("test", body, content_type="text/csv", metadata={}); second = objects.put_raw("test", body, content_type="text/csv", metadata={})
    assert first == second and objects.get(first["uri"]) == body
    with gzip.open(tmp_path / first["uri"], "rb") as handle: assert handle.read() == body
    control = LocalControlPlane(tmp_path); assert control.append("events", {"id": "a", "value": 1}, identity="id"); assert not control.append("events", {"id": "a", "value": 1}, identity="id")
    with pytest.raises(ValueError): control.append("events", {"id": "a", "value": 2}, identity="id")
    assert control.append_many("events", [{"id": "b", "value": 2}, {"id": "c", "value": 3}], identity="id") == 2
    assert control.append_many("events", [{"id": "b", "value": 2}], identity="id") == 0


def test_revision_and_unchanged_receipt_link_semantics() -> None:
    t0 = datetime(2026, 1, 2, 22, tzinfo=timezone.utc); first_receipt = _receipt("a", t0)
    parsed = [ParsedObservation(series_id="X", observation_time=t0, value=1.0, unit="index", available_at=t0, data_grade="captured_forward")]
    first, first_links, outcome = build_versions(source_id="test", receipt=first_receipt, parsed=parsed, prior_rows=[], created_at=t0)
    assert outcome == "new_facts" and first[0].revision_seq == 1 and first[0].supersedes is None
    unchanged, unchanged_links, outcome = build_versions(source_id="test", receipt=_receipt("b", t0 + timedelta(days=1)), parsed=parsed, prior_rows=[first[0].model_dump(mode="json")], created_at=t0 + timedelta(days=1))
    assert outcome == "unchanged_facts" and not unchanged and unchanged_links[0]["relation"] == "unchanged"
    revised_parsed = [parsed[0].model_copy(update={"value": 2.0, "available_at": t0 + timedelta(days=2)})]
    revised, _, outcome = build_versions(source_id="test", receipt=_receipt("c", t0 + timedelta(days=2)), parsed=revised_parsed, prior_rows=[first[0].model_dump(mode="json")], created_at=t0 + timedelta(days=2))
    assert outcome == "revised_facts" and revised[0].revision_seq == 2 and revised[0].supersedes == first[0].observation_id


def test_lineage_requires_terminal_outcome_and_fact_link() -> None:
    moment = datetime(2026, 1, 2, tzinfo=timezone.utc); receipt = _receipt("d", moment)
    parsed = [ParsedObservation(series_id="X", observation_time=moment, value=1, unit="index", available_at=moment, data_grade="native_pit")]
    versions, links, terminal = build_versions(source_id="test", receipt=receipt, parsed=parsed, prior_rows=[])
    outcome = make_outcome(receipt.receipt_id, terminal, parser_version="v5.1", fact_count=1)
    result = verify_lineage([receipt.model_dump(mode="json")], [outcome.model_dump(mode="json")], [versions[0].model_dump(mode="json")], links)
    assert result["ok"] and result["terminal_outcome_coverage"] == 1
    broken = verify_lineage([receipt.model_dump(mode="json")], [outcome.model_dump(mode="json")], [versions[0].model_dump(mode="json")], [])
    assert not broken["ok"] and broken["observation_linkage"] == 0


def test_pit_boundary_and_xnas_weekend_freshness() -> None:
    cutoff = "2026-01-02T21:00:00+00:00"
    assert market_feature_is_eligible(cutoff, cutoff)
    assert not market_feature_is_eligible("2026-01-02T21:00:01+00:00", cutoff)
    with pytest.raises(ValueError): market_feature_is_eligible("2026-01-02T21:00:00", cutoff)
    assert missing_completed_sessions("2026-08-21", through_session="2026-08-23") == 0
    early = session_records("2026-11-27", "2026-11-27")[0]
    assert early["close_at"].endswith("18:00:00+00:00")


def test_available_at_alignment_never_backfills_before_first_eligible_close() -> None:
    pd = pytest.importorskip("pandas")
    sessions = session_records("2026-01-05", "2026-01-07")
    first_close = pd.Timestamp(sessions[0]["close_at"])
    rows = pd.DataFrame([
        {"available_at": first_close + pd.Timedelta(seconds=1), "value": 7.0, "revision_seq": 1},
    ])
    values, age = _align_available(rows, sessions)
    assert np.isnan(values.iloc[0])
    assert values.iloc[1] == 7.0 and age.iloc[1] == 0.0


def test_direct_location_scale_model_recovers_synthetic_direction() -> None:
    rng = np.random.default_rng(7); x = rng.normal(size=(800, 4)); y = .02 + .04 * x[:, 0] - .03 * x[:, 1] + rng.standard_t(6, 800) * .01
    model = DirectDistributionModel.fit(x[:700], y[:700], alpha=.1, df=6, family="student_t_location_scale")
    high = model.predict(np.array([2., 0., 0., 0.]), sample_count=2000); low = model.predict(np.array([-2., 0., 0., 0.]), sample_count=2000)
    assert high["location"] > low["location"]
    assert 0 <= high["up_probability"] <= 1
    assert np.all(np.diff(high["quantiles"]) >= 0)


def test_core_and_challenger_candidates_use_preregistered_feature_blocks() -> None:
    rng = np.random.default_rng(71)
    x = rng.normal(size=(500, 4)); y = .01 * x[:, 0] + .02 * x[:, 2] + rng.normal(scale=.01, size=500)
    names = ["core_momentum", "core_yield", "challenger_ofr", "challenger_cmdi"]
    core = DirectDistributionModel.fit(x, y, alpha=1.0, df=6, family="student_t_location_scale", feature_names=names)
    challenger = DirectDistributionModel.fit(x, y, alpha=1.0, df=5, family="ex_ante_soft_regime_mixture", feature_names=names)
    assert core.active_feature_names == ("core_momentum", "core_yield")
    assert challenger.active_feature_names == tuple(names)
    assert len(core._design(x[0])) == 3
    assert len(challenger._design(x[0])) == 1 + 2 * len(names)


def test_convex_stacking_weight_is_selected_inside_anchor_floor() -> None:
    rng = np.random.default_rng(81)
    x = rng.normal(size=(260, 2)); y = 0.025 * x[:, 0] + rng.normal(scale=.004, size=260)
    rows = [{"baseline_p10": -.03, "baseline_p90": .03, "baseline_crps": .02} for _ in range(260)]
    weight, audit = _select_weight(
        rows,
        x,
        y,
        {"alpha": 1.0, "df": 6.0, "family": "student_t_location_scale"},
        0.35,
        feature_names=["core_a", "core_b"],
    )
    assert 0.0 <= weight <= 0.65
    assert len(audit["stacking_grid_crps"]) == 21
    assert f"{weight:.6f}" in audit["stacking_grid_crps"]
    assert audit["calibration_origins"] == 52 and len(audit["quantile_calibration"]) == 9


def test_inner_quantile_calibration_preserves_monotonic_distribution() -> None:
    samples = np.linspace(-.02, .02, 1000)
    adjustments = {str(level): (-.01 if level < .5 else .01) for level in QUANTILE_LEVELS}
    calibrated = _apply_quantile_calibration(samples, adjustments)
    assert np.all(np.diff(calibrated) >= 0)
    assert len(calibrated) == len(samples)


def test_preregistered_bundle_contains_real_hgb_and_evt_within_budget() -> None:
    assert len(FROZEN_SPECS) + 1 <= 12  # E0 anchor is the additional experiment.
    by_family = {str(row["family"]): row for row in FROZEN_SPECS}
    rng = np.random.default_rng(19)
    x = rng.normal(size=(500, 5))
    y = 0.02 * x[:, 0] + 0.01 * np.square(x[:, 1]) + rng.standard_t(4, 500) * 0.012
    hgb = DirectDistributionModel.fit(x, y, alpha=float(by_family["quantile_hist_gradient_boosting"]["alpha"]), df=6, family="quantile_hist_gradient_boosting")
    evt = DirectDistributionModel.fit(x, y, alpha=float(by_family["student_t_evt_tail"]["alpha"]), df=4, family="student_t_evt_tail")
    assert hgb.quantile_estimators is not None and len(hgb.quantile_estimators) == 3
    assert evt.evt_threshold is not None and evt.evt_scale is not None
    assert np.all(np.diff(hgb.predict(x[0], sample_count=1000)["quantiles"]) >= 0)
    frozen = train_v5(ROOT)
    assert frozen["experiment_count"] == len(FROZEN_SPECS) + 1
    assert frozen["experiment_count"] <= frozen["max_experiments"]


def test_evaluation_gate_does_not_silently_clip_or_pass_bad_model() -> None:
    rows = []
    for horizon in (1, 5, 21, 63):
        for index in range(80):
            actual = .02 if index % 2 else -.02
            rows.append({"origin": f"2020-{index // 28 + 1:02d}-{index % 28 + 1:02d}", "horizon": horizon, "actual": actual, "model_crps": .03, "baseline_crps": .02, "p10": -.01, "p25": -.005, "p50": 0., "p75": .005, "p90": .01, "baseline_p10": -.03, "baseline_p90": .03, "stress_regime": "pandemic" if index < 10 else "normal"})
    result = evaluate(rows, load_contract(ROOT), pit_leakage_count=0, lineage_linkage=1)
    assert not result["pass"] and any("CRPS" in reason for reason in result["reasons"])


def _latest(*, visible: bool) -> dict:
    value = {"schema_version": 5, "model_id": MODEL_ID, "model_version": 5, "status": "shadow_research_visible" if visible else "shadow_validation_hold", "probability_space": PROBABILITY_SPACE, "probability_unit": "fraction", "numbers_visible": visible, "combined_with_existing_models": False, "research_gate": {"pass": visible}, "operational_gate": {"pass": visible}, "horizons": {}, "path": {}}
    if visible:
        value["horizons"] = {str(h): {"up_probability": .5, "quantiles": {"p01": 1, "p05": 2, "p10": 3, "p25": 4, "p50": 5, "p75": 6, "p90": 7, "p95": 8, "p99": 9}} for h in (1, 5, 21, 63)}; value["path"] = {"p50": [1]}
    value["content_hash"] = content_hash(value); return value


def test_artifact_visibility_requires_both_gates_and_hides_hold_numbers() -> None:
    validate_latest(_latest(visible=False)); validate_latest(_latest(visible=True))
    bad = _latest(visible=True); bad["operational_gate"]["pass"] = False; bad["content_hash"] = content_hash({key: value for key, value in bad.items() if key != "content_hash"})
    with pytest.raises(ValueError, match="visibility"): validate_latest(bad)
    bad = _latest(visible=False); bad["path"] = {"p50": [1]}; bad["content_hash"] = content_hash({key: value for key, value in bad.items() if key != "content_hash"})
    with pytest.raises(ValueError, match="hide"): validate_latest(bad)


def test_read_model_accepts_isolated_v5_hold() -> None:
    payload = _latest(visible=False); payload.pop("content_hash")
    model = {key: ({} if value is dict else []) for key, value in __import__("ai_fc.read_model_contract", fromlist=["V2_KEYS"]).V2_KEYS.items()}
    legacy = __import__("ai_fc.read_model_contract", fromlist=["LEGACY_KEYS"]).LEGACY_KEYS
    model.update({key: ({} if value is dict else []) for key, value in legacy.items()}); model["timeseries"] = payload
    errors = [error for error in validate_read_model(model) if error.startswith("timeseries")]
    assert not errors


def test_source_catalog_and_secret_redaction_are_explicit() -> None:
    required = {"fred_nasdaqcom", "cboe_vix", "cboe_vix9d", "cboe_vix3m", "cboe_vvix", "cboe_skew", "ofr_fsi", "fed_ebp", "nyfed_cmdi", "treasury_yield_curve", "treasury_dts", "cftc_tff", "finra_otc", "sec_companyfacts", "eia_crude_oil"}
    assert required <= set(SOURCE_REGISTRY)
    safe = sanitized_uri("https://api.test/path?api_key=secret&series=X")
    assert "secret" not in safe and "REDACTED" in safe and "series=X" in safe


def test_json_parser_keeps_provider_dimensions_to_avoid_false_revisions() -> None:
    spec = SOURCE_REGISTRY["treasury_dts"]
    body = json.dumps({"data": [
        {"record_date": "2026-08-21", "account_type": "Treasury General Account", "open_today_bal": "100"},
        {"record_date": "2026-08-21", "account_type": "Tax and Loan Note Accounts", "open_today_bal": "20"},
    ]}).encode()
    parsed = parse_body(spec, body)
    assert len(parsed) == 2
    assert {row.dimensions["account_type"] for row in parsed} == {"Treasury General Account", "Tax and Loan Note Accounts"}
    finra = SOURCE_REGISTRY["finra_otc"]
    finra_rows = parse_body(finra, json.dumps([{"summaryStartDate": "2026-08-03", "initialPublishedDate": "2026-08-10", "summaryTypeCode": "ATS_W_VOL_STATS", "tierIdentifier": "NMS", "totalNotionalSum": 10}]).encode())
    assert finra_rows[0].observation_time.date().isoformat() == "2026-08-03"
    assert finra_rows[0].available_at.date().isoformat() == "2026-08-10"


def test_atlas_compute_worker_strips_provider_and_storage_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location("atlas", ROOT / "tools/atlas_timeseries.py"); assert spec and spec.loader
    atlas = importlib.util.module_from_spec(spec); spec.loader.exec_module(atlas)
    monkeypatch.setenv("FRED_API_KEY", "secret"); monkeypatch.setenv("TSV5_DATABASE_URL", "secret"); monkeypatch.setenv("SAFE_VALUE", "ok")
    env = atlas._compute_env()
    assert "FRED_API_KEY" not in env and "TSV5_DATABASE_URL" not in env and env["SAFE_VALUE"] == "ok"


def test_workflow_separates_collection_secrets_from_compute() -> None:
    text = (ROOT / ".github/workflows/timeseries-v5-refresh.yml").read_text(encoding="utf-8")
    collect, compute = text.split("  compute:", 1)
    assert "TSV5_DATABASE_URL" in collect and "FRED_API_KEY" in collect
    assert "TSV5_DATABASE_URL" not in compute and "FRED_API_KEY" not in compute
    assert "protected and allowlist guard" in compute
