"""Focused desktop/mobile render evidence for the daily scenario display."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


def capture(base_url: str, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            if "Executable doesn't exist" not in str(exc):
                raise
            browser = playwright.chromium.launch(channel="msedge", headless=True)
        for width, height in ((1280, 900), (390, 844)):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1, reduced_motion="reduce",
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base_url.rstrip("/") + "/#future", wait_until="networkidle", timeout=60_000)
            page.locator('[data-future-graph="original"]').click(timeout=30_000)
            title = page.locator("#original-flow-title")
            title.wait_for(state="visible")
            svg = page.locator('svg[data-daily-flow="true"]')
            svg.wait_for(state="visible")
            metrics = page.evaluate("""() => {
              const flow=DATA.daily_flow, sc=DATA.scenario;
              const svg=document.querySelector('svg[data-daily-flow="true"]');
              const path=svg.querySelector('[data-path-role="daily-representative"]');
              const end=flow.default_end_index;
              const key=svg.dataset.scenarioKey||'S1';
              const row=flow.scenarios[key];
              return {
                title:document.getElementById('original-flow-title').textContent,
                source_snapshot_id:flow.source_snapshot_id,
                asof:flow.asof, anchor:flow.anchor, calendar_end:flow.calendar_end,
                expected_nodes:end+1,
                rendered_nodes:(path.getAttribute('d').match(/[ML]/g)||[]).length,
                visible_end_date:svg.dataset.visibleEndDate,
                visible_end_value:Number(svg.dataset.visibleEndValue),
                expected_end_date:flow.dates[end], expected_end_value:row.values[end],
                member_path_index:row.member_path_index,
                shadow_passed:flow.shadow.passed,
                same_anchor:flow.anchor===sc.anchor,
                probability:row.probability,
                horizontal_overflow_px:Math.max(0,document.documentElement.scrollWidth-innerWidth),
                selected_horizon:document.querySelector('[data-original-horizon][aria-pressed="true"]')?.dataset.originalHorizon,
              };
            }""")
            assert "일간 시나리오 흐름" in metrics["title"], metrics
            assert metrics["shadow_passed"] and metrics["same_anchor"], metrics
            assert metrics["rendered_nodes"] == metrics["expected_nodes"], metrics
            assert metrics["visible_end_date"] == metrics["expected_end_date"], metrics
            assert metrics["visible_end_value"] == metrics["expected_end_value"], metrics
            assert metrics["horizontal_overflow_px"] <= 1, metrics
            svg.focus()
            before = svg.get_attribute("data-cursor-date")
            page.keyboard.press("ArrowRight")
            after = svg.get_attribute("data-cursor-date")
            metrics["keyboard_cursor_before"] = before
            metrics["keyboard_cursor_after"] = after
            assert before and after and before != after, metrics
            page.evaluate("document.activeElement.blur()")
            target = output / f"scenario_daily_flow_{width}.png"
            title.locator("xpath=ancestor::section[1]").screenshot(path=str(target), animations="disabled")
            metrics.update({
                "viewport": {"width": width, "height": height},
                "screenshot": target.name,
                "screenshot_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "page_errors": errors,
            })
            if width == 390:
                page.get_by_role("button", name=metrics["title"] + " 확대해서 보기", exact=True).click()
                dialog = page.locator(".chart-zoom-dialog")
                dialog.wait_for(state="visible")
                detail = dialog.locator('svg[data-daily-flow="true"]')
                metrics["mobile_detail_svg_width"] = detail.bounding_box()["width"]
                metrics["mobile_detail_nodes"] = detail.locator('[data-path-role="daily-representative"]').evaluate(
                    "path => (path.getAttribute('d').match(/[ML]/g)||[]).length"
                )
                assert metrics["mobile_detail_svg_width"] >= 1100, metrics
                assert metrics["mobile_detail_nodes"] == metrics["expected_nodes"], metrics
                detail_target = output / "scenario_daily_flow_390_detail.png"
                dialog.screenshot(path=str(detail_target), animations="disabled")
                metrics["mobile_detail_screenshot"] = detail_target.name
                metrics["mobile_detail_screenshot_sha256"] = hashlib.sha256(detail_target.read_bytes()).hexdigest()
                dialog.get_by_role("button", name="닫기", exact=True).click()
                assert page.locator(".chart-zoom-layer").is_hidden()
            assert not errors, errors
            rows.append(metrics)
            context.close()
        result = {"url": base_url, "browser_version": browser.version, "renders": rows}
        browser.close()
    (output / "render_evidence.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--site", type=Path)
    source.add_argument("--url")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    server = None
    try:
        if args.site:
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), partial(QuietHandler, directory=str(args.site.resolve())),
            )
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{server.server_address[1]}"
        else:
            url = args.url
        print(json.dumps(capture(url, args.output), ensure_ascii=False))
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
