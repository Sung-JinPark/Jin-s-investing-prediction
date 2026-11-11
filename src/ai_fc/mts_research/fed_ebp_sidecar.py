"""FED_EBP 연구 사이드카 — 원본 영수증 gzip 재생 파서 (P8, D12 데이터 복원 측면).

배경: Fed EBP CSV 가 2026-10-07 수집분부터 날짜를 ISO(YYYY-MM-DD)로 바꿨다. 봉인 V2
파서(``timeseries_v2.market_archive.parse_fed_ebp_csv``)는 ``%m/%d/%Y`` 만 받아 실패하고,
V2 아카이브 관측은 2026-07-01 에서 멈췄다. 원본 바이트는 영수증 gzip 에 그대로 남아 있다.

이 모듈은 봉인 코드를 고치지 않고(import 만) 같은 영수증을 다시 읽는다.

- 입력: ``data/timeseries_v2/ledgers/market_raw_receipts.jsonl`` 의
  ``source_id == "federal_reserve_excess_bond_premium"`` 영수증과 그 원본 gzip. 압축을 푼
  바이트의 sha256 이 영수증 ``raw_sha256`` 과 다르면 fail-closed.
- 날짜: ISO ``%Y-%m-%d`` 와 ``%m/%d/%Y`` 두 형식만 받는다. 그 밖은 fail-closed.
- 빈티지: retrieved_at 순으로 정렬한 영수증에서 ``raw_sha256`` 이 같은 **연속 구간** 하나가
  빈티지 하나다. 같은 바이트가 다른 바이트 뒤에 다시 나오면(A→B→A) 새 빈티지로 본다.
- ``available_at`` = 그 빈티지 첫 영수증의 ``retrieved_at``. Fed 는 EBP 전 이력을 개정하므로
  과거 관측도 저장소가 받은 시각에야 알 수 있었다(V2 의 captured_forward 규약과 같다).
  역사적 공개 시각으로 소급하지 않는다.

원장 행 규칙 (``data/mts_research/ledgers/fed_ebp_v1.jsonl``, identity=observation_id):

- **빈티지별 신규·변경·철회 관측만** 행으로 남긴다. 영수증×관측 전부(실측 152×약 645 ≈ 9.8만
  행)를 쓰지 않는다. 값(ebp·gz_spread·est_prob 중 하나라도)이 직전 상태와 비트 단위로 같으면
  행을 만들지 않는다. 같은 바이트를 다시 받은 영수증은 행을 만들지 않고 요약의
  ``n_receipts`` 로만 센다.
- ``change_kind``: new(처음 보는 관측) · revised(값 변경, 철회 뒤 재등장 포함) ·
  withdrawn(직전 빈티지에 있던 날짜가 사라짐, 값은 null).
- 개정은 덮어쓰지 않고 ``revision_seq`` +1, ``supersedes`` = 직전 행 id 인 새 행으로 남긴다.
- 어떤 시점의 상태 = 행을 ``available_at <= cutoff`` 로 거른 뒤 날짜별 최대 revision_seq.
- 행 내용은 그 빈티지까지의 영수증 접두부로만 정해진다. 새 영수증이 전부 기존 영수증보다
  늦은 retrieved_at 이면 기존 행은 바이트 단위로 같으므로 재실행은 멱등이다(append 0).
- 이 가정은 코드가 확인한다(``_plan_append``, dry-run 과 --append 둘 다). 원장 중 cutoff
  이내 행은 재생 행의 **접두부**와 id·본문이 같아야 하고, 새로 붙일 행의 available_at 은 원장
  최대 available_at 보다 늦어야 한다(같으면 원장 마지막 행과 같은 영수증 — 중단된 빈티지
  이어쓰기 — 만 허용). 소급 영수증(backdated receipt)이 끼어 재생이 갈라지면 행을 붙이지 않고
  fail-closed(exit 2)한다. append-only 원장에 갈라진 가지 두 개가 남아 PIT 재구성이 섞이는
  것을 막기 위해서다. 영수증 원장 파일 순서상 retrieved_at 역행 건수는 요약에 공시만 한다.
- 행 생성 판정은 세 값(ebp·gz_spread·est_prob)을 비트 단위로 비교한다. 실측 빈티지 2·3 의
  revised 행은 ebp 가 전부 1e-6 넘게 바뀐 실제 개정이다. gz_spread 는 빈티지 2 에서 30행이
  CSV 표기 자릿수만 달라진 변화(9자리 반올림 동일)이지만 같은 행의 ebp 가 실제로 개정됐으므로
  행 생성에는 영향이 없다 — 정정 대상 아님.

지위: scoring_excluded·display_only 연구 사이드카. V2 아카이브는 무수정이고 어떤 라이브
예측도 이 사이드카를 쓰지 않는다. EBP 재시험은 새 계약 사전등록 뒤에만 한다(V13 F3_ebp 는
2026-09-09 종결). 네트워크 접근 없음.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ..timeseries_v8.contracts import canonical_hash
from .artifacts import LEDGERS_RELATIVE, MtsArtifactError, append_event, read_chain, writer_lock
from .monitor_thresholds import NOTICE

SOURCE_ID = "fed_ebp_sidecar_v1"
PARSER_VERSION = "fed-ebp-sidecar-v1.0"
UPSTREAM_SOURCE_ID = "federal_reserve_excess_bond_premium"
SERIES_ID = "FED_EBP"
LEDGER_RELATIVE = LEDGERS_RELATIVE / "fed_ebp_v1.jsonl"
# 봉인 V2 경로 상수와 같은 값 — 봉인 모듈을 import 하지 않고도 읽을 수 있게 둔다(테스트가 일치 확인).
RECEIPTS_RELATIVE = Path("data/timeseries_v2/ledgers/market_raw_receipts.jsonl")
V2_FACTS_RELATIVE = Path("data/timeseries_v2/ledgers/market_observations.jsonl")
VALUE_FIELDS = ("ebp", "gz_spread", "est_prob")
ROW_RULE = "빈티지별 신규·변경·철회 관측만 (재수신 동일 바이트는 행 없음)"
RETEST_POLICY = "EBP 재시험은 새 계약 사전등록 뒤에만 (V13 F3_ebp 2026-09-09 종결)"

DateFormat = Literal["iso", "mdy"]
_DATE_FORMATS: tuple[tuple[DateFormat, str], ...] = (("iso", "%Y-%m-%d"), ("mdy", "%m/%d/%Y"))


@dataclass(frozen=True)
class EbpRow:
    """Fed EBP CSV 한 줄 — 날짜는 ISO 로 정규화, 원본 형식은 date_format 에 남긴다."""

    observation_time: str
    ebp: float
    gz_spread: float | None
    est_prob: float | None
    date_format: DateFormat

    def values(self) -> dict[str, float | None]:
        return {"ebp": self.ebp, "gz_spread": self.gz_spread, "est_prob": self.est_prob}


# ---------------------------------------------------------------------------
# 파서
# ---------------------------------------------------------------------------


def _parse_date(raw: str, line: int) -> tuple[str, DateFormat]:
    for name, pattern in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, pattern).date().isoformat(), name
        except ValueError:
            continue
    raise MtsArtifactError(f"EBP CSV {line}행: 날짜 형식 미지원 {raw!r} (ISO·%m/%d/%Y 만 허용)")


def _parse_float(raw: str | None, *, field: str, line: int, required: bool) -> float | None:
    text = str(raw or "").strip()
    if text in {"", "."}:
        if required:
            raise MtsArtifactError(f"EBP CSV {line}행: 필수 값 {field} 누락")
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise MtsArtifactError(f"EBP CSV {line}행: {field} 숫자 아님 {text!r}") from exc
    if not math.isfinite(value):
        raise MtsArtifactError(f"EBP CSV {line}행: {field} 비유한값 {text!r}")
    return value


def parse_ebp_csv_any(text: str) -> list[EbpRow]:
    """ISO·%m/%d/%Y 두 날짜 형식의 Fed EBP CSV 를 파싱한다 (날짜 오름차순).

    ebp 가 빈칸/'.' 인 줄은 관측 없음으로 건너뛴다(봉인 파서와 같은 규약). 헤더에 date·ebp 가
    없거나, 날짜 중복·형식 미지원·비유한값이면 MtsArtifactError 로 fail-closed 한다.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = {name.strip() for name in (reader.fieldnames or [])}
    if not {"date", "ebp"} <= header:
        raise MtsArtifactError(f"EBP CSV 헤더에 date·ebp 없음: {sorted(header)}")
    rows: dict[str, EbpRow] = {}
    for line, raw in enumerate(reader, start=2):
        record = {str(key).strip(): value for key, value in raw.items() if key is not None}
        raw_day = str(record.get("date") or "").strip()
        if not raw_day:
            continue
        if str(record.get("ebp") or "").strip() in {"", "."}:
            continue
        day, date_format = _parse_date(raw_day, line)
        if day in rows:
            raise MtsArtifactError(f"EBP CSV {line}행: 날짜 중복 {day}")
        rows[day] = EbpRow(
            observation_time=day,
            ebp=_parse_float(record.get("ebp"), field="ebp", line=line, required=True),
            gz_spread=_parse_float(record.get("gz_spread"), field="gz_spread", line=line, required=False),
            est_prob=_parse_float(record.get("est_prob"), field="est_prob", line=line, required=False),
            date_format=date_format,
        )
    return [rows[day] for day in sorted(rows)]


