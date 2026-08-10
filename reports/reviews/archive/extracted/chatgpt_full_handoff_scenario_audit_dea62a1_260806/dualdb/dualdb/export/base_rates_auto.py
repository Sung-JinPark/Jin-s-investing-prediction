"""dualdb → ai-fc base_rates 연동: dotcom_analog_auto.md 생성 (스펙 §9).

Q1(정렬)·Q2(조정 base rate)·Q5(IPO 과열)·사상자 통계를 ai-fc의
data/base_rates/ 포맷으로 내보낸다. Q15(k-NN)는 P4 완성 후 추가.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from .. import config
from ..analysis import weekly


def _latest_model_md(conn: sqlite3.Connection, model: str, render_fn) -> str | None:
    """model_run 최신 행의 output_json → 해당 모듈 render_md. 부재·실패 시 None (fail-soft)."""
    import json

    row = conn.execute(
        "SELECT output_json FROM model_run WHERE model=? ORDER BY run_id DESC LIMIT 1",
        (model,)).fetchone()
    if not row:
        return None
    try:
        return render_fn(json.loads(row["output_json"]))
    except Exception:  # noqa: BLE001 — 스키마 변화 등은 생략으로 처리
        return None


def render(conn: sqlite3.Connection) -> str:
    casualties = conn.execute(
        """SELECT outcome, COUNT(*) n, AVG(months_after_index_peak) avg_m
           FROM dotcom_casualty WHERE months_after_index_peak > 0
           GROUP BY outcome""").fetchall()
    cas_lines = "\n".join(
        f"- {r['outcome']}: {r['n']}건 · 지수 정점 후 평균 {r['avg_m']:.0f}개월"
        for r in casualties)
    parts = [
        "# Base Rates — 닷컴↔AI 이중시대 DB 자동 산출 (dualdb, 재생성 가능)",
        "",
        f"> `python -m dualdb export` — 생성 {date.today().isoformat()}",
        "> **참고 의견 (P3 게이트 전)** · 종목 통계는 생존자 표본, 전체 시장 서술은",
        "> 지수·Ritter·사상자 테이블 기준 (생존편향 3중 우회).",
        "",
        weekly.q1_alignment(conn),
        weekly.q2_corrections(conn),
        weekly.q5_ipo_heat(conn),
        weekly.q13_margin_debt(conn),
    ]
    # P4 모델 산출 (model_run 최신 행 재사용 — 재계산 없음)
    try:
        from ..analysis import twins
        from ..models import dtw_daily, knn_analog, lppl_walkforward
        for model, fn in (("knn_analog", knn_analog.render_md),
                          ("dtw_daily", dtw_daily.render_md),
                          ("twins", twins.render_md),
                          ("lppl_walkforward", lppl_walkforward.render_md)):
            md = _latest_model_md(conn, model, fn)
            if md:
                parts.append(md)
    except ImportError:
        pass
    parts += [
        "## 사상자 base rate (Tier-3 큐레이션, 지수 정점 기준)",
        cas_lines,
        "- 함의: 파산·초토화(-95%)의 본격화는 지수 정점 **후 8~31개월** — "
        "정점 이전 신호가 아니라 정점 확인 후의 시간표.",
        "",
        "## 한계 (정직 고지)",
        "- 사이클 표본 n=1 대 n=1 비교 — base rate는 참조선이지 예측 보증이 아님.",
        "- FRED 계열(금리·M2·HY)은 네트워크 차단으로 미충전 (CHANGELOG #7).",
        "- LPPL 워크포워드 실측: 닷컴에서 정점 1개월 전에야 수렴 — 조기경보 도구로",
        "  강등 (DECISIONS.md 8-7). 위상 추정은 방법 간 불일치(캘린더 M+42 /",
        "  일간 DTW M+43.5 / 월간 최적상관 M+37) — 단일 값 단정 금지.",
    ]
    return "\n".join(parts)


def export(conn: sqlite3.Connection) -> Path:
    md = render(conn)
    out = config.REPO_ROOT / "data" / "base_rates" / "dotcom_analog_auto.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return out
