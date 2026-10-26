"""Explicit read compatibility for pre-calendar forecasts, never a migration.

The recorded old code hash stays on every old run. Compatibility is limited
to this gate-only revision: fourteen numerical dependencies remain byte exact
and the two edited modules retain their complete AST outside the named gates.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


def legacy_run_compatible(root: Path, run: dict) -> bool:
    path = root / "data/contracts/daily6m_calendar_gate_compatibility_v1.json"
    if not path.is_file():
        return False
    body = json.loads(path.read_text(encoding="utf-8"))
    if (body.get("compatibility_id") != "daily6m-calendar-gate-compatibility-v1"
            or run.get("model_code_hash") != body.get("legacy_model_code_hash")
            or run.get("contract_hash") != body.get("contract_hash")):
        return False
    for relative, digest in body["unchanged_files"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
            return False
    for relative, rule in body["unchanged_ast"].items():
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        tree.body = [node for node in tree.body
                     if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     or node.name != rule["excluded_function"]]
        if hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest() != rule["ast_sha256"]:
            return False
    return True
