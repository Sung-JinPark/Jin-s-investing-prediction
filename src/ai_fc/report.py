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
    # T01 — 표시층 이중 단위. 게이트 산술은 무변경이며 이 값들은 판정에 쓰이지 않는다.
    from .gate_display import gate_display_facts, gate_display_lines
    try:
        gd = gate_display_facts(root)
        gd_lines = gate_display_lines(gd)
    except Exception:
        gd, gd_lines = {}, []
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

    # T01 — 이중 단위 패널. "행 평균 통과"가 단위 의존 진술임을 상시 노출한다.
    dual = ""
    if gd:
        rounds = gd.get("questions_with_multiple_rounds") or {}
        hist = "".join(
            f"<tr><td>{q}</td><td>{n}</td></tr>"
            for q, n in sorted((gd.get("rounds_per_question") or {}).items(),
                               key=lambda kv: (-kv[1], kv[0]))) or "<tr><td colspan=2>표본 없음</td></tr>"
        share = (sum(rounds.values()) / gd["n_rows_primary"]) if rounds and gd.get("n_rows_primary") else 0.0
        ci = gd.get("ci90") or []
        ci_txt = f"[{ci[0]:.5f}, {ci[1]:.5f}]" if len(ci) == 2 else "—"

        def _num(key: str, spec: str) -> str:
            """표본이 얇으면 표시층 값이 None 이다 — 판정 대신 대시를 낸다."""
            v = gd.get(key)
            return format(v, spec) if isinstance(v, (int, float)) else "—"
        dual = (
            '<div class="card"><h2>게이트 Brier — 두 단위</h2>'
            '<table><tr><th>단위</th><th>값</th><th>비고</th></tr>'
            f'<tr><td><b>행 평균</b></td><td><b>{_num("brier_primary_rows", ".5f")}</b></td>'
            '<td>게이트 <b>정본</b> — v_gate_status 와 같은 산술</td></tr>'
            f'<tr><td>문항 등가중</td><td>{_num("brier_per_question", ".5f")}</td>'
            '<td>게이밍 감시용 병기값 (판정 아님)</td></tr>'
            f'<tr><td>SE</td><td>{_num("se", ".4f")}</td>'
            f'<td>문턱 0.18 까지 <b>{_num("margin_se", ".2f")} SE</b></td></tr>'
            f'<tr><td>CI90</td><td>{ci_txt}</td><td>문항 클러스터 부트스트랩 B=2000</td></tr>'
            '</table>'
            '<p class="note">게이트 정본은 <b>행 평균</b>이고, 문항 등가중은 게이밍 감시용이다. '
            '쉬운 질문을 여러 회차 재예측하면 행 평균은 내려가지만 <b>문항 수는 늘지 않는다</b> — '
            f'현재 복수 회차 문항 {len(rounds)}개가 primary 행의 <b>{share:.0%}</b> 를 차지한다.</p>'
            '<table><tr><th>문항</th><th>회차</th></tr>' + hist + '</table>'
            f'<p class="note">해소 문항 {gd["n_questions_primary"]}/{gd["threshold_questions"]} — '
            '<b>미결</b>. 이 패널은 표시 전용이며 게이트 판정을 하지 않는다.</p></div>')

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

    # C5 부수 증명서 (설계도 §8) — 표시 계층 전용, 게이트 판정에 다리를 놓지 않는다
    c5_section = _c5_section(root)

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
{dual}

<h2>신뢰도 다이어그램 (캘리브레이션 커브) — "70%라고 한 것들이 실제 70% 실현되나"</h2>
<div class="card"><table>
<tr><th>확률 구간</th><th>n</th><th>평균 예측</th><th>실현율</th></tr>{curve_rows}</table>
<p class="note">{"⚠ 표본 5 미만 — 다이어그램 해석 불가 구간 (빈 10개는 표본 5+부터 유의미)."
                if n_resolved < 5 else "빈 10개 십분위."} rolling 질문의 겹치는 윈도우는 독립 표본이 아님.</p></div>
{murphy_section}
{c5_section}
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


