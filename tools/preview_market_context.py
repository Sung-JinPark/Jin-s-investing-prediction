"""Preview GRAPH02 with synthetic inputs and actual model paths; no durable writes."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from ai_fc import dashboard
from ai_fc.market_context.contracts import AXES, AXIS_LABELS, MODEL_ID, canonical_hash
from ai_fc.market_context.model import project_paths, summarize_paths


def fixture_projection():
    import exchange_calendars as xcals

    anchor_date, as_of = "2026-10-09", "2026-10-09T22:00:00+00:00"
    exchange = xcals.get_calendar("XNAS", start="2025-01-01", end="2028-01-31")
    sessions = [label.date().isoformat() for label in exchange.sessions]
    history_dates = [day for day in sessions if day <= anchor_date][-800:]
    dates = [day for day in sessions if day > anchor_date][:252]
    rng = np.random.default_rng(615)
    closes = (23000 * np.exp(np.cumsum(rng.normal(.0002, .012, len(history_dates))))).tolist()
    result = project_paths(closes, state=[0.0] * 21, coefficients=None, future_dates=dates)
    summarized = summarize_paths(result["candidate_paths"], anchor=closes[-1], future_dates=dates,
                                 baseline_paths=result["baseline_paths"])
    record_keys = ("date", "index_quantiles", "daily_return_quantiles", "drawdown_quantiles",
                   "probability_up_from_previous", "probability_down_from_previous", "probability_up_from_origin")
    projection = {
        "schema_version": 1, "model_id": MODEL_ID, "model_version": 1,
        "status": "research_preview", "as_of": as_of, "anchor_date": anchor_date,
        "anchor": closes[-1], "forecast_end_date": dates[-1], "forecast_id": "fixture-market-context-615",
        "input_hash": canonical_hash({"fixture": True, "closes": closes}),
        "contract_hash": canonical_hash({"fixture": True, "model": MODEL_ID}),
        "coefficient_hash": "not_fitted", "probability_unit": "fraction",
        "predictive_validation": "not_established", "numerical_context_applied": False, "score": None,
        "gate": {"pass": True, "fixture_only": True, "reasons": []},
        "records": [{key: row[key] for key in record_keys} for row in summarized["records"]],
        "representative": {**summarized["representative"], "path_id": f"path-{summarized['representative'].get('path_id', 'none')}"},
        "baseline_median": [closes[-1], *np.median(result["baseline_paths"], axis=0).tolist()],
        "history": {"dates": history_dates[-42:], "index": closes[-42:]},
        "attribution": result["attribution"],
        "state_summary": {"axes": [{"axis": axis, "label": AXIS_LABELS[axis], "score": None,
                                     "applied": False, "reason": "가상 시황 · 실제 수치 계수 검증 대기"} for axis in AXES],
                          "events": [{"title": "Anthropic 실적 · 예시", "axis": "ai_demand", "used_numerically": False,
                                      "reason": "공개 원천과 NASDAQ 연결 계수의 검증 전 · 참고 전용"},
                                     {"title": "중국 메모리 경쟁 · 예시", "axis": "semiconductor", "used_numerically": False,
                                      "reason": "뉴스 방향을 수익률로 임의 환산하지 않습니다."}]},
        "footnote": "검토용 가상 입력 · 실제 시장 전망이 아님 · 연구 프리뷰 · 매매 신호가 아닙니다.",
    }
    # UI precision is explicit; no model path or ledger is changed.
    def rounded(value):
        if isinstance(value, float):
            return round(value, 8)
        if isinstance(value, list):
            return [rounded(item) for item in value]
        if isinstance(value, dict):
            return {key: rounded(item) for key, item in value.items()}
        return value
    return rounded(projection), summarized["diagnostics"]


def build_preview(output: Path):
    projection, diagnostics = fixture_projection()
    sample = [0, *range(5, 253, 5), 252]
    all_dates = [projection["anchor_date"], *[row["date"] for row in projection["records"]]]
    medians = projection["baseline_median"]
    scenario = {
        "asof": projection["anchor_date"], "anchor": projection["anchor"], "ath": projection["anchor"] * 1.1,
        "corr10": projection["anchor"] * .99, "weeks": [all_dates[index][5:] for index in sample],
        "week_dates": [all_dates[index] for index in sample], "risk": ["저"] * len(sample),
        "paths": {key: {"label": label, "prob": probability, "values": [medians[index] * scale for index in sample]}
                  for key, label, probability, scale in (("S1", "가상 상승", 50, 1), ("S2", "가상 균형", 25, .97), ("S3", "가상 조정", 25, .9))},
        "note": "기존 S1 토글 검토용 가상 입력", "model": {"seed": 42, "n_paths": 20000},
    }
    data = {"meta": {"generated": projection["as_of"], "phase": "FIXTURE", "n_questions": 0},
            "questions": [], "forecast_history": {}, "resolutions": [], "clusters": [],
            "scenario": scenario, "scenario_v5_2": {"status": "hold", "runtime_gate": {"reasons": ["fixture"]}},
            "market_context": projection}
    base, sidecar = dashboard.split_market_context_data(data)
    output.mkdir(parents=True, exist_ok=True)
    html = dashboard.render_html(base, mode="embed")
    html = html.replace("</head>", '<script>if(!location.hash)location.hash="#future/original";</script></head>')
    banner = '<style>.fixture-banner{padding:9px 14px;background:#8b3723;color:white;text-align:center;font:700 13px sans-serif;position:relative;z-index:9000}</style><div class="fixture-banner" role="alert">검토용 가상 입력 · 실제 시장 전망이 아님</div>'
    html = html.replace("<body>", "<body>" + banner)
    target = output / "index.html"
    target.write_text(html, encoding="utf-8")
    (output / dashboard.MARKET_CONTEXT_FILENAME).write_text(json.dumps(sidecar, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    inline = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (output / "standalone.html").write_text(html.replace("</head>", f"<script>window.__DATA__={inline};</script></head>"), encoding="utf-8")
    (output / "fixture_manifest.json").write_text(json.dumps({"fixture_only": True, **diagnostics,
        "representative": {key: value for key, value in projection["representative"].items() if key != "values"},
        "sidecar_bytes": (output / dashboard.MARKET_CONTEXT_FILENAME).stat().st_size}, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def capture_preview(output: Path):
    from playwright.sync_api import sync_playwright

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(output.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    results = []
    try:
        with sync_playwright() as browser_tools:
            chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
            browser = browser_tools.chromium.launch(headless=True, channel="chrome" if chrome.is_file() else None)
            for width, height in ((1280, 1000), (390, 844)):
                context = browser.new_context(viewport={"width": width, "height": height}, has_touch=width == 390,
                                              reduced_motion="reduce")
                page = context.new_page()
                errors, sidecars = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: sidecars.append(request.url) if request.url.endswith("market_context.json") else None)
                page.goto(f"http://127.0.0.1:{server.server_port}/#future/original", wait_until="networkidle")
                svg = page.locator(".market-context-chart svg")
                svg.wait_for(state="visible")
                assert page.locator('[data-mc-path="actual-member"]').evaluate("node=>node.points.length") == 253
                assert page.locator('[data-mc-path="median"]').evaluate("node=>node.points.length") == 253
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), "body overflow"
                svg.focus()
                page.keyboard.press("Home")
                before = page.locator("[data-mc-readout]").inner_text()
                page.keyboard.press("End")
                assert before != page.locator("[data-mc-readout]").inner_text()
                box = svg.bounding_box()
                if width == 390:
                    page.touchscreen.tap(box["x"] + box["width"] * .6, box["y"] + box["height"] * .4)
                else:
                    page.mouse.move(box["x"] + box["width"] * .6, box["y"] + box["height"] * .4)
                assert "하락 가능성" in page.locator("[data-mc-readout]").inner_text()
                page.locator('[data-mc-days="21"]').click()
                assert page.locator('[data-mc-path="actual-member"]').evaluate("node=>node.points.length") == 22
                page.locator('[data-mc-days="252"]').click()
                assert page.locator('[data-mc-view="legacy"]').evaluate("node=>getComputedStyle(node).color") == "rgb(17, 17, 15)"
                page.evaluate("document.activeElement?.blur();window.scrollTo(0,0)")
                page.screenshot(path=str(output / f"market_context__{width}.png"), full_page=True)
                page.locator('[data-mc-view="legacy"]').click()
                page.locator("#original-flow-chart svg").wait_for(state="visible")
                page.evaluate("document.activeElement?.blur();window.scrollTo(0,0)")
                page.screenshot(path=str(output / f"legacy_s1__{width}.png"), full_page=True)
                page.locator('[data-mc-view="context"]').click()
                page.locator('[data-mc-path="actual-member"]').wait_for(state="visible")
                assert len(sidecars) == 1 and not errors, (sidecars, errors)
                results.append({"width": width, "page_errors": errors, "body_overflow": False,
                                "member_points": 253, "short_member_points": 22, "sidecar_requests": len(sidecars),
                                "keyboard_and_pointer_readout": True, "legacy_toggle": True})
                context.close()
            browser.close()
    finally:
        server.shutdown()
        worker.join(10)
        server.server_close()
    (output / "browser_checks.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PROJECT / "outputs/market_context_preview")
    parser.add_argument("--capture", action="store_true")
    options = parser.parse_args()
    print(build_preview(options.out).resolve())
    if options.capture:
        capture_preview(options.out)
