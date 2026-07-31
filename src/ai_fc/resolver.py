"""해소 판정 보조 — Brier 계산 후 확인받고 원장 append.

판정은 rules-lawyer처럼 문언 그대로. 시스템은 계산·기록만 하고,
outcome 최종 결정과 확인은 사람이 한다 (원장 append 전 확인 필수).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

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
    comparison_status: str = "pending"  # matched | held | pending | unsupported
    comparison_log: str = ""


@dataclass(frozen=True)
class SourceObservation:
    """판정용 한 출처의 구조화 관측값.

    actual은 발표 실측치(또는 FOMC 변동 bp), reference는 earnings 비교 기준
    (D-1 컨센서스·직전 분기 값)이다. 문자열 Decimal로 읽어 이중 출처의 숫자가
    정확히 같은지 대조한다. 서로 다른 반올림값을 임의로 평균하지 않는다.
    """

    actual: Decimal
    source: str
    reference: Optional[Decimal] = None
    observed_at: str = ""
    unit: str = ""


@dataclass(frozen=True)
class ResolutionObservation:
    """질문 하나의 독립된 1·2차 출처 관측값."""

    question_id: str
    primary: SourceObservation
    secondary: SourceObservation


@dataclass(frozen=True)
class NumericRule:
    """고정된 registry 판정 문언에서 보수적으로 추출한 수치 규칙."""

    label: str
    operator: str
    threshold: Optional[Decimal] = None
    reference_multiplier: Optional[Decimal] = None

    @property
    def needs_reference(self) -> bool:
        return self.reference_multiplier is not None


def _as_decimal(value: Any, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field}는 유한한 숫자여야 함")
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} 숫자 해석 실패: {value!r}") from exc
    if not out.is_finite():
        raise ValueError(f"{field}는 유한한 숫자여야 함")
    return out


def _source_observation(raw: Any, field: str) -> SourceObservation:
    if not isinstance(raw, dict):
        raise ValueError(f"{field}는 객체여야 함")
    source = str(raw.get("source") or "").strip()
    if not source:
        raise ValueError(f"{field}.source 누락")
    reference = raw.get("reference")
    return SourceObservation(
        actual=_as_decimal(raw.get("actual"), f"{field}.actual"),
        reference=(_as_decimal(reference, f"{field}.reference")
                   if reference is not None else None),
        source=source,
        observed_at=str(raw.get("observed_at") or "").strip(),
        unit=str(raw.get("unit") or "").strip(),
    )


def load_resolution_observations(path: Path) -> dict[str, ResolutionObservation]:
    """JSON 판정 관측값 로드.

    허용 형태는 단일 객체, 객체 배열, 또는 ``{"observations": [...]}``.
    원장은 전혀 건드리지 않으며 질문별 중복은 조용히 덮지 않고 거부한다.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "observations" in raw:
        items = raw["observations"]
    elif isinstance(raw, list):
        items = raw
    else:
        items = [raw]
    if not isinstance(items, list):
        raise ValueError("observations는 배열이어야 함")

    out: dict[str, ResolutionObservation] = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"observations[{i}]는 객체여야 함")
        qid = str(item.get("question_id") or "").strip()
        if not qid:
            raise ValueError(f"observations[{i}].question_id 누락")
        if qid in out:
            raise ValueError(f"중복 question_id 관측값: {qid}")
        out[qid] = ResolutionObservation(
            question_id=qid,
            primary=_source_observation(item.get("primary"), f"{qid}.primary"),
            secondary=_source_observation(item.get("secondary"), f"{qid}.secondary"),
        )
    return out


