"""Publication decisions outside the frozen forecasting kernels."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

V13_POINTER = "data/timeseries_v13/vol/vol_latest.json"


def _v13_semantics(pointer: dict) -> dict:
    body = {key: value for key, value in pointer.items()
            if key not in {"knowledge_cutoff", "content_hash"}}
    body["freshness"] = {key: value for key, value in pointer.get("freshness", {}).items()
                         if key != "evaluated_at"}
    return body


def v13_pointer_changed(root: Path) -> bool:
    """Stage verified numerical/gate changes, not an evaluation clock tick.

    The workflow verifies the complete newly evaluated pointer first. Every
    input, probability, pin, origin, freshness status and gate remains in this
    comparison. Existing pointer bytes and every ledger remain untouched.
    """
    current = json.loads((root / V13_POINTER).read_text(encoding="utf-8"))
    previous = subprocess.run(["git", "show", "HEAD:" + V13_POINTER], cwd=root,
                              capture_output=True, check=False)
    if previous.returncode:
        # A first publication must be staged. Repository/push failures still
        # fail the enclosing workflow rather than reporting a no-op.
        return True
    return _v13_semantics(json.loads(previous.stdout)) != _v13_semantics(current)
