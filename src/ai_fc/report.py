"""캘리브레이션 대시보드 — 자기완결 단일 HTML (외부 의존 없음, CSS 바 차트)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from . import config
from .db import queries

CSS = """
:root{--bg:#0a0e1a;--card:#131827;--border:#2a3553;--text:#e8ecf5;--muted:#8b95ad;
--cyan:#22d3ee;--ok:#34d399;--warn:#fbbf24;--bad:#ef4444;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Malgun Gothic',system-ui,sans-serif;
padding:30px;max-width:1000px;margin:0 auto;line-height:1.6}
h1{font-size:22px;margin-bottom:4px}h2{font-size:15px;color:var(--cyan);margin:26px 0 10px}
.sub{color:var(--muted);font-size:12px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px 22px;margin-top:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--cyan);padding:6px 10px;font-size:11px}
td{padding:6px 10px;border-top:1px solid var(--border)}
.bar{height:14px;background:var(--cyan);border-radius:3px;display:inline-block;vertical-align:middle}
.bar.ref{background:var(--muted);opacity:.4}
.gate{display:inline-block;padding:3px 12px;border-radius:12px;font-size:12px;font-weight:700;margin-right:8px}
.pass{background:rgba(52,211,153,.2);color:var(--ok)}
.fail{background:rgba(251,191,36,.15);color:var(--warn)}
.blocked{color:var(--bad);font-weight:700}
.note{font-size:11px;color:var(--muted);margin-top:8px}
"""


def _driver_section(conn: sqlite3.Connection, root: Path) -> str:
    """WS9 드라이버 일관성 표 — 그룹별 최신 확률 나열, 폭 큰 그룹만 '점검 후보' 하이라이트.

    자동 판정 없음: 방향 상충 휴리스틱(그룹 내 max ≥ 60 AND min ≤ 40)은
    사람이 볼 후보 표시일 뿐이다. 참고 의견 (P3 게이트 전).
    """
    from .registry import load_registry

    try:
        questions = load_registry(root / "questions" / "registry.yaml")
    except Exception:  # noqa: BLE001
        return ""
    probs = {}
    for row in conn.execute(
        """SELECT f.question_id, f.probability FROM forecasts f
           JOIN (SELECT question_id, MAX(round) r FROM forecasts GROUP BY question_id) m
             ON f.question_id = m.question_id AND f.round = m.r"""):
        probs[row["question_id"]] = int(row["probability"])

    groups: dict[str, list] = {}
    for q in questions:
        if q.status != "active":
            continue
        for drv in q.drivers:
            groups.setdefault(drv, []).append(q)
    if not groups:
        return ""

    blocks = []
    for drv in sorted(groups):
        qs = groups[drv]
        vals = [probs[q.question_id] for q in qs if q.question_id in probs]
        flag = (' <span class="gate fail">점검 후보 — 그룹 내 확률 폭 큼 (정합 여부는 사람 판단)</span>'
                if vals and max(vals) >= 60 and min(vals) <= 40 else "")
        rows = "".join(
            f"<tr><td>{q.question_id}</td><td>{q.title}</td>"
            f"<td>{probs.get(q.question_id, '—')}%</td>"
            f"<td>{q.deadline.isoformat() if q.deadline else q.cadence_raw}</td></tr>"
            for q in qs)
        blocks.append(f"<h3 style='color:var(--cyan);font-size:13px;margin:14px 0 6px'>"
                      f"{drv} ({len(qs)}문){flag}</h3>"
                      f"<table><tr><th>질문</th><th>제목</th><th>최신 확률</th>"
                      f"<th>기한/주기</th></tr>{rows}</table>")
    return ("<h2>드라이버 일관성 점검 (WS9) — 조건부 정합은 사람 판단</h2>"
            '<div class="card">' + "".join(blocks)
            + '<p class="note">같은 드라이버를 공유하는 질문들의 최신 확률 나열 — '
              '자동 판정 없음. 참고 의견 (P3 게이트 전).</p></div>')


def render_report(conn: sqlite3.Connection, root: Path) -> Path:
    gate = queries.gate_status(conn)
    briers = queries.brier_summary(conn)
    curve = queries.calibration_curve(conn)
    skills = queries.domain_skill(conn)
    now = datetime.now()
    month_cost = queries.month_cost(conn, now.year, now.month)
    n_forecasts = conn.execute("SELECT COUNT(*) AS n FROM forecasts").fetchone()["n"]

    n_resolved = gate["n_resolved"] or 0
    brier_txt = f"{gate['brier']:.4f}" if gate["brier"] is not None else "—"

    def bar(value: float, scale: float = 300) -> str:
        return f'<span class="bar" style="width:{max(value * scale, 2):.0f}px"></span>'

    # 캘리브레이션 커브 (십분위: 예측 vs 실현)
    curve_rows = "".join(
        f"<tr><td>{int(r['decile']) * 10}~{int(r['decile']) * 10 + 9}%</td>"
        f"<td>{r['n']}</td>"
        f"<td>{bar(r['avg_forecast'])} {r['avg_forecast'] * 100:.0f}%</td>"
        f"<td>{bar(r['avg_outcome'])} {r['avg_outcome'] * 100:.0f}%</td></tr>"
        for r in curve) or '<tr><td colspan="4">해소 표본 없음</td></tr>'

    brier_rows = "".join(
        f"<tr><td>{r['domain']}</td><td>{r['n']}</td>"
        f"<td>{r['brier']:.4f}</td><td>{bar(r['brier'], 800)}</td></tr>"
        for r in briers if r["n"]) or '<tr><td colspan="4">해소 표본 없음</td></tr>'

    skill_rows = "".join(
        f"<tr><td>{r['domain']}</td><td>{r['n']}</td><td>{r['brier']:.4f}</td>"
        f"<td>{'<span class=blocked>시그널 차단</span>' if r['blocked'] else ('표본 부족' if r['n'] < 5 else 'OK')}</td></tr>"
        for r in skills) or '<tr><td colspan="4">해소 표본 없음</td></tr>'

    # WS2: 벤치마크 3자 비교 (쌍대 표본만 — 비교 대상 존재 해소 한정)
    bench = list(conn.execute("SELECT * FROM v_benchmark_pairwise"))
    pair_labels = {"llm_vs_ml": "LLM vs ML앙상블", "llm_vs_market": "LLM vs 시장내재",
                   "all_three": "3자 모두 존재"}
    bench_rows = "".join(
        f"<tr><td>{pair_labels.get(r['pair'], r['pair'])}</td><td>{r['n']}</td>"
        f"<td>{r['llm_brier']:.4f}</td><td>{r['other_brier']:.4f}</td>"
        f"<td>{'LLM 우위' if r['llm_brier'] < r['other_brier'] else 'LLM 열위'}</td></tr>"
        for r in bench if r["n"]) or '<tr><td colspan="5">쌍대 표본 없음 (비교 대상 기록이 있는 해소 0건)</td></tr>'

    p2 = f'<span class="gate {"pass" if gate["gate_p2"] else "fail"}">P2 게이트 (30+/&lt;0.20): {"통과" if gate["gate_p2"] else "미달"}</span>'
    p3 = f'<span class="gate {"pass" if gate["gate_p3"] else "fail"}">P3 게이트 (50+/&lt;0.18): {"통과" if gate["gate_p3"] else "미달"}</span>'
    maturity = ('<p class="note">⚠ 표본 30 미만 — 통계적으로 미성숙. 모든 수치는 참고용.</p>'
                if n_resolved < 30 else "")

    # WS8-3: 대표 Brier에 제외표본 상시 병기 (검토질문 #3 응답)
    n_excl = queries.n_excluded_from_primary(conn)
    primary_txt = (f"v_brier_primary (n={n_resolved}, 제외 {n_excl}건: failed) — "
                   "원장은 전량 채점 유지, 게이트 산정식 무변경")

    # WS8-2: Murphy 분해 (전체 + 도메인별)
    murphy_all = queries.murphy_decomposition(conn)
    murphy_rows = ""
    if murphy_all:
        domains = [r["domain"] for r in briers if r["domain"] != "(전체)" and r["n"]]
        entries = [("(전체)", murphy_all)] + [
            (d, m) for d in domains if (m := queries.murphy_decomposition(conn, d))]
        murphy_rows = "".join(
            f"<tr><td>{d}</td><td>{m['n']}</td><td>{m['brier']:.4f}</td>"
            f"<td>{m['reliability']:.4f}</td><td>{m['resolution']:.4f}</td>"
            f"<td>{m['uncertainty']:.4f}</td></tr>" for d, m in entries)
    murphy_section = (f"""
