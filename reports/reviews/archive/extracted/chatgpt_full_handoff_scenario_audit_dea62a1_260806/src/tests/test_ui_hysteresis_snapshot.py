from __future__ import annotations

import json
import re
import subprocess

from ai_fc import dashboard


def test_beta_hysteresis_mock_states_render_snapshot() -> None:
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"function betaGateNote\(row\)\{.*?\n\}", source, flags=re.DOTALL)
    assert match, "pure betaGateNote renderer must remain extractable"
    script = match.group(0) + """
console.log(JSON.stringify([
  betaGateNote({status:'hysteresis_hold_1_of_2',gate_proximity:'below_boundary'}),
  betaGateNote({status:'eligible',gate_proximity:'at_boundary'}),
  betaGateNote({status:'eligible',gate_proximity:'clear'})
]));
"""
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, encoding="utf-8", check=True)
    assert json.loads(result.stdout) == [
        " · 표본 1/2회 미달·이전 β 유지",
        " · gate 경계(n=156)",
        "",
    ]
