"""내부 대시보드 — 예측 흐름 조회 사이트 (읽기 전용, 자기완결 HTML + stdlib 서버).

설계 원칙:
- 읽기 전용: 웹에서 예측 실행(forecast) 없음. 불변 파일 + SQLite 인덱스를 조회만.
- 코드 의존성 0 추가: 표준 라이브러리 http.server + 인라인 CSS/바닐라 JS.
- Pages 화면만 OFL 한글 웹폰트를 버전 고정 CDN으로 사용하며, 감사 HTML은 자기완결 상태를 유지.
- 두 모드: (1) 자기완결 스냅샷 HTML(reports/dashboard.html), (2) `--serve` LAN 서버.
- 지위: 참고 의견 (P3 게이트 전). 데이터는 공개 예측 기록 — 시크릿 미포함.
"""

from __future__ import annotations

import csv
import html as html_lib
import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, scenario as scenario_data
from .db import ingest, queries

# GoatCounter 사이트 코드 (예: "jin-investing" → https://jin-investing.goatcounter.com).
# 빈 문자열이면 분석 스니펫을 아예 넣지 않는다. 코드는 배포 페이지 소스에 공개되는
# 값이라 저장소에 커밋해도 비밀이 아니다. 집계는 GoatCounter 계정 소유자만 본다.
GOATCOUNTER_CODE = "jin-investing"

TEMPLATE = Path(__file__).parent / "dashboard_template.html"
DASHBOARD_PARTS = Path(__file__).parent / "dashboard_parts"
DASHBOARD_STYLES = DASHBOARD_PARTS / "dashboard.css"
DASHBOARD_LOOKUP_SCRIPT = DASHBOARD_PARTS / "forecast_lookup.js"
DASHBOARD_QR_SCRIPT = DASHBOARD_PARTS / "qr-creator.min.js"
DASHBOARD_SCRIPT = DASHBOARD_PARTS / "dashboard.js"
# Route-specific path arrays are loaded only when the future surface is opened.
# The shell plus summary payload must remain below this fixed ceiling.  Keep the
# binary unit explicit so feature growth is still bounded and the check is
# reproducible.
#
# ADR-002, resolved 2026-08-31 (see docs/DECISIONS.md): raised from 900 KiB.
# The blueprint's preferred option was to split payload into static JSON and
# hold the core budget, and that is what Pages does.  It cannot work for the
# standalone embed, which has no fetch: splitting there does not relocate
# content, it deletes it.  At 900 KiB the compacted shell (579 KB) plus
# non-body data (214 KB) consumed 86% of the contract before carrying any
# reasoning at all, leaving room for 18 rounds at ~6.9 KB each -- so the audit
# snapshot was dropping the very content it exists to show.  1.5 MiB carries
# one body per active question (992 KB at 29 questions) with 37% headroom, and
# still holds at 50 active questions.
DASHBOARD_RAW_BUDGET_BYTES = 1536 * 1024
FUTURE_PATHS_BUDGET_BYTES = 240_000
FUTURE_PATHS_FILENAME = "future_paths.json"
# 실측 2026-09-04: 라이브 statistics.json은 115,536 B로 120,000 B 가드의 96.3%였다
# (차트 27개 74.2KB + sources 21.9KB + IPO 참고 25.6KB). 여유가 3.7%뿐이라 차트 하나만
# 더해도 빌드가 실패한다. 페이로드는 이 화면이 실제로 그리는 내용이고 라우트 지연 로드라
# 크기 자체가 문제가 아니므로, ADR-002(대시보드 예산 상향)와 같은 방식으로 가드를 올린다.
# 33% 여유 = 통계 검수에서 늘어난 결론·caveat 문장과 차트 2~3개를 더 받을 수 있는 폭.
STATISTICS_DATA_BUDGET_BYTES = 160_000
STATISTICS_DATA_FILENAME = "statistics.json"
# 첫 화면을 막는 payload는 예산 없이 자라면 안 된다 — 실측 633KB에서 시작한다.
DATA_JSON_BUDGET_BYTES = 900_000
# 가드에 닿기 전에 보이도록 소프트 경고 임계(예산의 90%)를 둔다.
PAYLOAD_WARN_RATIO = 0.9
WANTED_SANS_CSS = (
    "https://cdn.jsdelivr.net/gh/wanteddev/wanted-sans@v1.0.3/"
    "packages/wanted-sans/fonts/webfonts/variable/split/"
    "WantedSansVariable.min.css"
)
FUTURE_DEFERRED_KEYS = (
    "scenario_v5_2", "scenario_v4_shadow", "cross_asset", "era_analog",
    "liquidity", "ai_regime", "multi_year_stress",
)

# Repeated immutable forecast headings dominate the self-contained Pages payload.
# Private-use one-codepoint tokens preserve every character while avoiding an ADR-002
# budget increase. dashboard.js expands the same ordered dictionary on read.
FORECAST_BODY_DICTIONARY = (
    "> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).",
    "> **P0 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트 통과 전).",
    "## [4] Premortem — 이 예측이 크게 틀렸다면",
    "## [1] Outside View — base rate",
    "## [2] Inside View — 보정",
    "## [0] 질문 검증",
    "## [3] 분해 트리",
    "## [5] 최종 출력",
    "## [미검증] 항목",
    "## 리서치 구성",
    "| 증거 | 방향 | 조정 |",
    "| 증거 | 방향 | 평가 |",
    "|---|---|---|",
    "- **핵심 근거 3줄**:",
    "- **관찰 지표 2개**:",
    "- **핵심 근거**:",
    "- **관찰 지표**:",
    "P1 참고 의견 — 자금 결정의 단독 근거 아님",
    "P0 참고 의견 — 자금 결정의 단독 근거 아님",
    "P3 게이트 통과 전",
    "참조 클래스:",
    "최종 확률",
    "required_snapshots",
    "NOT FOUND",
    "확률", "예측", "근거", "출처", "판정", "시나리오", "시장", "기준", "해소",
    "상승", "하락", "최종", "질문", "현재", "발생", "조정", "리스크", "참조",
    "실적", "전망", "분기",
    "general(종합) + devil(데블스 애드버킷) 서브에이전트 2개 병렬 — 증거 부록:",
    "증거 부록(`_r1_evidence.md`)",
    "| ↓ | −2%p |", "| ↓ | −3%p |", "| ↓ | −1%p |", "| ↑ | +2%p |",
    "CME FedWatch", "- **직전 대비**:",
    "| ↓ | −4%p |", "| base rate | 값 |", "| ↑ | +1%p |", "| ↑ | +3%p |", "| ↑ | +4%p |",
)

