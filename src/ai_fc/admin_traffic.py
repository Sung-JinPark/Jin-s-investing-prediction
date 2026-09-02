"""관리자 전용 저장소 방문 통계 — GitHub Traffic API 스냅샷 축적 + 로컬 대시보드.

GitHub Pages는 정적 호스팅이라 서버 로그가 없고, GitHub은 Pages 사이트
(*.github.io) 방문 분석을 제공하지 않는다 — 이 API가 세는 것은 github.com의
저장소 페이지 방문·클론·유입이다. 사이트 자체 방문 측정은 클라이언트 분석
서비스(예: GoatCounter) 계정이 따로 필요하다. 저장소 push 권한자만 조회할 수
있는 GitHub Traffic API(views/clones/referrers/paths)를 ``gh api``로 읽어 로컬
append-only 이력에 쌓고, 자기완결 HTML 대시보드를 렌더한다.

프라이버시·비밀 경계:
- 토큰 평문을 다루지 않는다 — 인증은 전적으로 ``gh`` CLI 세션에 위임한다.
- 산출물(이력 JSONL·대시보드 HTML)은 ``outputs/admin/``에만 쓴다. 이 경로는
  .gitignore 대상이라 공개 저장소에 커밋되지 않는다 — "나만 보는" 경계가
  로컬 파일 + API 권한(push 권한자)으로 유지된다.
- GitHub Traffic은 집계 통계다: 유입 referrer·경로·일별 조회/고유 방문자만
  제공하며 개인 식별 정보(IP·개별 방문자)는 원천적으로 없다.

데이터 한계(대시보드에도 공시):
- API 윈도는 롤링 14일 — 스냅샷을 주기적으로 떠서 장기 이력을 만든다.
- 같은 날짜의 수치는 스냅샷마다 커질 수 있어 날짜별 최댓값으로 병합한다.
- uniques는 날짜 간 합산 불가(같은 방문자가 여러 날 겹침).
- referrers/paths는 상위 10개·최근 14일 집계라 순간 스냅샷 간 비교만 유효하다.
"""
from __future__ import annotations

import html
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = "Sung-JinPark/Jin-s-investing-prediction"
HISTORY_RELATIVE = Path("outputs/admin/traffic_history.jsonl")
DASHBOARD_RELATIVE = Path("outputs/admin/traffic_dashboard.html")

_ENDPOINTS = {
    "views": f"repos/{REPO}/traffic/views",
    "clones": f"repos/{REPO}/traffic/clones",
    "referrers": f"repos/{REPO}/traffic/popular/referrers",
    "paths": f"repos/{REPO}/traffic/popular/paths",
}


class AdminTrafficError(RuntimeError):
    pass


def _fetch_gh(endpoint: str) -> Any:
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if result.returncode != 0:
        raise AdminTrafficError(
            f"gh api {endpoint} failed: {result.stderr.strip()[:200]}"
        )
    return json.loads(result.stdout)


