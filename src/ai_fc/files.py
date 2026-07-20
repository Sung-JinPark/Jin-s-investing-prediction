"""파일 파서/라이터 — 불변성 집행 지점.

원칙: 관대한 리더(기존 수기 파일의 이질성 흡수), 엄격한 라이터(신규 기록 검증).
forecasts/ 파일은 절대 수정하지 않는다. 라이터는 배타적-생성만 지원한다.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Optional

import frontmatter

from .models import ForecastRecord, LedgerRow, sha256_file, sha256_text

KNOWN_KEYS = {
    "forecast_id", "question_id", "question_snapshot", "timestamp", "phase",
    "model", "prompt_version", "probability", "ci80", "window_end",
    "snapshots", "market_implied", "edge", "sources_count", "method",
    "research_status",  # AUDIT-260715 T-3 — 신규 예측부터, 구파일 부재는 ok 취급
    "shadow_extremized",  # 표시 전용 섀도 캘리브레이션 열 (ARCHITECTURE §2-⑤)
    "digest_hash", "digest_inputs",  # WS4 재현성 스냅샷 — 구파일 부재 허용
    "ml_divergence_pp", "divergence_note", "divergence_class",  # WS6 — 구파일 부재 허용
    "research_quality",  # WS7 출처 등급 분포 — 구파일 부재 허용
    "pipeline_tier",  # v3 WS-B — standard|lite, 구파일 부재 = standard 취급
}

# WS6: 괴리 임계 (config.ML_DIVERGENCE_PP와 동일 값 — files는 config 무의존 원칙이라 상수 복제,
# 값 변경 시 양쪽 동기 필수)
DIVERGENCE_JUSTIFY_PP = 15
DIVERGENCE_CLASSES = {"event_conditionality", "regime_view", "model_limit", "other"}

LEDGER_HEADER = [
    "resolved_date", "question_id", "forecast_id", "forecast_date",
    "probability", "outcome", "brier", "domain", "notes",
]


class ImmutabilityError(RuntimeError):
    """불변 파일을 덮어쓰려 하거나 변조가 감지됐을 때."""


# ── 예측 파일 읽기 ────────────────────────────────────────────────

def iter_forecast_files(forecasts_dir: Path) -> Iterator[Path]:
    """예측 md 파일만 (TEMPLATE·*_evidence.md·retro/ 제외).

    retro/는 해소 회고 노트 (v3 WS-E) — 가변 문서라 불변 규약·해시 앵커 비대상.
    제외하지 않으면 파일명 규칙 불일치로 sync가 파싱 오류를 낸다 (v3 계획 D1).
    """
    for p in sorted(forecasts_dir.rglob("*.md")):
        if p.name == "TEMPLATE.md" or p.stem.endswith("_evidence"):
            continue
        if "retro" in p.parent.parts:
            continue
        yield p


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    s = str(raw).strip().replace(" KST", "")
    # 시각 없는 "YYYY-MM-DD"도 허용 (수동 예측 파일에 존재 — 관대한 리더 원칙,
    # 자정으로 해석해 due 계산이 '첫 예측 미실행'으로 오판하지 않게 한다)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_date(raw: Any) -> Optional[date]:
    if raw is None or raw == "null":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(raw))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _parse_optional_num(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None  # "~50" 같은 서술형은 버린다 (관대한 리더)


def parse_forecast_file(path: Path) -> ForecastRecord:
    stem_info = ForecastRecord.parse_stem(path.stem)
    if stem_info is None:
        raise ValueError(f"예측 파일명 규칙 불일치: {path.name}")
    qid_from_name, round_from_name = stem_info

    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    fm: dict[str, Any] = dict(post.metadata)

    ci80 = fm.get("ci80") or [None, None]
    if not isinstance(ci80, (list, tuple)) or len(ci80) != 2:
        ci80 = [None, None]

    snapshots = fm.get("snapshots") or {}
    if not isinstance(snapshots, dict):
        snapshots = {"_raw": str(snapshots)}

    extra = {k: v for k, v in fm.items() if k not in KNOWN_KEYS}

    return ForecastRecord(
        forecast_id=str(fm.get("forecast_id") or path.stem),
        question_id=str(fm.get("question_id") or qid_from_name),
        round=round_from_name,
        forecast_ts=_parse_ts(fm.get("timestamp")),
        probability=int(fm["probability"]),
        ci80_lo=int(ci80[0]) if ci80[0] is not None else None,
        ci80_hi=int(ci80[1]) if ci80[1] is not None else None,
        window_end=_parse_date(fm.get("window_end")),
        snapshots=snapshots,
        market_implied=_parse_optional_num(fm.get("market_implied")),
        edge=_parse_optional_num(fm.get("edge")),
        model=str(fm.get("model", "")),
        prompt_version=str(fm.get("prompt_version", "")),
        phase=str(fm.get("phase", "")),
        method=str(fm.get("method", "full")),
        sources_count=int(fm["sources_count"]) if fm.get("sources_count") is not None else None,
        path=path,
        file_sha256=sha256_file(path),
        extra=extra,
        research_status=(str(fm["research_status"])
                         if fm.get("research_status") else None),
        shadow_extremized=(int(fm["shadow_extremized"])
                           if isinstance(fm.get("shadow_extremized"), int) else None),
        ml_divergence_pp=_parse_optional_num(fm.get("ml_divergence_pp")),
        divergence_class=(str(fm["divergence_class"])
                          if fm.get("divergence_class") else None),
        pipeline_tier=(str(fm["pipeline_tier"])
                       if fm.get("pipeline_tier") else None),
    )


# ── 예측 파일 쓰기 (엄격) ─────────────────────────────────────────

def validate_new_record(fm: dict[str, Any]) -> list[str]:
    """신규 기록 frontmatter 검증. 오류 목록 반환(빈 리스트 = 통과)."""
    errors = []
    p = fm.get("probability")
    if not isinstance(p, int) or not (1 <= p <= 99):
        errors.append(f"probability는 1~99 정수여야 함: {p!r}")
    ci = fm.get("ci80")
    if ci is not None:
        if (not isinstance(ci, list) or len(ci) != 2
                or not all(isinstance(x, int) for x in ci) or ci[0] > ci[1]):
            errors.append(f"ci80은 [lo, hi] 정수쌍이어야 함: {ci!r}")
    for key in ("forecast_id", "question_id", "timestamp", "phase", "model", "prompt_version"):
        if not fm.get(key):
            errors.append(f"필수 키 누락: {key}")
    # WS6: 기록 시점 ML 괴리 ≥ 15%p면 정당화 필수 — 스키마가 무정당화 divergence를 거부
    pp = fm.get("ml_divergence_pp")
    if isinstance(pp, (int, float)) and pp >= DIVERGENCE_JUSTIFY_PP:
        if not fm.get("divergence_note"):
            errors.append(f"ml_divergence_pp {pp}%p ≥ {DIVERGENCE_JUSTIFY_PP} — "
                          "divergence_note 필수 (정당화 없는 divergence 기록 거부)")
        if fm.get("divergence_class") not in DIVERGENCE_CLASSES:
            errors.append(f"divergence_class는 {sorted(DIVERGENCE_CLASSES)} 중 하나 필수: "
                          f"{fm.get('divergence_class')!r}")
    return errors


def write_forecast_exclusive(path: Path, content: str) -> None:
    """배타적-생성. 경로가 존재하면 ImmutabilityError — 절대 덮어쓰지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except FileExistsError:
        raise ImmutabilityError(f"이미 존재하는 예측 파일에 쓰기 시도: {path}") from None