# ---------------------------------------------------------------------------
# 영수증 → 빈티지
# ---------------------------------------------------------------------------


def _utc(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise MtsArtifactError(f"{label}: ISO8601 아님 {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MtsArtifactError(f"{label}: 시간대 없는 시각 {value!r}")
    return parsed.astimezone(timezone.utc)


def _load_receipts(root: Path, *, retrieved_until: datetime | None) -> tuple[list[dict[str, Any]], int]:
    """EBP 영수증을 retrieved_at 순으로 정렬해 돌려준다 + 파일 순서상 retrieved_at 역행 건수."""
    path = root / RECEIPTS_RELATIVE
    if not path.is_file():
        raise MtsArtifactError(f"영수증 원장 없음: {RECEIPTS_RELATIVE.as_posix()}")
    receipts: list[tuple[datetime, int, dict[str, Any]]] = []
    latest_seen: datetime | None = None
    backdated = 0
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MtsArtifactError(f"영수증 원장 {index + 1}행 JSON 아님") from exc
        if row.get("source_id") != UPSTREAM_SOURCE_ID:
            continue
        at = _utc(row.get("retrieved_at"), label=f"receipt {row.get('receipt_id')}")
        if latest_seen is not None and at < latest_seen:
            backdated += 1
        latest_seen = at if latest_seen is None else max(latest_seen, at)
        if retrieved_until is not None and at > retrieved_until:
            continue
        receipts.append((at, index, row))
    receipts.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in receipts], backdated


def _read_raw(root: Path, receipt: dict[str, Any], cache: dict[tuple[str, str], bytes]) -> bytes:
    """원본 gzip 을 풀어 sha256 을 확인한다. 캐시 키는 (raw_path, sha256) — 영수증마다 존재 확인."""
    digest = str(receipt.get("raw_sha256") or "")
    relative = str(receipt.get("raw_path") or "")
    raw_path = root / relative
    if not relative or not raw_path.is_file():
        raise MtsArtifactError(f"원본 gzip 없음: {receipt.get('receipt_id')} → {receipt.get('raw_path')}")
    key = (relative, digest)
    if key in cache:
        return cache[key]
    try:
        with gzip.open(raw_path, "rb") as handle:
            payload = handle.read()
    except (OSError, EOFError) as exc:
        raise MtsArtifactError(f"원본 gzip 읽기 실패: {receipt.get('receipt_id')}") from exc
    if hashlib.sha256(payload).hexdigest() != digest:
        raise MtsArtifactError(f"원본 sha256 불일치: {receipt.get('receipt_id')}")
    cache[key] = payload
    return payload


def _vintages(root: Path, receipts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """연속 동일 바이트 구간 → 빈티지. 저장소 원본이 없는 영수증(private locator)은 건너뛰고 보고."""
    cache: dict[tuple[str, str], bytes] = {}
    vintages: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for receipt in receipts:
        if receipt.get("redistribution") != "repository_raw_allowed":
            skipped.append({"receipt_id": receipt.get("receipt_id"), "reason": "raw_not_in_repository"})
            continue
        payload = _read_raw(root, receipt, cache)
        if vintages and vintages[-1]["raw_sha256"] == receipt["raw_sha256"]:
            vintages[-1]["n_receipts"] += 1
            vintages[-1]["last_retrieved_at"] = receipt["retrieved_at"]
            continue
        vintages.append({
            "vintage_seq": len(vintages) + 1,
            "raw_sha256": receipt["raw_sha256"],
            "receipt_id": receipt["receipt_id"],
            "available_at": receipt["retrieved_at"],
            "last_retrieved_at": receipt["retrieved_at"],
            "n_receipts": 1,
            "payload": payload,
        })
    return vintages, skipped


# ---------------------------------------------------------------------------
# 재생 (행 생성)
# ---------------------------------------------------------------------------


def _row(vintage: dict[str, Any], day: str, values: dict[str, float | None], *,
         change_kind: str, date_format: str | None, prior: dict[str, Any] | None) -> dict[str, Any]:
    revision_seq = 1 if prior is None else int(prior["revision_seq"]) + 1
    supersedes = None if prior is None else prior["observation_id"]
    seed = {
        "source_id": SOURCE_ID, "series_id": SERIES_ID, "observation_time": day,
        "raw_sha256": vintage["raw_sha256"], "receipt_id": vintage["receipt_id"],
        "change_kind": change_kind, "revision_seq": revision_seq, "supersedes": supersedes, **values,
    }
    return {
        "observation_id": f"fed-ebp-obs-{canonical_hash(seed)[:24]}",
        "source_id": SOURCE_ID,
        "parser_version": PARSER_VERSION,
        "upstream_source_id": UPSTREAM_SOURCE_ID,
        "series_id": SERIES_ID,
        "observation_time": day,
        **values,
        "change_kind": change_kind,
        "revision_seq": revision_seq,
        "supersedes": supersedes,
        "vintage_seq": vintage["vintage_seq"],
        "raw_sha256": vintage["raw_sha256"],
        "receipt_id": vintage["receipt_id"],
        "available_at": vintage["available_at"],
        "source_date_format": date_format,
        "data_grade": "captured_forward",
        "scoring_excluded": True,
        "display_only": True,
        "live_forecast_use": False,
        "notice": NOTICE,
    }


def _diff_vintage(vintage: dict[str, Any], parsed: list[EbpRow],
                  state: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """직전 상태 대비 이 빈티지의 신규·변경·철회 행과 개수."""
    rows: list[dict[str, Any]] = []
    counts = {"new": 0, "revised": 0, "withdrawn": 0, "unchanged": 0}
    present = {row.observation_time for row in parsed}
    for item in parsed:
        prior = state.get(item.observation_time)
        values = item.values()
        if prior is not None and prior["change_kind"] != "withdrawn" and all(
            prior[field] == values[field] for field in VALUE_FIELDS
        ):
            counts["unchanged"] += 1
            continue
        kind = "new" if prior is None else "revised"
        rows.append(_row(vintage, item.observation_time, values,
                         change_kind=kind, date_format=item.date_format, prior=prior))
        counts[kind] += 1
    for day in sorted(set(state) - present):
        prior = state[day]
        if prior["change_kind"] == "withdrawn":
            continue
        empty = {field: None for field in VALUE_FIELDS}
        rows.append(_row(vintage, day, empty, change_kind="withdrawn", date_format=None, prior=prior))
        counts["withdrawn"] += 1
    for row in rows:
        state[row["observation_time"]] = row
    return rows, counts


def _sealed_parser_status(payload: bytes) -> dict[str, Any]:
    """봉인 V2 파서가 이 빈티지를 읽는지 — 진단 표시만 (봉인 코드는 import 만).

    어떤 예외든 "못 읽음"(ok=False)으로 기록하되 예외 형식을 함께 공시한다(삼키지 않음).
    """
    from ..timeseries_v2.market_archive import parse_fed_ebp_csv

    try:
        return {"ok": True, "n_rows": len(parse_fed_ebp_csv(payload)), "error": None, "error_type": None}
    except Exception as exc:  # noqa: BLE001 — 진단 표시 전용, 결과는 ok=False 로 공시
        return {"ok": False, "n_rows": None, "error": str(exc), "error_type": type(exc).__name__}


def _replay(root: Path, *, retrieved_until: datetime | None) -> dict[str, Any]:
    receipts, backdated = _load_receipts(root, retrieved_until=retrieved_until)
    vintages, skipped = _vintages(root, receipts)
    state: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for vintage in vintages:
        try:
            parsed = parse_ebp_csv_any(vintage["payload"].decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise MtsArtifactError(f"빈티지 {vintage['vintage_seq']} UTF-8 아님") from exc
        if not parsed:
            raise MtsArtifactError(f"빈티지 {vintage['vintage_seq']} 관측 0행")
        vintage_rows, counts = _diff_vintage(vintage, parsed, state)
        rows.extend(vintage_rows)
        formats = sorted({item.date_format for item in parsed})
        summaries.append({
            "vintage_seq": vintage["vintage_seq"],
            "raw_sha256": vintage["raw_sha256"],
            "receipt_id": vintage["receipt_id"],
            "available_at": vintage["available_at"],
            "last_retrieved_at": vintage["last_retrieved_at"],
            "n_receipts": vintage["n_receipts"],
            "n_observations": len(parsed),
            "date_format": formats[0] if len(formats) == 1 else "mixed",
            "first_observation_time": parsed[0].observation_time,
            "last_observation_time": parsed[-1].observation_time,
            "last_ebp": parsed[-1].ebp,
            "rows": len(vintage_rows),
            **counts,
            "sealed_v2_parser": _sealed_parser_status(vintage["payload"]),
        })
    return {"receipts": receipts, "receipts_backdated_in_file": backdated, "skipped": skipped,
            "vintages": summaries, "rows": rows, "state": state}


def replay_receipts(root: Path, *, retrieved_until: str | None = None) -> list[dict[str, Any]]:
    """영수증을 retrieved_at 순으로 재생해 원장 행(빈티지별 신규·변경·철회 관측)을 만든다.

    retrieved_until(ISO8601, 시간대 필수)을 주면 그 시각 이하 영수증만 쓴다. 쓰기 없음.
    """
    cutoff = None if retrieved_until is None else _utc(retrieved_until, label="retrieved_until")
    return _replay(root, retrieved_until=cutoff)["rows"]


def state_at(rows: list[dict[str, Any]], *, cutoff: str | None = None) -> dict[str, dict[str, Any]]:
    """available_at <= cutoff 인 행으로 날짜별 최신 상태(철회 제외)를 재구성한다."""
    limit = None if cutoff is None else _utc(cutoff, label="cutoff")
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if limit is not None and _utc(row["available_at"], label="available_at") > limit:
            continue
        day = row["observation_time"]
        if day not in latest or row["revision_seq"] > latest[day]["revision_seq"]:
            latest[day] = row
    return {day: row for day, row in sorted(latest.items()) if row["change_kind"] != "withdrawn"}


# ---------------------------------------------------------------------------
# V2 아카이브 대조 (read-only)
# ---------------------------------------------------------------------------


def _v2_latest(root: Path) -> dict[str, dict[str, Any]]:
    path = root / V2_FACTS_RELATIVE
    latest: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        if SERIES_ID not in line:
            continue
        row = json.loads(line)
        if row.get("series_id") != SERIES_ID:
            continue
        day = row["observation_time"]
        if day not in latest or row["revision_seq"] > latest[day]["revision_seq"]:
            latest[day] = row
    return latest


def _months_between(earlier: str, later: str) -> int:
    a, b = date.fromisoformat(earlier), date.fromisoformat(later)
    return (b.year - a.year) * 12 + (b.month - a.month)


def compare_with_v2(root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """V2 아카이브 FED_EBP 최신값이 같은 원본 바이트의 사이드카 상태와 비트 단위로 같은지."""
    v2 = _v2_latest(root)
    if not v2:
        return {"available": False}
    v2_digests = {row["raw_sha256"] for row in v2.values()}
    seqs = [row["vintage_seq"] for row in rows if row["raw_sha256"] in v2_digests]
    if not seqs:
        return {"available": True, "comparable": False, "n_v2": len(v2)}
    through = max(seqs)
    reference = state_at([row for row in rows if row["vintage_seq"] <= through])
    mismatched = sorted(day for day, row in v2.items()
                        if day not in reference or reference[day]["ebp"] != float(row["value"]))
    sidecar_last = max(state_at(rows)) if rows else None
    v2_last = max(v2)
    return {
        "available": True,
        "comparable": True,
        "n_v2": len(v2),
        "compared_through_vintage_seq": through,
        "n_mismatched": len(mismatched),
        "mismatched_sample": mismatched[:5],
        "v2_last_observation_time": v2_last,
        "sidecar_last_observation_time": sidecar_last,
        "v2_months_behind": None if sidecar_last is None else _months_between(v2_last, sidecar_last),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cutoff(args: argparse.Namespace) -> datetime | None:
    """--now(정확 시각) 또는 --as-of(그 UTC 날짜 말) 중 이른 쪽. 둘 다 없으면 전체 영수증."""
    bounds: list[datetime] = []
    now = getattr(args, "now", None)
    as_of = getattr(args, "as_of", None)
    if now:
        bounds.append(_utc(now, label="--now"))
    if as_of:
        try:
            day = date.fromisoformat(as_of)
        except ValueError as exc:
            raise MtsArtifactError(f"--as-of 는 YYYY-MM-DD: {as_of!r}") from exc
        bounds.append(datetime(day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=timezone.utc))
    return min(bounds) if bounds else None


def _ledger_body(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in ("previous_hash", "content_hash")}


def _available(row: dict[str, Any]) -> datetime:
    return _utc(row["available_at"], label=f"available_at {row.get('observation_id')}")


def _plan_append(existing: list[dict[str, Any]], rows: list[dict[str, Any]],
                 cutoff: datetime | None) -> list[dict[str, Any]]:
    """원장이 재생의 순수 확장인지 확인하고 붙일 행을 돌려준다 — 아니면 fail-closed.

    (a) 원장 중 available_at <= cutoff 인 행(cutoff 없으면 전부)은 원장 순서 그대로 재생 행의
        접두부와 id·본문이 같아야 한다. cutoff 보다 늦은 원장 행은 이전 실행이 더 넓은 cutoff
        로 쓴 정당한 행이므로 대조하지 않는다.
    (b) 붙일 행(접두부 뒤 나머지)의 available_at 은 원장 최대 available_at 보다 늦어야 한다.
        같을 때는 원장 마지막 행과 같은 영수증(중단된 빈티지 이어쓰기)만 허용한다.
    소급 영수증으로 재생이 갈라지면 (a) 또는 (b) 가 깨진다 — 갈라진 가지를 원장에 남기지 않는다.
    """
    inside = [row for row in existing if cutoff is None or _available(row) <= cutoff]
    if len(inside) > len(rows):
        raise MtsArtifactError(
            f"원장이 재생의 접두부가 아님: cutoff 이내 원장 {len(inside)}행 > 재생 {len(rows)}행")
    for index, (prior, row) in enumerate(zip(inside, rows)):
        if prior["observation_id"] != row["observation_id"]:
            raise MtsArtifactError(
                f"원장이 재생의 접두부가 아님(소급 영수증 의심): {index}번째 원장 "
                f"{prior['observation_id']} ≠ 재생 {row['observation_id']}")
        if _ledger_body(prior) != row:
            raise MtsArtifactError(f"append-only identity 충돌: {row['observation_id']}")
    pending = rows[len(inside):]
    if not pending or not existing:
        return pending
    known = {row["observation_id"] for row in existing}
    latest = max(_available(row) for row in existing)
    last_receipt = existing[-1].get("receipt_id")
    for row in pending:
        if row["observation_id"] in known:
            raise MtsArtifactError(f"append-only identity 충돌(cutoff 밖 기존 행): {row['observation_id']}")
        stamp = _available(row)
        if stamp < latest or (stamp == latest and row["receipt_id"] != last_receipt):
            raise MtsArtifactError(
                f"순수 확장 아님(소급 영수증 의심): {row['observation_id']} available_at "
                f"{row['available_at']} ≤ 원장 최대 {latest.isoformat()}")
    return pending


def _append_rows(root: Path, rows: list[dict[str, Any]], cutoff: datetime | None) -> int:
    """writer lock 안에서 원장을 다시 읽어 순수 확장을 재확인한 뒤 새 행만 append_event 한다.

    기존 행 본문 대조는 _plan_append 가 한 번에 한다 — append_event 는 호출마다 체인 전체를
    다시 검증하므로, 기존 행까지 append_event 로 넘기면 재실행이 O(행²) 가 된다.
    """
    with writer_lock(root):
        pending = _plan_append(read_chain(root, LEDGER_RELATIVE), rows, cutoff)
        for row in pending:
            append_event(root, LEDGER_RELATIVE, row)
    return len(pending)


def run_cli(root: Path, args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """fed-ebp-sidecar verb — 기본 dry-run, --append 일 때만 연구 원장에 쓴다."""
    append = bool(getattr(args, "append", False))
    base: dict[str, Any] = {
        "tool": "fed-ebp-sidecar",
        "source_id": SOURCE_ID,
        "parser_version": PARSER_VERSION,
        "ledger": LEDGER_RELATIVE.as_posix(),
        "row_rule": ROW_RULE,
        "display_only": True,
        "scoring_excluded": True,
        "notice": NOTICE,
        "live_forecast_use": False,
        "v2_archive_modified": False,
        "network_fetch_enabled": False,
        "retest_policy": RETEST_POLICY,
        "single_episode": False,
        "mode": "append" if append else "dry_run",
    }
    try:
        cutoff = _cutoff(args)
        replay = _replay(root, retrieved_until=cutoff)
        rows = replay["rows"]
        chain = read_chain(root, LEDGER_RELATIVE)
        existing = {row["observation_id"] for row in chain}
        pending = _plan_append(chain, rows, cutoff)  # dry-run 도 같은 검사로 미리 fail-closed
        planned_ids = {row["observation_id"] for row in rows}
        appended = _append_rows(root, rows, cutoff) if append else 0
    except MtsArtifactError as exc:
        return 2, {**base, "status": "error", "error": str(exc)}
    current = state_at(rows)
    last_day = max(current) if current else None
    payload = {
        **base,
        "status": "appended" if append else "dry_run",
        "receipt_cutoff": None if cutoff is None else cutoff.isoformat(),
        "n_receipts": len(replay["receipts"]),
        "receipts_backdated_in_file": replay["receipts_backdated_in_file"],
        "skipped_receipts": replay["skipped"],
        "n_vintages": len(replay["vintages"]),
        "n": len(rows),
        "n_dates": len(current),
        "vintages": replay["vintages"],
        "latest": None if last_day is None else {
            "observation_time": last_day,
            "ebp": current[last_day]["ebp"],
            "available_at": current[last_day]["available_at"],
            "vintage_seq": current[last_day]["vintage_seq"],
        },
        "v2_comparison": compare_with_v2(root, rows),
        "ledger_rows_existing": len(existing),
        "ledger_rows_not_in_replay": len(existing - planned_ids),
        "ledger_is_replay_prefix": True,  # _plan_append 통과 — 아니면 위에서 exit 2
        "rows_to_append": len(pending),
        "rows_appended": appended,
    }
    return 0, payload
