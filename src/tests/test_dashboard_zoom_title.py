"""A range switch must not leave the detail dialog labeled with its old range."""
import json
import shutil
import subprocess

import pytest

from ai_fc import dashboard


def test_zoom_reads_current_chart_title_when_focused_and_opened(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    helper = source[source.index("function enhanceChartZoom("):source.index("function contextTabs(")]
    program = tmp_path / "zoom.js"
    program.write_text("""
const CHART_ZOOM_SELECTOR='charts';
let title='3개월', opened;
const button={setAttribute:(key,value)=>button[key]=value};
const surface={dataset:{},classList:{add:()=>{}},querySelector:()=>true,before:()=>{}};
const document={querySelectorAll:()=>[surface]};
const chartZoomTitle=()=>title,esc=value=>value,el=()=>({}),$=()=>button;
const openChartZoom=(surface,trigger,label)=>{opened=label;};
""" + helper + """
enhanceChartZoom();
title='2027 연말';button.onfocus();
const accessible=button['aria-label'];
title='다음 1개월';button.onclick();
process.stdout.write(JSON.stringify({accessible,opened,current:button['aria-label']}));
""", encoding="utf-8")
    result = subprocess.run([node, str(program)], capture_output=True, text=True,
                            encoding="utf-8", check=True)
    assert json.loads(result.stdout) == {
        "accessible": "2027 연말 확대해서 보기",
        "opened": "다음 1개월",
        "current": "다음 1개월 확대해서 보기",
    }
