"""tools/v13_fetch_cftc_tff.py — CFTC Traders in Financial Futures(TFF, futures-only) 포지셔닝을 설계창용으로 적재한다.

## 원천 · 라이선스
- CFTC Public Reporting(Socrata) 데이터셋 `gpe5-46if`(TFF Futures Only). 저장소의 기존 후보 계약
  `data/contracts/cftc_cot_bitcoin_d0.yaml` 과 같은 엔드포인트. cftc.gov/data: "available for public download and use"
  (연방기관 산출물 — 공공영역, 출처 표기). 키 없음.
- 종목 코드는 **사전 핀**: VIX 선물(CFE) `1170E1` · NASDAQ-100 e-mini `209742`. 이름(`market_and_exchange_names`)은 2022-02 에
  개명됐으므로 코드로만 고른다.

## PIT — 보수 규칙 (발표 전 값 사용 금지)
- 보고 기준일은 화요일, 공표는 통상 금요일 15:30 ET. 연휴 주는 월요일 공표. 따라서 `available_at` 을
  **report_date + 7 달력일 00:00 ET(다음 화요일)** 로 둔다 — 실제 공표(금/월)보다 항상 같거나 늦다(룩어헤드 0).
- **2013-10 연방정부 셧다운**: 10-04 공표분부터 지연, CFTC 보도자료 6745-13(2013-10-23)에 따라 10-25 부터 순차 공표,
  11-08 공표분부터 정상. 보고 기준일 2013-10-01 ~ 2013-10-29 행은 `available_at = 2013-11-08` 로 고정(보수).
- 미보고 구간(예: VIX 선물 2008-12-23 ~ 2009-05-26 — TFF 에 행 없음, OI 가 얇아 보고 기준 미달로 추정 [미확인])은 그대로 둔다.
  블록 계산기가 `max_staleness_days` 를 넘는 구간을 NaN 으로 만든다 — step-fill 로 6개월을 채우지 않는다.

## 저장
- 원시 API 응답은 `exog/raw/cftc_tff_<code>_<sha16>.json.gz`(압축 전 sha256 을 영수증에), 정규화 행은
  `exog/cftc_tff_positions.jsonl`(append-only 취급 — 이 도구는 파일이 있으면 재작성하지 않고 거부한다).

    PYTHONUTF8=1 python tools/v13_fetch_cftc_tff.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data/timeseries_v13/exog"
RAW = STORE / "raw"
OUT = STORE / "cftc_tff_positions.jsonl"
RECEIPTS = STORE / "raw_receipts.jsonl"
PARSER_VERSION = "v13-exog-cftc-tff-1.0"
UA = "JinsInvestingResearch/1.0 (+public research dashboard)"
ENDPOINT = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
CONTRACTS = {"1170E1": "vix_futures_cfe", "209742": "nasdaq100_mini_cme"}
RANGE = ("2006-01-01", "2015-12-31")     # 설계창 2007-2014 + D1 류 선행창 여유. 홀드아웃(2015)은 적재만, 사용 금지
SHUTDOWN_REPORTS = (date(2013, 10, 1), date(2013, 10, 29))
SHUTDOWN_AVAILABLE = "2013-11-08"
SHUTDOWN_SOURCE = "https://www.cftc.gov/PressRoom/PressReleases/6745-13"
FIELDS = ["report_date_as_yyyy_mm_dd", "cftc_contract_market_code", "market_and_exchange_names", "open_interest_all",
          "dealer_positions_long_all", "dealer_positions_short_all", "dealer_positions_spread_all",
          "asset_mgr_positions_long", "asset_mgr_positions_short", "asset_mgr_positions_spread",
          "lev_money_positions_long", "lev_money_positions_short", "lev_money_positions_spread",
          "other_rept_positions_long", "other_rept_positions_short", "nonrept_positions_long_all",
          "nonrept_positions_short_all"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch(code: str) -> tuple[bytes, int, str]:
    params = {
        "$select": ",".join(FIELDS),
        "$where": f"cftc_contract_market_code='{code}' AND report_date_as_yyyy_mm_dd between '{RANGE[0]}' and '{RANGE[1]}'",
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": "5000",
    }
    url = ENDPOINT + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 — 연방 공공 API 고정 URL
        return resp.read(), int(resp.status), url


def _receipt(row: dict) -> None:
    existing = RECEIPTS.read_text(encoding="utf-8").splitlines() if RECEIPTS.exists() else []
    if any(json.loads(line).get("raw_sha256") == row["raw_sha256"] for line in existing if line.strip()):
        return
    with RECEIPTS.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def available_at(report_date: date) -> tuple[str, str]:
    if SHUTDOWN_REPORTS[0] <= report_date <= SHUTDOWN_REPORTS[1]:
        return SHUTDOWN_AVAILABLE, "shutdown_backlog_fixed_2013-11-08"
    return (report_date + timedelta(days=7)).isoformat(), "report_date_plus_7_calendar_days"


def _int(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def main() -> int:
    if OUT.exists():
        print(f"{OUT.relative_to(ROOT).as_posix()} 가 이미 있다 — 적재는 1회용이다. 재적재는 새 파일명으로.")
        return 2
    RAW.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for code, slug in CONTRACTS.items():
        payload, status, url = _fetch(code)
        sha = hashlib.sha256(payload).hexdigest()
        raw_path = RAW / f"cftc_tff_{code}_{sha[:16]}.json.gz"
        if not raw_path.exists():
            with gzip.GzipFile(filename=str(raw_path), mode="wb", mtime=0) as gz:
                gz.write(payload)
        data = json.loads(payload.decode("utf-8"))
        _receipt({"schema_version": 1, "source_id": "cftc_public_reporting", "series_id": f"tff_{slug}_{code}",
                  "public_url": url, "http_status": status, "raw_path": raw_path.relative_to(ROOT).as_posix(),
                  "raw_sha256": sha, "bytes": len(payload), "stored_encoding": "gzip", "rows": len(data),
                  "fetched_at": _now(), "parser_version": PARSER_VERSION,
                  "license": "US federal agency public data (cftc.gov/data: available for public download and use); attribution",
                  "pit_rule": "available_at = report_date + 7 calendar days; 2013-10-01..10-29 reports fixed to 2013-11-08 (CFTC release 6745-13)"})
        seen: set[str] = set()
        for r in data:
            rd = str(r["report_date_as_yyyy_mm_dd"])[:10]
            if rd in seen:
                raise ValueError(f"duplicate report date {code} {rd}")
            seen.add(rd)
            avail, rule = available_at(date.fromisoformat(rd))
            oi = _int(r.get("open_interest_all"))
            lev_l, lev_s = _int(r.get("lev_money_positions_long")), _int(r.get("lev_money_positions_short"))
            am_l, am_s = _int(r.get("asset_mgr_positions_long")), _int(r.get("asset_mgr_positions_short"))
            dl_l, dl_s = _int(r.get("dealer_positions_long_all")), _int(r.get("dealer_positions_short_all"))
            rows.append({
                "schema_version": 1, "source_id": "cftc_public_reporting", "contract_code": code, "contract": slug,
                "market_name": r.get("market_and_exchange_names"), "report_date": rd,
                "available_at": avail, "available_at_rule": rule,
                "open_interest": oi,
                "lev_money_long": lev_l, "lev_money_short": lev_s, "lev_money_spread": _int(r.get("lev_money_positions_spread")),
                "asset_mgr_long": am_l, "asset_mgr_short": am_s, "asset_mgr_spread": _int(r.get("asset_mgr_positions_spread")),
                "dealer_long": dl_l, "dealer_short": dl_s,
                "lev_net_over_oi": (round((lev_l - lev_s) / oi, 6) if oi and lev_l is not None and lev_s is not None else None),
                "asset_mgr_net_over_oi": (round((am_l - am_s) / oi, 6) if oi and am_l is not None and am_s is not None else None),
                "dealer_net_over_oi": (round((dl_l - dl_s) / oi, 6) if oi and dl_l is not None and dl_s is not None else None),
                "raw_sha256": sha,
            })
        print(f"{code} {slug}: {len(data)} rows {min(seen)}..{max(seen)}")
    rows.sort(key=lambda r: (r["report_date"], r["contract_code"]))
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()}: {len(rows)} rows · sha256 {hashlib.sha256(OUT.read_bytes()).hexdigest()[:16]}…")
    print(f"shutdown-fixed rows: {sum(r['available_at_rule'].startswith('shutdown') for r in rows)} (source {SHUTDOWN_SOURCE})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
