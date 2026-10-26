"""mts_research 자체 CLI — 공유 ai_fc/cli.py 를 건드리지 않는다 (§20.1).

사용: cd src && python -m ai_fc.mts_research.cli <verb> [...]
exit code: 0 성공 · 2 검증 차단 · 3 scope 거부 · 4 전제 부족.
쓰기는 data/mts_research/ + docs/research/mts_upgrade/ 아래만.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _root(value: str | None) -> Path:
    if value:
        return Path(value).resolve()
    return Path(__file__).resolve().parents[3]


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cmd_inventory(args: argparse.Namespace) -> int:
    """read-only §17.1 조사 — 존재·크기·행수·환경. payload 스캔 없음."""
    root = _root(args.root)
    from .snapshots import environment_lock_hash

    paths = [
        "docs/design/mts_program_blueprint_v1_260909.md",
        "docs/MODEL_REGISTRY.md",
        "data/contracts/multivariate_timeseries_v8.yaml",
        "data/contracts/multivariate_timeseries_v13_vol.yaml",
        "data/contracts/multivariate_timeseries_v14_conditional.yaml",
        "data/contracts/timeseries_daily6m_v1.yaml",
        "src/ai_fc/timeseries_v8/model.py",
        "src/ai_fc/timeseries_v8/backtest.py",
        "src/ai_fc/timeseries_v8/pipeline.py",
        "data/timeseries_v13/vol/champion_coefficients.json",
        "data/timeseries_v13/ledgers/vol_live.jsonl",
        "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl",
        "data/timeseries_v2/ledgers/market_observations.jsonl",
    ]
    table = {}
    for relative in paths:
        path = root / relative
        entry: dict[str, Any] = {"exists": path.is_file()}
        if path.is_file():
            entry["bytes"] = path.stat().st_size
            if path.suffix == ".jsonl":
                entry["rows"] = sum(
                    1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
                )
        table[relative] = entry
    _emit({
        "root": str(root),
        "environment_lock_hash": environment_lock_hash(),
        "paths": table,
        "full_inventory": "docs/research/mts_upgrade/repository_inventory.md",
    })
    return 0


def cmd_validate_contract(args: argparse.Namespace) -> int:
    root = _root(args.root)
    from .contracts import load_research_contract, validate_for

    contract, conflicts = load_research_contract(Path(args.contract), root)
    report = validate_for(args.action, contract, root=root, conflicts=conflicts)
    _emit(report.model_dump(mode="json"))
    return 0 if report.ok else 2


def cmd_audit_time(args: argparse.Namespace) -> int:
    """scope 가드 선행 — 읽은 데이터만 숫자, 나머지 NOT_RUN (§19.3)."""
    root = _root(args.root)
    from . import artifacts
    from .audits.time_audit import build_report
    from .contracts import DRAFT_CONTRACT_RELATIVE, MtsScopeError, load_research_contract, read_scope_guard

    contract, _ = load_research_contract(root / DRAFT_CONTRACT_RELATIVE, root)
    try:
        read_scope_guard(
            root, contract,
            requested_series={"NASDAQCOM", "VIX", "DGS2", "DGS10", "DTWEXB", "DTWEXBGS", "FED_EBP"},
            requested_window=("1995-01-01", None),
            purpose="audit",
            run_id=f"audit-time-{_now().date().isoformat()}",
            record_exposure=artifacts.record_exposure,
        )
    except MtsScopeError as exc:
        _emit({"status": "SCOPE_REFUSED", "detail": str(exc)})
        return 3
    report = build_report(root)
    _emit({
        "status": "MEASURED",
        "output": "data/mts_research/derived/data_time_audit.json",
        "t12": report["dollar_splice"].get("t12_verdict"),
        "t13": report["dollar_splice"].get("t13_verdict"),
    })
    return 0


def cmd_replay_baseline(args: argparse.Namespace) -> int:
    """W2 identity replay — baseline_identity.json 생성 (T49)."""
    root = _root(args.root)
    from .adapters.report import build_baseline_identity_report

    tier2 = None
    tier2_path = root / "data/mts_research/derived/v8_tier2_replay.json"
    if tier2_path.is_file():
        tier2 = json.loads(tier2_path.read_text(encoding="utf-8"))
    report = build_baseline_identity_report(
        root, now=_now(), run_id=f"replay-baseline-{_now().date().isoformat()}", tier2=tier2
    )
    _emit({
        "pb_identity": report["verdict"]["pb_identity"],
        "v8_tier1_identity": report["verdict"]["v8_tier1_identity"],
        "v8_tier2": report["v8_tier2"].get("status"),
        "output": "docs/research/mts_upgrade/baseline_identity.json",
    })
    return 0 if report["verdict"]["pb_identity"] and report["verdict"]["v8_tier1_identity"] else 2


def cmd_plan_experiment(args: argparse.Namespace) -> int:
    root = _root(args.root)
    from .contracts import DRAFT_CONTRACT_RELATIVE, load_research_contract, validate_for

    contract, conflicts = load_research_contract(root / DRAFT_CONTRACT_RELATIVE, root)
    report = validate_for("dry_run", contract, root=root, conflicts=conflicts)
    _emit({
        "state": contract.state,
        "mode": contract.execution.mode,
        "enabled_experiments": list(contract.execution.enabled_experiments),
        "blockers": list(report.blockers),
        "plan": "등록된 실험 없음 — 계약 동결·예산 영수증 후 W7" if not report.ok else "n/a",
    })
    return 0 if report.ok else 4


def cmd_run_experiment(args: argparse.Namespace) -> int:
    """--dry-run: 코호트·권한·예산 검증만 — 보호 payload read·fit·예산 소모 없음 (§20.1)."""
    root = _root(args.root)
    from .contracts import DRAFT_CONTRACT_RELATIVE, load_research_contract, validate_for

    contract, conflicts = load_research_contract(root / DRAFT_CONTRACT_RELATIVE, root)
    if not args.dry_run:
        report = validate_for("run", contract, root=root, conflicts=conflicts)
        _emit({"status": "REFUSED", "blockers": list(report.blockers)})
        return 2  # draft/audit_only 에서 실제 실행은 거부 (T55 경로)
    report = validate_for("dry_run", contract, root=root, conflicts=conflicts)
    _emit({
        "status": "DRY_RUN",
        "ok": report.ok,
        "blockers": list(report.blockers),
        "budget_consumed": 0,
        "protected_payload_read": 0,
    })
    return 0 if report.ok else 4


def cmd_evaluate(args: argparse.Namespace) -> int:
    """라벨 read scope 영수증 필수 — 없으면 구체적 결핍으로 거부."""
    root = _root(args.root)
    from .contracts import DRAFT_CONTRACT_RELATIVE, load_research_contract, validate_for

    contract, conflicts = load_research_contract(root / DRAFT_CONTRACT_RELATIVE, root)
    report = validate_for("evaluate", contract, root=root, conflicts=conflicts)
    _emit({
        "status": "REFUSED" if not report.ok else "READY",
        "experiment_id": args.experiment_id,
        "blockers": list(report.blockers),
    })
    return 0 if report.ok else 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_fc.mts_research.cli")
    parser.add_argument("--root", default=None, help="저장소 루트 (기본: 패키지 기준 자동)")
    subparsers = parser.add_subparsers(dest="verb", required=True)

    subparsers.add_parser("inventory").set_defaults(func=cmd_inventory)
    validate = subparsers.add_parser("validate-contract")
    validate.add_argument("--contract", required=True)
    validate.add_argument("--action", default="validate",
                          choices=["validate", "audit", "dry_run", "run", "evaluate"])
    validate.set_defaults(func=cmd_validate_contract)
    subparsers.add_parser("audit-time").set_defaults(func=cmd_audit_time)
    subparsers.add_parser("replay-baseline").set_defaults(func=cmd_replay_baseline)
    subparsers.add_parser("plan-experiment").set_defaults(func=cmd_plan_experiment)
    run = subparsers.add_parser("run-experiment")
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run_experiment)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--experiment-id", required=True)
    evaluate.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
