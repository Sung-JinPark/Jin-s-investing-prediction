"""내부 대시보드 — 예측 흐름 조회 사이트 (읽기 전용, 자기완결 HTML + stdlib 서버).

설계 원칙:
- 읽기 전용: 웹에서 예측 실행(forecast) 없음. 불변 파일 + SQLite 인덱스를 조회만.
- 의존성 0 추가: 표준 라이브러리 http.server + 인라인 CSS/바닐라 JS (CDN·프레임워크 없음).
- 두 모드: (1) 자기완결 스냅샷 HTML(reports/dashboard.html), (2) `--serve` LAN 서버.
- 지위: 참고 의견 (P3 게이트 전). 데이터는 공개 예측 기록 — 시크릿 미포함.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from . import config, scenario as scenario_data
from .db import ingest, queries

TEMPLATE = Path(__file__).parent / "dashboard_template.html"
DASHBOARD_PARTS = Path(__file__).parent / "dashboard_parts"
DASHBOARD_STYLES = DASHBOARD_PARTS / "dashboard.css"
DASHBOARD_LOOKUP_SCRIPT = DASHBOARD_PARTS / "forecast_lookup.js"
DASHBOARD_QR_SCRIPT = DASHBOARD_PARTS / "qr-creator.min.js"
DASHBOARD_SCRIPT = DASHBOARD_PARTS / "dashboard.js"
DASHBOARD_RAW_BUDGET_BYTES = 1_000_000

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
    scenario_history = scenario_data.load_scenario_history(root, scenario)
    legacy_context = _latest_context_run(root)
    from .era_analog import build_era_analog
    era_analog = build_era_analog(legacy_context)
    from .cross_asset import load_cross_asset, load_cross_asset_history
    cross_asset = load_cross_asset(root)
    cross_asset_history = load_cross_asset_history(root)
    from .market_extensions import load_liquidity, load_scenario_tracker
    from .ai_capital_cycle import load_ai_regime
    scenario_tracker = load_scenario_tracker(root)
    liquidity = load_liquidity(root)
    ai_regime = load_ai_regime(root)
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
            "label": "BTC·NASDAQ·Realty Income 자산 전이",
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
        "liquidity": liquidity,
        "ai_regime": ai_regime,
        "source_monitoring": {"defillama_stablecoins": defillama_monitor},
        "method_changes": method_changes,
    }
    from .read_model_contract import assert_valid
    assert_valid(model)
    return model


def _latest_context_run(root: Path) -> dict | None:
    """ml_history 최신 kind:'context' run — 다중 시대 오버레이·레짐 (커밋 데이터, 정적 안전)."""
    try:
        from .ml.history import iter_history
        latest = None
        for run in iter_history(root):
            if run.get("kind") == "context":
                latest = run
        return latest
    except Exception:  # noqa: BLE001 — 부재 시 대시보드는 해당 패널만 생략
        return None


def load_template() -> str:
    """소스 partial을 외부 요청 없는 단일 HTML shell로 조립한다."""
    shell = TEMPLATE.read_text(encoding="utf-8")
    styles = DASHBOARD_STYLES.read_text(encoding="utf-8")
    script = "\n".join((
        DASHBOARD_LOOKUP_SCRIPT.read_text(encoding="utf-8"),
        DASHBOARD_QR_SCRIPT.read_text(encoding="utf-8"),
        DASHBOARD_SCRIPT.read_text(encoding="utf-8"),
    ))
    for marker in ("<!--STYLES-->", "<!--APP_SCRIPT-->"):
        if marker not in shell:
            raise ValueError(f"dashboard template marker missing: {marker}")
    return shell.replace("<!--STYLES-->", styles).replace("<!--APP_SCRIPT-->", script)


def render_html(read_model: dict, mode: str = "embed") -> str:
    shell = _compact_static_bundle(load_template())
    scenario = read_model.get("scenario") or {}
    asof = scenario.get("asof") or "latest registered snapshot"
    og_title = f"Jin's Investing Prediction · {asof}"
    og_description = "조건부 시장 시나리오를 불변 기록과 함께 읽습니다. 목표가·투자자문이 아닙니다."
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
        # Compact only the embedded JSON. Source CSS/JS remain readable and testable;
        # removing JSON's repeated separator spaces keeps the standalone snapshot compact.
        blob = json.dumps(
            read_model, ensure_ascii=False, default=str, separators=(",", ":")
        )
        data_script = f"<script>window.__DATA__ = {blob};</script>"
    elif mode == "pages":
        data_script = '<script>window.__DATA_URL__ = "data.json";</script>'
    elif mode == "fetch":
        data_script = '<script>window.__DATA_URL__ = "/api/data";</script>'
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
        # The authored bundle uses explicit semicolons and has no ASI-sensitive bare
        # return/throw lines (covered by the UI contract test), so line joins are safe.
        return "<script>" + "".join(lines) + "</script>"

    html = re.sub(r"<style>(.*?)</style>", compact_style, html, flags=re.S)
    html = re.sub(r"<script>(.*?)</script>", compact_script, html, flags=re.S)
    return "\n".join(line.strip() for line in html.splitlines() if line.strip())


def write_dashboard(conn: sqlite3.Connection, root: Path) -> Path:
    model = build_read_model(conn, root)
    out = root / "reports" / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(model, mode="embed"), encoding="utf-8")
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
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"
    index.write_text(render_html(model, mode="pages"), encoding="utf-8")
    _write_og_image(model, out_dir / "og" / "market-snapshot.png")
    (out_dir / "data.json").write_text(
        json.dumps(model, ensure_ascii=False, default=str, separators=(",", ":")),
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