def _c5_section(root) -> str:
    """C5 부수 증명서 — 예리도·BSS·ESS·부트스트랩·경로 (설계도 §8.2).

    전부 **표시 계층**이다. 게이트 산술(v_gate_status)은 이 함수가 건드리지 않는다.
    파생 실패는 숨기지 않고 그 사실을 인쇄한다 (페일클로즈).
    """
    try:
        from . import c5_certificate as c5
        r = c5.report(root)
    except Exception as exc:  # noqa: BLE001 — 대시보드가 증명서 때문에 죽으면 안 된다
        return ('<h2>C5 부수 증명서</h2><div class="card">'
                f'<p class="note">파생 실패: {exc}</p></div>')

    sharp = r["sharpness"].get("rows")
    if sharp:
        verdict = ("<b>임계 초과</b> — 완전 캘리브레이션에서도 미달"
                   if sharp["mean_pq"] >= c5.BRIER_THRESHOLD_P3 else "임계 이하")
        rf = r["sharpness"].get("reforecast")
        rf_txt = (f" · 재예측 예리화 {rf['first']:.4f}→{rf['latest']:.4f} "
                  f"({rf['delta']:+.4f}, {rf['sharpened']}/{rf['n']}문항)" if rf else "")
        sharp_txt = (f"행 평균 p(1−p) = <b>{sharp['mean_pq']:.4f}</b> "
                     f"(임계 {c5.BRIER_THRESHOLD_P3}) → {verdict} · n={sharp['n']}행"
                     f" · 결손 {sharp['deficit']:+.4f}{rf_txt}")
    else:
        sharp_txt = "예측 표본 없음"

    bss = r["bss"]
    bss_txt = (f"{bss['bss']:+.4f} (모델 {bss['brier_model']:.4f} / anchor "
               f"{bss['brier_anchor']:.4f}, n={bss['n']}, 미회수 {bss['missing']})"
               if bss["bss"] is not None else f"표본 없음 (anchor 미회수 {bss['missing']})")
    bss_warn = ('<p class="note">⚠ BSS ≤ 0 — base rate 대비 증분 실력이 측정되지 않았다. '
                '게이트를 통과해도 자동 활성화하지 않는다 (C5-A4).</p>'
                if bss["bss"] is not None and bss["bss"] <= 0 else "")

    ess, essr = r["ess"], r["ess_registry"]
    bs = r["bootstrap"]
    bs_txt = (bs["note"] if bs and bs["note"] else
              (f"[{bs['ci_lo']:.4f}, {bs['ci_hi']:.4f}] · 클러스터 {bs['n_clusters']}개"
               if bs else "표본 없음"))
    paths = " · ".join(f"{k} n={v}" for k, v in sorted(r["paths"].items())) or "없음"
    viol = r["diversification"]["violations"]
    viol_txt = ("<br>".join(f"⚠ {v}" for v in viol) if viol else "없음")

    return f"""<h2>C5 부수 증명서 — 게이트가 못 보는 것 (표시 전용)</h2>
<div class="card">
<p><b>예리도 (D2)</b>: {sharp_txt}</p>
<p><b>BSS vs anchor</b>: {bss_txt}
<span class="sub">— 쉬운 질문을 고르면 anchor 도 같이 예리해지므로 패딩에 면역</span></p>{bss_warn}
<p><b>유효표본 (D3)</b>: 해소 명목 {ess['nominal']} · ESS 하한 {ess['ess_lower']:.1f} ·
레지스트리 명목 {essr['nominal']} · ESS 하한 {essr['ess_lower']:.1f}</p>
<p><b>클러스터 부트스트랩 CI90</b>: {bs_txt}</p>
<p><b>생산 경로</b>: {paths}
<span class="sub">— claude_code 경로는 cost_log 에 계측되지 않는다 (0 이 아니라 '모름')</span></p>
<p><b>분산 규칙 위반</b>: {viol_txt}</p>
<p class="note">전부 표시 계층 — 게이트 판정식(v_gate_status)은 무변경.
설계도 docs/design/c5_calibration_program_blueprint_v1_260909.md §8.</p></div>"""