<h2>Murphy 분해 — Brier = Reliability − Resolution + Uncertainty</h2>
<div class="card"><table>
<tr><th>도메인</th><th>n</th><th>Brier</th><th>REL (낮을수록 보정 좋음)</th>
<th>RES (높을수록 판별력)</th><th>UNC</th></tr>{murphy_rows}</table>
<p class="note">표시 계층 — 게이트 무관. 표본 소수 구간에선 분해가 불안정.</p></div>"""
                      if murphy_rows else
                      '<h2>Murphy 분해</h2><div class="card"><p class="note">해소 표본 없음</p></div>')

    # WS8-4: rolling Brier (윈도우 10) — 마지막 10개 지점만 표시
    roll = queries.rolling_brier(conn, window=10)
    roll_txt = (" → ".join(f"{r['rolling']:.3f}" for r in roll[-10:])
                if len(roll) >= 3 else "표본 부족 (3+ 필요)")

    # WS8-5: 섀도 extremized 가상 Brier (표시 전용 — 공식 아님)
    sh = queries.shadow_brier(conn)
    shadow_txt = (f"섀도(α=√3) {sh['shadow_brier']:.4f} vs 공식 {sh['official_brier']:.4f} "
                  f"(n={sh['n']}) — 해소 100+ 실보정 게이트 전 사전 관찰"
                  if sh else "섀도 기록 표본 없음 (신규 예측부터 축적)")

    # WS9: 드라이버 일관성 표 (자동 판정 없음 — 점검 후보 하이라이트만)
    driver_section = _driver_section(conn, root)

    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>ai-fc 캘리브레이션</title><style>{CSS}</style></head><body>
<h1>캘리브레이션 대시보드</h1>
<p class="sub">생성 {now.strftime("%Y-%m-%d %H:%M")} · 예측 {n_forecasts}건 · 해소 {n_resolved}건 ·
이달 비용 ${month_cost:.2f} / ${config.MONTHLY_BUDGET:.0f}</p>

<div class="card">{p2} {p3}
<p style="margin-top:10px">전체 Brier: <b>{brier_txt}</b>
<span class="sub">(무지성 50% = 0.25 · 톱 인간 ≈ 0.12~0.15)</span></p>
<p class="note">{primary_txt}</p>
<p class="note">rolling Brier(윈도우 10): {roll_txt}</p>
<p class="note">{shadow_txt}</p>{maturity}</div>

<h2>신뢰도 다이어그램 (캘리브레이션 커브) — "70%라고 한 것들이 실제 70% 실현되나"</h2>
<div class="card"><table>
<tr><th>확률 구간</th><th>n</th><th>평균 예측</th><th>실현율</th></tr>{curve_rows}</table>
<p class="note">{"⚠ 표본 5 미만 — 다이어그램 해석 불가 구간 (빈 10개는 표본 5+부터 유의미)."
                if n_resolved < 5 else "빈 10개 십분위."} rolling 질문의 겹치는 윈도우는 독립 표본이 아님.</p></div>
{murphy_section}
{driver_section}

<h2>벤치마크 3자 비교 — LLM vs ML앙상블 vs 시장내재 (쌍대 표본만)</h2>
<div class="card"><table>
<tr><th>비교</th><th>쌍대 n</th><th>LLM Brier</th><th>비교대상 Brier</th><th>판정</th></tr>{bench_rows}</table>
<p class="note">원본: calibration/benchmark_ledger.csv (append-only). 비교 대상 부재 해소는 NULL로 제외 —
불공정 비교 차단. edge 주장은 P3 게이트 + 쌍대 표본 축적 후에만. 참고 의견 (P3 게이트 전).</p></div>

<h2>도메인별 Brier</h2>
<div class="card"><table>
<tr><th>도메인</th><th>n</th><th>Brier</th><th>낮을수록 우수</th></tr>{brier_rows}</table></div>

<h2>도메인 skill — 무능 도메인 자동 차단 (Brier&gt;0.22 & n≥10)</h2>
<div class="card"><table>
<tr><th>도메인</th><th>n</th><th>Brier</th><th>상태</th></tr>{skill_rows}</table></div>

<p class="note">본 대시보드는 파생 인덱스에서 생성됨 — 원본은 calibration/ledger.csv.
P3 게이트 통과 전 모든 예측은 참고 의견.</p>
</body></html>"""

    out_dir = root / "reports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "calibration.html"
    out.write_text(html, encoding="utf-8")
    return out
