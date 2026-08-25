"""Origin-specific PIT DFM fitting and deterministic cache addressing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


class DfmCacheError(RuntimeError):
    pass


@dataclass(frozen=True)
class DfmFitArtifact:
    cache_key: str
    contract_hash: str
    cutoff: str
    input_hash: str
    max_input_available_at: str
    factor_names: tuple[str, ...]
    parameters: tuple[float, ...]
    last_factors: tuple[float, ...]
    convergence_status: str


def dfm_cache_key(contract_hash: str, cutoff: datetime, input_hash: str) -> str:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise DfmCacheError("DFM cutoff must be timezone-aware")
    material = {"contract_hash": contract_hash, "cutoff": cutoff.astimezone(timezone.utc).isoformat(), "input_hash": input_hash}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PitDfmCache:
    def __init__(self) -> None:
        self._artifacts: dict[str, DfmFitArtifact] = {}

    def fit_or_get(
        self, *, contract_hash: str, cutoff: datetime, input_hash: str,
        input_available_at: tuple[datetime, ...], fitter: Callable[[], Mapping[str, Any]],
    ) -> DfmFitArtifact:
        if not input_available_at:
            raise DfmCacheError("DFM inputs are required")
        cutoff_utc = cutoff.astimezone(timezone.utc)
        maximum = max(value.astimezone(timezone.utc) for value in input_available_at)
        if maximum > cutoff_utc:
            raise DfmCacheError("DFM contains future-available input")
        key = dfm_cache_key(contract_hash, cutoff, input_hash)
        if key in self._artifacts:
            return self._artifacts[key]
        result = fitter()
        artifact = DfmFitArtifact(
            cache_key=key,
            contract_hash=contract_hash,
            cutoff=cutoff_utc.isoformat().replace("+00:00", "Z"),
            input_hash=input_hash,
            max_input_available_at=maximum.isoformat().replace("+00:00", "Z"),
            factor_names=tuple(result["factor_names"]),
            parameters=tuple(float(value) for value in result["parameters"]),
            last_factors=tuple(float(value) for value in result["last_factors"]),
            convergence_status=str(result["convergence_status"]),
        )
        if artifact.convergence_status != "converged":
            raise DfmCacheError("DFM convergence failed; previous values cannot be reused")
        self._artifacts[key] = artifact
        return artifact

    def latest_before(self, origin_cutoff: datetime) -> DfmFitArtifact:
        cutoff = origin_cutoff.astimezone(timezone.utc)
        eligible = [artifact for artifact in self._artifacts.values() if datetime.fromisoformat(artifact.cutoff.replace("Z", "+00:00")) <= cutoff]
        if not eligible:
            raise DfmCacheError("no DFM cache exists before origin cutoff")
        return max(eligible, key=lambda artifact: (artifact.cutoff, artifact.cache_key))


def fit_dynamic_factor_mq(endog: Any) -> Mapping[str, Any]:
    """Production adapter; called only in the locked training runtime."""
    from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

    model = DynamicFactorMQ(endog, factors=2, factor_orders=1, idiosyncratic_ar1=True, standardize=False)
    result = model.fit(method="em", maxiter=500, disp=False)
    converged = bool(result.mle_retvals.get("converged", False))
    factors = result.factors.filtered.iloc[-1].to_numpy(dtype=float)
    return {
        "factor_names": ("growth_factor", "inflation_factor"),
        "parameters": result.params.to_numpy(dtype=float),
        "last_factors": factors,
        "convergence_status": "converged" if converged else "failed",
    }
