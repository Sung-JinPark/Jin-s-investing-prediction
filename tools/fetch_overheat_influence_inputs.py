"""과열도 v7 영향도 측정용 장기 이력 수집 — 공식 FRED API 에서 한 번 받아 파일로 고정한다.

생산 계산(매일의 지수)은 원장만 쓴다. 이 파일은 '어느 지표가 증시 하락에 앞서 움직였나'를 재는 1회성 분석의 입력이며,
수집 시점의 최신 개정본이다(당시 발표본이 아님). 점수는 여기서 계산하지 않는다.

    FRED_API_KEY=... python tools/fetch_overheat_influence_inputs.py

키는 환경 변수에서만 읽고 어디에도 쓰지 않는다(저장되는 URL 에는 키가 없다).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/statistics/overheat/influence_inputs_v7.json"
API = "https://api.stlouisfed.org/fred/series/observations"
USER_AGENT = "JinsInvestingOverheatInfluence/1.0 (+public research dashboard)"
START = "1960-01-01"
#: 원장이 이미 가진 계열의 장기 이력(생산 계산과 같은 계열 — Z.1 직접 수집 두 개는 같은 코드의 FRED 미러).
SERIES = {
    "NASDAQCOM": "daily", "T10Y3M": "daily", "T10Y2Y": "daily", "DCOILWTICO": "daily",
    "NFCI": "weekly",
    "M2SL": "monthly", "FEDFUNDS": "monthly", "GS10": "monthly", "HQMCB10YR": "monthly", "CPIAUCSL": "monthly",
    "UNRATE": "monthly", "TOTALSL": "monthly", "SPASTT01USM661N": "monthly", "HOUST": "monthly",
    "GDP": "quarterly", "GFDEBTN": "quarterly", "DRTSCILM": "quarterly", "CPATAX": "quarterly",
    "W328RC1Q027SBEA": "quarterly", "Y001RC1Q027SBEA": "quarterly", "Y034RC1Q027SBEA": "quarterly",
    "NCBEILQ027S": "quarterly", "BOGZ1LM153064475Q": "quarterly", "BOGZ1LM893064105Q": "quarterly",
    "DABSHNO": "quarterly", "BOGZ1FL010000346Q": "quarterly", "TDSP": "quarterly",
    "BOGZ1FL663067003Q": "quarterly", "BOGZ1FL103163005Q": "quarterly", "BOGZ1FA103163005Q": "quarterly",
}
LEDGER_ALIAS = {"BOGZ1FL663067003Q": "FL663067003", "BOGZ1FL103163005Q": "FL103163005",
                "BOGZ1FA103163005Q": "FA103163005"}


def fetch(series_id: str, key: str) -> list[list]:
    query = urllib.parse.urlencode({"series_id": series_id, "api_key": key, "file_type": "json",
                                    "observation_start": START})
    request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.load(response)
            return [[row["date"], float(row["value"])] for row in payload["observations"]
                    if row["value"] not in (".", "")]
        except Exception as exc:  # noqa: BLE001 — 일시 오류는 다시 시도, 끝내 실패하면 이름만 알린다
            last = exc
            time.sleep(2 + 3 * attempt)
    raise SystemExit(f"FRED fetch failed for {series_id}: {type(last).__name__}")


def main() -> int:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise SystemExit("FRED_API_KEY is not set")
    series = {}
    for series_id, frequency in SERIES.items():
        rows = fetch(series_id, key)
        if not rows:
            raise SystemExit(f"FRED returned no observations for {series_id}")
        name = LEDGER_ALIAS.get(series_id, series_id)
        series[name] = {"fred_id": series_id, "frequency": frequency, "first": rows[0][0], "last": rows[-1][0],
                        "n": len(rows), "observations": rows}
        sys.stdout.write(f"{name:22s} {frequency:9s} {rows[0][0]} .. {rows[-1][0]}  n={len(rows)}\n")
    body = json.dumps(series, sort_keys=True, separators=(",", ":"))
    payload = {
        "schema_version": 1, "dataset_id": "overheat_influence_inputs_v7",
        "source": "FRED API (api.stlouisfed.org/fred/series/observations), observation_start " + START,
        "vintage": "latest revision at fetch time — not point-in-time",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "series": series,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8",
                   newline="\n")
    sys.stdout.write(f"wrote {OUT.relative_to(ROOT).as_posix()} sha256={payload['sha256'][:16]} "
                     f"bytes={OUT.stat().st_size}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
