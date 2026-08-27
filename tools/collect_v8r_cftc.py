from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_fc.timeseries_v8r.cftc_cot import (
    collect_to_repository,
    verify_repository_collection,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args()
    if args.verify_only:
        result = verify_repository_collection(args.repo_root)
        if args.verification_output:
            output = args.verification_output
            if not output.is_absolute():
                output = args.repo_root / output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result["pass"] else 2
    print(json.dumps(collect_to_repository(args.repo_root), ensure_ascii=False,
                     sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
