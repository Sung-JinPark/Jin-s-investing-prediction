"""FinBERT 금융 감성 지수 — **수집 중단됨 (2026-08-31, DECISIONS 12-4)**.

Google News RSS 수집을 중단했다. 근거는 피드 응답 본문에 내장된 라이선스로,
"solely for the purpose of rendering Google News results within a personal feed
reader for personal, non-commercial use. Any other use of the feed is expressly
prohibited." 이며, `news.google.com/robots.txt`가 `/rss/`를 모든 UA에 대해
disallow 한다. 이 프로젝트는 헤드라인을 FinBERT 입력으로 쓰고 집계 지수를 공개
페이지에 게시하므로 "personal feed reader"에 해당하지 않는다.

모듈을 지우지 않고 남겨둔 이유는 **과거 기록을 계속 읽기 위해서**다.
`data/ml_history/*.jsonl`은 append-only이고 이미 수집된 감성 행이 들어 있으며,
`base_rates.py`·`db/queries.py`·리포트 렌더러가 그 행을 참조한다. 수집(네트워크
호출)만 끊고 자료구조와 읽기 경로는 그대로 둔다.

- 모델: ProsusAI/finbert (~110M) — 금융 텍스트 positive/negative/neutral 분류.
- 출력: 피드별·종합 감성 지수 [-1, +1] = (P(pos)−P(neg))의 헤드라인 평균.
- 한계: 헤드라인 감성은 동행·후행 지표에 가깝다 — base rate 문맥 신호로만 사용.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MODEL_ID = "ProsusAI/finbert"
_clf = None

# 수집 중단 전 사용하던 피드 키.  과거 ml_history 행이 이 키를 쓰므로 읽기·표시
# 경로가 계속 참조한다.  검색 쿼리(Google News 파라미터)는 함께 제거했다.
FEED_KEYS = ("ai-semis", "fed-macro", "market", "nvda", "memory")


@dataclass
class FeedSentiment:
    feed: str
    n_headlines: int
    score: float               # [-1, +1]
    top_negative: list[str] = field(default_factory=list)
    top_positive: list[str] = field(default_factory=list)





def run_all_feeds() -> list[FeedSentiment]:
    """수집 중단 — 항상 빈 목록.

    호출부(`ml/runner.py`)는 빈 목록을 받으면 `sentiment_overall`을 None으로
    기록한다. 0.0으로 기록하면 "중립 감성 관측"으로 오독되므로 반드시 None이다.
    """
    return []