def next_round(forecasts_dir: Path, question_id: str) -> int:
    rounds = [
        info[1]
        for p in iter_forecast_files(forecasts_dir)
        if (info := ForecastRecord.parse_stem(p.stem)) and info[0] == question_id
    ]
    return max(rounds, default=0) + 1


# ── 원장 (append-only) ───────────────────────────────────────────

def parse_ledger(ledger_path: Path) -> list[LedgerRow]:
    rows: list[LedgerRow] = []
    raw_lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if not raw_lines:
        return rows
    reader = csv.DictReader(io.StringIO("\n".join(raw_lines)))
    if reader.fieldnames != LEDGER_HEADER:
        raise ValueError(f"원장 헤더 불일치: {reader.fieldnames}")
    for i, rec in enumerate(reader, start=1):
        rows.append(LedgerRow(
            line_no=i,
            resolved_date=rec["resolved_date"],
            question_id=rec["question_id"],
            forecast_id=rec["forecast_id"],
            forecast_date=rec["forecast_date"],
            probability=int(rec["probability"]),
            outcome=int(rec["outcome"]),
            brier=float(rec["brier"]),
            domain=rec["domain"],
            notes=rec.get("notes", ""),
            line_hash=sha256_text(raw_lines[i]),  # raw_lines[0]은 헤더
        ))
    return rows


def append_ledger_row(ledger_path: Path, row: dict[str, Any]) -> None:
    """원장에 1행 append. 기존 내용은 절대 건드리지 않는다."""
    line = ",".join(_csv_escape(str(row.get(k, ""))) for k in LEDGER_HEADER)
    with open(ledger_path, "a", encoding="utf-8", newline="") as f:
        f.write(line + "\n")


def _csv_escape(value: str) -> str:
    if any(c in value for c in ',"\n'):
        return '"' + value.replace('"', '""') + '"'
    return value


# ── 벤치마크 3자 원장 (WS2 — append-only, 기존 원장과 별도 파일) ────

BENCHMARK_HEADER = [
    "resolved_date", "question_id", "forecast_id",
    "llm_prob", "llm_brier", "ml_prob", "ml_brier",
    "market_prob", "market_brier", "ml_asof", "market_asof", "notes",
]


def parse_benchmark_ledger(path: Path) -> list[dict[str, Any]]:
    """벤치마크 원장 파싱 — 각 행 dict에 line_no·line_hash 부가. 파일 부재 시 [].

    확률·Brier의 빈 문자열은 None (NULL 정직성 — 부재를 0으로 위장하지 않는다).
    """
    if not path.exists():
        return []
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    if not raw_lines:
        return []
    reader = csv.DictReader(io.StringIO("\n".join(raw_lines)))
    if reader.fieldnames != BENCHMARK_HEADER:
        raise ValueError(f"벤치마크 원장 헤더 불일치: {reader.fieldnames}")
    rows: list[dict[str, Any]] = []
    num_keys = ("llm_prob", "llm_brier", "ml_prob", "ml_brier", "market_prob", "market_brier")
    for i, rec in enumerate(reader, start=1):
        row: dict[str, Any] = dict(rec)
        for k in num_keys:
            row[k] = float(rec[k]) if rec.get(k) not in (None, "",) else None
        row["line_no"] = i
        row["line_hash"] = sha256_text(raw_lines[i])
        rows.append(row)
    return rows


def append_benchmark_row(path: Path, row: dict[str, Any]) -> None:
    """벤치마크 원장에 1행 append — 파일 없으면 헤더부터 생성. None은 빈 칸."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(",".join(BENCHMARK_HEADER) + "\n", encoding="utf-8")
    line = ",".join(
        _csv_escape("" if row.get(k) is None else str(row.get(k, "")))
        for k in BENCHMARK_HEADER)
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write(line + "\n")
