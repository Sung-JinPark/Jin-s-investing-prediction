from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_fc.timeseries_v6.public_archive import collect_public_archives


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/timeseries_v6/manifests/public_archive_latest.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = collect_public_archives(root)
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"content_hash": result["content_hash"], "sources": len(result["partitions"]), "rows": sum(row["row_count"] for row in result["partitions"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
