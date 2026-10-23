"""Emit an auditable ready/pending decision without model or source writes."""
import argparse
import json
from pathlib import Path

from ai_fc.daily6m_readiness import check_daily6m_readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--as-of")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    options = parser.parse_args()
    try:
        report = check_daily6m_readiness(options.root, as_of=options.as_of)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        report = {"schema_version": 1, "ready": False, "status": "validation_failed",
                  "reasons": [str(exc)[:512]], "forecast_writes": False, "source_writes": False}
    raw = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(raw, encoding="utf-8")
    if options.github_output:
        with options.github_output.open("a", encoding="utf-8") as handle:
            handle.write("ready=" + str(report["ready"]).lower() + "\n")
    print(raw, end="")
    return 1 if report["status"] == "validation_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
