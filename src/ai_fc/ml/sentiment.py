"""FinBERT 금융 감성 지수 — GDELT 헤드라인 수집 → 추론 전용 스코어링.

**소스 이력**: 2026-08-31 Google News RSS 수집을 중단하고(DECISIONS 12-4a)
같은 날 GDELT로 재개했다(12-7).  Google News는 피드 응답 본문에 라이선스가
내장돼 "personal feed reader" 용도로 한정하고 그 외 사용을 명시 금지했으며
`robots.txt`가 `/rss/`를 전 UA에 disallow 했다.

GDELT는 조사한 소스 중 **자동 수집·파생 집계 공개·제목 표시 셋을 모두 명시적으로
허용하는 유일한 곳**이다 (gdeltproject.org/about.html#termsofuse):

    "all datasets released by the GDELT Project are available for unlimited and
    unrestricted use for any academic, commercial, or governmental use of any
    kind without fee."
    "You may redistribute, rehost, republish, and mirror any of the GDELT
    datasets in any form. However, any use or redistribution of the data must
    include a citation to the GDELT Project and a link to this website."

AI/ML 사용을 제한하는 조항이 없고(FRED와 대비된다), API 키가 필요 없으며,
`api.gdeltproject.org`에는 robots.txt 자체가 없다.

**인용은 선택이 아니라 허가의 조건이다.**  `ATTRIBUTION`을 감성 지수가 표시되는
모든 산출물에 함께 실어야 한다.

- 모델: ProsusAI/finbert (~110M) — 금융 텍스트 positive/negative/neutral 분류.
- 출력: 피드별·종합 감성 지수 [-1, +1] = (P(pos)−P(neg))의 헤드라인 평균.
- 한계: 헤드라인 감성은 동행·후행 지표에 가깝다 — base rate 문맥 신호로만 사용.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

MODEL_ID = "ProsusAI/finbert"
_clf = None

ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = {"User-Agent": "AI-Superforecaster/1.0 (+non-commercial research)"}

#: 허가 조건.  감성 지수를 표시하는 산출물에 반드시 함께 실어야 한다.
ATTRIBUTION = "출처: The GDELT Project — https://www.gdeltproject.org/"

#: GDELT 질의.  단일 항을 괄호로 싸면 API가 거부한다
#: ("Parentheses may only be used around OR'd statements").
#: FinBERT는 영문 금융 텍스트 모델이라 `sourcelang:english`로 고정한다 —
#: 필터 없이 돌리면 중국어 헤드라인이 섞여 들어온다(실측).
FEEDS = {
    "ai-semis": "(NVIDIA OR TSMC OR semiconductor) AI stocks sourcelang:english",
    "fed-macro": "Federal Reserve rate inflation sourcelang:english",
    "market": "Nasdaq stock market sourcelang:english",
    # 등록 질문 도메인 정렬 (NVDA 실적 2문, MU 마진 질문)
    "nvda": "NVIDIA stock earnings sourcelang:english",
    "memory": "(Micron OR SK Hynix) memory chip prices sourcelang:english",
}

#: 피드 간 최소 간격(초).  GDELT는 rate limit 수치를 공개하지 않고, 5개 피드를
#: 연속 호출하면 절반이 URLError로 떨어지는 것을 실측했다.  같은 질의가 잠시 뒤
#: 재시도에서 성공하므로 질의 문법이 아니라 유량 문제다.
FEED_INTERVAL_SECONDS = 8.0


@dataclass
class FeedSentiment:
    feed: str
    n_headlines: int
    score: float               # [-1, +1]
    top_negative: list[str] = field(default_factory=list)
    top_positive: list[str] = field(default_factory=list)


def normalize_title(title: str) -> str:
    """GDELT 제목의 토큰화 흔적을 되돌린다.

    GDELT는 제목을 토큰화해 보관하므로 구두점 앞에 공백이 들어간다 —
    실측: "Ive Covered Semiconductors for 5 Years . Nvidia Is My No . 1 Pick".
    FinBERT에 그대로 넣으면 문장 경계가 잘못 잡히므로 정리한다.  아포스트로피는
    GDELT 단계에서 이미 사라져 복원할 수 없다("Ive") — 감성 분류에는 영향이 작다.
    """
    title = re.sub(r"\s+([.,!?;:%])", r"\1", title)
    return re.sub(r"\s{2,}", " ", title).strip()


def fetch_headlines(query: str, limit: int = 25, *, retries: int = 4) -> list[str]:
    """GDELT DOC 2.0에서 최근 헤드라인 제목을 받는다.

    GDELT는 rate limit 수치를 공개하지 않고 실측상 429·타임아웃이 잦으므로
    지수 백오프로 재시도한다.  끝내 실패하면 예외를 올려 호출부가 해당 피드를
    관측 없음으로 처리하게 한다 — 0.0을 관측값으로 기록하지 않기 위해서다.
    """
    url = f"{ENDPOINT}?" + urllib.parse.urlencode({
        "query": query, "mode": "artlist", "format": "json",
        "maxrecords": str(limit), "timespan": "7d",
    })
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            titles = [
                normalize_title(article.get("title", ""))
                for article in payload.get("articles", [])
            ]
            return [title for title in titles if title][:limit]
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"GDELT fetch failed after {retries} attempts") from last


def _load_classifier():
    global _clf
    if _clf is None:
        from transformers import pipeline

        _clf = pipeline("text-classification", model=MODEL_ID,
                        top_k=None, device=-1, truncation=True)
    return _clf


def score_feed(feed: str, query: str) -> FeedSentiment:
    headlines = fetch_headlines(query)
    if not headlines:
        return FeedSentiment(feed=feed, n_headlines=0, score=0.0)
    clf = _load_classifier()
    results = clf(headlines)
    scored = []
    for title, dists in zip(headlines, results):
        probs = {d["label"]: d["score"] for d in dists}
        scored.append((title, probs.get("positive", 0.0) - probs.get("negative", 0.0)))
    scored.sort(key=lambda x: x[1])
    avg = sum(v for _, v in scored) / len(scored)
    return FeedSentiment(
        feed=feed, n_headlines=len(scored), score=avg,
        top_negative=[t for t, v in scored[:3] if v < -0.2],
        top_positive=[t for t, v in scored[-3:] if v > 0.2],
    )


def run_all_feeds() -> list[FeedSentiment]:
    """모든 피드를 스코어링한다.  한 피드의 실패가 전체를 막지 않는다.

    실패한 피드는 `n_headlines=0`으로 남는다.  호출부(`ml/runner.py`)는 전체
    헤드라인 수가 0이면 `sentiment_overall`을 None으로 기록한다 — 0.0으로 적으면
    "중립을 관측했다"는 거짓이 원장에 남기 때문이다 (DECISIONS 12-4a).
    """
    out = []
    for index, (feed, query) in enumerate(FEEDS.items()):
        if index:
            time.sleep(FEED_INTERVAL_SECONDS)
        try:
            out.append(score_feed(feed, query))
        except Exception:  # noqa: BLE001 — 피드 하나가 전체를 막지 않게
            out.append(FeedSentiment(feed=feed, n_headlines=0, score=0.0))
    return out
