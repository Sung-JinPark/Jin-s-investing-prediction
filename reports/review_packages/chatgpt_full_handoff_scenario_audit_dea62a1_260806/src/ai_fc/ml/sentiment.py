"""FinBERT 금융 감성 지수 — 무료 RSS 헤드라인 파싱 → 추론 전용 스코어링.

- 모델: ProsusAI/finbert (~110M) — 금융 텍스트 positive/negative/neutral 분류.
- 피드: Google News RSS(무료·키 불필요) 검색 쿼리 3종 매핑
  (AI/반도체, 연준/매크로, 시장 전반). 실패 시 해당 피드만 생략(fail-soft).
- 출력: 피드별·종합 감성 지수 [-1, +1] = (P(pos)−P(neg))의 헤드라인 평균.
- 한계: 헤드라인 감성은 동행·후행 지표에 가깝다 — base rate 문맥 신호로만 사용.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MODEL_ID = "ProsusAI/finbert"
_clf = None

FEEDS = {
    "ai-semis": "NVIDIA OR TSMC OR semiconductor AI stocks",
    "fed-macro": "Federal Reserve rate inflation",
    "market": "Nasdaq stock market",
    # 등록 질문 도메인 정렬 (NVDA 실적 2문, MU 마진 질문)
    "nvda": "NVIDIA stock earnings",
    "memory": "Micron OR SK Hynix memory chip prices",
}


@dataclass
class FeedSentiment:
    feed: str
    n_headlines: int
    score: float               # [-1, +1]
    top_negative: list[str] = field(default_factory=list)
    top_positive: list[str] = field(default_factory=list)


def fetch_headlines(query: str, limit: int = 25) -> list[str]:
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(query) + "&hl=en-US&gl=US&ceid=US:en")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_text = resp.read().decode("utf-8", errors="replace")
    root = ET.fromstring(xml_text)
    titles = [item.findtext("title", "") for item in root.iter("item")]
    return [t for t in titles if t][:limit]


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
    out = []
    for feed, query in FEEDS.items():
        try:
            out.append(score_feed(feed, query))
        except Exception:  # noqa: BLE001 — 피드 하나가 전체를 막지 않게
            out.append(FeedSentiment(feed=feed, n_headlines=0, score=0.0))
    return out
