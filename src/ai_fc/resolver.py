"""해소 판정 보조 — Brier 계산 후 확인받고 원장 append.

판정은 rules-lawyer처럼 문언 그대로. 시스템은 계산·기록만 하고,
outcome 최종 결정과 확인은 사람이 한다 (원장 append 전 확인 필수).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

import typer

from . import files as F
from .db import ingest
from .registry import load_registry

OUTCOME_MAP = {"yes": 1, "no": 0}

SERIES_SYMBOLS = {"q_ixic": "^IXIC", "q_soxx": "SOXX", "q_vix": "^VIX"}


# ── WS1 기계 판정 초안 (auto-resolve draft — 확정은 사람) ─────────

@dataclass
class DraftVerdict:
    """기계 판정 초안 — 참고 의견 (P3 게이트 전). 원장 기록은 사람 확정 후에만."""

    question_id: str
    forecast_id: Optional[str]      # rolling 인스턴스별, fixed는 None(질문 단위)
    outcome: Optional[str]          # 'yes' | 'no' | None(판정 불가/진행 중)
    evidence_value: str
    source: str
    confidence: str                 # 'high' | 'low'
    note: str = ""
    # v3 WS-D: 초안은 Yahoo 단일 소스 — 확정 전 2차 출처(WSJ/Nasdaq.com/거래소) 대조 필수.
    # 상수 True — 초안이 확정으로 오인되는 것을 구조적으로 방지 (7/14 Yahoo 일봉 철회 실사례).
    secondary_check_needed: bool = True


def _default_fetch(symbol: str, start: date, end: date):
    from .quant import feed
    return feed.yahoo_series(symbol, start, end, "1d")


def machine_check(q, *, window_start: Optional[date] = None,
                  window_end: Optional[date] = None,
                  today: Optional[date] = None,
                  fetch: Optional[Callable] = None) -> Optional[DraftVerdict]:
    """가격 임계형 질문(ml.mapping.QUESTION_MAPS)의 판정 초안. 비대상이면 None.

    - terminal 질문: 기한 도래 후 기한일(이하 최근) 종가 vs 임계.
    - path 질문: 판정 윈도우 내 일간 종가의 임계 터치 여부. 터치 즉시 yes(조기 확정),
      미터치+윈도우 종료 = no, 미터치+진행 중 = outcome None.
    네트워크 실패는 confidence='low' + note로 정직 보고 (fail-soft).
    """
    from .ml.mapping import QUESTION_MAPS

    qm = next((m for m in QUESTION_MAPS if m.question_id == q.question_id), None)
    if qm is None:
        return None
    today = today or date.today()
    fetch = fetch or _default_fetch
    symbol = SERIES_SYMBOLS[qm.series_key]

    try:
        if qm.mode in ("above_terminal", "below_terminal"):
            if q.deadline_kind != "fixed" or q.deadline is None or today <= q.deadline:
                return DraftVerdict(q.question_id, None, None, "", symbol, "low",
                                    "종점 질문 — 기한 미도래 (판정 불가)")
            dates, closes = fetch(symbol, q.deadline - timedelta(days=10), q.deadline)
            if not closes:
                return DraftVerdict(q.question_id, None, None, "", symbol, "low",
                                    "기한 전후 종가 데이터 없음")
            last_d, last_c = dates[-1], closes[-1]
            above = last_c >= qm.threshold
            outcome = "yes" if (above == (qm.mode == "above_terminal")) else "no"
            return DraftVerdict(
                q.question_id, None, outcome,
                f"{last_d} 종가 {last_c:,.2f} vs 임계 {qm.threshold:,.2f}",
                symbol, "high")

        # 경로 질문 — 판정 윈도우 결정: 고정 윈도우(qm.window) > 호출자 지정 > 불가
        if qm.window is not None:
            ws = date.fromisoformat(qm.window[0])
            we = date.fromisoformat(qm.window[1])
        elif window_start and window_end:
            ws, we = window_start, window_end
        else:
            return DraftVerdict(q.question_id, None, None, "", symbol, "low",
                                "경로 질문 — 윈도우 미지정 (rolling 인스턴스 필요)")
        if today < ws:
            return DraftVerdict(q.question_id, None, None, "", symbol, "low",
                                f"윈도우({ws}~{we}) 시작 전")
        dates, closes = fetch(symbol, ws, min(we, today))
        direction_above = qm.mode == "above_path"
        touches = [(d, c) for d, c in zip(dates, closes)
                   if (c >= qm.threshold if direction_above else c <= qm.threshold)]
        if touches:
            d0, c0 = touches[0]
            return DraftVerdict(
                q.question_id, None, "yes",
                f"{d0} 종가 {c0:,.2f} 터치 (임계 {qm.threshold:,.2f})", symbol, "high")
        extreme = max(closes) if direction_above else min(closes) if closes else None
        ev = (f"미터치 — 윈도우 내 {'최고' if direction_above else '최저'} "
              f"{extreme:,.2f} vs 임계 {qm.threshold:,.2f}" if extreme is not None
              else "윈도우 내 데이터 없음")
        if today > we:
            return DraftVerdict(q.question_id, None, "no", ev, symbol,
                                "high" if closes else "low")
        return DraftVerdict(q.question_id, None, None, ev, symbol, "high",
                            f"윈도우 진행 중 (~{we}) — 미터치")
    except Exception as exc:  # noqa: BLE001 — 네트워크 등: 정직한 low-confidence
        return DraftVerdict(q.question_id, None, None, "", symbol, "low",
                            f"조회 실패: {type(exc).__name__}: {exc}")


def draft_verdicts(conn: sqlite3.Connection, root: Path,
                   question_id: Optional[str] = None,
                   fetch: Optional[Callable] = None,
                   today: Optional[date] = None) -> list[DraftVerdict]:
    """해소 대상(기한 경과 fixed + 윈도우 종료 rolling)의 기계 판정 초안 일괄 산출.

    원장·파일 무접촉 — 출력만. 확정은 resolve <qid> --outcome 경로로 사람이.
    """
    today = today or date.today()
    questions = load_registry(root / "questions" / "registry.yaml")
    targets = [q for q in questions
               if (question_id is None or q.question_id == question_id)
               and q.status == "active"]
    out: list[DraftVerdict] = []
    for q in targets:
        if q.deadline_kind == "fixed":
            if question_id is None and (q.deadline is None or today <= q.deadline):
                continue  # 일괄 모드에선 기한 경과만
            v = machine_check(q, today=today, fetch=fetch)
            if v is not None:
                out.append(v)
        elif q.deadline_kind == "rolling":
            rows = conn.execute(
                """SELECT f.forecast_id, f.forecast_ts, f.window_end FROM forecasts f
                   LEFT JOIN resolutions r ON r.forecast_id = f.forecast_id
                   WHERE f.question_id=? AND f.window_end IS NOT NULL
                     AND r.forecast_id IS NULL""", (q.question_id,)).fetchall()
            for r in rows:
                wend = date.fromisoformat(r["window_end"])
                if question_id is None and today <= wend:
                    continue
                wstart = date.fromisoformat((r["forecast_ts"] or "")[:10]) \
                    if r["forecast_ts"] else None
                v = machine_check(q, window_start=wstart, window_end=wend,
                                  today=today, fetch=fetch)
                if v is not None:
                    v.forecast_id = r["forecast_id"]
                    out.append(v)
    return out


# ── WS2 벤치마크 병행 채점 (룩어헤드 차단) ────────────────────────

def _ml_ref_before(conn: sqlite3.Connection, question_id: str,
                   forecast_ts_iso: str) -> Optional[tuple[float, str]]:
    """예측 시점 **이전** 최신 ML 앙상블 확률. 이후 값 사용 금지 (룩어헤드 차단).

    부재 시 None — 소급 조회로 채우지 않는다 (NULL 정직성).
    """
    if not forecast_ts_iso:
        return None
    row = conn.execute(
        """SELECT prob, run_ts FROM ml_forecasts
           WHERE question_id=? AND model='ensemble' AND run_ts <= ?
           ORDER BY run_ts DESC LIMIT 1""",
        (question_id, forecast_ts_iso)).fetchone()
    return (float(row["prob"]), str(row["run_ts"])) if row else None


def resolve_question(conn: sqlite3.Connection, root: Path, question_id: str,
                     outcome: str | None, forecast_id: str | None,
                     evidence: str, assume_yes: bool) -> None:
    questions = {q.question_id: q for q in load_registry(root / "questions" / "registry.yaml")}
    q = questions.get(question_id)
    if q is None:
        typer.echo(f"registry에 없는 질문: {question_id}", err=True)
        raise typer.Exit(code=2)

    # 대상 예측 회차 수집 (rolling이면 지정 인스턴스만, 아니면 전 회차)
    rows = list(conn.execute(
        "SELECT forecast_id, probability, forecast_ts, window_end, market_implied "
        "FROM forecasts WHERE question_id = ? ORDER BY round", (question_id,)))
    if forecast_id:
        rows = [r for r in rows if r["forecast_id"] == forecast_id]
    if not rows:
        typer.echo("채점할 예측이 없음", err=True)
        raise typer.Exit(code=2)

    already = {r["forecast_id"] for r in conn.execute(
        "SELECT forecast_id FROM resolutions WHERE question_id = ?", (question_id,))}
    rows = [r for r in rows if r["forecast_id"] not in already]
    if not rows:
        typer.echo("모든 회차가 이미 채점됨")
        return

    typer.echo(f"\n질문: {q.title}")
    typer.echo(f"판정 기준: {q.resolution.strip()}")
    typer.echo(f"판정 출처: {q.resolution_source}")
    if evidence:
        typer.echo(f"제시된 근거: {evidence}")

    if outcome is None:
        outcome = typer.prompt("판정 결과 (yes/no/void)").strip().lower()
    if outcome == "void":
        typer.echo("void — 채점하지 않음. registry에서 status: void로 바꾸고 사유를 notes에 기록하세요.")
        return
    if outcome not in OUTCOME_MAP:
        typer.echo(f"잘못된 outcome: {outcome}", err=True)
        raise typer.Exit(code=2)
    val = OUTCOME_MAP[outcome]

    # Brier 미리보기
    typer.echo("\n채점 예정 (원장 append 전 확인):")
    scored = []
    for r in rows:
        brier = round((r["probability"] / 100.0 - val) ** 2, 4)
        scored.append((r, brier))
        typer.echo(f"  {r['forecast_id']}: p={r['probability']}% outcome={val} → Brier {brier}")

    if not assume_yes:
        typer.confirm("원장에 기록할까요? (append-only — 되돌릴 수 없음)", abort=True)

    today = date.today().isoformat()
    for r, brier in scored:
        F.append_ledger_row(root / "calibration" / "ledger.csv", {
            "resolved_date": today,
            "question_id": question_id,
            "forecast_id": r["forecast_id"],
            "forecast_date": (r["forecast_ts"] or "")[:10],
            "probability": r["probability"],
            "outcome": val,
            "brier": brier,
            "domain": q.domain,
            "notes": evidence,
        })
        # WS2: 벤치마크 3자 병행 채점 — 별도 원장 (기록·표시 전용, 게이트 무관)
        ml = _ml_ref_before(conn, question_id, r["forecast_ts"] or "")
        mi = r["market_implied"]
        F.append_benchmark_row(root / "calibration" / "benchmark_ledger.csv", {
            "resolved_date": today,
            "question_id": question_id,
            "forecast_id": r["forecast_id"],
            "llm_prob": round(r["probability"] / 100.0, 4),
            "llm_brier": brier,
            "ml_prob": round(ml[0], 4) if ml else None,
            "ml_brier": round((ml[0] - val) ** 2, 4) if ml else None,
            "market_prob": round(float(mi), 4) if mi is not None else None,
            "market_brier": round((float(mi) - val) ** 2, 4) if mi is not None else None,
            "ml_asof": ml[1] if ml else "",
            "market_asof": (r["forecast_ts"] or "")[:10] if mi is not None else "",
            "notes": "",
        })
    ingest.sync(conn, root)
    n_ml = sum(1 for r, _ in scored if _ml_ref_before(conn, question_id, r["forecast_ts"] or ""))
    n_mi = sum(1 for r, _ in scored if r["market_implied"] is not None)
    typer.echo(f"벤치마크 원장 기록: {len(scored)}행 (ML 비교 {n_ml} · 시장 비교 {n_mi} · "
               f"부재는 NULL — 참고 의견, P3 게이트 전)")

    row = conn.execute("SELECT * FROM v_gate_status").fetchone()
    typer.echo(f"\n기록 완료. 누계: 해소 {row['n_resolved']}건, Brier {row['brier']:.4f}")
    typer.echo(f"게이트 — P2(30+/<0.20): {'통과' if row['gate_p2'] else '미달'} / "
               f"P3(50+/<0.18): {'통과' if row['gate_p3'] else '미달'}")
    if q.deadline_kind == "fixed":
        typer.echo(f"※ registry에서 {question_id}의 status를 resolved로 갱신하세요 (rolling은 active 유지).")