def take_snapshot(
    root: Path, *,
    fetcher: Callable[[str], Any] = _fetch_gh,
    now: datetime | None = None,
) -> dict[str, Any]:
    """4개 엔드포인트를 읽어 이력에 append하고 스냅샷을 돌려준다."""
    fetched_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    snapshot: dict[str, Any] = {"fetched_at": fetched_at}
    for key, endpoint in _ENDPOINTS.items():
        snapshot[key] = fetcher(endpoint)
    history_path = root / HISTORY_RELATIVE
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with open(history_path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    return snapshot


def read_history(root: Path) -> list[dict[str, Any]]:
    path = root / HISTORY_RELATIVE
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def merge_daily(history: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """스냅샷들의 일별 수치를 날짜별 최댓값으로 병합한다 (당일 수치는 자라다 멈춘다)."""
    by_date: dict[str, dict[str, int]] = {}
    for snapshot in history:
        for row in (snapshot.get(key) or {}).get(key, []):
            day = str(row["timestamp"])[:10]
            slot = by_date.setdefault(day, {"count": 0, "uniques": 0})
            slot["count"] = max(slot["count"], int(row["count"]))
            slot["uniques"] = max(slot["uniques"], int(row["uniques"]))
    return [
        {"date": day, **values}
        for day, values in sorted(by_date.items())
    ]


def _bar_chart(rows: list[dict[str, Any]], title: str) -> str:
    if not rows:
        return f"<p class='empty'>{html.escape(title)}: 아직 데이터가 없습니다.</p>"
    width, height, pad = 860, 220, 34
    n = len(rows)
    peak = max(max(r["count"] for r in rows), 1)
    band = (width - pad * 2) / max(n, 1)
    bars, labels = [], []
    for i, row in enumerate(rows):
        x = pad + i * band
        count_h = (height - pad * 2) * row["count"] / peak
        uniq_h = (height - pad * 2) * row["uniques"] / peak
        bars.append(
            f"<rect x='{x + band * 0.12:.1f}' y='{height - pad - count_h:.1f}' "
            f"width='{band * 0.42:.1f}' height='{count_h:.1f}' fill='#28756a'>"
            f"<title>{row['date']} 조회 {row['count']}</title></rect>"
            f"<rect x='{x + band * 0.54:.1f}' y='{height - pad - uniq_h:.1f}' "
            f"width='{band * 0.34:.1f}' height='{uniq_h:.1f}' fill='#b58b2a'>"
            f"<title>{row['date']} 고유 {row['uniques']}</title></rect>"
        )
        if n <= 21 or i % max(1, n // 14) == 0:
            labels.append(
                f"<text x='{x + band * 0.5:.1f}' y='{height - pad + 14}' "
                f"font-size='9' text-anchor='middle' fill='#666'>"
                f"{row['date'][5:]}</text>"
            )
    return (
        f"<h2>{html.escape(title)}</h2>"
        f"<svg viewBox='0 0 {width} {height}' role='img'>"
        f"<text x='{pad}' y='16' font-size='11' fill='#28756a'>■ 조회수</text>"
        f"<text x='{pad + 70}' y='16' font-size='11' fill='#b58b2a'>■ 고유 방문자</text>"
        f"<text x='{width - pad}' y='16' font-size='11' text-anchor='end' fill='#666'>최대 {peak}</text>"
        f"{''.join(bars)}{''.join(labels)}</svg>"
    )


def _table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], title: str) -> str:
    if not rows:
        return f"<p class='empty'>{html.escape(title)}: 아직 데이터가 없습니다.</p>"
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = "".join(
        "<tr>" + "".join(
            f"<td>{html.escape(str(row.get(field, '')))}</td>" for field, _ in columns
        ) + "</tr>"
        for row in rows
    )
    return (
        f"<h2>{html.escape(title)}</h2>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def render_dashboard(root: Path) -> Path:
    history = read_history(root)
    if not history:
        raise AdminTrafficError("이력이 비어 있습니다 — 먼저 snapshot을 실행하세요")
    latest = history[-1]
    views = merge_daily(history, "views")
    clones = merge_daily(history, "clones")
    referrers = [
        {"referrer": r["referrer"], "count": r["count"], "uniques": r["uniques"]}
        for r in (latest.get("referrers") or [])
    ]
    paths = [
        {"path": r["path"], "title": r.get("title", ""), "count": r["count"], "uniques": r["uniques"]}
        for r in (latest.get("paths") or [])
    ]
    total_views = sum(r["count"] for r in views)
    body = (
        "<h1>저장소 방문 통계 (관리자 전용)</h1>"
        f"<p class='meta'>저장소 {html.escape(REPO)} · 스냅샷 {len(history)}회 · "
        f"최근 수집 {html.escape(str(latest['fetched_at']))} · "
        f"이력 합계 조회 {total_views}</p>"
        + _bar_chart(views, "일별 페이지 조회 (이력 병합)")
        + _bar_chart(clones, "일별 저장소 클론")
        + _table(referrers, [("referrer", "유입 경로(사이트)"), ("count", "조회"), ("uniques", "고유")],
                 "유입 referrer 상위 (최근 14일)")
        + _table(paths, [("path", "경로"), ("title", "제목"), ("count", "조회"), ("uniques", "고유")],
                 "많이 본 경로 상위 (최근 14일)")
        + "<h2>이 수치의 한계</h2><ul>"
        "<li><strong>측정 대상은 github.com 저장소 페이지</strong>(코드·Actions 등) 방문입니다. "
        "GitHub Pages 사이트(sung-jinpark.github.io) 방문은 포함되지 않습니다 — GitHub이 "
        "Pages 분석을 제공하지 않아, 사이트 방문 측정은 별도 클라이언트 분석 도구가 필요합니다.</li>"
        "<li>GitHub Traffic은 집계 통계입니다 — 유입 사이트·경로·일별 조회/고유 방문자만 제공하며, "
        "개인 식별(IP·개별 방문자 추적)은 제공하지 않고 이 대시보드도 수집하지 않습니다.</li>"
        "<li>API 원천은 롤링 14일 윈도입니다. 장기 추세는 스냅샷을 주기적으로 떠서 만든 병합 이력입니다.</li>"
        "<li>고유 방문자는 날짜 간 합산할 수 없습니다(같은 방문자가 여러 날 겹침).</li>"
        "<li>referrer/경로 표는 최신 스냅샷의 상위 10개입니다.</li>"
        "<li>이 파일과 이력은 outputs/admin/ (gitignore) 로컬 전용입니다 — 공개 저장소에 올라가지 않습니다.</li>"
        "</ul>"
    )
    page = (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>저장소 방문 통계 (관리자)</title><style>"
        "body{font-family:system-ui,'Malgun Gothic',sans-serif;max-width:920px;margin:24px auto;"
        "padding:0 16px;color:#11110f;background:#faf9f5}"
        "h1{font-size:22px}h2{font-size:15px;margin:26px 0 8px}"
        ".meta{color:#666;font-size:12px}.empty{color:#888;font-size:13px}"
        "svg{width:100%;height:auto;background:#fff;border:1px solid #e4e1d8;border-radius:8px}"
        "table{border-collapse:collapse;width:100%;font-size:13px;background:#fff}"
        "th,td{border:1px solid #e4e1d8;padding:6px 9px;text-align:left}"
        "th{background:#f1efe8}ul{font-size:12.5px;color:#555;line-height:1.7}"
        "</style></head><body>" + body + "</body></html>"
    )
    out = root / DASHBOARD_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8", newline="\n")
    return out
