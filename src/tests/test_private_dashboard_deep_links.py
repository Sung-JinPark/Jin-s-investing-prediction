"""Cold links must work before the chart's lazy navigation bridge is loaded."""
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

import pytest

from ai_fc.trendlines import contracts as C


def test_local_shell_forwards_public_deep_links_without_loading_chart_bundle(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    project = Path(__file__).resolve().parents[2]
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / relative, target)
    preview = runpy.run_path(str(project / "tools/preview_trendlines.py"))
    path = preview["build_local_service_preview"](tmp_path, tmp_path / "site")
    html = path.read_text(encoding="utf-8")
    navigation = re.search(r'<script>(if\(!location.hash\).*?)</script>', html).group(1)
    public = ["#future", "#future/original", "#future/timeseries/daily",
              "#statistics", "#statistics/dotcom/credit", "#statistics/history",
              "#statistics/market-liquidity", "#statistics/cross-asset",
              "#statistics/fear-greed", "#timeseries/path", "#today", "#records/journal"]
    local = ["", "#app", "#trendlines/sk-hynix", "#trendlines/soxx",
             "#future/trendlines/bitcoin"]
    program = tmp_path / "navigation.js"
    program.write_text("const vm=require('node:vm');\nconst script=" + json.dumps(navigation)
                       + ";const hashes=" + json.dumps(public + local) + ";\n" + """
const rows=hashes.map(hash=>{
  let target=null;
  const location={hash,replace:url=>{target=url;}};
  vm.runInNewContext(script,{location});
  return {hash:location.hash,target};
});
process.stdout.write(JSON.stringify(rows));
""", encoding="utf-8")
    result = subprocess.run([node, str(program)], capture_output=True, text=True,
                            encoding="utf-8", check=True)
    rows = json.loads(result.stdout)
    for original, row in zip(public, rows):
        assert row == {"hash": original, "target": "https://sung-jinpark.github.io/Jin-s-investing-prediction/" + original}
    assert rows[len(public):] == [{"hash": value or "#trendlines/sk-hynix", "target": None} for value in local]
    model = json.loads((tmp_path / "site/data.json").read_text(encoding="utf-8"))
    assert not model.get("scenario")
    assert not model["trendlines"].get("details")
