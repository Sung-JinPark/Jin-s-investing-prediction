"""Render the standalone Korean chronology report; no network or model writes."""
from pathlib import Path
import re
import markdown

ROOT = Path(__file__).resolve().parent


def main():
    body = markdown.markdown((ROOT / "report.md").read_text(encoding="utf-8"),
                             extensions=["tables", "fenced_code"])
    body = re.sub(r"(<table>.*?</table>)", r'<div class="table-wrap">\1</div>', body, flags=re.S)
    css = """
*{box-sizing:border-box}html{background:#f5f4f0;color:#21313f}
body{margin:0;font:16px/1.85 'Malgun Gothic','Segoe UI',sans-serif}
main{max-width:1120px;padding:52px 48px 80px;margin:auto;background:white}
h1{font-size:34px;color:#173f61;line-height:1.5;margin:0 0 28px}
h2{font-size:25px;line-height:1.5;margin:48px 0 20px;padding-top:20px;border-top:2px solid #cfdae1}
h3{font-size:20px;line-height:1.6;color:#255273;margin:32px 0 15px}
p{margin:0 0 20px}a{color:#156a9f;overflow-wrap:anywhere}
li{margin:10px 0}.table-wrap{overflow-x:auto;margin:24px 0 30px}
table{width:100%;border-collapse:collapse;font-size:14px;line-height:1.75}
th,td{text-align:left;vertical-align:top;border-bottom:1px solid #dce3e8;padding:12px;min-width:140px}
th{background:#eaf2f6}td:first-child,th:first-child{min-width:165px}
code{font-size:.85em;background:#f0f3f5;padding:2px 4px;overflow-wrap:anywhere}
@media(max-width:650px){main{padding:28px 20px 60px}body{font-size:15px}h1{font-size:27px}h2{font-size:22px}h3{font-size:19px}}
@media print{main{max-width:none;padding:0}html{background:white}h2,h3{break-after:avoid}tr{break-inside:avoid}}
"""
    html = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>중국 실적과 주가 하락의 선후관계와 한국 비교</title><style>'
            + css + '</style></head><body><main>' + body + '</main></body></html>')
    (ROOT / "report.html").write_text(html, encoding="utf-8")
    print(f"Rendered report.html ({len(html.encode('utf-8'))} bytes)")


if __name__ == "__main__":
    main()
