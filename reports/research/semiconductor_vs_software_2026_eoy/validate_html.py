"""Local offline HTML smoke/interaction/responsiveness QA using installed Edge."""
from __future__ import annotations
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")


def run():
    if not EDGE.is_file():
        raise RuntimeError("Existing Edge unavailable; no browser installation attempted")
    checks, errors, remote = [], [], []
    def check(name, ok, detail=None):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(EDGE), headless=True, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.set_default_timeout(5000)
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("request", lambda req: remote.append(req.url) if req.url.startswith(("http:", "https:")) else None)
        page.goto((ROOT / "report.html").as_uri(), wait_until="load")
        title = page.locator("h1").inner_text()
        check("visible_primary_conclusion", "미검증" in title or "우열" in title, title)
        check("desktop_document_no_horizontal_overflow", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))
        check("interactive_defaults_rendered", "1.67" in page.locator("#interactive-difference").inner_text())
        page.locator("#multiple-delta").evaluate("el => {el.value='3'; el.dispatchEvent(new Event('input',{bubbles:true}));}")
        changed = page.locator("#interactive-difference").inner_text()
        explanation = page.locator("#interactive-conclusion").inner_text()
        check("multiple_slider_reverses_leader", ("1.39" in changed or "1.40" in changed) and "소프트웨어" in explanation, {"spread": changed, "explanation": explanation})
        page.locator("#w-bull").fill("60")
        error = page.locator("#weights-error")
        check("invalid_weights_rejected_visibly", error.is_visible() and "100" in error.inner_text())
        page.locator("#reset-assumptions").click()
        check("reset_restores_default", "1.67" in page.locator("#interactive-difference").inner_text() and not error.is_visible())
        for field, value in (("#w-bull", "0"), ("#w-base", "100"), ("#w-bear", "0")):
            page.locator(field).fill(value)
        page.locator("#w-bull").fill("")
        check("blank_weight_not_silently_zero", error.is_visible() and "빈 값" in error.inner_text())
        page.locator("#reset-assumptions").click()
        body = page.locator("body").inner_text()
        check("actual_history_and_overlap_disclosed", "4,723" in body and "3,280" in body and "58" in body)
        check("classifier_baseline_metrics_present", "0.2528" in body or "0.25279" in body)
        check("no_pending_visible", page.locator(".pending:visible").count() == 0)
        check("no_javascript_errors", not errors, errors)
        check("self_contained_no_network_requests", not remote, remote)
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(ROOT / "report_desktop.png"), full_page=True)
        page.screenshot(path=str(ROOT / "report_overview.png"), full_page=False)
        for width in (390, 768):
            page.set_viewport_size({"width": width, "height": 1000})
            check(f"responsive_{width}_no_document_overflow", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))
            check(f"responsive_{width}_slider_available", page.locator("#multiple-delta").is_visible())
            if width == 390:
                page.screenshot(path=str(ROOT / "report_mobile.png"), full_page=True)
                page.evaluate("window.scrollTo(0,0)")
                page.screenshot(path=str(ROOT / "report_mobile_overview.png"), full_page=False)
        browser.close()
    result = {"status": "pass" if all(c["pass"] for c in checks) else "fail", "check_count": len(checks),
              "checks": checks, "errors": [c for c in checks if not c["pass"]], "browser": "installed Edge / headless Playwright",
              "screenshots": ["report_desktop.png", "report_overview.png", "report_mobile.png"]}
    (ROOT / "html_qa.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": len(checks), "errors": result["errors"]}, ensure_ascii=False))
    if result["errors"]:
        raise AssertionError("HTML QA failed; see html_qa.json")


if __name__ == "__main__":
    run()
