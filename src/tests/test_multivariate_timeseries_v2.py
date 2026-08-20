from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from ai_fc.facts import ObservationFact
from ai_fc.timeseries.model import fit_ridge_varx, select_ridge_varx
from ai_fc.timeseries_v2.artifact import (
    TimeSeriesV2ArtifactError,
    append_unique,
    blocked_latest,
    read_latest,
    write_latest,
)
from ai_fc.timeseries_v2.contracts import (
    TimeSeriesV2ContractError,
    frozen_hash,
    load_contract_v2,
    require_dfm_runtime,
)
from ai_fc.timeseries_v2.dfm_cache import (
    build_origin_dfm_cache,
    load_factor_states_for_sessions,
    read_dfm_manifest,
    verify_dfm_runtime_provenance,
)
from ai_fc.timeseries_v2.market_archive import (
    ARCHIVE_FACTS,
    MarketObservationV2,
    _append_observations,
    _market_available_at,
    _treasury_available_at,
    parse_cboe_vix_csv,
    parse_fed_ebp_csv,
    parse_treasury_xml,
    persist_market_raw,
    verify_market_lineage,
)
from ai_fc.timeseries_v2.model import (
    select_distribution_parameters_v2,
    select_ridge_varx_v2,
    simulate_correlated_paths_v2,
)
from ai_fc.timeseries_v2.pipeline import (
    TimeSeriesV2PipelineError,
    _candidate_development_eligibility,
    backtest_timeseries_v2,
    _monitoring_sample,
    _operational_gate_reasons,
    _required_market_freshness,
    _sealed_already_disclosed,
    _source_ledger_hashes,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "data/contracts").mkdir(parents=True)
    shutil.copy2(
        REPOSITORY_ROOT / "data/contracts/multivariate_timeseries_v2.yaml",
        root / "data/contracts/multivariate_timeseries_v2.yaml",
    )
    return root


def _macro_fact(series_id: str, observation: str, available_at: str, value: float) -> ObservationFact:
    return ObservationFact(
        source_id="alfred",
        series_id=series_id,
        observation_time=observation,
        value=value,
        available_at=available_at,
        vintage_start=available_at,
        retrieved_at="2026-08-20T00:00:00+00:00",
        source_revision_id=f"{series_id}:{observation}:{available_at}",
        source_hash="a" * 64,
        parser_version="test",
        timezone="America/New_York",
        calendar_id="US_FED",
    )


def test_batched_v2_selector_is_numerically_equivalent_to_preregistered_selector() -> None:
    rng = np.random.default_rng(260820)
    endog = rng.normal(0.0, 0.01, size=(380, 5))
    exog = rng.normal(0.0, 1.0, size=(380, 3))
    kwargs = {
        "endog_names": ("nasdaq", "vix", "dgs2", "curve", "dollar"),
        "exog_names": ("growth", "inflation", "age"),
        "lag_candidates": (1, 2),
        "alpha_candidates": (0.1, 1.0),
    }
    reference = select_ridge_varx(endog, exog, **kwargs)
    optimized = select_ridge_varx_v2(endog, exog, **kwargs)
    assert optimized.lag == reference.lag
    assert optimized.alpha == reference.alpha
    assert optimized.selection_score == pytest.approx(reference.selection_score, abs=1e-16)
    assert np.allclose(optimized.coefficients, reference.coefficients, rtol=1e-12, atol=1e-14)
    assert np.allclose(optimized.residuals, reference.residuals, rtol=1e-12, atol=1e-14)


