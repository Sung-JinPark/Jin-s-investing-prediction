"""tools/v13_fetch_scheduled_events.py — rung-7 예정 이벤트 달력(2007-2014)을 연방 공공영역 원천에서 적재한다.

## 무엇을 적재하는가

| kind | 원천 | 정의 |
|---|---|---|
| `fomc_scheduled` | Fed Board `fomchistorical{YYYY}.htm` (h5 "… Meeting - YYYY") | 정례 FOMC 회의의 **마지막 날**(성명 발표일) |
| `fomc_unscheduled` | 같은 페이지의 "Conference Call" · "(unscheduled)" 항목 | **블록에서 제외** — origin 시점에 알 수 없던 회의. 기록만 한다 |
| `bls_empsit` | BLS Archived News Releases 색인(고용보고서) | 실제 발표일 (아카이브 파일명 MMDDYYYY) |
| `bls_cpi` | BLS Archived News Releases 색인(CPI) | 실제 발표일 |

BLS 색인은 봇 차단(HTTP 403)으로 curl 로 받을 수 없어 내장 브라우저로 앵커 href 를 추출한 증거 JSON
(`data/timeseries_v13/exog/raw/bls_*_archive_release_dates_2007_2014.json`)을 입력으로 쓴다.
Fed 페이지는 직접 받아 원본 바이트를 `raw/` 에 보존하고 sha256 영수증을 남긴다.

## 라이선스
- Fed Board: "Unless otherwise indicated, information on the Board's website is in the public domain" (federalreserve.gov/disclaimer.htm).
- BLS: 공공영역, 출처 표기 요청 (bls.gov/bls/linksite.htm).

## PIT
- FOMC 정례 일정은 전년도에 공표된다 → 등급 `prepublished_schedule`, lag 0.
- BLS 는 연초 공표 일정 기준이나 여기 적재한 것은 **실제 발표일**이다. 2013-10 연방정부 셧다운으로 예정일≠실제일인
  발표(고용 2013-10-04→10-22 · 11-01→11-08, CPI 2013-10-16→10-30 · 11-15→11-20)는 `shutdown_shift: true` 로 표시한다.
  블록 정의(계약 rung7_calendar_blocks)가 이 행들을 어떻게 다루는지는 계약이 정본이다.

    PYTHONUTF8=1 python tools/v13_fetch_scheduled_events.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data/timeseries_v13/exog"
RAW = STORE / "raw"
OUT = STORE / "scheduled_events_2007_2014.jsonl"
RECEIPTS = STORE / "raw_receipts.jsonl"
PARSER_VERSION = "v13-exog-calendar-1.0"
UA = "JinsInvestingResearch/1.0 (+public research dashboard)"
YEARS = range(2007, 2015)
FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], start=1)}
# 2013-10 셧다운으로 연초 예정일과 실제 발표일이 다른 발표. 원래 예정일은 BLS 공식 '수정 일정' 페이지
# (https://www.bls.gov/bls/updated_release_schedule.htm — 'Originally scheduled' 열)에서 2026-10-21 내장 브라우저로 대조했다.
SHUTDOWN_VERIFICATION_URL = "https://www.bls.gov/bls/updated_release_schedule.htm"
SHUTDOWN_SHIFTS = {
    ("bls_empsit", "2013-10-22"): "2013-10-04",
    ("bls_empsit", "2013-11-08"): "2013-11-01",
    ("bls_cpi", "2013-10-30"): "2013-10-16",
    ("bls_cpi", "2013-11-20"): "2013-11-15",
}
EXPECTED_SCHEDULED_PER_YEAR = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch(url: str) -> tuple[bytes, int]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — 연방 공공 사이트 고정 URL
        return resp.read(), int(resp.status)


def _receipt(row: dict) -> None:
    existing = RECEIPTS.read_text(encoding="utf-8").splitlines() if RECEIPTS.exists() else []
    if any(json.loads(line).get("raw_sha256") == row["raw_sha256"] for line in existing if line.strip()):
        return
    with RECEIPTS.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


HEADING = re.compile(r"<h5[^>]*>(.*?)</h5>", re.S)
SPAN = re.compile(
    r"^(?P<m1>[A-Z][a-z]+)(?:/(?P<m2>[A-Z][a-z]+))?\s+(?P<d1>\d{1,2})(?:-(?:(?P<m3>[A-Z][a-z]+)\s+)?(?P<d2>\d{1,2}))?")


def parse_fomc(html: str, year: int) -> list[dict]:
    rows = []
    for raw in HEADING.findall(html):
        text = re.sub(r"<[^>]+>", "", raw)
        text = re.sub(r"\s+", " ", text).strip()
        if not text.endswith(f"- {year}"):
            continue
        body = text[: -len(f"- {year}")].strip()
        if "Meeting" in body and "unscheduled" not in body.lower():
            kind = "fomc_scheduled"
        elif "Conference Call" in body or "unscheduled" in body.lower():
            kind = "fomc_unscheduled"
        else:
            raise ValueError(f"unrecognised FOMC heading {text!r}")
        m = SPAN.match(body)
        if not m:
            raise ValueError(f"cannot parse span in {text!r}")
        d = m.groupdict()
        # 마지막 날 = 성명 발표일. "July 31-August 1" → August 1 · "April/May 30-1" → May 1 · "January 29-30" → Jan 30
        if d["d2"] is not None:
            month = d["m3"] or d["m2"] or d["m1"]
            day = int(d["d2"])
        else:
            month = d["m1"]
            day = int(d["d1"])
        rows.append({"kind": kind, "event_date": f"{year}-{MONTHS[month]:02d}-{day:02d}", "label": text})
    scheduled = [r for r in rows if r["kind"] == "fomc_scheduled"]
    if len(scheduled) != EXPECTED_SCHEDULED_PER_YEAR:
        raise ValueError(f"{year}: scheduled FOMC meetings {len(scheduled)} != {EXPECTED_SCHEDULED_PER_YEAR}: {scheduled}")
    return rows


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []
    for year in YEARS:
        url = FED_URL.format(year=year)
        payload, status = _fetch(url)
        sha = hashlib.sha256(payload).hexdigest()
        # rung-6 선례(VXNCLS_*.json.gz)와 같이 원본 바이트를 gzip 으로 보존한다. sha256 은 **압축 전** 바이트 기준.
        raw_path = RAW / f"fomchistorical{year}_{sha[:16]}.htm.gz"
        if not raw_path.exists():
            with gzip.GzipFile(filename=str(raw_path), mode="wb", mtime=0) as gz:
                gz.write(payload)
        _receipt({"schema_version": 1, "source_id": "federal_reserve_board", "series_id": f"fomc_calendar_{year}",
                  "public_url": url, "http_status": status, "raw_path": raw_path.relative_to(ROOT).as_posix(),
                  "raw_sha256": sha, "bytes": len(payload), "stored_encoding": "gzip",
                  "fetched_at": _now(), "parser_version": PARSER_VERSION,
                  "license": "public domain (federalreserve.gov/disclaimer.htm)"})
        for row in parse_fomc(payload.decode("utf-8", errors="replace"), year):
            events.append({**row, "source_id": "federal_reserve_board", "source_url": url, "raw_sha256": sha,
                           "pit_grade": "prepublished_schedule" if row["kind"] == "fomc_scheduled" else "not_prepublished",
                           "in_block": row["kind"] == "fomc_scheduled", "shutdown_shift": False})
        print(f"FOMC {year}: {sum(r['kind']=='fomc_scheduled' for r in events if r['event_date'].startswith(str(year)))} scheduled · "
              f"{sum(r['kind']=='fomc_unscheduled' for r in events if r['event_date'].startswith(str(year)))} unscheduled")

    for kind, fname in (("bls_empsit", "bls_empsit_archive_release_dates_2007_2014.json"),
                        ("bls_cpi", "bls_cpi_archive_release_dates_2007_2014.json")):
        path = RAW / fname
        payload = path.read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        doc = json.loads(payload.decode("utf-8"))
        _receipt({"schema_version": 1, "source_id": "bls_archive_index", "series_id": kind,
                  "public_url": doc["page_url"], "http_status": None, "raw_path": path.relative_to(ROOT).as_posix(),
                  "raw_sha256": sha, "bytes": len(payload), "fetched_at": doc["captured_at"],
                  "parser_version": PARSER_VERSION, "capture_method": doc["capture_method"],
                  "license": doc["license"]})
        for r in doc["release_dates"]:
            shifted_from = SHUTDOWN_SHIFTS.get((kind, r["release_date"]))
            events.append({"kind": kind, "event_date": r["release_date"], "label": f"{doc['release']} release",
                           "source_id": "bls_archive_index", "source_url": "https://www.bls.gov" + r["href"],
                           "raw_sha256": sha, "pit_grade": "actual_release_date", "in_block": True,
                           "shutdown_shift": shifted_from is not None,
                           **({"originally_scheduled": shifted_from,
                               "originally_scheduled_source": SHUTDOWN_VERIFICATION_URL} if shifted_from else {})})
        print(f"{kind}: {len(doc['release_dates'])} rows")

    events.sort(key=lambda r: (r["event_date"], r["kind"]))
    seen = set()
    for r in events:
        key = (r["kind"], r["event_date"])
        if key in seen:
            raise ValueError(f"duplicate event {key}")
        seen.add(key)
        r["schema_version"] = 1
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        for r in events:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()}: {len(events)} rows · sha256 {hashlib.sha256(OUT.read_bytes()).hexdigest()[:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
