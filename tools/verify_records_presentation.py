"""Exercise a freshly built records site without opening the durable index.

Usage: python tools/verify_records_presentation.py TEMP_SITE TEMP_REPORT
Requires the project's existing Playwright package and installed Chrome.
External requests are blocked, and share controls are previewed without sending.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


INTERNAL = re.compile(r"\b(?:r\d+|v\d+(?:\.\d+)*|P[0-3]|[A-Za-z]+_[A-Za-z_\d]+)\b", re.I)
SNAPSHOT_JS = """() => {
 const root=document.querySelector('#app');
 const labels=[...root.querySelectorAll('[aria-label],[title],[placeholder]')].flatMap(node=>
   ['aria-label','title','placeholder'].map(key=>node.getAttribute(key)||''));
 return {text:root.textContent+'\\n'+labels.join('\\n'),
   h1:root.querySelector('h1')?.textContent,
   width:document.documentElement.scrollWidth,viewport:innerWidth};
}"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


def verify(site: Path, report_dir: Path) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads((site / "data.json").read_text(encoding="utf-8"))
    handler = functools.partial(QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"
    result: dict = {"site": str(site), "viewports": [], "errors": [], "leaks": [], "overflow": []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            for width in (1280, 390):
                context = browser.new_context(viewport={"width": width, "height": 920}, accept_downloads=True, reduced_motion="reduce")
                legacy = {"hash": "#records/question/" + data["questions"][0]["id"], "title": "r4 source_uri legacy_internal_name", "type": "question"}
                context.add_init_script("localStorage.setItem('jin-investing-ui-v1'," + json.dumps(json.dumps({"version": 4, "pins": [legacy], "recent": [legacy]})) + ")")
                context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
                page = context.new_page()
                page.set_default_timeout(7000)
                page.on("pageerror", lambda error: result["errors"].append(str(error)))
                page.goto(base + "#records", wait_until="networkidle")
                page.locator("#qtbl tbody tr").first.wait_for(state="attached")
                checked: set[str] = set()
                counts = {"width": width, "questions": 0, "rounds": 0, "comparisons": 0, "screenshots": []}

                def navigate(hash_value: str) -> None:
                    page.evaluate("hash=>{history.replaceState(null,'',hash);return route();}", hash_value)

                def capture(label: str, screenshot: bool = False) -> None:
                    state = page.evaluate(SNAPSHOT_JS)
                    text = re.sub(r"https?://[^\s)>]+", " ", state["text"])
                    leaks = sorted(set(INTERNAL.findall(text)))
                    if leaks:
                        result["leaks"].append({"width": width, "screen": label, "tokens": leaks})
                    if state["width"] > width + 1:
                        result["overflow"].append({"width": width, "screen": label, "actual": state["width"]})
                    checked.add(label)
                    if screenshot:
                        page.wait_for_function("() => getComputedStyle(document.querySelector('#app > div')).opacity==='1'")
                        target = report_dir / f"{width}-{label}.png"
                        page.screenshot(path=str(target), full_page=False)
                        counts["screenshots"].append(str(target))

                capture("questions", screenshot=True)
                page.locator("#fq").fill("검색결과가없는문장")
                assert "0건" in page.locator("#qcount").inner_text()
                capture("empty-filter")
                page.locator("#freset").click()
                page.locator("#fd").select_option(index=1)
                assert page.locator("#qtbl tbody tr").count() > 0
                page.locator("#freset").click()
                if page.locator('[data-question-layout="cards"]').is_visible():
                    page.locator('[data-question-layout="cards"]').click()
                capture("question-cards")

                for question in data["questions"]:
                    navigate("#records/question/" + question["id"])
                    page.locator("#rnds").wait_for(state="attached")
                    counts["questions"] += 1
                    capture("question-" + question["id"])
                    for record in data["forecast_history"].get(question["id"], []):
                        page.locator(f'#rnds [data-r="{record["round"]}"]').click()
                        counts["rounds"] += 1
                        capture("round-" + record["forecast_id"])
                        button = page.locator(".reasoning-compare-toggle")
                        if button.count():
                            button.click()
                            assert page.locator("#reason-compare").is_visible()
                            counts["comparisons"] += 1
                            capture("previous-" + record["forecast_id"])
                    for details in page.locator("#app details").all():
                        details.evaluate("node=>node.open=true")
                    capture("details-" + question["id"])

                chosen = [question for question in data["questions"] if question.get("n_rounds", 0) > 1 and question["status"] == "active"][:2]
                for question in chosen:
                    navigate("#records/question/" + question["id"])
                    page.locator("#rnds").wait_for(state="attached")
                    page.locator("#app [data-compare-q]").click()
                navigate("#records/compare/" + ",".join(q["id"] for q in chosen))
                page.locator(".compare-card").first.wait_for()
                capture("compare", screenshot=True)
                page.locator("#compare-history svg").focus()
                page.keyboard.press("ArrowLeft")
                capture("compare-keyboard")

                for route, label in (("#records/performance", "performance"), ("#records/journal", "journal")):
                    navigate(route)
                    page.locator("#app h1").wait_for()
                    capture(label, screenshot=True)
                page.locator('[data-journal-mode="replay"]').click()
                page.locator('[data-replay-date]').first.click()
                capture("replay-first", screenshot=True)
                page.locator('[data-replay-offset="-7"]').click()
                capture("replay-week")

                page.evaluate("() => setShare(true)")
                assert page.locator("#share-layer").is_visible()
                share_text = page.locator("#share-summary").inner_text()
                assert not INTERNAL.search(share_text)
                page.locator("#share-close").click()
                page.evaluate("() => setUtility(true)")
                utility = page.locator("#utility-layer").inner_text()
                assert "legacy_internal_name" not in utility and "source_uri" not in utility
                page.evaluate("() => setUtility(false)")
                page.evaluate("() => setCommand(true)")
                commands = page.locator("#command-layer").inner_text()
                assert "legacy_internal_name" not in commands and "source_uri" not in commands
                page.evaluate("() => setCommand(false)")
                navigate("#records/question/" + chosen[0]["id"])
                page.locator("#rnds").wait_for(state="attached")
                page.locator("#app [data-pin-q]").click()
                assert page.locator("#app [data-pin-q]").get_attribute("aria-pressed") == "true"
                if page.locator("#app [data-calendar-q]").count():
                    with page.expect_download() as download:
                        page.locator("#app [data-calendar-q]").click()
                    downloaded = download.value
                    target = report_dir / f"{width}-calendar.ics"
                    downloaded.save_as(target)
                    calendar = target.read_text(encoding="utf-8")
                    assert "BEGIN:VEVENT" in calendar
                    summary = re.search(r"(?m)^SUMMARY:(.*)", calendar).group(1)
                    assert not INTERNAL.search(summary)
                capture("detail", screenshot=True)
                counts["screens_checked"] = len(checked)
                result["viewports"].append(counts)
                context.close()
            browser.close()
    except Exception as error:
        result["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        server.shutdown()
        server.server_close()
    result["passed"] = not result["errors"] and not result["leaks"] and not result["overflow"]
    (report_dir / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    parser.add_argument("report_dir", type=Path)
    args = parser.parse_args()
    report = verify(args.site.resolve(), args.report_dir.resolve())
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)
