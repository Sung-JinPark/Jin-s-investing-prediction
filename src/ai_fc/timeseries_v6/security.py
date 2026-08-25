"""Capability-scoped worker environments and credential redaction for V6."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, Mapping


class CapabilityError(RuntimeError):
    """Raised when a worker requests a capability outside its profile."""


PUBLIC_ENV_ALLOWLIST = frozenset(
    {
        "ALLUSERSPROFILE",
        "APPDATA",
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "NUMEXPR_NUM_THREADS",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "OS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PYTHONHASHSEED",
        "PYTHONPATH",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TZ",
        "USERPROFILE",
        "WINDIR",
    }
)

DETERMINISTIC_NUMERIC_ENV = {
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "PYTHONHASHSEED": "0",
}

COLLECTOR_SECRET_ALLOWLIST = frozenset(
    {
        "FRED_API_KEY",
        "BLS_API_KEY",
        "BEA_API_KEY",
        "EIA_API_KEY",
        "CBOE_API_KEY",
        "FINRA_API_KEY",
        "TSV6_DATABASE_URL",
        "TSV6_S3_ENDPOINT",
        "TSV6_S3_BUCKET",
        "TSV6_S3_ACCESS_KEY_ID",
        "TSV6_S3_SECRET_ACCESS_KEY",
    }
)

FORBIDDEN_SECRET_NAME_PATTERNS = (
    re.compile(r"(?:^|_)(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE_?KEY)(?:$|_)", re.I),
    re.compile(r"^(?:AWS|AZURE|GCP|GOOGLE|GITHUB|GH|OPENAI|ANTHROPIC|TSV5)_", re.I),
    re.compile(r"(?:^|_)DATABASE_URL$", re.I),
)

WORKER_CAPABILITIES: dict[str, frozenset[str]] = {
    "collector": frozenset({"provider_secret_read", "raw_object_write", "receipt_write"}),
    "materializer": frozenset({"typed_data_read", "snapshot_write", "parquet_write"}),
    "trainer_cpu": frozenset({"immutable_snapshot_read", "fit_write"}),
    "trainer_gpu": frozenset({"immutable_snapshot_read", "fit_write", "gpu_use"}),
    "evaluator": frozenset({"fit_read", "score_write", "gate_proposal_write"}),
    "codex": frozenset({"isolated_worktree_write", "allowlisted_code_test_write"}),
    "reviewer": frozenset({"evidence_read", "decision_proposal_write"}),
}


@dataclass(frozen=True)
class WorkerEnvironment:
    role: str
    values: dict[str, str]
    included_secret_names: tuple[str, ...]
    stripped_names: tuple[str, ...]

    def audit_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "included_public_names": sorted(set(self.values) - set(self.included_secret_names)),
            "included_secret_names": list(self.included_secret_names),
            "stripped_names": list(self.stripped_names),
            "secret_values_recorded": False,
        }


def is_secret_name(name: str) -> bool:
    upper = name.upper()
    if upper in COLLECTOR_SECRET_ALLOWLIST:
        return True
    return any(pattern.search(upper) for pattern in FORBIDDEN_SECRET_NAME_PATTERNS)


def require_capability(role: str, capability: str) -> None:
    allowed = WORKER_CAPABILITIES.get(role)
    if allowed is None:
        raise CapabilityError(f"unknown V6 worker role: {role}")
    if capability not in allowed:
        raise CapabilityError(f"worker {role} lacks capability {capability}")


def build_worker_environment(
    role: str,
    source: Mapping[str, str] | None = None,
    *,
    public_overrides: Mapping[str, str] | None = None,
) -> WorkerEnvironment:
    """Build a closed worker environment without logging credential values."""

    if role not in WORKER_CAPABILITIES:
        raise CapabilityError(f"unknown V6 worker role: {role}")
    source = os.environ if source is None else source
    values: dict[str, str] = {
        name: value
        for name, value in source.items()
        if name.upper() in PUBLIC_ENV_ALLOWLIST
    }
    included_secrets: list[str] = []
    if role == "collector":
        for name in sorted(COLLECTOR_SECRET_ALLOWLIST):
            if name in source:
                values[name] = source[name]
                included_secrets.append(name)
    if public_overrides:
        forbidden = sorted(name for name in public_overrides if is_secret_name(name))
        if forbidden:
            raise CapabilityError(f"secret-like public override rejected: {forbidden}")
        values.update(public_overrides)
    # Candidate selection and sealed evaluation must not inherit a host's
    # BLAS thread count.  Different reduction orders can move a converged
    # quantile solution enough to break byte-for-byte replay even though the
    # mathematical coordinate is unchanged.  These are public execution
    # controls, not credentials, and are deliberately forced for every V6
    # worker role.
    values.update(DETERMINISTIC_NUMERIC_ENV)
    stripped = sorted(
        name
        for name in source
        if is_secret_name(name) and name not in included_secrets
    )
    return WorkerEnvironment(
        role=role,
        values=values,
        included_secret_names=tuple(included_secrets),
        stripped_names=tuple(stripped),
    )


def redact_text(text: str, secret_values: Iterable[str]) -> str:
    """Redact exact runtime secrets and credential-bearing URL query values."""

    result = text
    for value in sorted({value for value in secret_values if value}, key=len, reverse=True):
        result = result.replace(value, "[REDACTED]")
    result = re.sub(
        r"(?i)(api_?key|token|secret|password)=([^&\s]+)",
        lambda match: f"{match.group(1)}=[REDACTED]",
        result,
    )
    return result


def scan_text_for_runtime_secrets(text: str, source: Mapping[str, str]) -> list[str]:
    """Return credential variable names whose values appear in output text."""

    return sorted(
        name
        for name, value in source.items()
        if is_secret_name(name) and value and len(value) >= 8 and value in text
    )


def capability_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "worker_capabilities": {
            role: sorted(capabilities)
            for role, capabilities in sorted(WORKER_CAPABILITIES.items())
        },
        "collector_secret_names": sorted(COLLECTOR_SECRET_ALLOWLIST),
        "non_collector_secret_names": [],
        "github_credentials_available_to_research_workers": False,
        "publication_credentials_available_to_research_workers": False,
    }
