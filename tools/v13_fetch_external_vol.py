"""tools/v13_fetch_external_vol.py — P5 외부 정보집합 수집기 (FRED 호스팅 변동성 지수).

봉인 V2 아카이브에 **쓰지 않는다** (V13 계약 36행 no_write_to_sealed). 별도 비봉인 스토어
`data/timeseries_v13/external/` 에 원자료 영수증 + append-only 관측 원장을 남긴다.

라이선스: `fred_market_signals` (https://fred.stlouisfed.org/graph/fredgraph.csv) 는
docs/generated/licenses.generated.md 17행에서 status=approved · "계약 범위 내 파생 통계 표시".
CBOE **직접** CDN 경로는 같은 파일 27행에서 보류 상태이므로 쓰지 않는다.

재현성: 응답 원본을 gzip 으로 보관하고 sha256 을 영수증에 남긴다. 같은 URL 을 다시 받아도
과거 값이 바뀌지 않음을 이후 대사로 확인할 수 있다.

    PYTHONUTF8=1 python tools/v13_fetch_external_vol.py
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data/timeseries_v13/external"
RAW = STORE / "raw"
OBS = STORE / "vol_indices.jsonl"
RECEIPTS = STORE / "raw_receipts.jsonl"
PARSER_VERSION = "v13-external-vol-1.0"
SOURCE_ID = "fred_market_signals"
UA = "JinsInvestingResearch/1.0 (+public research dashboard)"

# 수집 대상 — 사전등록 문서에서 확정한 계열만. 결과를 본 뒤 추가하지 않는다.
SERIES = {
    "VXNCLS": "CBOE NASDAQ-100 Volatility Index",
    "VXVCLS": "CBOE S&P 500 3-Month Volatility Index",
    "VXDCLS": "CBOE DJIA Volatility Index",
    "OVXCLS": "CBOE Crude Oil ETF Volatility Index",
    "GVZCLS": "CBOE Gold ETF Volatility Index",
}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def _fetch(sid: str) -> bytes:
    req = urllib.request.Request(URL.format(sid=sid), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def _parse(raw: bytes) -> list[tuple[str, float]]:
    """fredgraph.csv → [(YYYY-MM-DD, value)]. 결측('.')은 버린다."""
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))))
    out: list[tuple[str, float]] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        day, value = row[0].strip(), row[1].strip()
        if not day or value in ("", "."):
            continue
        try:
            dt.date.fromisoformat(day)
            out.append((day, float(value)))
        except ValueError:
            continue
    return out


def _available_at(day: str) -> str:
    """관측일 종가가 확정·배포되는 시각.

    이 지수들은 미 동부 16:15 에 확정되는 **장 마감 지수**이며 사후 개정되지 않는다.
    champion 피처인 VIX 종가와 같은 거래소·같은 세션·같은 배포 시각이므로, 원점 t 에서
    VIX_t 를 쓰는 것과 정확히 같은 자격으로 쓸 수 있다. 21:15 UTC 는 동부 16:15 의 겨울시각
    대응이며, 서머타임 구간에서는 실제 배포가 이보다 1시간 이르다(보수적 방향).
    """
    return f"{day}T21:15:00+00:00"


def main() -> int:
    STORE.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    existing: set[tuple[str, str]] = set()
    if OBS.is_file():
        for line in OBS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                existing.add((row["series_id"], row["observation_time"]))

    receipts: list[dict] = []
    appended = 0
    with OBS.open("a", encoding="utf-8", newline="\n") as obs_fh:
        for sid, title in SERIES.items():
            raw = _fetch(sid)
            digest = hashlib.sha256(raw).hexdigest()
            blob = RAW / f"{sid}_{digest[:16]}.csv.gz"
            if not blob.is_file():
                blob.write_bytes(gzip.compress(raw))
            rows = _parse(raw)
            new = 0
            for day, value in rows:
                if (sid, day) in existing:
                    continue
                obs_fh.write(json.dumps({
                    "series_id": sid,
                    "observation_time": day,
                    "value": value,
                    "available_at": _available_at(day),
                    "data_grade": "published_close_no_revision",
                    "source_id": SOURCE_ID,
                    "raw_sha256": digest,
                    "parser_version": PARSER_VERSION,
                }, ensure_ascii=False) + "\n")
                existing.add((sid, day))
                new += 1
            appended += new
            receipts.append({
                "schema_version": 1,
                "series_id": sid,
                "title": title,
                "source_id": SOURCE_ID,
                "url": URL.format(sid=sid),
                "fetched_at": fetched_at,
                "bytes": len(raw),
                "raw_sha256": digest,
                "raw_path": str(blob.relative_to(ROOT)).replace("\\", "/"),
                "rows_parsed": len(rows),
                "rows_appended": new,
                "first_observation": rows[0][0] if rows else None,
                "last_observation": rows[-1][0] if rows else None,
                "license": "fred_market_signals — licenses.generated.md 17행 approved",
                "parser_version": PARSER_VERSION,
            })
            print(f"{sid:8s} {len(rows):6d}행 파싱 · {new:6d}행 신규 · "
                  f"{rows[0][0] if rows else '—'} ~ {rows[-1][0] if rows else '—'} · sha {digest[:12]}")

    with RECEIPTS.open("a", encoding="utf-8", newline="\n") as fh:
        for receipt in receipts:
            fh.write(json.dumps(receipt, ensure_ascii=False) + "\n")

    print(f"\n총 {appended}행 추가 · 원장 {OBS.relative_to(ROOT)} · 영수증 {len(receipts)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
