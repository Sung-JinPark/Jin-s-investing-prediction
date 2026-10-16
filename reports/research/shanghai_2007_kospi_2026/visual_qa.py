"""Render the self-contained research report at desktop/mobile sizes, offline."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent


def main():
    out=ROOT/"qa";out.mkdir(exist_ok=True)
    results=[]
    with sync_playwright() as p:
        bundled=Path(p.chromium.executable_path)
        installed=Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        browser=p.chromium.launch(headless=True,executable_path=str(bundled if bundled.exists() else installed))
        for width,height in [(1440,1000),(768,1000),(390,844)]:
            page=browser.new_page(viewport={"width":width,"height":height},device_scale_factor=1)
            requests=[];errors=[]
            page.on("pageerror",lambda e: errors.append(str(e)))
            page.route("http://**/*",lambda route: (requests.append(route.request.url),route.abort()))
            page.route("https://**/*",lambda route: (requests.append(route.request.url),route.abort()))
            page.goto((ROOT/"report.html").as_uri(),wait_until="load")
            page.evaluate("document.fonts.ready")
            result=page.evaluate("""() => ({
                viewport:innerWidth, bodyWidth:document.body.scrollWidth,
                horizontalOverflow:document.documentElement.scrollWidth>innerWidth,
                images:[...document.images].map(i=>({loaded:i.complete&&i.naturalWidth>0, renderedWidth:i.getBoundingClientRect().width})),
                headings:document.querySelectorAll('h1').length,
                tables:document.querySelectorAll('table').length,
                contentHeight:document.documentElement.scrollHeight
            })""")
            result.update(width=width,errors=errors,remote_requests=requests)
            page.screenshot(path=str(out/f"report_{width}_top.png"))
            if width==1440:
                page.locator("#_5").count()  # never relies on unstable heading ids
                page.evaluate("window.scrollTo(0,1800)")
                page.screenshot(path=str(out/"report_desktop_middle.png"))
            if width==390:
                page.get_by_role("heading",name="향후 6개월과 12개월의 판단 조건",exact=True).scroll_into_view_if_needed()
                page.screenshot(path=str(out/"report_mobile_risk.png"))
            result["passed"]=(not result["horizontalOverflow"] and all(x["loaded"] for x in result["images"]) and not errors and not requests and result["headings"]==1)
            results.append(result);page.close()
        browser.close()
    (ROOT/"visual_qa.json").write_text(json.dumps({"results":results,"passed":all(r["passed"] for r in results)},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(results,ensure_ascii=False))
    if not all(r["passed"] for r in results):raise SystemExit(1)


if __name__=="__main__":main()
