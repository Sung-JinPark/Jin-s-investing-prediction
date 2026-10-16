"""One publication-loop probe: origin/main gate state + live site state.

Read-only by design: fetch/show against origin/main and an HTTPS GET of the
published data.json.  The local working tree is shared with parallel sessions
and is never touched.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request

ROOT = "C:/workspace/ai-investing"
LIVE_URL = "https://sung-jinpark.github.io/Jin-s-investing-prediction/data.json"


def show(path: str) -> str | None:
    out = subprocess.run(
        ["git", "-C", ROOT, "show", f"origin/main:{path}"], capture_output=True)
    return out.stdout.decode("utf-8") if out.returncode == 0 else None


def main() -> None:
    raw = show("data/timeseries_v8/multivariate_v8_latest.json")
    latest = json.loads(raw) if raw else {}
    gate = latest.get("gate") or {}
    forecasts = show("data/timeseries_v8/ledgers/shadow_forecasts.jsonl") or ""
    resolutions = show("data/timeseries_v8/ledgers/shadow_resolutions.jsonl") or ""
    live: dict[str, object]
    try:
        with urllib.request.urlopen(LIVE_URL, timeout=60) as response:
            payload = json.load(response)
        surface = payload.get("timeseries") or {}
        live = {
            "model_id": surface.get("model_id"),
            "status": surface.get("status"),
            "visible": surface.get("numbers_visible"),
        }
    except Exception as exc:  # the loop only logs; it never crashes on the probe
        live = {"error": str(exc)[:120]}
    print(json.dumps({
        "as_of": latest.get("as_of"),
        "status": latest.get("status"),
        "sealed_gate_pass": gate.get("sealed_gate_pass"),
        "operational_pass": gate.get("operational_pass"),
        "hold_reasons": len(gate.get("reasons") or []),
        "shadow_forecasts": sum(1 for line in forecasts.splitlines() if line.strip()),
        "shadow_resolutions": sum(1 for line in resolutions.splitlines() if line.strip()),
        "live": live,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
