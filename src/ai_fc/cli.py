"""ai-fc CLI 진입점.

사용: python -m ai_fc <command>  (src/ 디렉터리에서, 또는 PYTHONPATH=src)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import typer

from . import config
from .db import ingest, queries
from .registry import compute_due, load_registry, propose_schedule

app = typer.Typer(add_completion=False, help="AI Superforecaster P1 scaffold")


def _conn(root: Path):
    return ingest.connect(root / "db" / "index.db")


@app.command("sync")
def cmd_sync(
    rebuild: bool = typer.Option(False, "--rebuild", help="DB 전체 재구축 (불변성 사전대조 포함)"),
    force: bool = typer.Option(False, "--force", help="rebuild 사전대조 불일치를 무시하고 재기준화"),
    check: bool = typer.Option(False, "--check", help="드리프트 검사만 — 이상 시 비정상 종료"),
) -> None:
    """파일(진실) → SQLite(파생 인덱스) 동기화."""
    root = config.ROOT
    conn = _conn(root)
    report = ingest.sync(conn, root, rebuild=rebuild, force=force)
    typer.echo(report.summary())
    n_f = conn.execute("SELECT COUNT(*) AS n FROM forecasts").fetchone()["n"]
    n_q = conn.execute("SELECT COUNT(*) AS n FROM questions").fetchone()["n"]
    n_r = conn.execute("SELECT COUNT(*) AS n FROM resolutions").fetchone()["n"]
    typer.echo(f"질문 {n_q} / 예측 {n_f} / 해소 {n_r}")
    if check and not report.ok:
        raise typer.Exit(code=1)


@app.command("due")
def cmd_due(
    as_json: bool = typer.Option(False, "--json"),
    explain: bool = typer.Option(False, "--explain", help="질문별 다음 due 근거 표시"),
    notify: bool = typer.Option(False, "--notify", help="텔레그램 다이제스트 발송"),
) -> None:
    """재예측/해소 기한 도래 목록 (실행 전 sync 자동 수행)."""
    root = config.ROOT
    conn = _conn(root)
    report = ingest.sync(conn, root)
    if not report.ok:
        typer.echo(report.summary(), err=True)

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
            [{"qid": d.question_id, "kind": d.kind, "reason": d.reason} for d in due],
            ensure_ascii=False, indent=2))
    else:
        if not due:
            typer.echo("due 없음 — 모든 질문이 cadence 내에 있음")
        order = {"resolve": 0, "forecast": 1, "divergence": 2, "stale": 3, "manual-review": 4}
        for d in sorted(due, key=lambda x: order.get(x.kind, 9)):
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
    ingest.sync(conn, root)

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
    draft: bool = typer.Option(False, "--draft",
                               help="기계 판정 초안만 출력 (원장 무기록 — 확정은 사람)"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """해소 판정 보조: Brier 계산 후 확인받고 원장 append. --draft는 초안만."""
    from .resolver import draft_verdicts, resolve_question

    root = config.ROOT
    conn = _conn(root)
    ingest.sync(conn, root)

    if draft:
        verdicts = draft_verdicts(conn, root, question_id)
        if not verdicts:
            typer.echo("기계 판정 초안 대상 없음 (가격 임계형 + 기한/윈도우 도래 질문만)")
            return
        typer.echo("기계 판정 초안 — 참고 의견 (P3 게이트 전) · 원장 무기록, 확정은 사람:")
        for v in verdicts:
            fid = f" [{v.forecast_id}]" if v.forecast_id else ""
            oc = v.outcome or "판정불가"
            typer.echo(f"  {v.question_id:28s}{fid} → {oc:6s} ({v.confidence}) "
                       f"{v.evidence_value} {v.note}")
        typer.echo("⚠ 초안은 Yahoo 단일 소스 — 확정 전 2차 출처(WSJ/Nasdaq.com/거래소) "
                   "대조 필수, 불일치 시 판정 보류·기록 (WS-D)")
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
    ingest.sync(conn, root)
    out = render_report(conn, root)
    typer.echo(f"생성: {out}")
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
