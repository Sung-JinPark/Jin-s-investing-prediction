"""NASDAQ multivariate time-series V6 research namespace.

V6 is deliberately isolated from every V1--V5 and Scenario artifact.  Modules
under this package may read protected predecessors for comparison, but writes
are restricted to the V6 namespace and explicitly registered V6 support files.
"""

from .isolation import (
    PROTECTED_ROOTS,
    V6_ALLOWED_PATHS,
    compare_manifests,
    create_protected_manifest,
    validate_v6_write_paths,
)

__all__ = [
    "PROTECTED_ROOTS",
    "V6_ALLOWED_PATHS",
    "compare_manifests",
    "create_protected_manifest",
    "validate_v6_write_paths",
]
