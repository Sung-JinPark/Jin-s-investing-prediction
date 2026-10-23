"""ML 참조 채점 원장 — ML_M4_REFERENCE_SCORING (라이브 전진만 · 기록·표시만).

계약: data/contracts/ml_technique_m4_reference_scoring.yaml (결과 전 커밋, 블루프린트 §6).
원장: data/ml_reference/ledgers/reference_scores.jsonl (append-only, append_unique).

무엇을 채점하나 (ml_history 의 kind=ml run 행마다):
  ① question_probs — 모델별(bolt/c2/t5/gbm/ensemble/quantile) 확률을 질문의 실제 결과로
     Brier 채점. 결과는 calibration/ledger.csv 해소 행에서만 읽는다 (읽기 전용 — 레지스트리는
     fixed/rolling 구분용). rolling 질문은 forecast_date 가 run 일자 ±ROLLING_MATCH_DAYS 인
     원장 행만 같은 창으로 본다.
  ② series_bands — 지평 종점 분위수(q10~q90)를 실현 종가로 pinball(5레벨)·p10–p90 커버리지·
     CRPS 5분위 근사로 채점. 실현치는 봉인 V2 아카이브(read-only): ^IXIC → NASDAQCOM
     (Yahoo ^IXIC 와 FRED NASDAQCOM 은 같은 Nasdaq Composite 종가), ^VIX → VIX.
     SOXX 는 승인된 공식 원천이 없어 unresolvable_no_licensed_source 로 기록만 한다.
     baseline 은 같은 run 의 series_bands[k].gbm(mu_w·sigma_w) 로 만든 GBM 분위수.

무엇을 하지 않나: 멤버 가중·강등·승격 없음, 공식 확률 대체 없음, pre_registration 행은
요약 통계에서 제외, 홀드아웃·설계창 채점 없음. 성숙 판정은 달력이 아니라 아카이브 거래일
인덱스(V13 resolve.py 방식)로 한다.

행 키에 forecasts/sentiment/market/question_probs 를 쓰지 않는다 (ml_history 소비자와 충돌 방지).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import NormalDist, mean
from typing import Any

import yaml

from .. import config
from .. import files as F
from ..registry import load_registry
from ..timeseries_v2.market_archive import read_market_observations
from ..timeseries_v8.artifact import append_unique, read_ledger
from ..timeseries_v8.contracts import canonical_hash
from .history import iter_history

CONTRACT_RELATIVE = Path(config.ML_REFERENCE_CONTRACT)
LEDGER_RELATIVE = Path(config.ML_REFERENCE_LEDGER)
TECHNIQUE_ID = "ML_M4_REFERENCE_SCORING"
SCHEMA_VERSION = 1

LEVELS: dict[str, float] = {"q10": 0.10, "q25": 0.25, "q50": 0.50, "q75": 0.75, "q90": 0.90}
# Yahoo 심볼 → 봉인 V2 아카이브 series_id. ^IXIC 와 NASDAQCOM 은 같은 지수(Nasdaq Composite).
SYMBOL_TO_ARCHIVE: dict[str, str | None] = {"^IXIC": "NASDAQCOM", "^VIX": "VIX", "SOXX": None}
CALENDAR_PROXY_SERIES = "NASDAQCOM"   # 아카이브 없는 시리즈(SOXX)의 성숙 판정용 거래일 인덱스
UNRESOLVABLE = "unresolvable_no_licensed_source"
FORBIDDEN_ROW_KEYS = ("forecasts", "sentiment", "market", "question_probs")
ROLLING_MATCH_DAYS = 3


# ── 계약·입력 ─────────────────────────────────────────────────────

def load_contract(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("technique_id") != TECHNIQUE_ID:
        raise ValueError("ML 참조 채점 계약이 아니다")
    if not str(payload.get("decision_rule", "")).startswith("기록·표시만"):
        raise ValueError("계약 decision_rule 이 '기록·표시만' 이 아니다 — 이 모듈은 판정하지 않는다")
    return payload


def registered_date(contract: dict[str, Any]) -> date:
    return date.fromisoformat(str(contract["registered"]))


def _run_date(run_ts: str) -> date:
    return date.fromisoformat(run_ts[:10])


def _friday_of_week(d: date) -> date:
    """Yahoo 1wk 봉(월요일 anchor)의 종점 = 그 주 금요일. 토·일도 같은 주의 금요일."""
    return d - timedelta(days=d.weekday()) + timedelta(days=4)


def target_session(run_date: date, horizon_weeks: int) -> date:
    """지평 종점의 목표일 — run 주 금요일 + 7·h 일. 실현 세션은 이 날짜 이하의 마지막 아카이브 세션."""
    return _friday_of_week(run_date) + timedelta(days=7 * int(horizon_weeks))


@dataclass(frozen=True)
class ArchiveSeries:
    dates: tuple[str, ...]
    values: tuple[float, ...]

    def last_on_or_before(self, day: date) -> tuple[str, float] | None:
        iso = day.isoformat()
        best = None
        for d, v in zip(self.dates, self.values):
            if d <= iso:
                best = (d, v)
            else:
                break
        return best

    @property
    def last_date(self) -> str | None:
        return self.dates[-1] if self.dates else None


def read_archive(root: Path, knowledge_cutoff: str) -> dict[str, ArchiveSeries]:
    """봉인 V2 아카이브 읽기 전용 — available_at ≤ knowledge_cutoff 인 관측만."""
    by: dict[str, list[tuple[str, float]]] = {}
    for row in read_market_observations(root, knowledge_cutoff=knowledge_cutoff):
        by.setdefault(row.series_id, []).append((str(row.observation_time)[:10], float(row.value)))
    out: dict[str, ArchiveSeries] = {}
    for sid, rows in by.items():
        rows.sort()
        out[sid] = ArchiveSeries(tuple(d for d, _ in rows), tuple(v for _, v in rows))
    return out


# ── 지표 (결정론 수식 — 적합 없음) ─────────────────────────────────

def pinball(q: float, y: float, tau: float) -> float:
    diff = y - q
    return max(tau * diff, (tau - 1.0) * diff)


def score_quantiles(quantiles: dict[str, float], y: float, scale: float) -> dict[str, Any]:
    """5분위 밴드 vs 실현치 y. pinball 레벨별·평균, 80% 커버리지, CRPS 5분위 근사, scale 상대값."""
    pb = {k: pinball(float(quantiles[k]), y, tau) for k, tau in LEVELS.items()}
    pb_mean = mean(pb.values())
    crps = 2.0 * pb_mean   # CRPS = 2∫ρ_τ dτ 의 5점 균등가중 수치적분 — 근사, 비교 전용
    rel = (1.0 / scale) if scale else None
    return {
        "pinball": {k: round(v, 6) for k, v in pb.items()},
        "pinball_mean": round(pb_mean, 6),
        "coverage_p10_p90": int(float(quantiles["q10"]) <= y <= float(quantiles["q90"])),
        "crps_5q": round(crps, 6),
        "pinball_mean_rel": round(pb_mean * rel, 8) if rel else None,
        "crps_5q_rel": round(crps * rel, 8) if rel else None,
    }


def gbm_quantiles(last_value: float, mu_w: float, sigma_w: float, horizon_weeks: int
                  ) -> dict[str, float]:
    """baseline — 같은 run 에 기록된 주간 로그수익률 μ·σ 로 만든 GBM 종점 분위수 (결정론)."""
    nd = NormalDist()
    h = float(horizon_weeks)
    return {k: float(last_value * math.exp(mu_w * h + sigma_w * math.sqrt(h) * nd.inv_cdf(tau)))
            for k, tau in LEVELS.items()}


# ── 결과 원천 (읽기 전용) ─────────────────────────────────────────

def _ledger_rows(root: Path) -> list[Any]:
    path = root / "calibration" / "ledger.csv"
    return F.parse_ledger(path) if path.is_file() else []


def _registry_kinds(root: Path) -> dict[str, Any]:
    path = root / "questions" / "registry.yaml"
    if not path.is_file():
        return {}
    return {q.question_id: q for q in load_registry(path)}


def match_outcome(qid: str, run_day: date, ledger: list[Any], question: Any | None
                  ) -> tuple[dict[str, Any] | None, str]:
    """질문의 실제 결과를 원장에서 찾는다. (결과, 사유). 결과 None = 아직 채점 불가."""
    rows = [r for r in ledger if r.question_id == qid]
    if not rows:
        return None, "no_ledger_resolution"
    rolling = question is not None and question.deadline_kind == "rolling"
    if rolling:
        near = []
        for r in rows:
            try:
                gap = abs((date.fromisoformat(r.forecast_date) - run_day).days)
            except ValueError:
                continue
            if gap <= ROLLING_MATCH_DAYS:
                near.append((gap, r.line_no, r))
        if not near:
            return None, "no_matching_rolling_window"
        rows = [sorted(near)[0][2]]
    outcomes = {int(r.outcome) for r in rows}
    if len(outcomes) != 1:
        return None, "conflicting_outcomes"
    first = sorted(rows, key=lambda r: r.line_no)[0]
    try:
        if run_day > date.fromisoformat(first.resolved_date):
            return None, "run_after_resolution"   # 결과 뒤 산출 — 룩어헤드 행은 만들지 않는다
    except ValueError:
        pass
    if (question is not None and question.deadline_kind == "fixed"
            and question.deadline is not None and run_day > question.deadline):
        return None, "run_after_deadline"
    return ({"outcome": outcomes.pop(), "source": f"ledger:{first.forecast_id}",
             "resolved_date": first.resolved_date}, "ok")


# ── 행 구성 ───────────────────────────────────────────────────────

def _finish(payload: dict[str, Any]) -> dict[str, Any]:
    for key in FORBIDDEN_ROW_KEYS:
        if key in payload:
            raise ValueError(f"행 키 '{key}' 금지 — ml_history 소비자와 충돌")
    body = {k: v for k, v in payload.items() if k != "content_hash"}
    return {**body, "content_hash": canonical_hash(body)}


def _question_rows(run: dict[str, Any], *, ledger: list[Any], kinds: dict[str, Any],
                   pre_registration: bool, knowledge_cutoff: str, existing: set[str],
                   pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
    run_ts = str(run["run_ts"])
    run_day = _run_date(run_ts)
    rows: list[dict[str, Any]] = []
    by_q: dict[str, list[dict[str, Any]]] = {}
    for fc in run.get("forecasts", []):
        by_q.setdefault(str(fc["question_id"]), []).append(fc)
    for qid, fcs in by_q.items():
        found, reason = match_outcome(qid, run_day, ledger, kinds.get(qid))
        if found is None:
            pending.append({"run_ts": run_ts, "question_id": qid, "reason": reason})
            continue
        outcome = int(found["outcome"])
        gbm = next((float(f["prob"]) for f in fcs if f.get("model") == "gbm"), None)
        for fc in fcs:
            model = str(fc["model"])
            rid = f"{run_ts}|{qid}|{model}"
            if rid in existing:
                continue
            prob = float(fc["prob"])
            if not 0.0 <= prob <= 1.0:
                pending.append({"run_ts": run_ts, "question_id": qid, "model": model,
                                "reason": "prob_not_fraction"})
                continue
            payload: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION, "technique_id": TECHNIQUE_ID,
                "resolution_id": rid, "run_ts": run_ts, "kind": "question_prob",
                "model": model, "question_id": qid,
                "question_kind": fc.get("kind"), "threshold": fc.get("threshold"),
                "horizon_weeks": fc.get("horizon_weeks"),
                "prob": round(prob, 6), "realized": outcome,
                "outcome_source": found["source"], "resolved_date": found["resolved_date"],
                "brier": round((prob - outcome) ** 2, 8),
                "baseline_model": "gbm",
                "baseline_prob": round(gbm, 6) if gbm is not None else None,
                "baseline_brier": round((gbm - outcome) ** 2, 8) if gbm is not None else None,
                "pre_registration": pre_registration, "knowledge_cutoff": knowledge_cutoff,
            }
            tail = fc.get("prob_tail_c2")
            if tail is not None:   # C5 병기 — 섀도 비교용 (prob 과 별도 열)
                payload["prob_tail_c2"] = round(float(tail), 6)
                payload["brier_tail_c2"] = round((float(tail) - outcome) ** 2, 8)
            rows.append(_finish(payload))
    return rows


def _series_rows(run: dict[str, Any], *, archive: dict[str, ArchiveSeries],
                 pre_registration: bool, knowledge_cutoff: str, existing: set[str],
                 pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
    run_ts = str(run["run_ts"])
    run_day = _run_date(run_ts)
    rows: list[dict[str, Any]] = []
    calendar = archive.get(CALENDAR_PROXY_SERIES)
    for series, band in (run.get("series_bands") or {}).items():
        h = int(band.get("horizon_weeks") or 0)
        rid = f"{run_ts}|{series}|{h}"
        if rid in existing or h <= 0:
            continue
        symbol = str(band.get("symbol", ""))
        archive_id = SYMBOL_TO_ARCHIVE.get(symbol)
        target = target_session(run_day, h)
        terminal = band.get("terminal") or {}
        quantiles = {k: float(terminal[k]) for k in LEVELS if k in terminal}
        base: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION, "technique_id": TECHNIQUE_ID,
            "resolution_id": rid, "run_ts": run_ts, "kind": "series_band",
            "model": "combined_median", "series": series, "symbol": symbol,
            "archive_series": archive_id, "horizon_weeks": h,
            "last_value": band.get("last_value"), "target_session": target.isoformat(),
            "quantiles": quantiles,
            "pre_registration": pre_registration, "knowledge_cutoff": knowledge_cutoff,
        }
        if len(quantiles) != len(LEVELS):
            pending.append({"run_ts": run_ts, "series": series, "reason": "quantiles_incomplete"})
            continue
        if archive_id is None:
            # 승인된 공식 원천 없음 — 성숙(아카이브 거래일 인덱스 프록시) 뒤 기록만, 채점 없음
            if calendar is None or calendar.last_date is None or calendar.last_date < target.isoformat():
                pending.append({"run_ts": run_ts, "series": series, "reason": "immature"})
                continue
            rows.append(_finish({**base, "status": UNRESOLVABLE, "realized": None,
                                 "realized_session": None}))
            continue
        ser = archive.get(archive_id)
        if ser is None or ser.last_date is None or ser.last_date < target.isoformat():
            pending.append({"run_ts": run_ts, "series": series, "reason": "immature"})
            continue
        hit = ser.last_on_or_before(target)
        if hit is None:
            pending.append({"run_ts": run_ts, "series": series, "reason": "no_session_on_or_before_target"})
            continue
        realized_session, y = hit
        scale = float(band.get("last_value") or 0.0)
        scores = score_quantiles(quantiles, y, scale)
        g = band.get("gbm") or {}
        baseline = None
        if scale and "mu_w" in g and "sigma_w" in g:
            gq = gbm_quantiles(scale, float(g["mu_w"]), float(g["sigma_w"]), h)
            baseline = {"model": "gbm", "quantiles": {k: round(v, 6) for k, v in gq.items()},
                        **score_quantiles(gq, y, scale)}
        payload = {**base, "status": "scored", "realized": y,
                   "realized_session": realized_session, **scores, "baseline_gbm": baseline}
        tail = band.get("terminal_tail_c2")
        if tail:   # C5 병기 — q01/q99 커버리지만 (꼬리 밴드 섀도)
            payload["coverage_p01_p99_c2"] = int(float(tail["q01"]) <= y <= float(tail["q99"]))
        rows.append(_finish(payload))
    return rows


def build_rows(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """채점 가능한 행을 모은다 (append 없음). 멱등 — 이미 원장에 있는 resolution_id 는 건너뛴다."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    knowledge_cutoff = current.isoformat(timespec="seconds")
    contract = load_contract(root)
    registered = registered_date(contract)
    existing = {str(r.get("resolution_id")) for r in read_ledger(root, LEDGER_RELATIVE)}
    ledger = _ledger_rows(root)
    kinds = _registry_kinds(root)
    archive = read_archive(root, knowledge_cutoff)
    rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    n_runs = 0
    for run in iter_history(root):
        if run.get("kind") != "ml" or not run.get("run_ts"):
            continue
        n_runs += 1
        pre = _run_date(str(run["run_ts"])) < registered
        rows.extend(_question_rows(run, ledger=ledger, kinds=kinds, pre_registration=pre,
                                   knowledge_cutoff=knowledge_cutoff, existing=existing,
                                   pending=pending))
        rows.extend(_series_rows(run, archive=archive, pre_registration=pre,
                                 knowledge_cutoff=knowledge_cutoff, existing=existing,
                                 pending=pending))
    return {"knowledge_cutoff": knowledge_cutoff, "registered": registered.isoformat(),
            "runs": n_runs, "rows": rows, "pending": pending, "already": len(existing)}


