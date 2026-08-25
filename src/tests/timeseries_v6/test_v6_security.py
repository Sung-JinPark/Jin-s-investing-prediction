from __future__ import annotations

import json

import pytest

from ai_fc.timeseries_v6.security import (
    COLLECTOR_SECRET_ALLOWLIST,
    DETERMINISTIC_NUMERIC_ENV,
    CapabilityError,
    build_worker_environment,
    capability_manifest,
    redact_text,
    require_capability,
    scan_text_for_runtime_secrets,
)


FAKE_ENV = {
    "PATH": "/usr/bin",
    "TEMP": "/tmp",
    "PYTHONPATH": "/workspace/src",
    "FRED_API_KEY": "fake-fred-secret-123",
    "TSV6_DATABASE_URL": "postgresql://user:fake-password@db/research",
    "TSV6_S3_SECRET_ACCESS_KEY": "fake-s3-secret-456",
    "GITHUB_TOKEN": "fake-github-token-789",
    "OPENAI_API_KEY": "fake-openai-secret-012",
    "UNRELATED": "not-forwarded",
}


@pytest.mark.parametrize(
    "role",
    ["materializer", "trainer_cpu", "trainer_gpu", "evaluator", "codex", "reviewer"],
)
def test_non_collector_workers_receive_zero_secrets(role: str) -> None:
    environment = build_worker_environment(role, FAKE_ENV)
    assert environment.included_secret_names == ()
    assert set(environment.values) == {"PATH", "TEMP", "PYTHONPATH", *DETERMINISTIC_NUMERIC_ENV}
    assert all(environment.values[name] == value for name, value in DETERMINISTIC_NUMERIC_ENV.items())
    assert "FRED_API_KEY" in environment.stripped_names
    assert "GITHUB_TOKEN" in environment.stripped_names
    serialized = json.dumps(environment.audit_dict())
    assert "fake-fred-secret" not in serialized
    assert "fake-github-token" not in serialized


def test_collector_receives_only_exact_data_plane_secret_allowlist() -> None:
    environment = build_worker_environment("collector", FAKE_ENV)
    assert set(environment.included_secret_names) == {
        "FRED_API_KEY", "TSV6_DATABASE_URL", "TSV6_S3_SECRET_ACCESS_KEY"
    }
    assert "GITHUB_TOKEN" not in environment.values
    assert "OPENAI_API_KEY" not in environment.values
    assert set(environment.included_secret_names).issubset(COLLECTOR_SECRET_ALLOWLIST)


def test_capability_boundary_fails_closed() -> None:
    require_capability("collector", "provider_secret_read")
    require_capability("trainer_cpu", "fit_write")
    with pytest.raises(CapabilityError, match="lacks"):
        require_capability("codex", "provider_secret_read")
    with pytest.raises(CapabilityError, match="unknown"):
        require_capability("superuser", "anything")
    with pytest.raises(CapabilityError, match="secret-like"):
        build_worker_environment("codex", FAKE_ENV, public_overrides={"MY_TOKEN": "x"})


def test_output_redaction_and_secret_scan_never_record_values() -> None:
    text = (
        "request api_key=fake-fred-secret-123 "
        "Authorization fake-github-token-789 password=hunter2"
    )
    matches = scan_text_for_runtime_secrets(text, FAKE_ENV)
    assert matches == ["FRED_API_KEY", "GITHUB_TOKEN"]
    redacted = redact_text(text, [value for key, value in FAKE_ENV.items() if key != "PATH"])
    assert "fake-fred-secret-123" not in redacted
    assert "fake-github-token-789" not in redacted
    assert "password=[REDACTED]" in redacted


def test_capability_manifest_denies_research_publication_credentials() -> None:
    manifest = capability_manifest()
    assert manifest["github_credentials_available_to_research_workers"] is False
    assert manifest["publication_credentials_available_to_research_workers"] is False
    assert manifest["non_collector_secret_names"] == []


def test_numeric_thread_controls_override_host_variation() -> None:
    source = {**FAKE_ENV, "OMP_NUM_THREADS": "12", "OPENBLAS_NUM_THREADS": "8", "PYTHONHASHSEED": "99"}
    environment = build_worker_environment("trainer_cpu", source)
    assert {name: environment.values[name] for name in DETERMINISTIC_NUMERIC_ENV} == DETERMINISTIC_NUMERIC_ENV