# Public UI copy must not imply a target-price product.  Historical ledgers and
# archived model receipts remain byte-for-byte immutable; only the dashboard
# read model is normalized at the presentation boundary.
_PRESENTATION_COPY_REPLACEMENTS = (
    ("목표가격", "단일 가격 제시"),
    ("목표가", "단일 가격 제시"),
)

# 불변 기록을 그대로 전재하는 필드는 어휘 규정의 대상이 아니다.  여기까지 치환하면
# 인용된 제3자 사실(예: "Citi 목표가 $1,400→$1,150")이 개작되고, 화면과 GitHub의
# 불변 파일이 달라져 독자에게는 사후 편집으로 보인다.  규정은 사이트가 스스로 쓰는
# 문장에 적용하고, 전재 필드는 원문 그대로 둔다.
_IMMUTABLE_TRANSCRIPT_KEYS = frozenset({"body", "change_note", "notes"})


def _normalize_presentation_copy(value, *, key=None):
    """Return a JSON-compatible copy with prohibited UI wording normalized."""
    if key in _IMMUTABLE_TRANSCRIPT_KEYS:
        return value
    if isinstance(value, str):
        for source, replacement in _PRESENTATION_COPY_REPLACEMENTS:
            value = value.replace(source, replacement)
        return value
    if isinstance(value, dict):
        return {
            item_key: _normalize_presentation_copy(item, key=item_key)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_presentation_copy(item, key=key) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_presentation_copy(item, key=key) for item in value)
    return value

