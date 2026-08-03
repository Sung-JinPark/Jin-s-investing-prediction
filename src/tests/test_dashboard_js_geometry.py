from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def test_cross_asset_endpoint_labels_keep_minimum_gap() -> None:
    script_path = (
        Path(__file__).parents[1]
        / "ai_fc"
        / "dashboard_parts"
        / "dashboard.js"
    )
    source = script_path.read_text(encoding="utf-8")
    match = re.search(
        r"function resolveEndpointLabels\([\s\S]+?\n}\nfunction drawIndexedCompare",
        source,
    )
    assert match, "resolveEndpointLabels must remain a standalone testable helper"
    helper = match.group(0).removesuffix("\nfunction drawIndexedCompare")
    program = (
        helper
        + "\nconsole.log(JSON.stringify(resolveEndpointLabels("
        "[{key:'a',y:101},{key:'b',y:105},{key:'c',y:109}],16,40,200)))"
    )
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True
    )
    labels = json.loads(completed.stdout)
    ordered = sorted(item["labelY"] for item in labels)
    assert all(right - left >= 16 for left, right in zip(ordered, ordered[1:]))
    assert ordered[0] >= 40
    assert ordered[-1] <= 200
