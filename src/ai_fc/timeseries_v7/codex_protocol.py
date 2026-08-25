"""One-task Codex envelope and result validation."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import PurePosixPath


REQUIRED={'schema_version','run_id','cycle_id','generation_id','task_key','task_type','worker_capability','objective','input_artifacts','protected_manifest_hash','allowed_paths','forbidden_paths','required_tests','acceptance_criteria','max_diff_lines','timeout_seconds','budget','secret_policy','stop_after_this_task'}


def validate_envelope(value:dict)->None:
    missing=REQUIRED-set(value)
    if missing:raise ValueError(f'missing envelope fields: {sorted(missing)}')
    if value['stop_after_this_task'] is not True:raise ValueError('one-task stop must be true')
    if value['worker_capability']!='codex_worker':raise ValueError('wrong worker capability')
    if not value['allowed_paths']:raise ValueError('empty allowlist')
    for path in value['allowed_paths']+value['forbidden_paths']:
        p=PurePosixPath(path)
        if p.is_absolute() or '..' in p.parts:raise ValueError('unsafe envelope path')
