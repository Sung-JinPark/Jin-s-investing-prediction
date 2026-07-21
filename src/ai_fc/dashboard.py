"""내부 대시보드 — 예측 흐름 조회 사이트 (읽기 전용, 자기완결 HTML + stdlib 서버).

설계 원칙:
- 읽기 전용: 웹에서 예측 실행(forecast) 없음. 불변 파일 + SQLite 인덱스를 조회만.
- 의존성 0 추가: 표준 라이브러리 http.server + 인라인 CSS/바닐라 JS (CDN·프레임워크 없음).
- 두 모드: (1) 자기완결 스냅샷 HTML(reports/dashboard.html), (2) `--serve` LAN 서버.
- 지위: 참고 의견 (P3 게이트 전). 데이터는 공개 예측 기록 — 시크릿 미포함.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from . import config
from .db import ingest, queries

TEMPLATE = Path(__file__).parent / "dashboard_template.html"

# ── 시나리오 흐름 데이터 (정본: reports/md/nasdaq_weekly_scenario_v3_1_1) ──
SCENARIO = {
    "asof": "2026-07-14",
    "anchor": 26107.01,
    "ath": 27093.90,
    "corr10": 24384.51,
    "weeks": ["7/14", "7/17", "7/24", "7/31", "8/7", "8/14", "8/21", "8/28", "9/4",
              "9/11", "9/18", "9/25", "10/2", "10/9", "10/16", "10/23", "10/30",
              "11/6", "11/13", "11/20", "11/27", "12/4", "12/11", "12/18", "12/24", "12/31"],
    "paths": {
        "S1": {"label": "상승·ATH 돌파", "prob": 50, "color": "#3b82f6", "end": 27750,
               "values": [26107, 25950, 25700, 25500, 25750, 26100, 26400, 26700, 26900,
                          27000, 26700, 26300, 25900, 25600, 25800, 26100, 26400, 26900,
                          27200, 27400, 27500, 27600, 27550, 27650, 27700, 27750]},
        "S2": {"label": "상승·ATH 미달", "prob": 16, "color": "#059669", "end": 26650,
               "values": [26107, 25900, 25650, 25450, 25650, 25950, 26200, 26450, 26650,
                          26800, 26550, 26200, 25850, 25600, 25800, 26050, 26300, 26700,
                          26950, 27120, 26900, 26750, 26650, 26600, 26620, 26650]},
        "S3": {"label": "조정·횡보", "prob": 34, "color": "#ef4444", "end": 25450,
               "values": [26107, 25800, 25500, 25200, 24900, 24700, 24500, 24200, 24400,
                          24100, 23900, 23850, 23800, 24000, 24200, 24400, 24600, 24900,
                          25000, 25100, 25200, 25250, 25300, 25350, 25400, 25450]},
    },
    "analog": {"label": "닷컴 아날로그 (참조선 — 시나리오 아님)", "color": "#94a3b8", "clip": 30000,
               "values": [26107, 26918, 25300, 24794, 23943, 24787, 24886, 25925, 26717,
                          27130, 26966, 25752, 25718, 27125, 25671, 26467, 27876, 29152,
                          30269, 31661, 32399, 33083, 34019, 35267, 37301, 38239]},
    "risk": ["중", "중", "중", "중", "중", "저", "중", "고", "중", "중", "고", "고",
             "고", "고", "고", "고", "고", "고", "중", "중", "저", "중", "중", "저", "저", "저"],
    "events": [
        [0, "7/14 CPI 3.5%", 0], [0.45, "7/15–16 ASML·TSMC", 1], [2.64, "7/28–29 FOMC", 0],
        [4, "8/7 고용", 1], [6.71, "8/26 NVDA", 0], [9.64, "9/15–16 FOMC", 1],
        [11.57, "9/29 미드텀 저점 중위", 0], [14.8, "10월말 빅테크", 1],
        [15.64, "10/27–28 FOMC", 0], [16.57, "11/3 중간선거", 1],
        [21.64, "12/8–9 FOMC·산타랠리", 0],
    ],
    "note": ("경로는 확률 가중 평균이 아닌 대표 예시. 리듬 근거는 미드텀 시즌성·FOMC·실적 "
             "캘린더(위상 무관). 확률은 앙상블 prob_above 규칙 상속 (DECISIONS 8-1). "
             "참고 의견 — P3 게이트 전."),
}


def _row(r) -> dict:
    return {k: r[k] for k in r.keys()} if r is not None else {}


def _rows(rs) -> list[dict]:
    return [_row(r) for r in rs]


def _forecast_bodies(root: Path) -> dict[str, str]:
    """forecast_id → 본문 텍스트 (추론 전문 — 상세 뷰용). evidence·TEMPLATE 제외."""
    import frontmatter

    out: dict[str, str] = {}
    fdir = root / "forecasts"
    if not fdir.exists():
        return out
    for path in fdir.rglob("*.md"):
        name = path.stem
        if name.endswith("_evidence") or name.upper() == "TEMPLATE" or "retro" in path.parts:
            continue
        try:
            post = frontmatter.load(str(path))
            out[name] = post.content.strip()
        except Exception:  # noqa: BLE001
            continue
    return out


def build_read_model(conn: sqlite3.Connection, root: Path) -> dict:
    """18개 질의 + registry + 예측 이력 + ml/market 이력 → 대시보드 read-model."""
    from .registry import compute_due, load_registry

    now = datetime.now()
    questions = load_registry(root / "questions" / "registry.yaml")
    qmap = {q.question_id: q for q in questions}
    bodies = _forecast_bodies(root)

    # 예측 이력 — 질문별 회차 (forecasts 테이블 + 파일 본문)
    fc_hist: dict[str, list[dict]] = {}
    for r in conn.execute(
        "SELECT forecast_id, question_id, round, forecast_ts, probability, ci80_lo, ci80_hi,"
        " method, market_implied, edge, sources_count, shadow_extremized, model, phase"
        " FROM forecasts ORDER BY question_id, round"
    ):
        d = _row(r)
        d["body"] = bodies.get(d["forecast_id"], "")
        fc_hist.setdefault(d["question_id"], []).append(d)

    # 해소 결과
    resolutions: dict[str, list[dict]] = {}
    for r in conn.execute(
        "SELECT forecast_id, question_id, resolved_date, probability, outcome, brier, notes"
        " FROM resolutions ORDER BY resolved_date"
    ):
        d = _row(r)
        resolutions.setdefault(d["question_id"], []).append(d)

    # 질문 요약 (브라우저용)
    q_summary = []
    for q in questions:
        hist = fc_hist.get(q.question_id, [])
        latest = hist[-1] if hist else None
        q_summary.append({
            "id": q.question_id, "title": q.title, "domain": q.domain,
            "drivers": q.drivers, "status": q.status,
            "deadline": q.deadline.isoformat() if q.deadline else None,
            "deadline_kind": q.deadline_kind,
            "n_rounds": len(hist),
            "latest_prob": latest["probability"] if latest else None,
            "latest_ts": latest["forecast_ts"] if latest else None,
            "resolved": q.question_id in resolutions,
        })

    # ML·시장 이력 (as-of 재구성 + 대조선) — ml_forecasts ensemble + market_implied
    ml_runs = _rows(conn.execute(
        "SELECT run_ts, question_id, prob, threshold FROM ml_forecasts"
        " WHERE model='ensemble' ORDER BY run_ts"))
    market_runs = _rows(conn.execute(
        "SELECT run_ts, question_id, prob, source FROM market_implied ORDER BY run_ts"))

    # 캘리브레이션
    gate = _row(queries.gate_status(conn))
    try:
        gate_all = _row(conn.execute("SELECT * FROM v_gate_status_all").fetchone())
    except Exception:  # noqa: BLE001
        gate_all = {}
    calibration = {
        "gate": gate, "gate_all": gate_all,
        "n_excluded": queries.n_excluded_from_primary(conn),
        "curve": _rows(queries.calibration_curve(conn)),
        "brier_by_domain": _rows(queries.brier_summary(conn)),
        "domain_skill": _rows(queries.domain_skill(conn)),
        "murphy": queries.murphy_decomposition(conn),
        "rolling": queries.rolling_brier(conn),
        "shadow": queries.shadow_brier(conn),
    }
    try:
        calibration["benchmark"] = _rows(conn.execute(
            "SELECT * FROM v_benchmark_pairwise"))
    except Exception:  # noqa: BLE001
        calibration["benchmark"] = []

    # due (이번 주 할 일)
    try:
        due = compute_due(
            questions, queries.latest_forecasts(conn), queries.open_rolling_windows(conn),
            queries.resolved_forecast_ids(conn), now,
            latest_probs=queries.latest_probabilities(conn),
            ml_refs=queries.latest_ml_refs(conn, config.ML_REF_MAX_AGE_DAYS))
        due_list = [{"qid": d.question_id, "kind": d.kind, "reason": d.reason} for d in due]
    except Exception:  # noqa: BLE001
        due_list = []

    return {
        "meta": {
            "generated": now.isoformat(timespec="seconds"),
            "phase": gate.get("gate_p3") and "P3" or (gate.get("gate_p2") and "P2" or "P1"),
            "n_questions": len(questions),
            "n_forecasts": sum(len(v) for v in fc_hist.values()),
            "n_resolved": gate.get("n_resolved", 0),
            "cost_month": round(queries.month_cost(conn, now.year, now.month), 2),
        },
        "scenario": SCENARIO,
        "questions": q_summary,
        "forecast_history": fc_hist,
        "resolutions": resolutions,
        "ml_runs": ml_runs,
        "market_runs": market_runs,
        "calibration": calibration,
        "due": due_list,
    }


def render_html(read_model: dict, mode: str = "embed") -> str:
    shell = TEMPLATE.read_text(encoding="utf-8")
    if mode == "embed":
        blob = json.dumps(read_model, ensure_ascii=False, default=str)
        data_script = f"<script>window.__DATA__ = {blob};</script>"
    else:
        data_script = '<script>window.__DATA_URL__ = "/api/data";</script>'
    return shell.replace("<!--DATA-->", data_script)


def write_dashboard(conn: sqlite3.Connection, root: Path) -> Path:
    model = build_read_model(conn, root)
    out = root / "reports" / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(model, mode="embed"), encoding="utf-8")
    return out


def write_pages(conn: sqlite3.Connection, out_dir: Path, root: Path) -> Path:
    """GitHub Pages 정적 배포용 — <out_dir>/index.html (자기완결 임베드) + .nojekyll.

    CI에서 커밋된 불변 파일로 DB를 재구축(sync --rebuild)한 뒤 호출한다.
    데이터는 전부 공개 repo에 이미 존재하는 예측 기록 — 새 노출 없음.
    """
    model = build_read_model(conn, root)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"
    index.write_text(render_html(model, mode="embed"), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")  # _파일 무시 방지
    return index


# ── 서버 모드 (stdlib http.server — 읽기 전용, 라이브 재조회) ──

def serve(root: Path, host: str, port: int) -> None:
    import http.server
    import socketserver

    db_path = root / "db" / "index.db"
    shell = render_html({}, mode="fetch")  # DATA는 /api/data로 fetch

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(shell.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path.startswith("/api/data"):
                # 매 요청마다 라이브 재조회 (읽기 전용 — 새 연결, 쓰기 없음)
                conn = ingest.connect(db_path)
                try:
                    model = build_read_model(conn, root)
                finally:
                    conn.close()
                body = json.dumps(model, ensure_ascii=False, default=str).encode("utf-8")
                self._send(body, "application/json; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802 — 읽기 전용 서버: 쓰기 메서드 전면 차단
            self.send_error(405, "read-only dashboard")

        def log_message(self, *a) -> None:  # 콘솔 소음 억제
            pass

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server((host, port), Handler) as httpd:
        lan = " (LAN 노출 — 읽기 전용 공개 데이터만)" if host not in ("127.0.0.1", "localhost") else ""
        print(f"대시보드 서빙: http://{host}:{port}{lan}")
        print("종료: Ctrl+C")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n서버 종료")