def _numeric_rule(q) -> Optional[NumericRule]:
    """판정 문언이 명시적인 macro/earnings 유형만 규칙으로 승격.

    evidence 파일이 연산자·임계값을 정하게 두면 판정기준을 우회할 수 있으므로,
    규칙은 오직 불변 registry 문언에서 읽는다. 모호한 문언은 지원하지 않는다.
    """
    import re

    resolution = q.resolution.replace(",", "").replace("×", "x")
    # YES 규칙만 읽는다. 뒤쪽의 "3.7% 이하 NO" 같은 반대 예시를 임계값으로
    # 오인하면 판정이 뒤집히므로 첫 NO 토큰 이후는 규칙 추출에서 제외한다.
    yes_clause = re.split(r"\bNO\b", resolution, maxsplit=1, flags=re.IGNORECASE)[0]
    identity = f"{q.title}\n{resolution}"
    if q.domain == "macro":
        if "FOMC" in identity:
            m = re.search(
                r"\+?(\d+(?:\.\d+)?)\s*bp\s*이상", yes_clause, re.IGNORECASE)
            if m:
                return NumericRule("목표범위 상단 변동", "ge",
                                   threshold=Decimal(m.group(1)))
        if "NFP" in identity.upper():
            m = re.search(
                r"NFP\s*<\s*\+?(\d+(?:\.\d+)?)", yes_clause, re.IGNORECASE)
            if m:
                return NumericRule("NFP 최초 공표치", "lt",
                                   threshold=Decimal(m.group(1)))
        if "CPI" in identity.upper():
            symbolic = re.search(
                r"CPI(?:-U)?\s*YoY.*?(>=|≥|>|<=|≤|<)\s*"
                r"(\d+(?:\.\d+)?)%",
                yes_clause, re.IGNORECASE)
            if symbolic:
                op = {
                    ">=": "ge", "≥": "ge", ">": "gt",
                    "<=": "le", "≤": "le", "<": "lt",
                }[symbolic.group(1)]
                return NumericRule(
                    "CPI-U YoY", op, threshold=Decimal(symbolic.group(2)))
            m = re.search(
                r"CPI(?:-U)?\s*YoY.*?(\d+(?:\.\d+)?)%\s*(이상|초과|이하|미만)",
                yes_clause, re.IGNORECASE)
            if m:
                op = {"이상": "ge", "초과": "gt", "이하": "le", "미만": "lt"}[m.group(2)]
                return NumericRule("CPI-U YoY", op, threshold=Decimal(m.group(1)))
            if ">" in yes_clause:
                return NumericRule(
                    "CPI-U YoY vs 비교 기준", "gt",
                    reference_multiplier=Decimal("1"))
            if "<" in yes_clause:
                return NumericRule(
                    "CPI-U YoY vs 비교 기준", "lt",
                    reference_multiplier=Decimal("1"))
        if "GDP" in identity.upper() and ("컨센" in yes_clause.lower()
                                          or "consensus" in yes_clause.lower()):
            if ">" in yes_clause:
                return NumericRule(
                    "GDP 속보치 vs 컨센서스", "gt",
                    reference_multiplier=Decimal("1"))
            if "<" in yes_clause:
                return NumericRule(
                    "GDP 속보치 vs 컨센서스", "lt",
                    reference_multiplier=Decimal("1"))
        return None

    if q.domain != "earnings":
        return None
    lowered = yes_clause.lower()
    # actual >= D-1 consensus × multiplier (예: NVDA DC +5% beat).
    mult = re.search(r"(?:>=|≥).*?(?:컨센|consensus).*?x\s*(\d+(?:\.\d+)?)", lowered)
    if mult:
        return NumericRule("발표 실적 vs 비교 기준", "ge",
                           reference_multiplier=Decimal(mult.group(1)))
    # Symbol이 없더라도 판정 문언의 "+N% 이상 상회"를 multiplier로 해석.
    pct = re.search(r"(?:컨센|consensus).*?\+?(\d+(?:\.\d+)?)%\s*이상\s*상회", lowered)
    if pct:
        multiplier = Decimal("1") + Decimal(pct.group(1)) / Decimal("100")
        return NumericRule("발표 실적 vs 비교 기준", "ge",
                           reference_multiplier=multiplier)
    if ">" in lowered and ("컨센" in lowered or "consensus" in lowered):
        return NumericRule("발표 실적 vs 비교 기준", "gt",
                           reference_multiplier=Decimal("1"))
    if "<" in lowered and (
            "gross margin" in lowered or "총마진" in lowered
            or "직전" in lowered or "이전" in lowered):
        return NumericRule("발표 실적 vs 직전 값", "lt",
                           reference_multiplier=Decimal("1"))
    return None


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _compare(left: Decimal, operator: str, right: Decimal) -> bool:
    return {
        "ge": left >= right,
        "gt": left > right,
        "le": left <= right,
        "lt": left < right,
    }[operator]


def _source_identity(source: str) -> str:
    """URL이면 host, 서술형이면 정규화한 전체 문자열로 독립 출처를 구분."""
    from urllib.parse import urlparse

    parsed = urlparse(source)
    return (parsed.hostname or source).casefold().removeprefix("www.")


