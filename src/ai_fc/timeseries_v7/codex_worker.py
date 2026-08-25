"""Authorization checks for isolated Codex worktree results."""

from __future__ import annotations
import fnmatch
from .security import secret_name_matches


def validate_result_paths(changed_paths:list[str],allowed_patterns:list[str],forbidden_patterns:list[str])->dict[str,object]:
    unauthorized=[]
    for path in changed_paths:
        if any(fnmatch.fnmatch(path,pattern) for pattern in forbidden_patterns) or not any(fnmatch.fnmatch(path,pattern) for pattern in allowed_patterns):unauthorized.append(path)
    return {'pass':not unauthorized,'unauthorized_paths':sorted(unauthorized),'discard_diff':bool(unauthorized)}


def validate_secret_isolation(environment:dict[str,str])->dict[str,object]:
    matches=secret_name_matches(environment);return {'pass':not matches,'secret_names':matches}