# ── 시나리오 흐름 데이터 (정본: reports/md/nasdaq_weekly_scenario_v3_1_1) ──
SCENARIO = {
    "asof": "2026-07-14",
    "anchor": 26107.01,
    "ath": 27093.90,
    "corr10": 24384.51,
    # 오픈웨이트 앙상블(Chronos) 연말 분위수 밴드 — 기간 질의 답변의 통계 근거
    # (정본: reports/md/nasdaq_weekly_scenario_v3_1_1 / ml_auto.md 2026-07-15)
    "bands": {"eoy_median": 27101, "eoy_50": [25501, 28632], "eoy_80": [23842, 30096]},
    "weeks": ["7/14", "7/17", "7/24", "7/31", "8/7", "8/14", "8/21", "8/28", "9/4",
              "9/11", "9/18", "9/25", "10/2", "10/9", "10/16", "10/23", "10/30",
              "11/6", "11/13", "11/20", "11/27", "12/4", "12/11", "12/18", "12/24", "12/31"],
    "paths": {
        "S1": {"label": "상승·ATH 돌파", "prob": 50, "color": "#1d5fd0", "end": 27750,
               "values": [26107, 25950, 25700, 25500, 25750, 26100, 26400, 26700, 26900,
                          27000, 26700, 26300, 25900, 25600, 25800, 26100, 26400, 26900,
                          27200, 27400, 27500, 27600, 27550, 27650, 27700, 27750]},
        "S2": {"label": "상승·ATH 미달", "prob": 16, "color": "#0f8a4c", "end": 26650,
               "values": [26107, 25900, 25650, 25450, 25650, 25950, 26200, 26450, 26650,
                          26800, 26550, 26200, 25850, 25600, 25800, 26050, 26300, 26700,
                          26950, 27120, 26900, 26750, 26650, 26600, 26620, 26650]},
        "S3": {"label": "조정·횡보", "prob": 34, "color": "#cf2f2a", "end": 25450,
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


def _change_note(body: str) -> str:
    """Return one plain-language evidence sentence for the Decision Journal."""
    for raw in body.splitlines():
        line = re.sub(r"^[>#*+\-\d.\s]+", "", raw).strip()
        line = re.sub(r"[`*_\[\]]", "", line)
        if not line or line.startswith("|") or len(line) < 18:
            continue
        lowered = line.lower()
        if any(token in lowered for token in ("투자 자금 결정", "p3 게이트", "question_snapshot", "required_snapshots")):
            continue
        return line[:180]
    return "근거 문서에 기록된 조건을 재검토해 판단을 갱신했습니다."


def _forecast_bodies(root: Path) -> dict[str, dict[str, str]]:
    """forecast_id → 본문 텍스트 (추론 전문 — 상세 뷰용). evidence·TEMPLATE 제외."""
    import frontmatter

    out: dict[str, dict[str, str]] = {}
    fdir = root / "forecasts"
    if not fdir.exists():
        return out
    for path in fdir.rglob("*.md"):
        name = path.stem
        if name.endswith("_evidence") or name.upper() == "TEMPLATE" or "retro" in path.parts:
            continue
        try:
            post = frontmatter.load(str(path))
            body = post.content.strip()
            for index, phrase in enumerate(FORECAST_BODY_DICTIONARY):
                body = body.replace(phrase, chr(0xE000 + index))
            out[name] = {
                "body": body,
                "change_note": _change_note(post.content.strip()),
                "source_uri": path.relative_to(root).as_posix(),
            }
        except Exception:  # noqa: BLE001
            continue
    return out


def build_read_model(
    conn: sqlite3.Connection,
    root: Path,
    *,
    now: datetime | None = None,
) -> dict:
    """18개 질의 + registry + 예측 이력 + ml/market 이력 → 대시보드 read-model."""
    from .registry import compute_due, load_registry

    now = now or datetime.now().astimezone()
    questions = load_registry(root / "questions" / "registry.yaml")
    qmap = {q.question_id: q for q in questions}
    bodies = _forecast_bodies(root)

    # 예측 이력 — 질문별 회차 (forecasts 테이블 + 파일 본문)
    fc_hist: dict[str, list[dict]] = {}
    for r in conn.execute(
        # The browser receives only fields used by the history/detail surfaces.  The
        # database remains the complete audit index; redundant question_id and unused
        # nullable research columns would otherwise consume the static Pages budget on
        # every round.
        "SELECT forecast_id, question_id, round, forecast_ts, probability, ci80_lo, ci80_hi,"
        " method, sources_count, model FROM forecasts ORDER BY question_id, round"
    ):
        d = _row(r)
        record = bodies.get(d["forecast_id"], {})
        d["body"] = record.get("body", "")
        d["change_note"] = record.get("change_note", "")
        d["source_uri"] = record.get("source_uri", "")
        question_id = d.pop("question_id")
        fc_hist.setdefault(question_id, []).append(d)

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
            "probability_space": "physical_event",
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
        "gate_v2": queries.gate_status_v2(conn),
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
        due_list = [{"qid": d.question_id, "kind": d.kind, "reason": d.reason,
                     "overdue_days": d.overdue_days} for d in due]
    except Exception:  # noqa: BLE001
        due_list = []

    scenario = scenario_data.load_latest_scenario(root, SCENARIO)
    scenario["horizon_coverage"] = scenario_data.summarize_horizon_coverage(root)
    from .scenario_v5 import load_current_candidate as load_scenario_v5_candidate
    scenario_v5 = load_scenario_v5_candidate(root, now, maximum_age_trading_days=1)
    if (scenario_v5.get("status") == "unavailable"
            or scenario_v5.get("runtime_gate", {}).get("display_eligible") is False):
        runtime_gate = scenario_v5.get("runtime_gate") or {
            "display_eligible": False,
            "reasons": [scenario_v5.get("reason") or "candidate unavailable"],
        }
        scenario_v5 = {
            "schema_version": 2,
            "status": scenario_v5.get("status", "unavailable"),
            "candidate_id": "scenario_v5_1_time_aligned_legacy_prior_v1",
            "reason": scenario_v5.get("reason") or (
                "No valid fresh Scenario V5.1 research candidate; "
                "the current V5.2 candidate or official legacy fallback remains active."
            ),
            "asof": scenario_v5.get("asof"),
            "generated_at": scenario_v5.get("generated_at"),
            "runtime_gate": runtime_gate,
        }
    from .scenario_v5_2.artifact import dashboard_projection as load_scenario_v5_2_projection
    scenario_v5_2 = load_scenario_v5_2_projection(
        root, now, maximum_age_trading_days=1
    )
    from .display_promotion import load_display_promotion
    display_promotion = load_display_promotion(root, scenario_v5_2)
    from .scenario_v4_shadow import load_shadow
    scenario_v4_shadow = load_shadow(root)
    structural_event = (
        ((scenario.get("structural_forecast") or {}).get("evidence") or {})
        .get("physical_event") or {}
    )
    if structural_event.get("question_id"):
        for row in q_summary:
            if row["id"] == structural_event["question_id"]:
                row["proximity_context"] = structural_event.get("proximity_context")
    from .event_calendar import load_events
    calendar_events = load_events(root)
    scenario_history = scenario_data.load_scenario_history(root, scenario)
    legacy_context = _latest_context_run(root)
    from .era_analog import build_era_analog
    era_analog = build_era_analog(legacy_context)
    from .cross_asset import load_cross_asset, load_cross_asset_history
    cross_asset = load_cross_asset(root)
    cross_asset_history = load_cross_asset_history(root)
    from .multi_year_stress import build_multi_year_stress
    multi_year_stress = build_multi_year_stress(cross_asset)
    from .market_extensions import load_liquidity, load_scenario_tracker
    from .statistics_lab import statistics_dashboard_projection
    from .ai_capital_cycle import load_ai_regime
    from .o_entry_cohort import load_cohort_summary
    scenario_tracker = load_scenario_tracker(root)
    liquidity = load_liquidity(root)
    statistics_lab = statistics_dashboard_projection(root)
    from .timeseries.artifact import load_projection as load_timeseries_projection
    from .timeseries_v2.artifact import load_projection as load_timeseries_v2_projection
    from .timeseries_v5.artifact import load_projection as load_timeseries_v5_projection
    from .timeseries_v8_display import load_projection as load_timeseries_v8_projection
    timeseries_v1 = load_timeseries_projection(root)
    # V8 owns this surface only while BOTH its sealed and operational gates
    # hold (the loader returns None otherwise, including on HOLD, so the
    # honest validation-pending governance below keeps rendering).  If a V5
    # pointer exists its PASS/HOLD decision owns the fallback: falling through
    # to an older model would silently hide a V5 operational failure.
    timeseries_v8 = load_timeseries_v8_projection(root)
    timeseries_v5 = load_timeseries_v5_projection(root)
    timeseries = timeseries_v8 or (
        timeseries_v5 if timeseries_v5 is not None
        else (load_timeseries_v2_projection(root) or timeseries_v1)
    )
    ai_regime = load_ai_regime(root)
    o_entry_cohort = load_cohort_summary(root)
    band_calibration_path = root / "data/scenarios/band_calibration.csv"
    band_calibration_rows: list[dict[str, str]] = []
    try:
        with band_calibration_path.open(encoding="utf-8", newline="") as handle:
            band_calibration_rows = list(csv.DictReader(handle))
    except OSError:
        band_calibration_rows = []
    band_calibration = {
        "status": "ready" if len(band_calibration_rows) >= 60 else "accumulating",
        "probability_space": "scenario_conditional",
        "source_path": "data/scenarios/band_calibration.csv",
        "observations": len(band_calibration_rows),
        "minimum_observations": 60,
        "gate_pass": len(band_calibration_rows) >= 60,
        "latest_asof": (
            band_calibration_rows[-1].get("asof") if band_calibration_rows else None
        ),
        "rows": band_calibration_rows,
    }
    method_changes = []
    try:
        method_changes = [
            json.loads(line) for line in (root / "data/method_changes.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()
        ]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        method_changes = []
    try:
        defillama_monitor = json.loads(
            (root / "data/source_monitoring/defillama_stablecoins_status.json")
            .read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        defillama_monitor = {
            "status": "not_started", "consecutive_successful_days": 0,
            "required_successful_days": 14, "license_status": "review_required",
            "activation_eligible": False,
        }

    # v2 additive intelligence surfaces. Existing keys remain backward-compatible.
    from .model_registry import arena_rows
    clusters = queries.resolution_clusters(conn)
    corrections = _rows(conn.execute(
        "SELECT * FROM correction_ledger ORDER BY created_at,correction_id"))
    probability_counts = _rows(conn.execute(
        """SELECT probability_space,source_unit,COUNT(*) AS n
           FROM probability_record GROUP BY probability_space,source_unit
           ORDER BY probability_space,source_unit"""))
    db_meta = {row["key"]: row["value"] for row in conn.execute(
        "SELECT key,value FROM db_meta")}
    trust_sources = queries.source_health(conn)
    trust = {
        "status": ("degraded" if any(item["status"] != "ok" for item in trust_sources)
                   else "ok"),
        "sources": trust_sources,
        "index": {
            "branch": db_meta.get("branch", "미산출"),
            "head": db_meta.get("head", "미산출"),
            "source_fingerprint": db_meta.get("source_fingerprint", "미산출"),
            "schema_version": db_meta.get("schema_version", "미산출"),
        },
        "quarantine_count": sum(item["quarantine_count"] for item in trust_sources),
    }
    try:
        ledger_audit = json.loads(
            (root / "docs/generated/ledger_audit.json").read_text(encoding="utf-8"))
        trust["ledgers"] = ledger_audit.get("ledgers", [])
        trust["ledger_summary"] = ledger_audit.get("summary", {})
        trust["ledger_audit_at"] = ledger_audit.get("generated_at")
    except (OSError, json.JSONDecodeError, TypeError):
        trust["ledgers"] = []
        trust["ledger_summary"] = {"status": "audit_unavailable"}
    receipts = [{
        "receipt_id": "scenario:current", "label": "현재 시장 시나리오",
        "model": scenario.get("method") or "미산출",
        "dataset": scenario.get("asof") or "미산출",
        "source": scenario.get("source") or "미산출",
        "method": scenario.get("method") or "미산출",
        "limitation": scenario.get("note") or "미산출",
        "commit": db_meta.get("head") or "미산출",
        "lineage": _rows(conn.execute(
            "SELECT upstream_type,upstream_id,relation FROM lineage_edge "
            "WHERE downstream_id='scenario' ORDER BY edge_id")),
    }]
    if cross_asset.get("status") != "blocked":
        receipts.append({
            "receipt_id": "cross-asset:current",
            "label": "NASDAQ·Bitcoin·리츠·주택주 교차자산 비교",
            "model": "downside-beta-plus-conditional-offset-v1",
            "dataset": cross_asset.get("asof") or "미산출",
            "source": " · ".join(
                item.get("label", "") for item in cross_asset.get("sources", [])
                if item.get("label")) or "미산출",
            "method": "공통거래일 수정종가·하락꼬리 beta·조건부 sensitivity",
            "limitation": cross_asset.get("forecast", {}).get("semantics") or "미산출",
            "commit": db_meta.get("head") or "미산출",
            "lineage": _rows(conn.execute(
                "SELECT upstream_type,upstream_id,relation FROM lineage_edge "
                "WHERE downstream_id='cross_asset' ORDER BY edge_id")),
            "requests": cross_asset.get("receipts") or [],
        })
    asof_index = [{
        "asof": item.get("asof"), "generated_at": item.get("generated_at"),
        "snapshot_ref": f"scenario:{item.get('asof')}", "available": True,
    } for item in scenario_history]
    asof_index.extend({
        "asof": item.get("asof"), "generated_at": item.get("generated_at"),
        "snapshot_ref": f"cross-asset:{item.get('asof')}",
        "snapshot_id": item.get("snapshot_id"), "archive": item.get("archive"),
        "revision": item.get("revision"), "correction_id": item.get("correction_id"),
        "available": True,
    } for item in cross_asset_history)
    changelog = [{
        "from": previous.get("asof"), "to": current.get("asof"),
        "anchor_delta": round(float(current.get("anchor", 0)) - float(previous.get("anchor", 0)), 2),
        "scenario_probability_delta": {
            key: int(current.get("paths", {}).get(key, {}).get("prob", 0))
                 - int(previous.get("paths", {}).get(key, {}).get("prob", 0))
            for key in ("S1", "S2", "S3")
        },
    } for previous, current in zip(scenario_history, scenario_history[1:])]
    for previous, current in zip(cross_asset_history, cross_asset_history[1:]):
        def _delta(group: str, field: str) -> float | None:
            left = previous.get(group, {}).get(field)
            right = current.get(group, {}).get(field)
            if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
                return None
            return round(float(right) - float(left), 3)
        changelog.append({
            "kind": "cross_asset",
            "from": previous.get("snapshot_id"), "to": current.get("snapshot_id"),
            "asof": current.get("asof"), "correction_id": current.get("correction_id"),
            "corr_60d_delta": {
                "bitcoin_nasdaq": _delta("corr_60d", "bitcoin_nasdaq"),
                "realty_income_nasdaq": _delta("corr_60d", "realty_income_nasdaq"),
            },
            "downside_beta_delta": {
                "bitcoin_to_nasdaq": _delta("downside_beta_5y", "bitcoin_to_nasdaq"),
                "realty_income_to_nasdaq": _delta("downside_beta_5y", "realty_income_to_nasdaq"),
            },
        })

    model = {
        "meta": {
            "generated": now.isoformat(timespec="seconds"),
            "phase": gate.get("gate_p3") and "P3" or (gate.get("gate_p2") and "P2" or "P1"),
            "n_questions": len(questions),
            "n_forecasts": sum(len(v) for v in fc_hist.values()),
            "n_resolved": gate.get("n_resolved", 0),
            "cost_month": round(queries.month_cost(conn, now.year, now.month), 2),
            "public_repository_url": config.PUBLIC_REPOSITORY_URL,
        },
        "scenario": scenario,
        "scenario_v5": scenario_v5,
        "scenario_v5_2": scenario_v5_2,
        "display_promotion": display_promotion,
        "scenario_v4_shadow": scenario_v4_shadow,
        "calendar_events": calendar_events,
        "scenario_history": scenario_history,
        "analog_context": {
            "status": era_analog["status"],
            "migrated_to": "era_analog",
        },
        "questions": q_summary,
        "forecast_history": fc_hist,
        "resolutions": resolutions,
        "ml_runs": ml_runs,
        "market_runs": market_runs,
        "calibration": calibration,
        "due": due_list,
        "trust": trust,
        "arena": arena_rows(conn),
        "receipts": receipts,
        "asof_index": asof_index,
        "clusters": clusters,
        "corrections": corrections,
        "probability_semantics": {
            "canonical_unit": "fraction", "display_unit": "percent",
            "spaces": {
                "physical_event": "실제 사건 발생 확률",
                "risk_neutral_terminal": "옵션가격 기반 위험중립 종점 분포",
                "path_touch": "경로 중 임계값 접촉 확률",
                "scenario_conditional": "시나리오 엔진 내부 조건부 가중치",
                "reference_only": "결합 금지 참고값",
            },
            "guardrail": "서로 다른 probability_space는 산술 결합하지 않습니다.",
            "counts": probability_counts,
        },
        "changelog": changelog,
        "era_analog": era_analog,
        "cross_asset": cross_asset,
        "scenario_tracker": scenario_tracker,
        "band_calibration": band_calibration,
        "liquidity": liquidity,
        "statistics_lab": statistics_lab,
        "timeseries": timeseries,
        "multi_year_stress": multi_year_stress,
        "ai_regime": ai_regime,
        "o_entry_cohort": o_entry_cohort,
        "source_monitoring": {"defillama_stablecoins": defillama_monitor},
        "method_changes": method_changes,
    }
    from .read_model_contract import assert_valid
    assert_valid(model)
    return _normalize_presentation_copy(model)


def _latest_context_run(root: Path) -> dict | None:
    """ml_history 최신 kind:'context' run — 다중 시대 오버레이·레짐 (커밋 데이터, 정적 안전)."""
    try:
        from .ml.history import iter_history
        latest = None
        latest_knn = None
        for run in iter_history(root):
            if run.get("kind") == "context":
                latest = run
            elif run.get("kind") == "dualdb_model_run" and run.get("model") == "knn_analog":
                latest_knn = run
        if latest_knn is None:
            try:
                latest_knn = json.loads(
                    (root / "data/model_runs/knn_analog_latest.json")
                    .read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                latest_knn = None
        if latest is not None and latest_knn is not None:
            latest = json.loads(json.dumps(latest))
            analog = latest.setdefault("analog", {})
            analog["model_run_asof"] = latest_knn.get("asof")
            analog["model_run_id"] = latest_knn.get("run_id")
            analog["forward_cases"] = latest_knn.get("neighbors") or []
        return latest
    except Exception:  # noqa: BLE001 — 부재 시 대시보드는 해당 패널만 생략
        return None


def load_template(*, include_qr: bool = True) -> str:
    """소스 partial을 단일 HTML shell로 조립한다.

    The standalone audit snapshot omits the optional QR encoder so the core
    read model remains inside its fixed 900 KiB budget.  GitHub Pages keeps the
    encoder and therefore preserves the customer sharing control.
    """
    shell = TEMPLATE.read_text(encoding="utf-8")
    styles = DASHBOARD_STYLES.read_text(encoding="utf-8")
    script_parts = [DASHBOARD_LOOKUP_SCRIPT.read_text(encoding="utf-8")]
    if include_qr:
        script_parts.append(DASHBOARD_QR_SCRIPT.read_text(encoding="utf-8"))
    script_parts.append(DASHBOARD_SCRIPT.read_text(encoding="utf-8"))
    script = "\n".join(script_parts)
    for marker in ("<!--STYLES-->", "<!--APP_SCRIPT-->", "<!--ANALYTICS-->"):
        if marker not in shell:
            raise ValueError(f"dashboard template marker missing: {marker}")
    # <!--ANALYTICS-->는 여기서 치환하지 않는다 — 자기완결 감사 HTML(embed)에는
    # 외부 스크립트가 들어가면 안 되므로, render_html이 pages 모드에서만 채운다
    # (WEBFONTS와 같은 규칙).
    return shell.replace("<!--STYLES-->", styles).replace("<!--APP_SCRIPT-->", script)


def _analytics_snippet(code: str | None = None) -> str:
    """GoatCounter 스니펫 — 쿠키 없는 집계 페이지뷰 카운터.

    해시 라우팅 대시보드라 기본 pathname 집계로는 모든 방문이 "/" 하나로
    뭉친다. path 콜백으로 해시(#statistics 등)를 경로에 포함시키고,
    hashchange마다 수동 카운트해 화면 단위 유입·이용 통계를 만든다.
    개인 식별 정보는 수집하지 않는다 (GoatCounter는 쿠키·핑거프린팅 없이
    referrer·국가·브라우저·경로만 집계).
    """
    resolved = GOATCOUNTER_CODE if code is None else code
    if not resolved:
        return ""
    endpoint = f"https://{resolved}.goatcounter.com/count"
    return (
        "<script>window.goatcounter={path:function(){return "
        "location.pathname+location.search+location.hash}};"
        "window.addEventListener('hashchange',function(){"
        "if(window.goatcounter.count)window.goatcounter.count({"
        "path:location.pathname+location.search+location.hash})});</script>"
        f"<script data-goatcounter=\"{endpoint}\" async "
        "src=\"https://gc.zgo.at/count.js\"></script>"
    )


def _future_path_checkpoints(candidate: dict) -> list[dict]:
    dates = (candidate.get("distribution") or {}).get("dates") or []
    scenarios = ((candidate.get("conditional_small_multiples") or {})
                 .get("scenarios") or {})
    if not dates or not scenarios:
        return []
    as_of = datetime.fromisoformat(str(candidate["as_of"])).date()
    observed_dates = [date.fromisoformat(value) for value in dates]
    targets = (
        ("1개월", as_of + timedelta(days=30)),
        ("3개월", as_of + timedelta(days=90)),
        ("2026년 말", date(2026, 12, 31)),
        ("2027년 말", observed_dates[-1]),
    )
    checkpoints = []
    used: set[int] = set()
    anchor_value = (candidate.get("anchor") or {})
    anchor = float((anchor_value.get("close") or 0)
                   if isinstance(anchor_value, dict) else anchor_value or 0)
    for label, target in targets:
        index = min(
            range(len(observed_dates)),
            key=lambda item: abs(observed_dates[item] - target),
        )
        if index in used:
            continue
        used.add(index)
        values = {
            key: round(float(row["bands"]["p50"][index]), 2)
            for key, row in scenarios.items() if row.get("bands", {}).get("p50")
        }
        checkpoints.append({
            "label": label,
            "date": dates[index],
            "p50": values,
            "return_from_anchor": {
                key: round(value / anchor - 1.0, 6) if anchor else None
                for key, value in values.items()
            },
        })
    return checkpoints


def split_future_paths(read_model: dict) -> tuple[dict, dict | None]:
    """Move route-only arrays into a bounded lazy artifact without mutating input."""
    existing = (read_model.get("scenario_v5_2") or {}).get("deferred_paths") or {}
    if existing.get("required"):
        return read_model, None
    base = dict(read_model)
    deferred = {
        key: base.pop(key) for key in FUTURE_DEFERRED_KEYS if key in base
    }
    candidate = deferred.get("scenario_v5_2") or {}
    candidate_has_paths = bool(candidate.get("conditional_small_multiples"))
    if candidate and not candidate_has_paths:
        # A projection without path arrays (candidate missing, or its content
        # integrity failed) has nothing to defer and no semantic reference to
        # match, so a deferred_paths marker would send the front end into a
        # fetch that can only fail with a misleading network-style error.
        # Keeping the (small) summary inline routes the front end to
        # renderFlow's gate-reason screen instead — no chart is substituted.
        # A closed gate WITH content ("stale_last_valid", owner-approved
        # DECISIONS.md 2026-09-02) defers normally below so the last valid
        # chart can render with its explicit disclosure.
        base["scenario_v5_2"] = candidate
    elif candidate:
        model = candidate.get("model") or {}
        base["scenario_v5_2"] = {
            "schema_version": candidate.get("schema_version"),
            "status": candidate.get("status"),
            "candidate_id": candidate.get("candidate_id"),
            "semantic_reference": candidate.get("semantic_reference"),
            "banner": candidate.get("banner"),
            "as_of": candidate.get("as_of"),
            "runtime_gate": candidate.get("runtime_gate"),
            "governance": candidate.get("governance"),
            "anchor": candidate.get("anchor"),
            "model": {
                "model_id": model.get("model_id"),
                "path_count": model.get("path_count"),
                "hard_event_mapping": model.get("hard_event_mapping"),
            },
            "path_checkpoints": _future_path_checkpoints(candidate),
            "deferred_paths": {
                "required": True,
                "loaded": False,
                "url": FUTURE_PATHS_FILENAME,
                "failure_mode": "summary_with_explicit_banner",
            },
        }
    era = deferred.get("era_analog") or {}
    context = era.get("context") or {}
    base["era_analog"] = {
        "status": era.get("status"),
        "context": {
            "regime": context.get("regime") or {},
            "breadth": context.get("breadth") or {},
        },
        "deferred": True,
    }
    payload = {
        "schema_version": 1,
        "contract_id": "future_paths_v1",
        "semantic_reference": candidate.get("semantic_reference"),
        "data": deferred,
    }
    payload_size = len(json.dumps(
        payload, ensure_ascii=False, default=str, separators=(",", ":")
    ).encode("utf-8"))
    if payload_size > FUTURE_PATHS_BUDGET_BYTES:
        raise ValueError(
            f"future paths budget exceeded: {payload_size} > {FUTURE_PATHS_BUDGET_BYTES}"
        )
    if payload_size > FUTURE_PATHS_BUDGET_BYTES * PAYLOAD_WARN_RATIO:
        print(
            f"warning: future_paths.json {payload_size}B is "
            f"{payload_size / FUTURE_PATHS_BUDGET_BYTES:.1%} of its budget"
        )
    return base, payload


def split_statistics_data(read_model: dict) -> tuple[dict, dict | None]:
    """Move statistics-only chart coordinates into an independently bounded route artifact."""
    existing = (read_model.get("statistics_lab") or {}).get("deferred_data") or {}
    if existing.get("required"):
        return read_model, None
    if "statistics_lab" not in read_model:
        return read_model, None
    base = dict(read_model)
    statistics_lab = base.pop("statistics_lab")
    if statistics_lab.get("status") != "ok":
        base["statistics_lab"] = statistics_lab
        return base, None
    base["statistics_lab"] = {
        "schema_version": statistics_lab.get("schema_version"),
        "dataset_id": statistics_lab.get("dataset_id"),
        "status": statistics_lab.get("status"),
        "generated_at": statistics_lab.get("generated_at"),
        "as_of": statistics_lab.get("as_of"),
        "cycle_alignment": statistics_lab.get("cycle_alignment"),
        "chart_count": len(statistics_lab.get("charts") or []),
        "source_count": len(statistics_lab.get("sources") or []),
        "deferred_data": {
            "required": True,
            "loaded": False,
            "url": STATISTICS_DATA_FILENAME,
            "failure_mode": "summary_with_explicit_error",
        },
    }
    payload = {
        "schema_version": 1,
        "contract_id": "statistics_route_v1",
        "data": {"statistics_lab": statistics_lab},
    }
    payload_size = len(json.dumps(
        payload, ensure_ascii=False, default=str, separators=(",", ":")
    ).encode("utf-8"))
    if payload_size > STATISTICS_DATA_BUDGET_BYTES:
        raise ValueError(
            f"statistics data budget exceeded: {payload_size} > {STATISTICS_DATA_BUDGET_BYTES}"
        )
    if payload_size > STATISTICS_DATA_BUDGET_BYTES * PAYLOAD_WARN_RATIO:
        print(
            f"warning: statistics.json {payload_size}B is "
            f"{payload_size / STATISTICS_DATA_BUDGET_BYTES:.1%} of its budget"
        )
    return base, payload


def _compact_embed_forecast_history(read_model: dict) -> dict:
    """Keep active latest reasoning inline and link archived rounds to source.

    Pages and API modes retain the complete read model.  The standalone embed
    has a fixed 900 KiB contract, so superseded forecast bodies are omitted
    only at this serialization boundary. Bodies for resolved questions are
    archived the same way because they are no longer an active forecast view.
    Their structured fields and immutable ``source_uri`` remain available,
    and the input model is never mutated.
    """
    history = read_model.get("forecast_history")
    if not isinstance(history, dict):
        return read_model
    resolved = {
        row.get("id") for row in (read_model.get("questions") or [])
        if isinstance(row, dict) and row.get("status") == "resolved"
    }
    compacted = dict(read_model)
    compacted["forecast_history"] = {
        question_id: [
            (
                {key: value for key, value in row.items() if key != "body"}
                if index < len(rows) - 1 or question_id in resolved else dict(row)
            )
            for index, row in enumerate(rows)
        ]
        for question_id, rows in history.items()
    }
    return compacted


def _compact_embed_band_calibration(read_model: dict) -> dict:
    """Archive raw band-calibration rows out of the standalone snapshot.

    The dashboard UI renders only the aggregate promotion-gate counters
    (status/observations/gate_pass), never the per-day rows, so the embed
    keeps every rendered figure while the row-level ledger stays published
    unchanged in the Pages ``data.json`` payload, the ``/api/data`` route and
    the immutable source CSV referenced by ``source_path``.  This mirrors the
    resolved-forecast-body archival: transport changes, information does not.
    """
    band = read_model.get("band_calibration")
    if not isinstance(band, dict) or "rows" not in band:
        return read_model
    compacted = dict(read_model)
    archived = {key: value for key, value in band.items() if key != "rows"}
    archived["rows_archived"] = {
        "archived": True,
        "row_count": len(band.get("rows") or []),
        "reason": "embed_size_budget",
        "source_path": band.get("source_path"),
        "full_payload": "data.json",
    }
    compacted["band_calibration"] = archived
    return compacted


# Append-only governance sections keep gaining provenance columns that the UI
# never renders, so the standalone embed used to track that growth row by row.
# An explicit allowlist of rendered fields bounds the fixed 900 KiB contract
# against future column growth.  Each section below has a single consumer in
# dashboard.js and the listed fields are exactly the ones it reads; Pages
# ``data.json``, ``/api/data`` and the immutable sources keep every column.
EMBED_RENDERED_FIELDS = {
    # dashboard.js decisionJournal(): filters on kind, renders the rest.
    "method_changes": ("kind", "date", "title", "reason", "snapshot_id", "report"),
    # dashboard.js correction-card: status/field_name/old_value/reason only.
    "corrections": ("status", "field_name", "old_value", "reason"),
    # dashboard.js calendar strip + scenario event overlay.
    "calendar_events": (
        "event_id", "source_id", "source_url", "title", "date",
        "status", "kind", "time_et", "ticker",
    ),
}


def _project_embed_rows(read_model: dict) -> dict:
    """Carry only rendered columns for append-only list sections in the embed.

    Mirrors the resolved-forecast-body and band-calibration archival: transport
    changes, information does not.  The dropped column names are disclosed in
    ``embed_field_projection`` so a reader of the standalone snapshot can see
    what was omitted and where the complete payload lives.  The input model is
    never mutated.
    """
    projected = dict(read_model)
    sections: dict[str, dict] = {}
    for key, allowed in EMBED_RENDERED_FIELDS.items():
        rows = read_model.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        dropped = sorted({
            field
            for row in rows if isinstance(row, dict)
            for field in row if field not in allowed
        })
        if not dropped:
            continue
        projected[key] = [
            {field: value for field, value in row.items() if field in allowed}
            if isinstance(row, dict) else row
            for row in rows
        ]
        sections[key] = {
            "row_count": len(rows),
            "kept_fields": list(allowed),
            "dropped_fields": dropped,
        }
    if sections:
        projected["embed_field_projection"] = {
            "projected": True,
            "reason": "embed_size_budget",
            "full_payload": "data.json",
            "sections": sections,
        }
    return projected


# Reasoning bodies are the largest single term in the embed and they scale with
# the number of active questions, not with feature work.  Under the ADR-002
# budget they all fit -- _compact_embed_forecast_history has already dropped the
# superseded and resolved ones, so what remains is one per active question.
# This limit is now a backstop against a pathological single body rather than a
# routine cap: it sits above the active-question count so it does not bite in
# normal operation, and rounds beyond it keep every structured field and their
# immutable source_uri.  Pages data.json and /api/data keep every body.
EMBED_INLINE_BODY_LIMIT = 40


def _limit_embed_inline_bodies(read_model: dict) -> dict:
    """Inline only the newest reasoning bodies; link the older ones.

    Applied after :func:`_compact_embed_forecast_history`, which has already
    dropped superseded and resolved bodies.  What remains is one body per
    active question, which still outgrows the fixed contract as the registry
    fills.  Rounds beyond the limit keep every structured field and their
    ``source_uri``; the omission is disclosed in ``embed_body_budget``.  The
    input model is never mutated.
    """
    history = read_model.get("forecast_history")
    if not isinstance(history, dict):
        return read_model
    carried = sorted(
        (
            (str(row.get("forecast_ts") or ""), question_id, index)
            for question_id, rows in history.items()
            for index, row in enumerate(rows)
            if isinstance(row, dict) and row.get("body")
        ),
        reverse=True,
    )
    if len(carried) <= EMBED_INLINE_BODY_LIMIT:
        return read_model
    keep = {(qid, index) for _, qid, index in carried[:EMBED_INLINE_BODY_LIMIT]}
    limited = dict(read_model)
    limited["forecast_history"] = {
        question_id: [
            row if (question_id, index) in keep or not row.get("body")
            else {key: value for key, value in row.items() if key != "body"}
            for index, row in enumerate(rows)
        ]
        for question_id, rows in history.items()
    }
    limited["embed_body_budget"] = {
        "limited": True,
        "reason": "embed_size_budget",
        "inline_bodies": EMBED_INLINE_BODY_LIMIT,
        "linked_bodies": len(carried) - EMBED_INLINE_BODY_LIMIT,
        "full_payload": "data.json",
        "source_field": "source_uri",
    }
    return limited


def render_html(read_model: dict, mode: str = "embed") -> str:
    shell = _compact_static_bundle(load_template(include_qr=mode != "embed"))
    webfonts = ""
    if mode == "pages":
        webfonts = "\n".join((
            '<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>',
            f'<link rel="preload" as="style" href="{WANTED_SANS_CSS}" crossorigin>',
            f'<link rel="stylesheet" href="{WANTED_SANS_CSS}" crossorigin>',
        ))
    shell = shell.replace("<!--WEBFONTS-->", webfonts)
    shell = shell.replace(
        "<!--ANALYTICS-->", _analytics_snippet() if mode == "pages" else ""
    )
    scenario = read_model.get("scenario") or {}
    asof = scenario.get("asof") or "latest registered snapshot"
    og_title = f"Jin's Investing Prediction · {asof}"
    og_description = "조건부 시장 시나리오를 불변 기록과 함께 읽습니다. 단일 가격 제시·투자자문이 아닙니다."
    og_image = "https://sung-jinpark.github.io/Jin-s-investing-prediction/og/market-snapshot.png"
    og_meta = "\n".join((
        f'<meta property="og:title" content="{html_lib.escape(og_title, quote=True)}">',
        f'<meta property="og:description" content="{html_lib.escape(og_description, quote=True)}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:url" content="https://sung-jinpark.github.io/Jin-s-investing-prediction/">',
        f'<meta property="og:image" content="{og_image}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{html_lib.escape(og_title, quote=True)}">',
        f'<meta name="twitter:description" content="{html_lib.escape(og_description, quote=True)}">',
        f'<meta name="twitter:image" content="{og_image}">',
    ))
    shell = shell.replace("<!--OG_META-->", og_meta)
    if mode == "embed":
        read_model, _ = split_statistics_data(read_model)
        read_model, _ = split_future_paths(read_model)
        read_model = _compact_embed_forecast_history(read_model)
        read_model = _limit_embed_inline_bodies(read_model)
        read_model = _compact_embed_band_calibration(read_model)
        read_model = _project_embed_rows(read_model)
        # Compact only the embedded JSON. Source CSS/JS remain readable and testable;
        # removing JSON's repeated separator spaces keeps the standalone snapshot compact.
        blob = json.dumps(
            read_model, ensure_ascii=False, default=str, separators=(",", ":")
        )
        data_script = (
            f'<script>window.__FUTURE_PATHS_URL__ = "{FUTURE_PATHS_FILENAME}";'
            f'window.__STATISTICS_URL__ = "{STATISTICS_DATA_FILENAME}";'
            f"window.__DATA__ = {blob};</script>"
        )
    elif mode == "pages":
        data_script = (
            '<script>window.__DATA_URL__ = "data.json";'
            f'window.__FUTURE_PATHS_URL__ = "{FUTURE_PATHS_FILENAME}";'
            f'window.__STATISTICS_URL__ = "{STATISTICS_DATA_FILENAME}";</script>'
        )
    elif mode == "fetch":
        data_script = (
            '<script>window.__DATA_URL__ = "/api/data";'
            'window.__FUTURE_PATHS_URL__ = "/api/future-paths";'
            'window.__STATISTICS_URL__ = "/api/statistics";</script>'
        )
    else:
        raise ValueError(f"unknown dashboard render mode: {mode}")
    html = shell.replace("<!--DATA-->", data_script)
    if mode == "embed" and len(html.encode("utf-8")) > DASHBOARD_RAW_BUDGET_BYTES:
        raise ValueError(
            f"dashboard raw size budget exceeded: "
            f"{len(html.encode('utf-8'))} > {DASHBOARD_RAW_BUDGET_BYTES}"
        )
    return html


def _compact_static_bundle(html: str) -> str:
    """Compact authored static assets without parsing or rewriting JavaScript tokens."""
    def compact_style(match: re.Match[str]) -> str:
        body = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)
        body = "".join(line.strip() for line in body.splitlines())
        body = re.sub(r"\s*([{}:;,>])\s*", r"\1", body).replace(";}", "}")
        return f"<style>{body}</style>"

    def compact_script(match: re.Match[str]) -> str:
        lines = []
        for line in match.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            lines.append(stripped)
        # Keep one separator between authored lines.  Removing it can merge valid
        # tokens such as ``else`` + ``if`` into the invalid identifier ``elseif``.
        return "<script>" + " ".join(lines) + "</script>"

    html = re.sub(r"<style>(.*?)</style>", compact_style, html, flags=re.S)
    html = re.sub(r"<script>(.*?)</script>", compact_script, html, flags=re.S)
    return "\n".join(line.strip() for line in html.splitlines() if line.strip())


def write_dashboard(conn: sqlite3.Connection, root: Path) -> Path:
    model = build_read_model(conn, root)
    base, statistics_data = split_statistics_data(model)
    base, future_paths = split_future_paths(base)
    out = root / "reports" / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(base, mode="embed"), encoding="utf-8")
    if future_paths is not None:
        (out.parent / FUTURE_PATHS_FILENAME).write_text(
            json.dumps(
                future_paths, ensure_ascii=False, default=str,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    if statistics_data is not None:
        (out.parent / STATISTICS_DATA_FILENAME).write_text(
            json.dumps(
                statistics_data, ensure_ascii=False, default=str,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    return out


def _write_og_image(model: dict, target: Path) -> None:
    """Render the social preview locally; no browser, CDN or remote font required."""
    from PIL import Image, ImageDraw, ImageFont

    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1200, 630), "#f2eee6")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("DejaVuSans.ttf", 56)
        label_font = ImageFont.truetype("DejaVuSans.ttf", 23)
        metric_font = ImageFont.truetype("DejaVuSans.ttf", 43)
    except OSError:
        title_font = label_font = metric_font = ImageFont.load_default()
    draw.rounded_rectangle((42, 38, 1158, 592), 30, fill="#fbf8f2", outline="#d8d0c4", width=2)
    draw.rounded_rectangle((42, 38, 62, 592), 10, fill="#27705d")
    draw.text((104, 92), "JIN'S INVESTING / PREDICTION", fill="#27705d", font=label_font)
    draw.text((104, 145), "Market paths, with provenance.", fill="#151815", font=title_font)
    scenario = model.get("scenario") or {}
    paths = scenario.get("paths") or {}
    labels = [("UPSIDE", paths.get("S1", {}).get("prob", 0), "#bf571b"),
              ("RECOVERY", paths.get("S2", {}).get("prob", 0), "#c57a10"),
              ("DOWNSIDE", paths.get("S3", {}).get("prob", 0), "#8d2943")]
    for index, (label, value, color) in enumerate(labels):
        left = 104 + index * 320
        draw.text((left, 286), label, fill="#6c6a64", font=label_font)
        draw.text((left, 326), f"{value}%", fill=color, font=metric_font)
    draw.line((104, 433, 1094, 433), fill="#d8d0c4", width=2)
    asof = scenario.get("asof") or "latest"
    draw.text((104, 463), f"AS OF {asof}", fill="#474a45", font=label_font)
    draw.text((104, 520), "CONDITIONAL SCENARIO  ·  NOT INVESTMENT ADVICE", fill="#7a4d10", font=label_font)
    image.save(target, format="PNG", optimize=True)


def write_pages(conn: sqlite3.Connection, out_dir: Path, root: Path) -> Path:
    """GitHub Pages static bundle with a cacheable local JSON data artifact.

    CI에서 커밋된 불변 파일로 DB를 재구축(sync --rebuild)한 뒤 호출한다.
    데이터는 전부 공개 repo에 이미 존재하는 예측 기록 — 새 노출 없음.
    """
    model = build_read_model(conn, root)
    base, statistics_data = split_statistics_data(model)
    base, future_paths = split_future_paths(base)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"
    index.write_text(render_html(model, mode="pages"), encoding="utf-8")
    _write_og_image(model, out_dir / "og" / "market-snapshot.png")
    base_json = json.dumps(base, ensure_ascii=False, default=str, separators=(",", ":"))
    base_size = len(base_json.encode("utf-8"))
    if base_size > DATA_JSON_BUDGET_BYTES:
        raise ValueError(
            f"data.json budget exceeded: {base_size} > {DATA_JSON_BUDGET_BYTES}"
        )
    if base_size > DATA_JSON_BUDGET_BYTES * PAYLOAD_WARN_RATIO:
        print(
            f"warning: data.json {base_size}B is "
            f"{base_size / DATA_JSON_BUDGET_BYTES:.1%} of its budget"
        )
    (out_dir / "data.json").write_text(base_json, encoding="utf-8")
    if future_paths is not None:
        (out_dir / FUTURE_PATHS_FILENAME).write_text(
            json.dumps(
                future_paths, ensure_ascii=False, default=str,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    if statistics_data is not None:
        (out_dir / STATISTICS_DATA_FILENAME).write_text(
            json.dumps(
                statistics_data, ensure_ascii=False, default=str,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
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
                    model, _ = split_statistics_data(build_read_model(conn, root))
                    model, _ = split_future_paths(model)
                finally:
                    conn.close()
                body = json.dumps(model, ensure_ascii=False, default=str).encode("utf-8")
                self._send(body, "application/json; charset=utf-8")
            elif self.path.startswith("/api/future-paths"):
                conn = ingest.connect(db_path)
                try:
                    _, future_paths = split_future_paths(build_read_model(conn, root))
                finally:
                    conn.close()
                body = json.dumps(
                    future_paths, ensure_ascii=False, default=str,
                    separators=(",", ":"),
                ).encode("utf-8")
                self._send(body, "application/json; charset=utf-8")
            elif self.path.startswith("/api/statistics"):
                conn = ingest.connect(db_path)
                try:
                    _, statistics_data = split_statistics_data(build_read_model(conn, root))
                finally:
                    conn.close()
                body = json.dumps(
                    statistics_data, ensure_ascii=False, default=str,
                    separators=(",", ":"),
                ).encode("utf-8")
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