def resolve_reference(root: Path, *, now: datetime | None = None, dry_run: bool = False
                      ) -> dict[str, Any]:
    """성숙한 행을 원장에 append (append_unique, key=resolution_id). dry_run 이면 후보만."""
    built = build_rows(root, now=now)
    appended = 0
    if not dry_run:
        for row in built["rows"]:
            if append_unique(root, LEDGER_RELATIVE, row, key="resolution_id"):
                appended += 1
    return {**built, "appended": appended, "dry_run": dry_run}


# ── 요약 (표시만 — 판정 없음) ──────────────────────────────────────

def summarize(root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    minimum = int(contract.get("minimum_sample") or 30)
    rows = read_ledger(root, LEDGER_RELATIVE)
    primary = [r for r in rows if not r.get("pre_registration")]
    excluded = len(rows) - len(primary)

    q_by_model: dict[str, list[dict[str, Any]]] = {}
    for r in primary:
        if r.get("kind") == "question_prob":
            q_by_model.setdefault(str(r.get("model")), []).append(r)
    question: dict[str, Any] = {}
    for model, rs in sorted(q_by_model.items()):
        both = [r for r in rs if r.get("baseline_brier") is not None]
        tails = [r for r in rs if r.get("brier_tail_c2") is not None]
        question[model] = {
            "n": len(rs),
            "brier_mean": round(mean(float(r["brier"]) for r in rs), 6),
            "baseline_brier_mean": (round(mean(float(r["baseline_brier"]) for r in both), 6)
                                    if both else None),
            "brier_tail_c2_mean": (round(mean(float(r["brier_tail_c2"]) for r in tails), 6)
                                   if tails else None),
        }

    s_by: dict[str, list[dict[str, Any]]] = {}
    unresolvable = 0
    for r in primary:
        if r.get("kind") != "series_band":
            continue
        if r.get("status") == UNRESOLVABLE:
            unresolvable += 1
            continue
        s_by.setdefault(str(r.get("series")), []).append(r)
    series: dict[str, Any] = {}
    for key, rs in sorted(s_by.items()):
        base = [r["baseline_gbm"] for r in rs if r.get("baseline_gbm")]
        series[key] = {
            "n": len(rs),
            "symbol": rs[0].get("symbol"),
            "coverage_p10_p90": round(mean(int(r["coverage_p10_p90"]) for r in rs), 4),
            "pinball_mean_rel": round(mean(float(r["pinball_mean_rel"]) for r in rs), 8),
            "crps_5q_rel": round(mean(float(r["crps_5q_rel"]) for r in rs), 8),
            "baseline_coverage_p10_p90": (round(mean(int(b["coverage_p10_p90"]) for b in base), 4)
                                          if base else None),
            "baseline_crps_5q_rel": (round(mean(float(b["crps_5q_rel"]) for b in base), 8)
                                     if base else None),
        }
    return {"technique_id": TECHNIQUE_ID, "registered": str(contract.get("registered")),
            "minimum_sample": minimum, "rows_total": len(rows), "excluded_pre_registration": excluded,
            "question": question, "series": series, "unresolvable": unresolvable,
            "decision_rule": contract.get("decision_rule")}


def render_resolve(result: dict[str, Any]) -> str:
    lines = [f"ML 참조 채점 ({TECHNIQUE_ID}) — knowledge_cutoff {result['knowledge_cutoff']} · "
             f"등록 {result['registered']} · ml run {result['runs']}건 · 기존 원장 {result['already']}행"]
    verb = "후보(dry-run, 미기록)" if result.get("dry_run") else "append"
    lines.append(f"{verb}: {len(result['rows'])}행 · 실제 기록 {result.get('appended', 0)}행 · "
                 f"보류 {len(result['pending'])}건")
    for r in result["rows"][:40]:
        pre = " [pre_registration]" if r.get("pre_registration") else ""
        if r["kind"] == "question_prob":
            lines.append(f"  - {r['run_ts'][:10]} {r['question_id']} {r['model']}: p={r['prob']:.3f} "
                         f"→ {r['realized']} · Brier {r['brier']:.4f}{pre}")
        elif r.get("status") == UNRESOLVABLE:
            lines.append(f"  - {r['run_ts'][:10]} {r['series']} h={r['horizon_weeks']}: "
                         f"{UNRESOLVABLE}{pre}")
        else:
            lines.append(f"  - {r['run_ts'][:10]} {r['series']} h={r['horizon_weeks']}: "
                         f"실현 {r['realized']:,.2f}@{r['realized_session']} · 커버 {r['coverage_p10_p90']} · "
                         f"CRPS5q/last {r['crps_5q_rel']:.4f}{pre}")
    if len(result["rows"]) > 40:
        lines.append(f"  … 외 {len(result['rows']) - 40}행")
    reasons: dict[str, int] = {}
    for p in result["pending"]:
        reasons[p["reason"]] = reasons.get(p["reason"], 0) + 1
    if reasons:
        lines.append("보류 사유: " + " · ".join(f"{k} {v}" for k, v in sorted(reasons.items())))
    lines.append("판정 없음 — 기록·표시만 (멤버 가중·강등·승격 없음, 참고 의견, P3 게이트 전).")
    return "\n".join(lines)


def render_status(s: dict[str, Any]) -> str:
    lines = [f"ML 참조 채점 요약 ({s['technique_id']}, 등록 {s['registered']}) — "
             f"원장 {s['rows_total']}행 · pre_registration 제외 {s['excluded_pre_registration']}행 · "
             f"SOXX 미채점 {s['unresolvable']}행"]
    short = f"(표본 부족 — minimum_sample {s['minimum_sample']} 미만, 요약은 참고치)"
    if not s["question"]:
        lines.append("질문 확률: primary 행 없음")
    for model, m in s["question"].items():
        tail = (f" · c2꼬리 Brier {m['brier_tail_c2_mean']:.4f}" if m.get("brier_tail_c2_mean") is not None else "")
        base = (f" · gbm 기준 {m['baseline_brier_mean']:.4f}" if m.get("baseline_brier_mean") is not None else "")
        flag = "" if m["n"] >= s["minimum_sample"] else f" {short}"
        lines.append(f"  질문 {model}: n={m['n']} · 평균 Brier {m['brier_mean']:.4f}{base}{tail}{flag}")
    if not s["series"]:
        lines.append("시리즈 밴드: primary 채점 행 없음")
    for key, m in s["series"].items():
        flag = "" if m["n"] >= s["minimum_sample"] else f" {short}"
        base = (f" · gbm 커버 {m['baseline_coverage_p10_p90']:.0%} CRPS {m['baseline_crps_5q_rel']:.4f}"
                if m.get("baseline_crps_5q_rel") is not None else "")
        lines.append(f"  밴드 {key}({m['symbol']}): n={m['n']} · p10–p90 커버 {m['coverage_p10_p90']:.0%}(명목 80%) · "
                     f"pinball/last {m['pinball_mean_rel']:.4f} · CRPS5q/last {m['crps_5q_rel']:.4f}{base}{flag}")
    lines.append(f"결정 규칙: {s['decision_rule']}")
    return "\n".join(lines)
