"""FRED 공식 API 수집 — `fredgraph.csv` 스크랩의 대체 경로.

FRED 이용약관은 "data mining, mirroring, robots, scraping, or similar
data-gathering or extraction methods"를 금지하면서 **"except as expressly
allowed by the terms of use applicable to the FRED API"** 라는 단서를 둔다.
`fredgraph.csv`는 그래프 페이지용 엔드포인트로 그 단서에 해당하지 않으므로,
자동 수집은 API 키를 쓰는 공식 API로만 한다 (DECISIONS 12-6).

두 가지를 지킨다.

1. **키는 영수증에 남기지 않는다.**  `observations_csv()`가 네트워크에 쓰는
   URL에는 키가 들어가지만, 소스 영수증·해시에 기록할 URL은
   `observations_public_url()`이 돌려주는 **키 없는** 형태여야 한다.  이 구분을
   흐리면 `security-check`가 잡아야 할 시크릿이 저장소에 커밋된다.
2. **호출부의 파서를 바꾸지 않는다.**  API는 JSON을 주지만 기존 수집기들은
   `fredgraph.csv` 모양(헤더 1줄 + `날짜,값`, 결측은 `.`)을 파싱한다.
   `observations_csv()`가 그 모양으로 렌더해 돌려주므로 파서는 그대로 둔다.
"""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.parse

OBSERVATIONS_ENDPOINT = "https://api.stlouisfed.org/fred/series/observations"

#: 결측 관측치 표기.  fredgraph.csv와 FRED API가 같은 규약을 쓴다.
MISSING = "."


class FredApiError(RuntimeError):
    """API 키 부재 또는 응답 형식 위반."""


def api_key() -> str:
    """환경변수에서 FRED API 키를 읽는다.

    키가 없으면 조용히 스크랩으로 되돌아가지 않고 실패한다 — 폴백을 두면
    약관 준수 경로가 사실상 무력해지기 때문이다.
    """
    key = (os.environ.get("FRED_API_KEY") or "").strip()
    if not key:
        raise FredApiError(
            "FRED_API_KEY가 필요합니다. FRED 약관은 API 경로만 자동 수집을 허용하며, "
            "fredgraph.csv 스크랩으로 대체하지 않습니다 (DECISIONS 12-6). "
            "무료 키: https://fredaccount.stlouisfed.org/apikeys"
        )
    return key


def observations_public_url(series_id: str, *, observation_start: str | None = None) -> str:
    """영수증·출처 표기에 쓸 **키 없는** URL.

    네트워크 요청에는 쓰지 않는다.  키가 포함된 URL을 그대로 기록하면 시크릿이
    저장소에 남는다.
    """
    params = {"series_id": series_id, "file_type": "json"}
    if observation_start:
        params["observation_start"] = observation_start
    return f"{OBSERVATIONS_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _request_url(series_id: str, *, key: str, observation_start: str | None) -> str:
    params = {"series_id": series_id, "api_key": key, "file_type": "json"}
    if observation_start:
        params["observation_start"] = observation_start
    return f"{OBSERVATIONS_ENDPOINT}?{urllib.parse.urlencode(params)}"


def observations_to_csv(payload: str | bytes, series_id: str) -> str:
    """FRED API JSON 응답을 `fredgraph.csv` 모양의 CSV 텍스트로 렌더한다.

    호출부 파서들이 헤더 1줄을 건너뛰고 `row[0]=날짜`, `row[1]=값`을 읽으므로
    같은 모양을 유지한다.  결측은 원본과 같이 `.`으로 남긴다 — 0으로 바꾸면
    관측되지 않은 구간이 관측된 0으로 둔갑한다.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    try:
        data = json.loads(payload)
        rows = data["observations"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FredApiError(f"FRED API 응답 형식 위반: {series_id}") from exc

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["observation_date", series_id])
    for row in rows:
        if not isinstance(row, dict):
            raise FredApiError(f"FRED API 관측치 형식 위반: {series_id}")
        writer.writerow([row.get("date", ""), row.get("value", MISSING) or MISSING])
    return buffer.getvalue()


def observations_csv(
    series_id: str, *, observation_start: str | None = None, timeout: int = 45,
    fetch_text=None,
) -> str:
    """공식 API로 관측치를 받아 `fredgraph.csv` 모양의 CSV 텍스트로 돌려준다.

    전송은 기본적으로 저장소가 이미 감사한 `quant.feed.get_with_curl_fallback`을
    재사용한다 (GitHub 러너에서 Python TLS 읽기가 간헐적으로 멈추는 문제 때문).
    호출부가 자체 전송을 주입할 수 있도록 `fetch_text`를 받되, **키가 담긴 URL은
    이 함수 밖으로 나가지 않는다** — 주입된 전송에만 전달되고 반환값에는 없다.
    """
    if fetch_text is None:
        from .quant import feed
        fetch_text = feed.get_with_curl_fallback

    url = _request_url(series_id, key=api_key(), observation_start=observation_start)
    return observations_to_csv(fetch_text(url, timeout=timeout), series_id)