def test_batched_distribution_and_paths_are_deterministic_and_preserve_cross_correlation() -> None:
    rng = np.random.default_rng(9127)
    covariance = np.array([[1.0, 0.72], [0.72, 1.0]]) * 0.0001
    endog = rng.multivariate_normal(np.zeros(2), covariance, size=900)
    exog = np.empty((len(endog), 0))
    fit = fit_ridge_varx(
        endog,
        exog,
        lag=1,
        alpha=1.0,
        endog_names=("nasdaq", "vix"),
        exog_names=(),
    )
    selected_a = select_distribution_parameters_v2(fit.residuals, seed=77)
    selected_b = select_distribution_parameters_v2(fit.residuals, seed=77)
    assert selected_a == selected_b
    kwargs = {
        "fits": (fit, fit),
        "weights": (1.0, 0.0),
        "endog_history": endog,
        "exog_last": exog[-1],
        "anchor": 100.0,
        "path_count": 1500,
        "horizon": 21,
        "block_length": selected_a[0],
        "ewma_lambda": selected_a[1],
        "seed": 831,
    }
    first = simulate_correlated_paths_v2(**kwargs)
    second = simulate_correlated_paths_v2(**kwargs)
    assert first["path_hash"] == second["path_hash"]
    innovations = np.asarray(first["innovations"]).reshape(-1, 2)
    simulated_correlation = float(np.corrcoef(innovations.T)[0, 1])
    residual_correlation = float(np.corrcoef(fit.residuals.T)[0, 1])
    assert simulated_correlation == pytest.approx(residual_correlation, abs=0.08)


def test_market_and_treasury_availability_respect_new_york_dst() -> None:
    assert _market_available_at("2026-01-15") == "2026-01-15T21:15:00+00:00"
    assert _market_available_at("2026-07-15") == "2026-07-15T20:15:00+00:00"
    assert _treasury_available_at("2026-01-15") == "2026-01-15T23:00:00+00:00"
    assert _treasury_available_at("2026-07-15") == "2026-07-15T22:00:00+00:00"


def test_v2_contract_freezes_candidates_windows_units_and_isolation(tmp_path: Path) -> None:
    contract = load_contract_v2(_root(tmp_path))
    assert contract["model_id"] == "shadow.mf_dfm_ridge_varx_v2"
    assert list(contract["model"]["candidates"]) == ["C1", "C2", "C3", "C4", "C5"]
    assert contract["model"]["windows"]["development"] == ["2007-01-01", "2018-12-31"]
    assert contract["model"]["windows"]["sealed"] == ["2019-01-01", "latest"]
    assert contract["probability_contract"]["stored_unit"] == "fraction"
    assert contract["probability_contract"]["combine_with_official_forecasts"] is False
    assert contract["probability_contract"]["combine_with_scenario_v5_2"] is False
    assert "BAMLH0A0HYM2" not in contract["model"]["varx"]["endogenous"]
    assert contract["model"]["dynamic_factor"]["em_tolerance"] == 1e-5
    original_hash = frozen_hash(contract)
    contract["model"]["dynamic_factor"]["em_tolerance"] = 2e-5
    assert frozen_hash(contract) != original_hash


def test_market_raw_is_content_addressed_and_secret_free(tmp_path: Path) -> None:
    root = _root(tmp_path)
    receipt = persist_market_raw(
        root,
        source_id="cboe_vix_archive",
        source_uri="https://example.test/data.csv?api_key=SECRET",
        payload=b"DATE,CLOSE\n01/02/2020,12.5\n",
        retrieved_at="2026-08-20T00:00:00+00:00",
    )
    assert "SECRET" not in json.dumps(receipt.model_dump())
    assert receipt.raw_sha256 in receipt.raw_path
    assert (root / receipt.raw_path).is_file()


def test_official_archive_parsers_read_vix_and_treasury() -> None:
    vix = parse_cboe_vix_csv(b"DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2007,12,13,11,12.34\n")
    assert vix == [("2007-01-02", 12.34)]
    treasury = parse_treasury_xml(b"""<?xml version='1.0'?>
    <feed xmlns:m='http://schemas.microsoft.com/ado/2007/08/dataservices/metadata'
          xmlns:d='http://schemas.microsoft.com/ado/2007/08/dataservices'>
      <entry><content><m:properties><d:NEW_DATE>2007-01-02T00:00:00</d:NEW_DATE>
      <d:BC_2YEAR>4.80</d:BC_2YEAR><d:BC_10YEAR>4.68</d:BC_10YEAR>
      </m:properties></content></entry></feed>""")
    assert treasury == [("2007-01-02", 4.8, 4.68)]
    ebp = parse_fed_ebp_csv(b"date,gz_spread,ebp,est_prob\n1/1/2007,1.2,-0.15,0.2\n")
    assert ebp == [("2007-01-01", -0.15)]


