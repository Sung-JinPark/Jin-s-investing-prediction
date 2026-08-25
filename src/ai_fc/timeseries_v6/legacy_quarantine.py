"""Hard boundary preventing V4/V5 derived matrices from entering V6."""

from pathlib import PurePosixPath


class LegacyQuarantineError(RuntimeError):
    pass


LEGACY_ROOTS = ("data/timeseries_v4", "data/timeseries_v5", "outputs/timeseries_v4", "outputs/timeseries_v5")
FORBIDDEN_FEATURE_PATTERNS = ("crisis_year", "future_move", "future_quartile", "oracle_regime", "v4_ffill")


def validate_v6_training_inputs(paths: list[str], feature_names: list[str]) -> None:
    for raw in paths:
        path = PurePosixPath(raw.replace("\\", "/")).as_posix()
        if any(path == root or path.startswith(f"{root}/") for root in LEGACY_ROOTS):
            raise LegacyQuarantineError(f"legacy derived input prohibited: {path}")
    for name in feature_names:
        lowered = name.lower()
        if any(pattern in lowered for pattern in FORBIDDEN_FEATURE_PATTERNS):
            raise LegacyQuarantineError(f"ex-post or legacy feature prohibited: {name}")