def numeric_machine_check(q, observation: Optional[ResolutionObservation], *,
                          today: Optional[date] = None) -> DraftVerdict:
    """macro/earnings 수치 판정 초안 — 두 독립 출처가 일치할 때만 outcome 산출."""
    today = today or date.today()
    if q.deadline_kind != "fixed" or q.deadline is None:
        return DraftVerdict(
            q.question_id, None, None, "", "", "low",
            "고정 기한 수치형 질문만 지원", True, "unsupported",
            "[unsupported] fixed deadline 없음")
    if today <= q.deadline:
        return DraftVerdict(
            q.question_id, None, None, "", "", "low",
            f"기한 미도래 ({q.deadline})", True, "pending",
            f"[pending] 오늘 {today} ≤ 기한 {q.deadline}")

    rule = _numeric_rule(q)
    if rule is None:
        return DraftVerdict(
            q.question_id, None, None, "", "", "low",
            "판정불가 유형 — registry 문언에서 안전한 수치 규칙을 추출하지 못함",
            True, "unsupported",
            "[unsupported] 주관적·모호한 판정은 사람 검토 필요")
    if observation is None:
        return DraftVerdict(
            q.question_id, None, None, "", "", "low",
            "구조화된 1·2차 출처 관측값 필요 (--resolution-data)",
            True, "pending",
            f"[pending] {rule.label}: 이중 출처 관측값 없음")

    p, s = observation.primary, observation.secondary
    held_reasons: list[str] = []
    if _source_identity(p.source) == _source_identity(s.source):
        held_reasons.append("1·2차 source가 동일")
    if p.actual != s.actual:
        held_reasons.append(
            f"actual 불일치 {_decimal_text(p.actual)} ≠ {_decimal_text(s.actual)}")
    if rule.needs_reference:
        if p.reference is None or s.reference is None:
            held_reasons.append("reference 누락")
        elif p.reference != s.reference:
            held_reasons.append(
                f"reference 불일치 {_decimal_text(p.reference)} ≠ "
                f"{_decimal_text(s.reference)}")
    if not p.unit or not s.unit:
        held_reasons.append("unit 누락")
    elif p.unit.casefold() != s.unit.casefold():
        held_reasons.append(f"unit 불일치 {p.unit!r} ≠ {s.unit!r}")
    if not p.observed_at or not s.observed_at:
        held_reasons.append("observed_at 누락")
    elif p.observed_at != s.observed_at:
        held_reasons.append(
            f"observed_at 불일치 {p.observed_at!r} ≠ {s.observed_at!r}")

    sources = f"{p.source} ↔ {s.source}"
    if held_reasons:
        return DraftVerdict(
            q.question_id, None, None, "", sources, "low",
            "수치 불일치 — 판정 보류·사람 검토", True, "held",
            "[held] " + "; ".join(held_reasons))

    if rule.needs_reference:
        assert p.reference is not None  # held 분기에서 누락 차단
        target = p.reference * rule.reference_multiplier
        evidence_value = (
            f"{rule.label}: actual {_decimal_text(p.actual)} vs 기준 "
            f"{_decimal_text(p.reference)} × {_decimal_text(rule.reference_multiplier)}"
            f" = {_decimal_text(target)}")
    else:
        assert rule.threshold is not None
        target = rule.threshold
        evidence_value = (
            f"{rule.label}: actual {_decimal_text(p.actual)} vs 임계 "
            f"{_decimal_text(target)}")
    outcome = "yes" if _compare(p.actual, rule.operator, target) else "no"
    stamp = f" ({p.observed_at})" if p.observed_at else ""
    return DraftVerdict(
        q.question_id, None, outcome, evidence_value, sources, "high",
        f"두 출처 수치 일치{stamp}", False, "matched",
        f"[matched] primary={p.source} secondary={s.source} "
        f"actual={_decimal_text(p.actual)}"
        + (f" reference={_decimal_text(p.reference)}"
           if p.reference is not None else ""))


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
                   today: Optional[date] = None,
                   observations: Optional[
                       Mapping[str, ResolutionObservation]] = None) -> list[DraftVerdict]:
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
        # 결정론 수치형은 가격 매핑과 독립. bulk에서는 기한 경과만, qid 명시 시에는
        # pending/unsupported 사유까지 보여 사용자가 관측값·판정 문언을 보완할 수 있게 한다.
        if q.domain in {"macro", "earnings"}:
            if (question_id is None
                    and (q.deadline_kind != "fixed" or q.deadline is None
                         or today <= q.deadline)):
                continue
            out.append(numeric_machine_check(
                q, (observations or {}).get(q.question_id), today=today))
            continue
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