def test_market_observation_is_reconstructed_not_native_and_revision_is_explicit(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = persist_market_raw(
        root, source_id="official", source_uri="https://example.test/one.csv", payload=b"one",
        retrieved_at="2026-08-20T00:00:00+00:00",
    )
    outcome = _append_observations(
        root, source_id="official", series_id="NASDAQCOM", unit="index",
        values=[("2007-01-03", 100.0)], receipt=first,
        available_at=lambda day: f"{day}T21:15:00+00:00",
    )
    assert outcome["appended"] == 1
    second = persist_market_raw(
        root, source_id="official", source_uri="https://example.test/two.csv", payload=b"two",
        retrieved_at="2026-08-21T00:00:00+00:00",
    )
    revised = _append_observations(
        root, source_id="official", series_id="NASDAQCOM", unit="index",
        values=[("2007-01-03", 101.0)], receipt=second,
        available_at=lambda day: f"{day}T21:15:00+00:00",
    )
    assert revised["appended"] == 1
    rows = [
        MarketObservationV2.model_validate_json(line)
        for line in (root / ARCHIVE_FACTS).read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0].data_grade == "reconstructed_market_archive"
    assert rows[1].supersedes == rows[0].observation_id
    assert rows[1].revision_seq == 2
    assert rows[1].available_at == second.retrieved_at
    assert verify_market_lineage(root)["ok"] is True


def test_forward_captured_observation_is_not_backdated(tmp_path: Path) -> None:
    root = _root(tmp_path)
    receipt = persist_market_raw(
        root, source_id="official", source_uri="https://example.test/new.csv", payload=b"new",
        retrieved_at="2026-08-20T23:00:00+00:00",
    )
    _append_observations(
        root, source_id="official", series_id="VIX", unit="index",
        values=[("2020-01-02", 15.0)], receipt=receipt,
        available_at=lambda day: f"{day}T21:15:00+00:00", data_grade="captured_forward",
    )
    row = MarketObservationV2.model_validate_json(
        (root / ARCHIVE_FACTS).read_text(encoding="utf-8").strip()
    )
    assert row.data_grade == "captured_forward"
    assert row.available_at == receipt.retrieved_at


def test_dfm_cache_is_origin_specific_pit_and_future_cache_is_not_linked(tmp_path: Path) -> None:
    root = _root(tmp_path)
    contract = load_contract_v2(root)
    facts = [
        _macro_fact("PAYEMS", "2005-12-01", "2006-01-06T13:30:00+00:00", 100.0),
        _macro_fact("CPIAUCSL", "2005-12-01", "2006-01-18T13:30:00+00:00", 200.0),
    ]
    calls: list[str] = []

    def fake_fitter(rows, *, knowledge_cutoff: str):
        assert all(row.available_at <= knowledge_cutoff for row in rows if row.available_at <= knowledge_cutoff)
        calls.append(knowledge_cutoff)
        return {
            "states": {"growth_factor": float(len(calls)), "inflation_factor": -float(len(calls))},
            "converged": {"growth_factor": True, "inflation_factor": True},
        }

    result = build_origin_dfm_cache(
        root, contract=contract, facts=facts, end_cutoff="2006-01-31T00:00:00+00:00",
        fitter=fake_fitter,
    )
    assert result["created"] == 2
    assert calls == sorted(calls)
    origins = load_factor_states_for_sessions(
        root,
        session_cutoffs=["2006-01-10T23:59:59+00:00", "2006-01-20T23:59:59+00:00"],
        contract_hash=frozen_hash(contract),
    )
    assert origins[0]["growth_factor"] == 1.0
    assert origins[1]["growth_factor"] == 2.0
    assert origins[0]["cache_cutoff"] <= origins[0]["origin"]
    assert origins[1]["cache_cutoff"] <= origins[1]["origin"]
    replay = build_origin_dfm_cache(
        root, contract=contract, facts=facts, end_cutoff="2006-01-31T00:00:00+00:00",
        fitter=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must reuse cache")),
    )
    assert replay["created"] == 0
    assert replay["reused"] == 2


def test_dfm_runtime_correction_preserves_old_cache_and_supersedes_manifest(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _root(tmp_path)
    contract = load_contract_v2(root)
    facts = [
        _macro_fact("PAYEMS", "2005-12-01", "2006-01-06T13:30:00+00:00", 100.0),
        _macro_fact("CPIAUCSL", "2005-12-01", "2006-01-18T13:30:00+00:00", 200.0),
    ]

    def fitter(_rows, *, knowledge_cutoff: str):
        return {
            "states": {"growth_factor": 1.0, "inflation_factor": -1.0},
            "converged": {"growth_factor": True, "inflation_factor": True},
        }

    first_runtime = {
        "python": "3.12.0", "numpy": "2.0.0", "pandas": "2.2.0",
        "scipy": "1.14.0", "statsmodels": "0.14.6",
    }
    second_runtime = {**first_runtime, "numpy": "2.1.0"}
    monkeypatch.setattr("ai_fc.timeseries_v2.dfm_cache.runtime_manifest", lambda: first_runtime)
    first = build_origin_dfm_cache(
        root, contract=contract, facts=facts,
        end_cutoff="2006-01-31T00:00:00+00:00", fitter=fitter,
    )
    original_paths = {row["path"] for row in first["entries"]}
    monkeypatch.setattr("ai_fc.timeseries_v2.dfm_cache.runtime_manifest", lambda: second_runtime)
    corrected = build_origin_dfm_cache(
        root, contract=contract, facts=facts,
        end_cutoff="2006-01-31T00:00:00+00:00", fitter=fitter,
    )
    active = read_dfm_manifest(root)
    full = read_dfm_manifest(root, active_only=False)
    assert corrected["created"] == first["cutoffs"]
    assert len(active) == first["cutoffs"]
    assert len(full) == first["cutoffs"] * 2
    assert all(row["runtime"]["numpy"] == "2.1.0" for row in active)
    assert all(row.get("supersedes") for row in active)
    assert all((root / path).is_file() for path in original_paths)


def test_failed_dfm_refit_invalidates_prior_factor_instead_of_reusing_it(tmp_path: Path) -> None:
    root = _root(tmp_path)
    contract = load_contract_v2(root)
    facts = [
        _macro_fact("PAYEMS", "2005-12-01", "2006-01-06T13:30:00+00:00", 100.0),
        _macro_fact("CPIAUCSL", "2005-12-01", "2006-01-18T13:30:00+00:00", 200.0),
    ]
    calls = 0

    def fitter(_rows, *, knowledge_cutoff: str):
        nonlocal calls
        calls += 1
        ready = calls == 1
        return {
            "states": {"growth_factor": 1.0, "inflation_factor": -1.0},
            "converged": {"growth_factor": ready, "inflation_factor": ready},
        }

    build_origin_dfm_cache(
        root, contract=contract, facts=facts,
        end_cutoff="2006-01-31T00:00:00+00:00", fitter=fitter,
    )
    origins = load_factor_states_for_sessions(
        root, session_cutoffs=["2006-01-20T23:59:59+00:00"],
        contract_hash=frozen_hash(contract),
    )
    assert origins[0]["cache_id"] is None
    assert origins[0]["growth_factor"] is None


def test_blocked_latest_never_exposes_numbers_and_visible_requires_gate(tmp_path: Path) -> None:
    root = _root(tmp_path)
    payload = blocked_latest(
        as_of="2026-08-19", knowledge_cutoff="2026-08-20T00:00:00+00:00",
        contract_hash="a" * 64, reasons=["sealed gate HOLD"], data_summary={},
    )
    path = write_latest(root, payload)
    assert path.is_file()
    assert read_latest(root)["publication"]["customer_numbers_visible"] is False
    payload["publication"]["customer_numbers_visible"] = True
    with pytest.raises(TimeSeriesV2ArtifactError, match="before all gates"):
        write_latest(root, payload)


def test_sealed_ledger_is_append_only_and_single_identity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    payload = {"run_id": "sealed-1", "status": "hold"}
    assert append_unique(root, Path("data/timeseries_v2/ledgers/sealed.jsonl"), payload, key="run_id")
    assert not append_unique(root, Path("data/timeseries_v2/ledgers/sealed.jsonl"), payload, key="run_id")
    with pytest.raises(TimeSeriesV2ArtifactError, match="collision"):
        append_unique(
            root, Path("data/timeseries_v2/ledgers/sealed.jsonl"),
            {"run_id": "sealed-1", "status": "pass"}, key="run_id",
        )


def test_sealed_evaluation_can_be_disclosed_only_once_per_frozen_contract(tmp_path: Path) -> None:
    root = _root(tmp_path)
    contract = load_contract_v2(root)
    row = {
        "run_id": "sealed-v2", "model_id": contract["model_id"],
        "contract_hash": frozen_hash(contract), "summary": {"gate_pass": False},
    }
    append_unique(
        root, Path("data/timeseries_v2/ledgers/sealed_evaluations.jsonl"), row, key="run_id",
    )
    assert _sealed_already_disclosed(
        root, model_id=contract["model_id"], contract_hash=frozen_hash(contract),
    ) == row


def test_development_only_candidate_disclosure_is_disabled(tmp_path: Path) -> None:
    with pytest.raises(TimeSeriesV2PipelineError, match="non-sealed preflight"):
        backtest_timeseries_v2(_root(tmp_path), disclose_sealed=False)


def test_sealed_evaluation_cannot_reduce_the_preregistered_20000_paths(tmp_path: Path) -> None:
    with pytest.raises(TimeSeriesV2PipelineError, match="exactly 20000 paths"):
        backtest_timeseries_v2(_root(tmp_path), path_count=1000)


def test_sealed_provenance_records_each_source_ledger_hash(tmp_path: Path) -> None:
    root = _root(tmp_path)
    expected = {
        "data/timeseries/ledgers/observation_chunks.jsonl": b"macro-manifest\n",
        "data/timeseries/ledgers/raw_receipts.jsonl": b"macro-receipts\n",
        "data/timeseries_v2/ledgers/market_observations.jsonl": b"market-observations\n",
        "data/timeseries_v2/ledgers/market_raw_receipts.jsonl": b"market-receipts\n",
        "data/timeseries_v2/ledgers/dfm_cache_manifest.jsonl": b"dfm-cache\n",
    }
    for relative, body in expected.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    observed = _source_ledger_hashes(root)

    assert set(observed) == {
        "macro_observation_manifest", "macro_receipts", "market_observations",
        "market_receipts", "dfm_cache_manifest",
    }
    assert all(value is not None and len(value) == 64 for value in observed.values())
    assert observed["market_receipts"] == hashlib.sha256(
        expected["data/timeseries_v2/ledgers/market_raw_receipts.jsonl"]
    ).hexdigest()


def test_dfm_runtime_is_exactly_preregistered_and_auditable(tmp_path: Path) -> None:
    expected = {
        "python": "3.12.10", "numpy": "2.2.6", "pandas": "2.2.3",
        "scipy": "1.15.3", "statsmodels": "0.14.6",
    }
    assert require_dfm_runtime(expected) == expected
    with pytest.raises(TimeSeriesV2ContractError, match="statsmodels==0.14.6"):
        require_dfm_runtime({**expected, "statsmodels": "0.14.5"})

    root = _root(tmp_path)
    manifest = root / "data/timeseries_v2/ledgers/dfm_cache_manifest.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"cache_id": "dfm-a", "runtime": expected}) + "\n", encoding="utf-8")
    assert verify_dfm_runtime_provenance(root)["ok"] is True
    manifest.write_text(json.dumps({"cache_id": "dfm-a"}) + "\n", encoding="utf-8")
    audit = verify_dfm_runtime_provenance(root)
    assert audit["ok"] is False
    assert audit["missing_runtime"] == ["dfm-a"]


def test_candidate_selection_requires_comparable_full_development_era(tmp_path: Path) -> None:
    from types import SimpleNamespace

    contract = load_contract_v2(_root(tmp_path))
    eligible, reasons = _candidate_development_eligibility(
        SimpleNamespace(dates=("1997-01-02", "2026-08-14")), contract=contract,
    )
    assert eligible is True
    assert reasons == []
    eligible, reasons = _candidate_development_eligibility(
        SimpleNamespace(dates=("2011-06-02", "2026-08-14")), contract=contract,
    )
    assert eligible is False
    assert reasons == ["development_window_pit_coverage_incomplete"]


def test_required_market_freshness_blocks_any_group_older_than_48_hours(tmp_path: Path) -> None:
    from types import SimpleNamespace

    contract = load_contract_v2(_root(tmp_path))
    rows = []
    for series in ("NASDAQCOM", "VIX", "DGS2", "DGS10"):
        rows.append(SimpleNamespace(
            series_id=series,
            observation_time="2026-08-19",
            available_at="2026-08-19T20:15:00+00:00",
        ))
    rows.append(SimpleNamespace(
        series_id="DTWEXBGS",
        observation_time="2026-08-14",
        available_at="2026-08-14T20:15:00+00:00",
    ))
    result = _required_market_freshness(
        rows, contract=contract, knowledge_cutoff="2026-08-20T02:00:00+00:00",
    )
    assert result["ok"] is False
    assert result["stale_groups"] == ["DTWEXBGS_or_DTWEXB"]
    rows.append(SimpleNamespace(
        series_id="DTWEXBGS",
        observation_time="2020-01-03",
        available_at="2026-08-20T01:59:00+00:00",
    ))
    result = _required_market_freshness(
        rows, contract=contract, knowledge_cutoff="2026-08-20T02:00:00+00:00",
    )
    assert result["stale_groups"] == ["DTWEXBGS_or_DTWEXB"]
    result = _required_market_freshness(
        rows[:-2] + [SimpleNamespace(
            series_id="DTWEXBGS",
            observation_time="2026-08-19",
            available_at="2026-08-19T20:15:00+00:00",
        )],
        contract=contract,
        knowledge_cutoff="2026-08-20T02:00:00+00:00",
    )
    assert result["ok"] is True


def test_operational_monitoring_uses_matured_shadow_origins_and_enforces_coverage(tmp_path: Path) -> None:
    root = _root(tmp_path)
    contract = load_contract_v2(root)
    sample = _monitoring_sample(np.array([3.0, 1.0, 2.0]), count=5)
    assert sample == sorted(sample)
    path = root / "data/timeseries_v2/ledgers/resolutions.jsonl"
    path.parent.mkdir(parents=True)
    rows = []
    for index in range(26):
        for horizon in (21, 63):
            rows.append({
                "as_of": f"2026-01-{index + 1:02d}", "horizon_sessions": horizon,
                "model_crps": 0.9, "baseline_crps": {"random_walk": 1.0},
                "covered_p10_p90": False,
            })
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    reasons, evidence = _operational_gate_reasons(
        root, contract=contract, fallback_scores=[],
    )
    assert evidence["source"] == "matured_shadow_forecasts"
    assert evidence["matured_origin_count"] == 26
    assert any("적중률" in reason for reason in reasons)


def test_v2_workflow_preserves_raw_before_model_and_uses_secret_only_for_collection() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/timeseries-v2-refresh.yml").read_text(encoding="utf-8")
    macro = workflow.index("Append ALFRED native PIT macro vintages")
    market = workflow.index("Append official reconstructed market archives")
    checkpoint = workflow.index("Checkpoint raw receipts and append-only observations before models")
    prepare = workflow.index("Prepare origin-specific DFM caches on Saturday")
    assert macro < checkpoint and market < checkpoint < prepare
    assert "FRED_API_KEY: ${{ secrets.FRED_API_KEY }}" in workflow
    assert "timeseries-v2-backtest" in workflow
    assert "timeseries-v2-monitor-backtest" in workflow
    assert "data/timeseries_v2" in workflow


def test_v2_workflow_runs_exact_runtime_gate_on_same_repo_pr_and_main_bootstrap() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/timeseries-v2-refresh.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow
    assert "ref: ${{ github.head_ref || github.ref_name }}" in workflow
    assert "bootstrap=\"${{ github.event_name == 'pull_request' || github.event_name == 'push' }}\"" in workflow
    assert '[ "$bootstrap" = "true" ]' in workflow
    assert "statsmodels==0.14.6" in (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
