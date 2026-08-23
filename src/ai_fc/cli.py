"""ai-fc CLI 진입점.

사용: python -m ai_fc <command>  (src/ 디렉터리에서, 또는 PYTHONPATH=src)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import typer

from . import config
from .db import ingest, queries
from .registry import compute_due, load_registry, propose_schedule
from .scenario import refresh_scenario

app = typer.Typer(add_completion=False, help="AI Superforecaster P1 scaffold")


def _timeseries_exit(callable_, *args, **kwargs):
    """Render fail-closed research pipeline errors without leaking credentials."""
    from .timeseries.artifact import TimeSeriesArtifactError
    from .timeseries.model import TimeSeriesModelError
    from .timeseries.pipeline import TimeSeriesPipelineError

    try:
        return callable_(*args, **kwargs)
    except (OSError, ValueError, RuntimeError, TimeSeriesArtifactError,
            TimeSeriesModelError, TimeSeriesPipelineError) as exc:
        typer.echo(f"시계열 연구모델 중단: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("timeseries-bootstrap")
def cmd_timeseries_bootstrap() -> None:
    """ALFRED 전체 빈티지를 raw-first append-only 원장으로 최초 백필한다."""
    from .timeseries.pipeline import bootstrap_timeseries

    result = _timeseries_exit(
        bootstrap_timeseries, config.ROOT, api_key=os.environ.get("FRED_API_KEY", ""),
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("timeseries-refresh")
def cmd_timeseries_refresh() -> None:
    """ALFRED 신규 원문과 수정 빈티지를 append한다."""
    from .timeseries.pipeline import refresh_timeseries

    result = _timeseries_exit(
        refresh_timeseries, config.ROOT, api_key=os.environ.get("FRED_API_KEY", ""),
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("timeseries-fit")
def cmd_timeseries_fit(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
) -> None:
    """PIT DFM과 확장·10년 Ridge VARX를 적합한다."""
    from .timeseries.pipeline import fit_timeseries

    result = _timeseries_exit(
        fit_timeseries, config.ROOT, knowledge_cutoff=knowledge_cutoff,
    )
    typer.echo(f"fit: {result['run_id']} · {result['as_of']} · {result['status']}")


@app.command("timeseries-backtest")
def cmd_timeseries_backtest(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
    path_count: int = typer.Option(20000, "--path-count", min=20000, max=20000),
) -> None:
    """2007년 이후 purged rolling-origin 평가를 실행한다."""
    from .timeseries.pipeline import backtest_timeseries

    result = _timeseries_exit(
        backtest_timeseries,
        config.ROOT,
        knowledge_cutoff=knowledge_cutoff,
        path_count=path_count,
    )
    typer.echo(
        f"backtest: {result['run_id']} · gate={result['summary']['status']} · "
        f"origins={result['summary']['origin_count']}"
    )


@app.command("timeseries-forecast")
def cmd_timeseries_forecast(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
) -> None:
    """검증 Gate를 통과한 경우에만 최신 1·5·21·63일 분포를 append한다."""
    from .timeseries.pipeline import forecast_timeseries

    path, result = _timeseries_exit(
        forecast_timeseries, config.ROOT, knowledge_cutoff=knowledge_cutoff,
    )
    typer.echo(
        f"forecast: {path.relative_to(config.ROOT)} · "
        f"display={result['display_state']} · numbers={result['publication']['customer_numbers_visible']}"
    )


@app.command("timeseries-resolve")
def cmd_timeseries_resolve(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
) -> None:
    """성숙한 shadow 예측의 실제 결과를 append-only 해소 원장에 기록한다."""
    from .timeseries.pipeline import resolve_timeseries

    result = _timeseries_exit(
        resolve_timeseries, config.ROOT, knowledge_cutoff=knowledge_cutoff,
    )
    typer.echo(json.dumps(result, ensure_ascii=False))


@app.command("timeseries-verify")
def cmd_timeseries_verify() -> None:
    """latest pointer·content hash·확률 단위·PIT 표시 Gate를 검증한다."""
    from .timeseries.pipeline import verify_timeseries

    result = _timeseries_exit(verify_timeseries, config.ROOT)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("timeseries-workbook")
def cmd_timeseries_workbook() -> None:
    """JSONL 정본과 Parquet read model을 대사한 8-sheet Excel 감사본을 생성한다."""
    from .timeseries.workbook import export_timeseries_workbook

    path, summary = _timeseries_exit(export_timeseries_workbook, config.ROOT)
    typer.echo(
        f"workbook: {path.relative_to(config.ROOT)} · sheets={summary['sheets']} · "
        f"observations={summary['observations']} · sha256={summary['sha256']}"
    )


@app.command("timeseries-v2-bootstrap")
def cmd_timeseries_v2_bootstrap() -> None:
    """공식 시장 아카이브를 raw-first V2 원장으로 최초 백필한다."""
    from .timeseries_v2.pipeline import bootstrap_timeseries_v2

    result = _timeseries_exit(bootstrap_timeseries_v2, config.ROOT)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("timeseries-v2-refresh")
def cmd_timeseries_v2_refresh() -> None:
    """공식 시장 아카이브의 신규 관측·수정치를 V2에 append한다."""
    from .timeseries_v2.pipeline import refresh_timeseries_v2

    result = _timeseries_exit(refresh_timeseries_v2, config.ROOT)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("timeseries-v2-prepare")
def cmd_timeseries_v2_prepare(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
    max_dfm_cutoffs: int | None = typer.Option(None, "--max-dfm-cutoffs", min=1),
) -> None:
    """ALFRED 원점별 DFM 캐시와 공식 시장 표본을 준비한다."""
    from .timeseries_v2.pipeline import prepare_timeseries_v2

    result = _timeseries_exit(
        prepare_timeseries_v2, config.ROOT,
        knowledge_cutoff=knowledge_cutoff, max_dfm_cutoffs=max_dfm_cutoffs,
    )
    if isinstance(result.get("dfm"), dict):
        result["dfm"] = {
            key: value for key, value in result["dfm"].items() if key != "entries"
        }
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("timeseries-v2-backtest")
def cmd_timeseries_v2_backtest(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
    path_count: int = typer.Option(20000, "--path-count", min=20000, max=20000),
) -> None:
    """동결 후보 C1~C5 개발 선택과 2019+ 봉인 평가를 한 번 실행한다."""
    from .timeseries_v2.pipeline import backtest_timeseries_v2

    result = _timeseries_exit(
        backtest_timeseries_v2, config.ROOT, knowledge_cutoff=knowledge_cutoff,
        path_count=path_count,
    )
    typer.echo(json.dumps({
        "run_id": result["run_id"], "selected_candidate": result["selected_candidate"],
        "gate_pass": result["summary"]["gate_pass"],
        "reasons": result["summary"]["reasons"],
    }, ensure_ascii=False, indent=2))


@app.command("timeseries-v2-monitor-backtest")
def cmd_timeseries_v2_monitor_backtest(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
    path_count: int = typer.Option(1000, "--path-count", min=200, max=20000),
) -> None:
    """봉인된 승자를 바꾸지 않고 월간 워크포워드 성능만 갱신한다."""
    from .timeseries_v2.pipeline import monitor_backtest_timeseries_v2

    result = _timeseries_exit(
        monitor_backtest_timeseries_v2, config.ROOT,
        knowledge_cutoff=knowledge_cutoff, path_count=path_count,
    )
    typer.echo(json.dumps({
        "run_id": result["run_id"], "selected_candidate": result["selected_candidate"],
        "gate_pass": result["summary"]["gate_pass"],
        "candidate_selection_reopened": result["candidate_selection_reopened"],
    }, ensure_ascii=False, indent=2))


@app.command("timeseries-v2-fit")
def cmd_timeseries_v2_fit(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
) -> None:
    """선택이 봉인된 V2 핵심 후보를 주간 재적합한다."""
    from .timeseries_v2.pipeline import fit_timeseries_v2

    result = _timeseries_exit(
        fit_timeseries_v2, config.ROOT, knowledge_cutoff=knowledge_cutoff,
    )
    typer.echo(json.dumps({
        "run_id": result["run_id"], "candidate_id": result["candidate_id"],
        "as_of": result["as_of"], "backtest_gate_pass": result["backtest_gate_pass"],
    }, ensure_ascii=False, indent=2))


@app.command("timeseries-v2-forecast")
def cmd_timeseries_v2_forecast(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
    ralph_run_id: str | None = typer.Option(None, "--ralph-run-id"),
) -> None:
    """봉인 Gate 통과 시에만 V2 연구 숫자를 append·공개한다."""
    from .timeseries_v2.pipeline import forecast_timeseries_v2

    path, result = _timeseries_exit(
        forecast_timeseries_v2, config.ROOT,
        knowledge_cutoff=knowledge_cutoff, ralph_run_id=ralph_run_id,
    )
    typer.echo(json.dumps({
        "path": path.relative_to(config.ROOT).as_posix(),
        "display_state": result["display_state"],
        "numbers_visible": result["publication"]["customer_numbers_visible"],
    }, ensure_ascii=False, indent=2))


@app.command("timeseries-v2-verify")
def cmd_timeseries_v2_verify() -> None:
    """V2 계보·PIT 캐시·봉인·공개 상태를 fail-closed 검증한다."""
    from .timeseries_v2.pipeline import verify_timeseries_v2

    result = _timeseries_exit(verify_timeseries_v2, config.ROOT)
    # Ralph release gate requires an explicit final boolean, not inference from status.
    result["publication_gate_pass"] = bool(
        result["ok"] and result["sealed_disclosed"] and result["numbers_visible"]
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("timeseries-v2-preflight")
def cmd_timeseries_v2_preflight(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
) -> None:
    """봉인 구간을 열지 않는 Ralph용 제한 계산 백테스트를 실행한다."""
    from .timeseries_v2.pipeline import quick_backtest_timeseries_v2

    result = _timeseries_exit(
        quick_backtest_timeseries_v2, config.ROOT, knowledge_cutoff=knowledge_cutoff,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("timeseries-v2-resolve")
def cmd_timeseries_v2_resolve(
    knowledge_cutoff: str | None = typer.Option(None, "--knowledge-cutoff"),
) -> None:
    """성숙한 V2 shadow 예측을 실제 NASDAQ 결과로 append-only 해소한다."""
    from .timeseries_v2.pipeline import resolve_timeseries_v2

    result = _timeseries_exit(
        resolve_timeseries_v2, config.ROOT, knowledge_cutoff=knowledge_cutoff,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("timeseries-v2-workbook")
def cmd_timeseries_v2_workbook() -> None:
    """V2 정본과 모델·봉인·Ralph 계보를 8-sheet 검토본으로 생성한다."""
    from .timeseries_v2.workbook import export_timeseries_v2_workbook

    path, summary = _timeseries_exit(export_timeseries_v2_workbook, config.ROOT)
    typer.echo(json.dumps({
        "path": path.relative_to(config.ROOT).as_posix(), **summary,
    }, ensure_ascii=False, indent=2))


@app.command("timeseries-v3-backtest")
def cmd_timeseries_v3_backtest(
    sample_count: int | None = typer.Option(
        None, "--sample-count", min=200,
        help="Research diagnostics only; omitted uses the frozen contract count.",
    ),
    bootstrap_iterations: int = typer.Option(
        1000, "--bootstrap-iterations", min=100, max=10000,
    ),
) -> None:
    """Run the fixed-comparator V3 pseudo-OOS research evaluation."""
    from .timeseries_v3.pipeline import run_research_backtest

    result = _timeseries_exit(
        run_research_backtest, config.ROOT,
        sample_count=sample_count, bootstrap_iterations=bootstrap_iterations,
    )
    typer.echo(json.dumps({
        "run_id": result["run_id"],
        "gate_pass": result["research_gate"]["pass"],
        "reasons": result["research_gate"]["reasons"],
        "origin_count": result["origin_count"],
        "customer_numbers_visible": False,
    }, ensure_ascii=False, indent=2))


@app.command("timeseries-v3-forecast")
def cmd_timeseries_v3_forecast() -> None:
    """Append a non-public V3 validation forecast without changing customer UI."""
    from .timeseries_v3.pipeline import build_latest_shadow

    result = _timeseries_exit(build_latest_shadow, config.ROOT)
    typer.echo(json.dumps({
        "forecast_id": result["forecast"]["forecast_id"],
        "display_state": result["latest"]["display_state"],
        "research_gate_pass": result["forecast"]["research_gate_pass"],
        "customer_numbers_visible": result["latest"]["customer_numbers_visible"],
    }, ensure_ascii=False, indent=2))


@app.command("timeseries-v3-verify")
def cmd_timeseries_v3_verify() -> None:
    """Verify V2 immutability and V3 fail-closed publication controls."""
    from .timeseries_v3.pipeline import verify_v3

    result = _timeseries_exit(verify_v3, config.ROOT)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("timeseries-v3-workbook")
def cmd_timeseries_v3_workbook() -> None:
    """Export the deterministic eight-sheet V3 audit workbook."""
    from .timeseries_v3.workbook import export_timeseries_v3_workbook

    path, summary = _timeseries_exit(export_timeseries_v3_workbook, config.ROOT)
    typer.echo(json.dumps({
        "path": path.relative_to(config.ROOT).as_posix(), **summary,
    }, ensure_ascii=False, indent=2))


@app.command("timeseries-v4-collect")
def cmd_timeseries_v4_collect(
    volume_start_year: int = typer.Option(2009, "--volume-start-year", min=2009),
) -> None:
    """Collect the V4 official/public market and expectation archives raw-first."""
    from .timeseries_v4.source_store import collect_v4_sources, export_v4_parquet

    result = _timeseries_exit(
        collect_v4_sources, config.ROOT, volume_start_year=volume_start_year,
    )
    if result.get("ok"):
        result["parquet"] = _timeseries_exit(export_v4_parquet, config.ROOT)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("timeseries-v4-verify-sources")
def cmd_timeseries_v4_verify_sources() -> None:
    """Verify every V4 receipt, raw blob and append-only observation link."""
    from .timeseries_v4.source_store import verify_v4_source_store

    result = _timeseries_exit(verify_v4_source_store, config.ROOT)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("timeseries-v4-backtest")
def cmd_timeseries_v4_backtest(
    bootstrap_iterations: int = typer.Option(1000, "--bootstrap-iterations", min=100),
) -> None:
    """Run the exact predecessor replay and V4 PIT distributional Gate."""
    from .timeseries_v4.pipeline import run_v4_backtest

    result = _timeseries_exit(
        run_v4_backtest, config.ROOT, bootstrap_iterations=bootstrap_iterations,
    )
    typer.echo(json.dumps({
        "run_id": result["run_id"],
        "status": result["status"],
        "research_gate": result["research_gate"],
        "customer_numbers_visible": False,
    }, ensure_ascii=False, indent=2))


@app.command("timeseries-v4-verify")
def cmd_timeseries_v4_verify() -> None:
    """Verify V4 hashes, lineage, predecessor identity and fail-closed state."""
    from .timeseries_v4.pipeline import verify_v4_run

    result = _timeseries_exit(verify_v4_run, config.ROOT)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise typer.Exit(code=1)


@app.command("audit-ledgers")
def cmd_audit_ledgers(
    check: bool = typer.Option(False, "--check", help="Do not rewrite baseline/report files"),
) -> None:
    """Audit every registered append/archive ledger for growth and integrity."""
    from .ledger_audit import audit_ledgers, has_violations

    report = audit_ledgers(config.ROOT, write=not check)
    summary = report["summary"]
    typer.echo(
        "ledger audit: "
        f"accumulating={summary['accumulating']} stalled={summary['stalled']} "
        f"inactive={summary['inactive']} violation={summary['violation']} "
        f"planned={summary['planned']}"
    )
    if has_violations(report):
        raise typer.Exit(code=1)


@app.command("export-research-pack")
def cmd_export_research_pack(
    month: str | None = typer.Option(None, "--month", help="Pack month in YYYY-MM"),
) -> None:
    """Export registered ledgers to an immutable monthly Parquet research pack."""
    from .research_pack import ResearchPackError, export_research_pack

    try:
        path = export_research_pack(config.ROOT, month)
    except ResearchPackError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"research pack: {path.relative_to(config.ROOT)}")


def _conn(root: Path):
    return ingest.connect(root / "db" / "index.db")


def _sync_or_exit(conn, root: Path) -> None:
    report = ingest.sync(conn, root, strict=True)
    if not report.ok:
        typer.echo(report.summary(), err=True)
        raise typer.Exit(code=1)


@app.command("provider-guard")
def cmd_provider_guard() -> None:
    """CI-safe check that official provider config has an exact human approval."""
    from .provider_governance import assert_official_provider_allowed

    snapshot = (
        config.OPENAI_OFFICIAL_MODEL
        if config.OFFICIAL_LLM_PROVIDER == "openai"
        else config.REASONING_MODEL
    )
    try:
        assert_official_provider_allowed(
            config.ROOT, config.OFFICIAL_LLM_PROVIDER, snapshot
        )
    except (PermissionError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"official provider approved: {config.OFFICIAL_LLM_PROVIDER}:{snapshot}")


@app.command("openai-smoke")
def cmd_openai_smoke(
    model: str | None = typer.Option(
        None, "--model", help="승인된 OpenAI tier/snapshot (기본: 환경 설정)"
    ),
) -> None:
    """최소 유료 호출로 OpenAI 키·모델·비용 원장 연결을 검증한다."""
    from .llm import PipelineBudget
    from .llm_provider import OpenAIResponsesProvider
    from .provider_governance import assert_official_provider_allowed

    root = config.ROOT
    selected = (model or config.OPENAI_OFFICIAL_MODEL).strip()
    if not selected:
        typer.echo("AI_FC_OPENAI_OFFICIAL_MODEL 또는 --model이 필요합니다.", err=True)
        raise typer.Exit(code=2)
    try:
        assert_official_provider_allowed(root, "openai", selected)
    except (PermissionError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    conn = _conn(root)
    _sync_or_exit(conn, root)
    now = datetime.now(ZoneInfo(config.TZ_NAME))
    provider_spend = queries.month_cost(conn, now.year, now.month, "openai")
    if provider_spend >= config.OPENAI_MONTHLY_BUDGET:
        typer.echo(
            f"OpenAI 월 예산 초과: ${provider_spend:.2f} >= "
            f"${config.OPENAI_MONTHLY_BUDGET:.2f}",
            err=True,
        )
        raise typer.Exit(code=1)

    provider = OpenAIResponsesProvider(model=selected, role="official")
    _text, usage = provider.smoke(PipelineBudget(limit_usd=0.10))
    queries.log_cost(
        conn,
        "_system",
        "smoke",
        selected,
        usage.input_tokens,
        usage.output_tokens,
        usage.cost_usd,
        provider="openai",
        snapshot=selected,
        request_id=usage.request_id,
        cached_input_tokens=usage.cached_input_tokens,
        web_search_calls=usage.web_search_calls,
        ledger_path=root / "calibration" / "cost_log.csv",
    )
    typer.echo(
        f"OpenAI 연결 정상 · model={selected} · "
        f"tokens={usage.input_tokens}+{usage.output_tokens} · "
        f"estimated_cost=${usage.cost_usd:.6f}"
    )


@app.command("security-check")
def cmd_security_check() -> None:
    """Fail CI when a source artifact resembles a committed API credential."""
    from .security_audit import scan

    findings = scan(config.ROOT)
    if findings:
        typer.echo("secret-like values found:\n" + "\n".join(findings), err=True)
        raise typer.Exit(code=1)
    typer.echo("secret pattern scan clean")


@app.command("scenario")
def cmd_scenario(
    asof: str | None = typer.Option(
        None, "--asof", help="이 날짜까지의 마지막 확정 일봉으로 생성 (YYYY-MM-DD)"),
    force: bool = typer.Option(
        False, "--force", help="같은 시장 기준일이어도 스냅샷을 다시 생성"),
) -> None:
    """NASDAQ 시장 맵 시나리오를 공개 확정 일봉에서 재생성한다."""
    try:
        cutoff = date.fromisoformat(asof) if asof else None
    except ValueError as exc:
        raise typer.BadParameter("--asof는 YYYY-MM-DD 형식이어야 합니다.") from exc
    path, payload, changed = refresh_scenario(config.ROOT, asof=cutoff, force=force)
    state = "갱신" if changed else "변경 없음"
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} · 시장 기준 {payload['asof']} · "
        f"S1/S2/S3 {payload['paths']['S1']['prob']}/"
        f"{payload['paths']['S2']['prob']}/{payload['paths']['S3']['prob']}%"
    )


@app.command("scenario-structure")
def cmd_scenario_structure() -> None:
    """기존 분포를 재모의하지 않고 DB 조건부 연도별 구조 경로를 추가한다."""
    from .scenario import upgrade_scenario_structure

    path, payload, changed = upgrade_scenario_structure(config.ROOT)
    state = "갱신" if changed else "변경 없음"
    years = payload["structural_forecast"]["years"]
    diagnostics = ", ".join(
        f"{row['year']} S1 {row['path_diagnostics']['S1']['max_drawdown_pct']}%"
        for row in years
    )
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} · 시장 기준 {payload['asof']} · "
        f"DB 구조 경로 {diagnostics}"
    )


@app.command("scenario-v5-build")
def cmd_scenario_v5_build(
    force: bool = typer.Option(False, "--force", help="Rewrite even when inputs are unchanged"),
) -> None:
    """Build the additive Evidence-Conditioned Scenario V5 research candidate."""
    from .scenario_v5.artifact import ScenarioV5Error, build_candidate
    from .scenario_v5.audit import build_reports, capture_protected_baseline

    capture_protected_baseline(config.ROOT)
    try:
        path, payload, changed = build_candidate(config.ROOT, force=force)
        build_reports(config.ROOT)
    except (ScenarioV5Error, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        typer.echo(f"Scenario V5 build blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    state = "updated" if changed else "no-op"
    scenarios = payload["conditional_distribution"]["scenarios"]
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} | "
        f"S1/S2/S3={scenarios['S1']['probability']:.4f}/"
        f"{scenarios['S2']['probability']:.4f}/{scenarios['S3']['probability']:.4f} | "
        f"ESS={payload['posterior_diagnostics']['effective_sample_size']:.1f} | "
        "RESEARCH CANDIDATE - NOT OFFICIAL - NOT CHAMPION"
    )


@app.command("scenario-v5-verify")
def cmd_scenario_v5_verify(
    path: Path | None = typer.Option(None, "--path", help="Candidate JSON to verify"),
) -> None:
    """Verify V5 schema, probability, provenance, and source-snapshot integrity."""
    from .scenario_v5.artifact import verify_candidate

    result = verify_candidate(config.ROOT, path)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("scenario-v5-1-build")
def cmd_scenario_v5_1_build(
    force: bool = typer.Option(False, "--force", help="Rewrite even when model content is unchanged"),
) -> None:
    """Build the additive, fail-closed Scenario V5.1 research candidate."""
    from .scenario_v5.hardening import ScenarioV51Error, build_candidate_v5_1

    try:
        path, payload, changed = build_candidate_v5_1(config.ROOT, force=force)
    except (ScenarioV51Error, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        typer.echo(f"Scenario V5.1 build blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    state = "updated" if changed else "model-content no-op"
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} | "
        f"model={payload['model_content_sha256']} | "
        f"receipt={payload['build_receipt_sha256']} | "
        "RESEARCH CANDIDATE - NOT OFFICIAL"
    )


@app.command("scenario-v5-1-verify")
def cmd_scenario_v5_1_verify(
    path: Path | None = typer.Option(None, "--path", help="Candidate JSON to verify"),
) -> None:
    """Verify V5.1 schema, replay, source hashes, and circularity gates."""
    from .scenario_v5.hardening import verify_candidate_v5_1

    result = verify_candidate_v5_1(config.ROOT, path)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("scenario-v5-2-build")
def cmd_scenario_v5_2_build(
    force: bool = typer.Option(False, "--force", help="Rewrite even when model content is unchanged"),
) -> None:
    """Build the macro-actualized historical-shape research candidate."""
    from .scenario_v5_2 import build_candidate
    from .scenario_v5_2.engine import ScenarioV52Error

    try:
        path, payload, changed = build_candidate(config.ROOT, force=force)
    except (ScenarioV52Error, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        typer.echo(f"Scenario V5.2 build blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    state = "updated" if changed else "model-content no-op"
    probabilities = payload["ablations"]["full_evidence"]["probabilities"]
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} | "
        f"model={payload['model_content_sha256']} | "
        f"P(-10% touch)={probabilities['first_touch_minus_10_by_october_end']:.4f} | "
        "RESEARCH CANDIDATE - NOT OFFICIAL - NOT CHAMPION"
    )


@app.command("scenario-v5-2-verify")
def cmd_scenario_v5_2_verify(
    path: Path | None = typer.Option(None, "--path", help="Candidate JSON to verify"),
    replay: bool = typer.Option(True, "--replay/--no-replay", help="Regenerate deterministic model output"),
) -> None:
    """Verify V5.2 PIT, replay, probability, circularity, and display gates."""
    from .scenario_v5_2 import verify_candidate

    result = verify_candidate(config.ROOT, path, replay=replay)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("scenario-v5-2-learn-event")
def cmd_scenario_v5_2_learn_event(
    input_path: Path = typer.Option(..., "--input", help="Normalized event JSON"),
) -> None:
    """Append one PIT-safe macro event, rebuild V5.2, and refresh both dashboards."""
    from . import dashboard as dash
    from .scenario_v5_2.event_learning import EventLearningError, learn_event

    resolved = input_path if input_path.is_absolute() else config.ROOT / input_path
    try:
        receipt = learn_event(config.ROOT, resolved)
        conn = _conn(config.ROOT)
        try:
            dashboard_path = dash.write_dashboard(conn, config.ROOT)
        finally:
            conn.close()
    except (EventLearningError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        typer.echo(f"Scenario V5.2 event learning blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    receipt["repository_dashboard_path"] = dashboard_path.relative_to(config.ROOT).as_posix()
    typer.echo(json.dumps(receipt, ensure_ascii=False, indent=2))


@app.command("scenario-v5-backtest")
def cmd_scenario_v5_backtest() -> None:
    """Materialize the PIT-safe rolling-origin framework without fabricated scores."""
    from .scenario_v5.audit import rolling_origin_framework

    path = rolling_origin_framework(config.ROOT)
    typer.echo(
        f"framework only: {path.relative_to(config.ROOT)} | "
        "promotion blocked pending approved PIT rolling origins"
    )


@app.command("scenario-v5-report-views")
def cmd_scenario_v5_report_views() -> None:
    """Print every V5 evidence view and its numerical-use decision."""
    from .scenario_v5.audit import report_views

    payload = report_views(config.ROOT)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] != "ok":
        raise typer.Exit(code=1)


@app.command("scenario-v4-shadow")
def cmd_scenario_v4_shadow() -> None:
    """Build the RCFHS-SB v1 candidate as a shadow artifact only."""
    from .scenario_v4_shadow import refresh_shadow

    path, payload, changed = refresh_shadow(config.ROOT)
    state = "updated" if changed else "unchanged"
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} · source "
        f"{payload.get('source_snapshot_id')} · promotion {payload['promotion_state']}"
    )


@app.command("cross-asset")
def cmd_cross_asset(
    asof: str | None = typer.Option(
        None, "--asof", help="이 날짜까지의 마지막 공통 확정 일봉 (YYYY-MM-DD)"),
    force: bool = typer.Option(
        False, "--force", help="같은 시장 기준일이어도 스냅샷을 다시 생성"),
) -> None:
    """닷컴기 실측축과 BTC 반사실 민감도를 공개 가격에서 재생성한다."""
    from .cross_asset import refresh_cross_asset

    try:
        cutoff = date.fromisoformat(asof) if asof else None
    except ValueError as exc:
        raise typer.BadParameter("--asof는 YYYY-MM-DD 형식이어야 합니다.") from exc
    path, payload, changed = refresh_cross_asset(
        config.ROOT, asof=cutoff, force=force)
    state = "갱신" if changed else "변경 없음"
    metrics = payload["diagnostics"]["corr_60d"]
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} · 공통 시장 기준 {payload['asof']} · "
        f"60일 corr BTC/NDX {metrics['bitcoin_nasdaq']} · O/NDX "
        f"{metrics['realty_income_nasdaq']}"
    )


@app.command("o-entry-cohort")
def cmd_o_entry_cohort(
    asof: str | None = typer.Option(
        None, "--asof", help="이 날짜까지 완결된 O cohort만 산출 (YYYY-MM-DD)"),
) -> None:
    """사전 등록된 Realty Income 월별 진입 cohort를 PIT 규칙으로 재생성한다."""
    from .o_entry_cohort import refresh_cohort

    try:
        cutoff = date.fromisoformat(asof) if asof else None
    except ValueError as exc:
        raise typer.BadParameter("--asof는 YYYY-MM-DD 형식이어야 합니다.") from exc
    path, payload, changed = refresh_cohort(config.ROOT, asof=cutoff)
    state = "갱신" if changed else "변경 없음"
    main = [row for row in payload["summary"]
            if row["sample"] == "dotcom_1998_2005" and row["cohort"] == "all_months"
            and row["horizon_months"] == 12 and row["basis"] == "total_return_proxy"]
    n = main[0]["n"] if main else 0
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} · 기준 {payload['asof']} · "
        f"1998–2005 12개월 총수익 cohort n={n} · entry-state 규칙 없음"
    )


@app.command("cross-asset-horizon")
def cmd_cross_asset_horizon() -> None:
    """감사된 최신 입력을 고정한 채 교차자산 조건부 지평만 5년으로 승격한다."""
    from .cross_asset import upgrade_cross_asset_horizon

    path, payload, changed = upgrade_cross_asset_horizon(config.ROOT)
    state = "갱신" if changed else "변경 없음"
    source = payload["forecast"].get("source_snapshot_id") or "현재 스냅샷"
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} · 시장 기준 {payload['asof']} · "
        f"M0-M{payload['forecast']['horizon_months']} · 측정 입력 {source} 고정"
    )


@app.command("market-extensions")
def cmd_market_extensions(
    asof: str | None = typer.Option(
        None, "--asof", help="이 날짜까지의 마지막 확정 주간으로 생성 (YYYY-MM-DD)"),
) -> None:
    """사전등록 Scenario Tracker와 reference-only 유동성 지도를 갱신한다."""
    from .market_extensions import refresh_market_extensions

    try:
        cutoff = date.fromisoformat(asof) if asof else None
    except ValueError as exc:
        raise typer.BadParameter("--asof는 YYYY-MM-DD 형식이어야 합니다.") from exc
    result = refresh_market_extensions(config.ROOT, asof=cutoff)
    tracker = result["tracker"]
    liquidity = result["liquidity"]
    typer.echo(
        f"시장 확장 기준 {tracker['asof']} · tracker "
        f"{tracker['summary']['available']}/{tracker['summary']['total']} 신호 · "
        f"liquidity zone {liquidity['zone']} · probability=표시 안 함"
    )


@app.command("statistics-refresh")
def cmd_statistics_refresh() -> None:
    """닷컴과 현재 사이클의 공개 통계 비교 DB를 주간 갱신한다."""
    from .statistics_lab import refresh_statistics_lab

    path, payload, changed = refresh_statistics_lab(config.ROOT)
    state = "갱신" if changed else "변경 없음"
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} · 기준 {payload['as_of']} · "
        f"차트 {len(payload['charts'])}개 · model_use=false"
    )


@app.command("ipo-reference-batch")
def cmd_ipo_reference_batch() -> None:
    """IPO 학술 원천 변경을 확인하고 현재 구간 검토 배치를 기록한다."""
    from .ipo_reference_batch import refresh_ipo_reference_batch

    path, payload, new_receipts = refresh_ipo_reference_batch(config.ROOT)
    typer.echo(
        f"IPO 참고통계 배치: {path.relative_to(config.ROOT)} · "
        f"상태 {payload['status']} · 새 영수증 {new_receipts}개 · "
        "historical_rows_locked=true"
    )


@app.command("official-data-workbook")
def cmd_official_data_workbook() -> None:
    """공식 원천 누적 DB를 사람이 검토할 수 있는 Excel 감사본으로 내보낸다."""
    from .official_data_workbook import export_official_data_workbook

    path, counts = export_official_data_workbook(config.ROOT)
    typer.echo(
        f"Excel 감사본: {path.relative_to(config.ROOT)} · "
        f"원천 {counts['sources']} · 관측 {counts['observations']} · "
        f"영수증 {counts['receipts']} · 장표 {counts['charts']}"
    )


@app.command("segment-filing-inventory")
def cmd_segment_filing_inventory(
    asof: str | None = typer.Option(
        None, "--asof", help="SEC filing accession 목록 기준일 (YYYY-MM-DD)"),
) -> None:
    """L1-1 준비용 4사×최근 12개 10-Q/K accession만 목록화한다."""
    from .segment_filing_inventory import refresh_inventory

    try:
        cutoff = date.fromisoformat(asof) if asof else None
    except ValueError as exc:
        raise typer.BadParameter("--asof는 YYYY-MM-DD 형식이어야 합니다.") from exc
    path, payload, changed = refresh_inventory(config.ROOT, asof=cutoff)
    state = "갱신" if changed else "변경 없음"
    counts = "/".join(str(payload["companies"][symbol]["filing_count"])
                      for symbol in ("MSFT", "AMZN", "GOOGL", "META"))
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} · 4사 filing {counts} · "
        "segment extraction not_started"
    )


@app.command("ai-capital-cycle")
def cmd_ai_capital_cycle(
    asof: str | None = typer.Option(
        None, "--asof", help="D0–D2 수집 기준일 (YYYY-MM-DD)"),
) -> None:
    """SEC D1 layer와 D2 disclosure-coverage gate를 갱신한다."""
    from .ai_capital_cycle import refresh_ai_capital_cycle

    try:
        cutoff = date.fromisoformat(asof) if asof else None
    except ValueError as exc:
        raise typer.BadParameter("--asof는 YYYY-MM-DD 형식이어야 합니다.") from exc
    result = refresh_ai_capital_cycle(config.ROOT, asof=cutoff)
    coverage = result["coverage"]
    gate_label = (
        "D3 map blocked"
        if coverage["status"] == "insufficient"
        else "D3 gate eligible"
    )
    typer.echo(
        f"AI 자본사이클 D2 기준 {coverage['asof']} · coverage "
        f"{coverage['coverage']:.0%}/{coverage['coverage_threshold']:.0%} · "
        f"{gate_label}"
    )


@app.command("source-monitor")
def cmd_source_monitor(
    asof: str | None = typer.Option(
        None, "--asof", help="후보 원천 D0 모니터링 기준일 (YYYY-MM-DD)"),
) -> None:
    """비활성 후보 원천의 스키마 안정성 영수증만 수집한다."""
    from .source_monitoring import collect_defillama_health

    try:
        cutoff = date.fromisoformat(asof) if asof else None
    except ValueError as exc:
        raise typer.BadParameter("--asof는 YYYY-MM-DD 형식이어야 합니다.") from exc
    path, status, changed = collect_defillama_health(config.ROOT, asof=cutoff)
    state = "갱신" if changed else "변경 없음"
    typer.echo(
        f"{state}: {path.relative_to(config.ROOT)} · DefiLlama D0 "
        f"{status['consecutive_successful_days']}/{status['required_successful_days']}일 · "
        f"license={status['license_status']} · activation={status['activation_eligible']}"
    )


@app.command("sync")
def cmd_sync(
    rebuild: bool = typer.Option(False, "--rebuild", help="DB 전체 재구축 (불변성 사전대조 포함)"),
    force: bool = typer.Option(False, "--force", help="rebuild 사전대조 불일치를 무시하고 재기준화"),
    check: bool = typer.Option(False, "--check", help="드리프트 검사만 — 이상 시 비정상 종료"),
) -> None:
    """파일(진실) → SQLite(파생 인덱스) 동기화."""
    root = config.ROOT
    if check:
        report, counts = ingest.check(root)
        typer.echo(report.summary())
        typer.echo(
            f"질문 {counts['questions']} / 예측 {counts['forecasts']} / 해소 {counts['resolutions']}"
        )
        if not report.ok:
            raise typer.Exit(code=1)
        return
    conn = _conn(root)
    report = ingest.sync(conn, root, rebuild=rebuild, force=force, strict=True)
    typer.echo(report.summary())
    n_f = conn.execute("SELECT COUNT(*) AS n FROM forecasts").fetchone()["n"]
    n_q = conn.execute("SELECT COUNT(*) AS n FROM questions").fetchone()["n"]
    n_r = conn.execute("SELECT COUNT(*) AS n FROM resolutions").fetchone()["n"]
    typer.echo(f"질문 {n_q} / 예측 {n_f} / 해소 {n_r}")
    if not report.ok:
        raise typer.Exit(code=1)
    from .inventory import write_inventory
    write_inventory(root, conn)


@app.command("inventory")
def cmd_inventory(
    check: bool = typer.Option(False, "--check", help="생성 문서가 현재 원천/DB와 같은지 검사"),
) -> None:
    """원천 파일과 파생 인덱스의 자동 현황 문서를 생성한다."""
    from .inventory import OUTPUT, inventory_is_current, write_inventory

    root = config.ROOT
    conn = _conn(root)
    _sync_or_exit(conn, root)
    if check:
        if not inventory_is_current(root, conn):
            typer.echo(f"inventory drift: {OUTPUT.as_posix()}", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"inventory current: {OUTPUT.as_posix()}")
        return
    path = write_inventory(root, conn)
    typer.echo(f"generated: {path.relative_to(root)}")


@app.command("due")
def cmd_due(
    as_json: bool = typer.Option(False, "--json"),
    explain: bool = typer.Option(False, "--explain", help="질문별 다음 due 근거 표시"),
    notify: bool = typer.Option(False, "--notify", help="텔레그램 다이제스트 발송"),
) -> None:
    """재예측/해소 기한 도래 목록 (실행 전 sync 자동 수행)."""
    root = config.ROOT
    conn = _conn(root)
    _sync_or_exit(conn, root)

    questions = load_registry(root / "questions" / "registry.yaml")
    due = compute_due(
        questions,
        queries.latest_forecasts(conn),
        queries.open_rolling_windows(conn),
        queries.resolved_forecast_ids(conn),
        datetime.now(),
        latest_probs=queries.latest_probabilities(conn),
        ml_refs=queries.latest_ml_refs(conn, config.ML_REF_MAX_AGE_DAYS),
        divergence_classes=queries.latest_divergence_classes(conn),
    )

    if as_json:
        typer.echo(json.dumps(
            [{"qid": d.question_id, "kind": d.kind, "reason": d.reason,
              "overdue_days": d.overdue_days} for d in due],
            ensure_ascii=False, indent=2))
    else:
        if not due:
            typer.echo("due 없음 — 모든 질문이 cadence 내에 있음")
        for d in due:
            typer.echo(f"[{d.kind:13s}] {d.question_id:28s} {d.reason}")

    # 수동 base rate 빈티지 경고 (AUDIT-260715 D-5 — 경고만, 차단 아님)
    from .base_rates import scan_stale_base_rates
    stale = scan_stale_base_rates(root, config.BASE_RATE_VINTAGE_WARN_DAYS)
    for name, last in stale:
        typer.echo(f"[빈티지 경고 ] base_rates/{name:24s} 최신 수집일 {last} "
                   f"({config.BASE_RATE_VINTAGE_WARN_DAYS}일+ 경과 — 갱신 검토)")

    if explain:
        from .registry import active_interval_days
        typer.echo("\n── 질문별 다음 due 근거 ──")
        lf = queries.latest_forecasts(conn)
        for q in questions:
            if q.status != "active":
                continue
            interval = active_interval_days(q, datetime.now().date())
            last = lf.get(q.question_id)
            typer.echo(f"{q.question_id:28s} 간격={interval if interval else 'manual/once'}일 "
                       f"마지막={last.date() if last else '없음'}")

    if notify:
        from .notify import send_digest
        send_digest(due)


@app.command("migrate-schedule")
def cmd_migrate_schedule(
    write: bool = typer.Option(False, "--write", help="registry.yaml에 schedule 필드 기록"),
) -> None:
    """한국어 cadence → schedule 필드 제안 (1회성 보조 마이그레이션).

    --write 없이 실행하면 제안만 표시. --write 시 registry.yaml 갱신
    (registry는 가변 — 단, git diff로 검토할 것).
    """
    root = config.ROOT
    registry_path = root / "questions" / "registry.yaml"
    questions = load_registry(registry_path)

    proposals: dict[str, list] = {}
    for q in questions:
        if q.schedule:
            continue  # 이미 있음
        prop = propose_schedule(q.cadence_raw)
        marker = json.dumps(prop, ensure_ascii=False) if prop else "(해석 불가 — manual 유지)"
        typer.echo(f"{q.question_id:28s} {q.cadence_raw!r}\n{'':30s}→ {marker}")
        if prop:
            proposals[q.question_id] = prop

    if not write:
        typer.echo("\n--write로 registry.yaml에 반영 (반영 후 git diff로 검토 권장)")
        return

    import yaml
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    for q in data["questions"]:
        if q["id"] in proposals and "schedule" not in q:
            q["schedule"] = proposals[q["id"]]
    registry_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8")
    typer.echo(f"\n{len(proposals)}개 질문에 schedule 기록 완료 — git diff로 검토하세요")


@app.command("forecast")
def cmd_forecast(
    question_id: str = typer.Argument(None),
    due_all: bool = typer.Option(False, "--due", help="due 질문 전체 실행"),
    max_n: int = typer.Option(3, "--max"),
    agents: int = typer.Option(2, "--agents", help="리서치 에이전트 수 (2 또는 4)"),
    budget: float = typer.Option(config.DEFAULT_PIPELINE_BUDGET, "--budget"),
    dry_run: bool = typer.Option(False, "--dry-run", help="스크래치패드에만 기록 (forecasts/ 무접촉)"),
    yes: bool = typer.Option(False, "--yes", help="확인 프롬프트 생략"),
) -> None:
    """질문 예측 실행: 리서치 → 추론 → 불변 기록 → DB 동기화."""
    from .orchestrator import run_forecast

    root = config.ROOT
    conn = _conn(root)
    _sync_or_exit(conn, root)

    if due_all:
        questions = load_registry(root / "questions" / "registry.yaml")
        due = compute_due(questions, queries.latest_forecasts(conn),
                          queries.open_rolling_windows(conn),
                          queries.resolved_forecast_ids(conn), datetime.now())
        # divergence는 의도적으로 제외 — "재예측 트리거 후보"일 뿐, 실행은 인간 결정 (ML 게이트)
        targets = [d.question_id for d in due if d.kind == "forecast"][:max_n]
        if not targets:
            typer.echo("예측 due 없음")
            return
    elif question_id:
        targets = [question_id]
    else:
        typer.echo("question_id 또는 --due 필요", err=True)
        raise typer.Exit(code=2)

    for qid in targets:
        if not yes and not dry_run:
            typer.confirm(f"{qid} 예측을 실행할까요? (예상 비용 ~${budget:.2f} 이내)", abort=True)
        result = run_forecast(conn, root, qid, n_agents=agents,
                              budget_usd=budget, dry_run=dry_run)
        typer.echo(result)


@app.command("resolve")
def cmd_resolve(
    question_id: str = typer.Argument(None),
    outcome: str = typer.Option(None, "--outcome", help="yes | no | void"),
    forecast_id: str = typer.Option(None, "--forecast-id", help="rolling 인스턴스 지정"),
    evidence: str = typer.Option("", "--evidence", help="판정 근거 (URL·설명)"),
    resolution_data: Path = typer.Option(
        None, "--resolution-data",
        help="macro/earnings 이중 출처 관측 JSON (--draft 전용)"),
    draft: bool = typer.Option(False, "--draft",
                               help="기계 판정 초안만 출력 (원장 무기록 — 확정은 사람)"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """해소 판정 보조: Brier 계산 후 확인받고 원장 append. --draft는 초안만."""
    from .resolver import (draft_verdicts, load_resolution_observations,
                           resolve_question)

    root = config.ROOT
    conn = _conn(root)
    _sync_or_exit(conn, root)

    if draft:
        observations = {}
        if resolution_data is not None:
            try:
                observations = load_resolution_observations(resolution_data)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                typer.echo(f"판정 관측 JSON 오류: {exc}", err=True)
                raise typer.Exit(code=2) from exc
        verdicts = draft_verdicts(
            conn, root, question_id, observations=observations)
        if not verdicts:
            typer.echo("기계 판정 초안 대상 없음 (가격·macro·earnings 결정론형 + 기한 도래만)")
            return
        typer.echo("기계 판정 초안 — 참고 의견 (P3 게이트 전) · 원장 무기록, 확정은 사람:")
        for v in verdicts:
            fid = f" [{v.forecast_id}]" if v.forecast_id else ""
            oc = v.outcome or "판정불가"
            typer.echo(f"  {v.question_id:28s}{fid} → {oc:6s} ({v.confidence}) "
                       f"{v.evidence_value} {v.note}")
            if v.comparison_log:
                typer.echo(f"    ↳ source-check {v.comparison_log}")
        typer.echo("⚠ macro/earnings는 두 출처 수치가 일치할 때만 초안 판정. "
                   "가격형은 여전히 2차 공식 출처 대조가 필요하며, 불일치는 held.")
        typer.echo("확정: python -m ai_fc resolve <qid> --outcome yes|no --evidence <근거>")
        return

    if not question_id:
        typer.echo("question_id 필요 (--draft 없이 실행 시)", err=True)
        raise typer.Exit(code=2)
    resolve_question(conn, root, question_id, outcome=outcome,
                     forecast_id=forecast_id, evidence=evidence, assume_yes=yes)


@app.command("report")
def cmd_report(
    open_browser: bool = typer.Option(False, "--open"),
) -> None:
    """캘리브레이션 HTML 대시보드 생성."""
    from .report import render_report

    root = config.ROOT
    conn = _conn(root)
    _sync_or_exit(conn, root)
    out = render_report(conn, root)
    typer.echo(f"생성: {out}")
    if open_browser:
        import webbrowser
        webbrowser.open(out.as_uri())


@app.command("dashboard")
def cmd_dashboard(
    serve: bool = typer.Option(False, "--serve", help="LAN 서버 구동 (stdlib http.server, 읽기 전용)"),
    host: str = typer.Option("127.0.0.1", "--host", help="바인드 주소 — 팀 공유는 0.0.0.0"),
    port: int = typer.Option(8899, "--port"),
    pages_out: str = typer.Option(None, "--pages-out", help="GitHub Pages 정적 배포 디렉터리 (CI용)"),
    open_browser: bool = typer.Option(False, "--open"),
) -> None:
    """예측 흐름 조회 대시보드 — 스냅샷 / LAN 서버 / GitHub Pages 정적 빌드 (전부 읽기 전용).

    스냅샷: reports/dashboard.html (브라우저로 열면 끝, 의존성 0).
    서버:   --serve [--host 0.0.0.0]  ← 팀 공유 (LAN).
    Pages:  --pages-out <dir>  ← CI가 <dir>/index.html 생성 → github-pages 배포.
    """
    from pathlib import Path as _P

    from . import dashboard as dash

    root = config.ROOT
    if serve:
        conn = _conn(root)
        _sync_or_exit(conn, root)  # 최신화 후 서버는 매 요청 라이브 재조회
        conn.close()
        dash.serve(root, host, port)
        return
    conn = _conn(root)
    _sync_or_exit(conn, root)
    if pages_out:
        out = dash.write_pages(conn, _P(pages_out), root)
        typer.echo(f"Pages 빌드: {out}")
        return
    out = dash.write_dashboard(conn, root)
    typer.echo(f"생성: {out.relative_to(root)}")
    typer.echo("팀 공유(LAN): python -m ai_fc dashboard --serve --host 0.0.0.0")
    if open_browser:
        import webbrowser
        webbrowser.open(out.as_uri())


@app.command("quant")
def cmd_quant(
    no_write: bool = typer.Option(False, "--no-write", help="base_rates 갱신 없이 콘솔만"),
) -> None:
    """정량 도구 재적합 (오버레이·Hurst·DTW·LPPL·GBM·미드텀) → base_rates 자동 갱신."""
    from .quant.runner import run_all, write_base_rates

    typer.echo("원시 데이터 수집·재적합 중 (Yahoo·FRED, ~30초)...")
    results, md = run_all()
    typer.echo(md)
    if not no_write:
        out = write_base_rates(config.ROOT, md)
        typer.echo(f"\nbase_rates 갱신: {out.relative_to(config.ROOT)}")


@app.command("ml")
def cmd_ml(
    no_write: bool = typer.Option(False, "--no-write", help="base_rates 갱신 없이 콘솔만"),
) -> None:
    """오픈웨이트 추론 (Chronos 분위수·FinBERT 감성) → 이력 기록 + base_rates 갱신. 학습 없음."""
    from .ml.runner import run_all, run_and_record, write_base_rates

    typer.echo("오픈웨이트 추론 중 (최초 실행 시 HF 모델 다운로드)...")
    if no_write:
        _, md = run_all()
        typer.echo(md)
        return
    root = config.ROOT
    conn = _conn(root)
    _, md = run_and_record(root, conn)
    typer.echo(md)
    out = write_base_rates(root, md)
    typer.echo(f"\nbase_rates 갱신: {out.relative_to(root)} · 이력: data/ml_history/")


@app.command("market")
def cmd_market(
    no_write: bool = typer.Option(False, "--no-write", help="base_rates 갱신 없이 콘솔만"),
) -> None:
    """시장내재확률 수집 (Kalshi·Polymarket·CBOE 옵션) → 이력 기록. 참조 전용 — P3 게이트 봉인."""
    from .market.runner import run_all, run_and_record, render_md, write_base_rates

    typer.echo("시장내재확률 수집 중 (무료·무인증 소스, fail-soft)...")
    if no_write:
        typer.echo(render_md(run_all()))
        return
    root = config.ROOT
    conn = _conn(root)
    _, md = run_and_record(root, conn)
    typer.echo(md)
    out = write_base_rates(root, md)
    typer.echo(f"\nbase_rates 갱신: {out.relative_to(root)} · 이력: data/ml_history/")


@app.command("notify")
def cmd_notify(test: bool = typer.Option(False, "--test")) -> None:
    """텔레그램 연결 테스트."""
    from .notify import send_message
    ok = send_message("ai-fc 알림 테스트 ✅" if test else "ai-fc")
    typer.echo("발송 성공" if ok else "발송 실패 (토큰/챗ID 확인)")


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # 한국어 콘솔 출력
        sys.stderr.reconfigure(encoding="utf-8")
    app()


if __name__ == "__main__":
    main()
