"""Check the local report at desktop/tablet/mobile widths without remote requests."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent


def main():
    out = ROOT / "qa"
    out.mkdir(exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe")
        for width, height in [(1440, 1000), (768, 1000), (390, 844)]:
            page = browser.new_page(viewport={"width": width, "height": height})
            requests, errors = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://**/*", lambda route: (requests.append(route.request.url), route.abort()))
            page.route("https://**/*", lambda route: (requests.append(route.request.url), route.abort()))
            page.goto((ROOT / "report.html").as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            result = page.evaluate("""() => ({
              horizontalOverflow:document.documentElement.scrollWidth>innerWidth,
              headings:document.querySelectorAll('h1').length,
              tables:document.querySelectorAll('table').length,
              contentHeight:document.documentElement.scrollHeight
            })""")
            result.update(width=width, errors=errors, remote_requests=requests)
            page.screenshot(path=str(out / f"report_{width}_top.png"))
            if width == 390:
                page.get_by_role("heading", name="한국의 정책은 예고가 먼저이고 실제 인상은 하락 뒤였다", exact=True).scroll_into_view_if_needed()
                page.screenshot(path=str(out / "report_mobile_korea.png"))
            if width == 1440:
                page.get_by_role("heading", name="한국에서 같은 신호가 나타난 정도", exact=True).scroll_into_view_if_needed()
                page.screenshot(path=str(out / "report_desktop_matrix.png"))
            result["passed"] = (not result["horizontalOverflow"] and not errors
                                 and not requests and result["headings"] == 1 and result["tables"] == 3)
            results.append(result)
            page.close()
        browser.close()
    passed = all(r["passed"] for r in results)
    (ROOT / "visual_qa.json").write_text(json.dumps({"results": results, "passed": passed},
                                         ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
