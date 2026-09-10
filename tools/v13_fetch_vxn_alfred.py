"""tools/v13_fetch_vxn_alfred.py — VXNCLS 를 ALFRED 빈티지로 PIT 적격 수집한다.

## 왜 이 도구가 필요한가

V9 계약이 VXNCLS 를 `blocked_features` 에 `required: alfred_vintage_collection` 으로 올려 뒀다.
현재 vintage 는 계약(`data/contracts/fred_market_signals.yaml`)이 스스로
"historical current-vintage rows are not valid for backtests" 라 적는 등급이다.

## 취득 경로 — DECISIONS 12-6 준수

공식 API `api.stlouisfed.org` 를 **API 키와 함께** 쓴다. `fredgraph.csv` 스크랩은 쓰지 않는다.
키는 네트워크 URL 에만 들어가고 영수증·원장에는 **키 없는 공개형 URL** 만 남긴다.

## ALFRED 빈티지의 한계 — 실측하고 공시한다

VXNCLS 의 ALFRED 최초 빈티지는 **2014-04-17** 이다(빈티지 3,100개, `series/vintagedates` 실측).
설계창 전반부(2007-2010)에는 동시대 빈티지가 **존재하지 않는다**. 따라서:

- `2014-04-16` 이하 관측 → **최초 가용 빈티지(2014-04-17)** 의 값을 쓴다.
  등급 `earliest_available_vintage` — archive_verified 가 아니고, 현재본보다는 낫다.
- `2014-04-17` 이상 관측 → 그 관측이 처음 등장한 빈티지의 값(초판)을 쓴다.
  등급 `initial_release`.

이 구분이 왜 중요한가: 2026-09-10 실측에서 최초 빈티지와 현재본이 설계창 1,903일 중
**2일** 어긋났다. `2009-11-27` 25.40→25.41(사소)과 **`2010-04-27` 21.30→17.81**.
후자는 현재본이 전일값을 복사한 손상이며, VIX 가 +5.34 급등한 날의 변동성 정보를 지운다.
즉 현재본을 그대로 쓰면 설계창 전반부의 사건일 하나가 사라진 채로 검정하게 된다.

    PYTHONUTF8=1 python tools/v13_fetch_vxn_alfred.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_fc.fred_api import OBSERVATIONS_ENDPOINT, api_key  # noqa: E402

SERIES = "VXNCLS"
STORE = ROOT / "data/timeseries_v13/exog"
RAW = STORE / "raw"
OBS = STORE / "vxn_vintage_observations.jsonl"
RECEIPTS = STORE / "raw_receipts.jsonl"
AUDIT = STORE / "vxn_vintage_vs_current_audit.json"
PARSER_VERSION = "v13-exog-alfred-1.0"
SOURCE_ID = "alfred"
UA = "JinsInvestingResearch/1.0 (+public research dashboard)"
VINTAGE_ENDPOINT = "https://api.stlouisfed.org/fred/series/vintagedates"

DESIGN_START = "2007-01-01"
OBS_END = "2014-12-31"   # 설계창 끝. 라이브 확장은 별도 트랙.


def _public_url(params: dict) -> str:
    """영수증에 남길 **키 없는** URL."""
    safe = {k: v for k, v in params.items() if k != "api_key"}
    return OBSERVATIONS_ENDPOINT + "?" + urllib.parse.urlencode(safe)


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def _observations(key: str, *, realtime: tuple[str, str],
                  obs_range: tuple[str, str]) -> tuple[list[dict], str, bytes]:
    params = {
        "series_id": SERIES, "api_key": key, "file_type": "json",
        "realtime_start": realtime[0], "realtime_end": realtime[1],
        "observation_start": obs_range[0], "observation_end": obs_range[1],
    }
    raw = _get(OBSERVATIONS_ENDPOINT + "?" + urllib.parse.urlencode(params))
    rows = json.loads(raw.decode("utf-8"))["observations"]
    return rows, _public_url(params), raw


def _first_vintage(key: str) -> str:
    params = {"series_id": SERIES, "api_key": key, "file_type": "json"}
    raw = _get(VINTAGE_ENDPOINT + "?" + urllib.parse.urlencode(params))
    dates = json.loads(raw.decode("utf-8"))["vintage_dates"]
    if not dates:
        raise RuntimeError(f"{SERIES} 에 ALFRED 빈티지가 없다")
    return dates[0]


def _keep(rows: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        value = (row.get("value") or "").strip()
        if value in ("", "."):
            continue
        try:
            out[row["date"]] = float(value)
        except (KeyError, ValueError):
            continue
    return out


def main() -> int:
    key = api_key()
    STORE.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    first_vintage = _first_vintage(key)
    print(f"{SERIES} ALFRED 최초 빈티지: {first_vintage}")
    cutoff = (datetime.fromisoformat(first_vintage).date()).isoformat()

    receipts: list[dict] = []

    # ① 최초 가용 빈티지에서 본 과거 구간
    early_rows, early_url, early_raw = _observations(
        key, realtime=(first_vintage, first_vintage), obs_range=(DESIGN_START, cutoff))
    early = _keep(early_rows)
    early_digest = hashlib.sha256(early_raw).hexdigest()
    (RAW / f"{SERIES}_vintage_{first_vintage}_{early_digest[:16]}.json.gz").write_bytes(
        gzip.compress(early_raw))
    receipts.append({
        "schema_version": 1, "series_id": SERIES, "source_id": SOURCE_ID,
        "segment": "earliest_available_vintage", "vintage": first_vintage,
        "observation_range": [DESIGN_START, cutoff], "rows": len(early),
        "public_url": early_url, "raw_sha256": early_digest, "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
    })
    print(f"  최초빈티지 구간 {DESIGN_START} ~ {cutoff}: {len(early)}행")

    # ② 최초 빈티지 이후는 초판(initial release)
    #    realtime 범위를 통째로 열면 빈티지 상한(API 제한)에 걸린다 — 연 단위로 쪼갠다.
    late_all: list[dict] = []
    late_raw_parts: list[bytes] = []
    late_url = ""
    start_year = int(cutoff[:4])
    end_year = int(OBS_END[:4])
    for year in range(start_year, end_year + 1):
        rt0 = max(f"{year}-01-01", first_vintage)
        rt1 = f"{year}-12-31"
        try:
            rows, url, raw = _observations(
                key, realtime=(rt0, rt1), obs_range=(cutoff, OBS_END))
        except urllib.error.HTTPError as exc:
            print(f"  [건너뜀] realtime {rt0}~{rt1}: HTTP {exc.code}")
            continue
        late_all.extend(r for r in rows if (r.get("value") or ".").strip() not in ("", "."))
        late_raw_parts.append(raw)
        late_url = url
    late_raw = b"\n".join(late_raw_parts)
    late: dict[str, float] = {}
    late_release: dict[str, str] = {}
    for row in sorted(late_all, key=lambda r: (r["date"], r.get("realtime_start", ""))):
        day = row["date"]
        if day in late:
            continue  # 같은 날짜의 첫 realtime 행 = 초판
        try:
            late[day] = float(row["value"])
        except ValueError:
            continue
        late_release[day] = row.get("realtime_start", "")
    late_digest = hashlib.sha256(late_raw).hexdigest()
    (RAW / f"{SERIES}_initial_{late_digest[:16]}.json.gz").write_bytes(gzip.compress(late_raw))
    receipts.append({
        "schema_version": 1, "series_id": SERIES, "source_id": SOURCE_ID,
        "segment": "initial_release", "vintage": f"{first_vintage}..latest",
        "observation_range": [cutoff, OBS_END], "rows": len(late),
        "public_url": late_url, "raw_sha256": late_digest, "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
    })
    print(f"  초판 구간 {cutoff} ~ : {len(late)}행")

    # ③ 현재본 — 감사용(검정에는 쓰지 않는다)
    today = datetime.now(timezone.utc).date().isoformat()
    cur_rows, cur_url, cur_raw = _observations(
        key, realtime=(today, today), obs_range=(DESIGN_START, OBS_END))
    current = _keep(cur_rows)
    cur_digest = hashlib.sha256(cur_raw).hexdigest()
    (RAW / f"{SERIES}_current_{cur_digest[:16]}.json.gz").write_bytes(gzip.compress(cur_raw))
    receipts.append({
        "schema_version": 1, "series_id": SERIES, "source_id": SOURCE_ID,
        "segment": "current_vintage_audit_only", "vintage": "latest",
        "observation_range": [DESIGN_START, OBS_END], "rows": len(current),
        "public_url": cur_url, "raw_sha256": cur_digest, "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
        "note": "감사 전용 — 검정에 쓰지 않는다. PIT 계열과 어긋난 날을 드러내기 위해서만 받는다.",
    })

    pit = dict(early)
    grade = {day: "earliest_available_vintage" for day in early}
    for day, value in late.items():
        pit[day] = value
        grade[day] = "initial_release"

    mismatches = []
    for day in sorted(set(pit) & set(current)):
        if abs(pit[day] - current[day]) > 1e-9:
            mismatches.append({"date": day, "pit": pit[day], "current": current[day],
                               "grade": grade[day],
                               "delta": round(current[day] - pit[day], 6)})

    with OBS.open("w", encoding="utf-8", newline="\n") as fh:
        for day in sorted(pit):
            fh.write(json.dumps({
                "series_id": SERIES,
                "observation_time": day,
                "value": pit[day],
                "available_at": f"{day}T21:15:00+00:00",
                "pit_grade": grade[day],
                "vintage_used": first_vintage if grade[day] == "earliest_available_vintage"
                                else late_release.get(day, ""),
                "source_id": SOURCE_ID,
                "parser_version": PARSER_VERSION,
            }, ensure_ascii=False) + "\n")

    with RECEIPTS.open("a", encoding="utf-8", newline="\n") as fh:
        for receipt in receipts:
            fh.write(json.dumps(receipt, ensure_ascii=False) + "\n")

    audit = {
        "schema": "v13_vxn_vintage_vs_current_audit",
        "series_id": SERIES,
        "alfred_first_vintage": first_vintage,
        "limitation": (
            f"설계창 전반부(2007-2010)에는 동시대 빈티지가 존재하지 않는다 — ALFRED 최초 빈티지가 "
            f"{first_vintage} 이다. 그 이전 관측은 최초 가용 빈티지의 값을 쓰며 등급은 "
            "earliest_available_vintage 다. archive_verified 가 아니다."),
        "rows_pit": len(pit),
        "rows_current": len(current),
        "compared": len(set(pit) & set(current)),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "why_it_matters": (
            "현재본을 그대로 쓰면 원래 발표값과 다른 날이 생긴다. 아래 목록이 그 전부이며, "
            "검정에는 PIT 열을 쓴다."),
        "fetched_at": fetched_at,
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=1, sort_keys=True),
                     encoding="utf-8", newline="\n")

    print(f"\nPIT 관측 {len(pit)}행 · 현재본과 비교 {audit['compared']}일 · 불일치 {len(mismatches)}일")
    for m in mismatches:
        print(f"   {m['date']}: PIT {m['pit']} → 현재 {m['current']} ({m['grade']})")
    print(f"기록: {OBS.relative_to(ROOT)} · 영수증 {len(receipts)}건 · 감사 {AUDIT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
