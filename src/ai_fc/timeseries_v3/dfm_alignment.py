"""Factor sign/scale anchoring and origin-state feature derivation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class DFMAlignmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlignedFactor:
    name: str
    states: np.ndarray
    loadings: dict[str, float]
    sign: int
    reference_mean: float
    reference_scale: float
    loading_correlation: float | None


def align_factor(
    name: str, states: np.ndarray, loadings: dict[str, float], *,
    positive_references: tuple[str, ...], previous_loadings: dict[str, float] | None = None,
    reference_slice: slice = slice(None), minimum_loading_correlation: float = 0.50,
) -> AlignedFactor:
    values = np.asarray(states, dtype=float).reshape(-1)
    shared_reference = [key for key in positive_references if key in loadings]
    if not shared_reference:
        raise DFMAlignmentError(f"{name} has no reference loading")
    sign = 1 if float(np.mean([loadings[key] for key in shared_reference])) >= 0 else -1
    correlation: float | None = None
    if previous_loadings:
        shared = sorted(set(loadings) & set(previous_loadings))
        if len(shared) >= 2:
            current = np.array([loadings[key] * sign for key in shared], dtype=float)
            prior = np.array([previous_loadings[key] for key in shared], dtype=float)
            correlation = float(np.corrcoef(current, prior)[0, 1])
            if correlation < 0:
                sign *= -1
                current *= -1
                correlation = float(np.corrcoef(current, prior)[0, 1])
            if not np.isfinite(correlation) or correlation < minimum_loading_correlation:
                raise DFMAlignmentError(
                    f"{name} loading correlation {correlation!r} below {minimum_loading_correlation}"
                )
    signed = values * sign
    reference = signed[reference_slice]
    reference = reference[np.isfinite(reference)]
    if reference.size < 5:
        raise DFMAlignmentError(f"{name} fixed reference period is too short")
    mean = float(np.mean(reference))
    scale = float(np.std(reference, ddof=1))
    if not np.isfinite(scale) or scale <= 1e-12:
        raise DFMAlignmentError(f"{name} reference scale is degenerate")
    aligned_loadings = {key: float(value * sign * scale) for key, value in loadings.items()}
    return AlignedFactor(name, (signed - mean) / scale, aligned_loadings, sign, mean, scale, correlation)


def factor_features(
    aligned: AlignedFactor, *, state_prediction: np.ndarray | None = None,
    prior_vintage: np.ndarray | None = None, release_surprise_z: np.ndarray | None = None,
    age_since_release: np.ndarray | None = None, sessions_per_month: int = 21,
) -> dict[str, np.ndarray]:
    level = aligned.states
    size = level.size
    def lag_delta(lag: int) -> np.ndarray:
        output = np.full(size, np.nan)
        output[lag:] = level[lag:] - level[:-lag]
        return output
    prediction = np.asarray(state_prediction, dtype=float) if state_prediction is not None else np.full(size, np.nan)
    prior = np.asarray(prior_vintage, dtype=float) if prior_vintage is not None else np.full(size, np.nan)
    surprise = np.asarray(release_surprise_z, dtype=float) if release_surprise_z is not None else np.full(size, np.nan)
    age = np.asarray(age_since_release, dtype=float) if age_since_release is not None else np.full(size, np.nan)
    return {
        f"{aligned.name}_level": level.copy(),
        f"{aligned.name}_delta_1m": lag_delta(sessions_per_month),
        f"{aligned.name}_delta_3m": lag_delta(3 * sessions_per_month),
        f"{aligned.name}_innovation": level - prediction,
        f"{aligned.name}_revision": level - prior,
        f"{aligned.name}_release_surprise_z": surprise,
        f"{aligned.name}_age_since_release": age,
        f"{aligned.name}_availability_mask": np.isfinite(level).astype(float),
    }
