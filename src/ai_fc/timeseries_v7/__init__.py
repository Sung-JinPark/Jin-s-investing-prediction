"""NASDAQ V7 research governance primitives.

V7 model training is intentionally absent until the predecessor protection and
contract-feasibility tasks have passed.
"""

from .protection import (
    ProtectedScopeError,
    build_protected_snapshot,
    compare_snapshots,
    create_baseline,
    verify_baseline,
)

__all__ = [
    "ProtectedScopeError",
    "build_protected_snapshot",
    "compare_snapshots",
    "create_baseline",
    "verify_baseline",
]
