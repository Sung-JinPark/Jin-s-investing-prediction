"""Build a clearly marked synthetic daily6m preview, without writing research ledgers."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from ai_fc import dashboard
from ai_fc.timeseries_daily6m.contracts import ENDOGENOUS_NAMES, EXOGENOUS_NAMES, canonical_hash
from ai_fc.timeseries_daily6m.model import future_session_dates, generate_forecast


def build_preview(output: Path) -> Path:
    import exchange_calendars as xcals

    anchor_date, as_of, anchor = "2026-10-09", "2026-10-09T22:00:00+00:00", 23000.0
    calendar = xcals.get_calendar("XNAS", start="2020-01-01", end=anchor_date)
    dates = [label.date().isoformat() for label in calendar.sessions[-800:]]
    rng = np.random.default_rng(603)
    endogenous = rng.normal(0, [0.009, 0.035, 2.0, 1.5, 0.004], size=(800, 5))
    endogenous[:, 0] += 0.00025
    exogenous = rng.normal(0, 0.25, size=(800, 3))
    bundle = SimpleNamespace(dates=tuple(dates), endogenous=endogenous, exogenous=exogenous,
                             endogenous_names=ENDOGENOUS_NAMES, exogenous_names=EXOGENOUS_NAMES,
                             issues=())
    history = {"dates": dates[-63:], "index": (
        anchor * np.exp(np.cumsum(endogenous[-63:, 0]) - np.sum(endogenous[-63:, 0]))
    ).tolist()}
    future_dates, calendar_end, calendar_hash = future_session_dates(anchor_date)
    generated = generate_forecast(bundle, anchor=anchor, as_of=as_of, future_dates=future_dates,
                                  history=history, lineage={"fixture": True, "available_at_max": as_of})
    body = {key: value for key, value in generated.items() if key != "content_hash"}
    body.update({
        "run_id": "fixture-daily6m-synthetic-603", "status": "research_preview", "numbers_visible": True,
        "anchor_date": anchor_date, "anchor": {"date": anchor_date, "value": anchor},
        "dates": future_dates, "calendar_end_date": calendar_end, "calendar_hash": calendar_hash,
        "forecast_end_date": future_dates[-1], "gate": {"pass": True, "fixture_only": True, "reasons": []},
        "evidence": {"fixture": True, "predictive_validation": "not_established"},
        "realized": {"dates": [], "index": []},
        "footnote": "검토용 가상 입력 · 실제 시장 예측이 아닙니다 · 연구 프리뷰 · 매매 신호가 아닙니다",
    })
    projection = {**body, "content_hash": canonical_hash(body)}
    data = {
        "meta": {"generated": "2026-10-12T09:00:00+09:00", "phase": "FIXTURE", "n_questions": 0},
        "questions": [], "forecast_history": {}, "resolutions": [], "clusters": [], "scenario": {},
        "timeseries": {"status": "hold", "numbers_visible": False, "gate": {"reasons": ["fixture"]}},
        "timeseries_daily": projection,
    }
    base, sidecar = dashboard.split_timeseries_daily_data(data)
    output.mkdir(parents=True, exist_ok=True)
    html = dashboard.render_html(base, mode="embed")
    html = html.replace("</head>", '<script>if(!location.hash)location.hash="#timeseries/daily";</script></head>')
    banner = '<div class="fixture-banner" role="alert">검토용 가상 입력 · 실제 시장 전망이 아닙니다</div>'
    styles = '<style>.fixture-banner{position:fixed;top:0;left:0;width:100%;z-index:10000;background:#8a341e;color:white;text-align:center;padding:7px 12px;font:600 13px sans-serif;box-sizing:border-box}body{padding-top:34px}</style>'
    html = html.replace("<body>", "<body>" + styles + banner)
    target = output / "index.html"
    target.write_text(html, encoding="utf-8")
    # A fixture-only portable copy also opens directly without a local HTTP
    # server. Production delivery keeps the separately pinned sidecar.
    inline_data = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"), allow_nan=False)
    standalone = html.replace("</head>", f"<script>window.__DATA__ = {inline_data};</script></head>")
    (output / "standalone.html").write_text(standalone, encoding="utf-8")
    (output / dashboard.TIMESERIES_DAILY_FILENAME).write_text(
        json.dumps(sidecar, ensure_ascii=False, default=str, separators=(",", ":")), encoding="utf-8",
    )
    (output / "fixture_manifest.json").write_text(json.dumps({
        "fixture_only": True, "synthetic_seed": 603, "path_count": generated["path_count"],
        "horizon_sessions": len(future_dates), "path_hash": generated["path_hash"],
        "raw_kernel_identity": generated["comparison"]["v8_raw_identity"],
        "site_bytes": target.stat().st_size,
        "sidecar_bytes": (output / dashboard.TIMESERIES_DAILY_FILENAME).stat().st_size,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def capture_preview(output: Path) -> None:
    """Exercise the delivered fixture at desktop/mobile without external data."""
    from playwright.sync_api import sync_playwright

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = partial(QuietHandler, directory=str(output.resolve()))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    results = []
    try:
        with sync_playwright() as browser_tools:
            # Use an already installed browser; never download dependencies.
            chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
            browser = browser_tools.chromium.launch(headless=True, channel="chrome" if chrome.is_file() else None)
            portable = browser.new_page()
            portable.goto((output / "standalone.html").resolve().as_uri())
            portable.locator(".ts-daily-chart svg").wait_for(state="visible")
            assert portable.locator("[data-daily-months='6']").get_attribute("aria-pressed") == "true"
            portable.close()
            for width, height in ((1280, 900), (390, 844)):
                context = browser.new_context(viewport={"width": width, "height": height},
                                              reduced_motion="reduce", has_touch=width == 390)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/#timeseries/daily", wait_until="networkidle")
                svg = page.locator(".ts-daily-chart svg")
                svg.wait_for(state="visible")
                assert page.locator(".ts-daily-prob-line").count() == 1
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "body overflow"
                page.evaluate("document.activeElement?.blur(); window.scrollTo(0,0)")
                page.screenshot(path=str(output / f"daily__{width}.png"), full_page=True)
                endpoint = page.locator("[data-daily-endpoint]")
                six_month_endpoint = endpoint.inner_text()
                page.get_by_role("button", name="1개월", exact=True).click()
                one_month_endpoint = endpoint.inner_text()
                assert one_month_endpoint != six_month_endpoint
                page.get_by_role("button", name="3개월", exact=True).click()
                assert endpoint.inner_text() not in (one_month_endpoint, six_month_endpoint)
                page.get_by_role("button", name="6개월", exact=True).click()
                assert endpoint.inner_text() == six_month_endpoint
                page.get_by_role("button", name="가능한 일별 움직임 예시 보기", exact=True).click()
                assert page.locator("[data-daily-sample]").count() == 5
                page.evaluate("document.activeElement?.blur(); window.scrollTo(0,0)")
                page.screenshot(path=str(output / f"daily_samples__{width}.png"), full_page=True)
                svg.focus()
                page.keyboard.press("ArrowLeft")
                before = page.locator(".ts-daily-chart .ts-readout").inner_text()
                page.keyboard.press("ArrowRight")
                after = page.locator(".ts-daily-chart .ts-readout").inner_text()
                assert before != after, "keyboard must change the shared date readout"
                box = svg.bounding_box()
                if width == 390:
                    page.touchscreen.tap(box["x"] + box["width"] * .7, box["y"] + box["height"] * .4)
                else:
                    page.mouse.move(box["x"] + box["width"] * .7, box["y"] + box["height"] * .4)
                assert page.locator(".ts-daily-chart .ts-readout").inner_text()
                assert not errors, errors
                results.append({"width": width, "page_errors": errors, "six_month_endpoint": six_month_endpoint,
                                "one_month_endpoint": one_month_endpoint, "sample_count": 5,
                                "keyboard_changed_readout": True, "body_overflow": False})
                context.close()
            browser.close()
    finally:
        server.shutdown()
        worker.join(10)
        server.server_close()
    (output / "browser_checks.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PROJECT / "outputs/timeseries_daily6m_preview")
    parser.add_argument("--capture", action="store_true", help="Capture and verify desktop/mobile with the installed browser")
    options = parser.parse_args()
    print(build_preview(options.out).resolve())
    if options.capture:
        capture_preview(options.out)
