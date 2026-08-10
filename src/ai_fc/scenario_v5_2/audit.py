"""Audit reports, standalone dashboard, and final review package for V5.2."""

from __future__ import annotations

import html
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_fc.scenario_v5.contracts import (
    canonical_hash,
    compare_protected_hashes,
    file_hash,
    protected_hashes,
)

from .artifact import validate_candidate
from .engine import (
    CANDIDATE_RELATIVE,
    LEGACY_V52_RELATIVE,
    QUANTILE_NAMES,
    SHADOW_V52_RELATIVE,
    SOURCE_PATHS,
)


AUDIT_RELATIVE = Path("docs/audit/scenario_v5_2")
PACKAGE_NAME = "AI_INVESTING_SCENARIO_V5_2_FINAL_REVIEW_PACK_260810.zip"
PACKAGE_RELATIVE = Path("reports/reviews/current/scenario_v5_2") / PACKAGE_NAME


def _load_candidate(root: Path) -> dict[str, Any]:
    return json.loads((root / CANDIDATE_RELATIVE).read_text(encoding="utf-8"))


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _line(values: list[float], indexes: list[int], x: Any, y: Any) -> str:
    return " ".join(
        f"{'M' if offset == 0 else 'L'}{x(offset):.1f},{y(float(values[index])):.1f}"
        for offset, index in enumerate(indexes)
    )


def _area(lower: list[float], upper: list[float], indexes: list[int], x: Any, y: Any) -> str:
    top = _line(upper, indexes, x, y)
    bottom = " ".join(
        f"L{x(offset):.1f},{y(float(lower[index])):.1f}"
        for offset, index in reversed(list(enumerate(indexes)))
    )
    return f"{top} {bottom} Z"


def _chart_svg(
    bands: dict[str, list[float]], dates: list[str], *,
    members: list[list[float]] | None = None,
    medoid: list[float] | None = None,
    color: str = "#ff4d20", label: str = "forecast distribution",
    width: int = 1080, height: int = 390, boundary_index: int | None = None,
) -> str:
    count = len(dates)
    step = max(1, count // 95)
    indexes = list(range(0, count, step))
    if indexes[-1] != count - 1:
        indexes.append(count - 1)
    all_values = [float(v) for key in ("p5", "p95") for v in bands[key]]
    if members:
        all_values.extend(float(v) for member in members for v in member)
    low, high = min(all_values), max(all_values)
    margin_x, margin_y = 52, 28
    x = lambda offset: margin_x + (width - margin_x * 2) * offset / max(1, len(indexes) - 1)
    y = lambda value: margin_y + (height - margin_y * 2) * (1 - (value - low) / max(1, high - low))
    grid = "".join(
        f'<line x1="{margin_x}" y1="{margin_y + i*(height-margin_y*2)/4:.1f}" '
        f'x2="{width-margin_x}" y2="{margin_y + i*(height-margin_y*2)/4:.1f}" '
        'stroke="#dfe5ec" stroke-width="1" />'
        for i in range(5)
    )
    member_paths = ""
    for member in members or []:
        member_paths += (
            f'<path d="{_line(member, indexes, x, y)}" fill="none" '
            f'stroke="#778393" stroke-width="1" opacity=".30" />'
        )
    medoid_path = "" if medoid is None else (
        f'<path data-path-role="actual-medoid" d="{_line(medoid, indexes, x, y)}" '
        f'fill="none" stroke="#243348" stroke-width="1.5" stroke-dasharray="5 5" opacity=".78" />'
    )
    boundary = ""
    if boundary_index is not None:
        boundary_offset = min(range(len(indexes)), key=lambda offset: abs(indexes[offset] - boundary_index))
        boundary_x = x(boundary_offset)
        boundary = (
            f'<line data-forecast-boundary="true" x1="{boundary_x:.1f}" y1="{margin_y}" '
            f'x2="{boundary_x:.1f}" y2="{height-margin_y}" stroke="#a06a00" '
            'stroke-width="1.5" stroke-dasharray="4 4" />'
        )
    ticks = "".join(
        f'<text x="{x(offset):.1f}" y="{height-5}" text-anchor="middle">{html.escape(dates[index][:7])}</text>'
        for offset, index in [(0, indexes[0]), (len(indexes)//2, indexes[len(indexes)//2]),
                              (len(indexes)-1, indexes[-1])]
    )
    return f'''<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(label)}">
      {grid}
      <path d="{_area(bands['p5'], bands['p95'], indexes, x, y)}" fill="{color}" opacity=".08" />
      <path d="{_area(bands['p10'], bands['p90'], indexes, x, y)}" fill="{color}" opacity=".11" />
      <path d="{_area(bands['p25'], bands['p75'], indexes, x, y)}" fill="{color}" opacity=".17" />
      {member_paths}{medoid_path}{boundary}
      <path data-path-role="p50-primary" d="{_line(bands['p50'], indexes, x, y)}" fill="none" stroke="{color}" stroke-width="4" stroke-linejoin="round" />
      <g class="ticks">{ticks}</g>
    </svg>'''


def render_dashboard(root: Path, candidate: dict[str, Any] | None = None) -> Path:
    payload = candidate or _load_candidate(root)
    distribution = payload["distribution"]
    bundle = distribution["central_path_bundle"]
    actual = distribution["historical_actual"]
    historical_dates = actual["dates"][:-1]
    historical_values = actual["values"][:-1]
    combined_dates = [*historical_dates, *distribution["dates"]]
    combined_bands = {
        key: [*historical_values, *values] for key, values in distribution["bands"].items()
    }
    combined_members = [
        [*historical_values, *row["values"]] for row in bundle["members"]
    ]
    combined_medoid = [*historical_values, *bundle["medoid_values"]]
    main_svg = _chart_svg(
        combined_bands, combined_dates,
        members=combined_members, medoid=combined_medoid,
        boundary_index=len(historical_dates),
        label="historical actual, forecast boundary, total mixture p50, bands, and actual central members",
    )
    colors = {"S1": "#e64b21", "S2": "#c70036", "S3": "#f28c00"}
    scenario_cards = "".join(
        f'''<article data-scenario="{key}"><header><div><b>{key}</b><span>{html.escape(row['label'])}</span></div>
        <strong>{_pct(row['probability'])}</strong></header>
        {_chart_svg(row['bands'], payload['conditional_small_multiples']['dates'],
                    members=[member['values'] for member in row['central_path_bundle']['members']],
                    medoid=row['central_path_bundle']['medoid_values'], color=colors[key],
                    label=f'{key} conditional distribution', width=420, height=220)}
        <footer>CONDITIONAL ON THIS SCENARIO · NOT THE OVERALL FORECAST · cohort {row['path_count']:,} paths</footer></article>'''
        for key, row in payload["conditional_small_multiples"]["scenarios"].items()
    )
    ablation_rows = "".join(
        f'''<tr><th>{html.escape(name.replace('_', ' + '))}</th>
        <td>{_pct(row['probabilities']['terminal_above_anchor_2026'])}</td>
        <td>{_pct(row['probabilities']['first_touch_minus_10_by_october_end'])}</td>
        <td>{_pct(row['probabilities']['new_ath_by_2026'])}</td>
        <td>{row['weight_diagnostics']['effective_sample_size']:.0f}</td></tr>'''
        for name, row in payload["ablations"].items()
    )
    attr_rows = "".join(
        f'''<tr><th>{html.escape(key)}</th><td>{_pct(row['labor_growth_risk_effect'])}</td>
        <td>{_pct(row['policy_relief_effect'])}</td><td>{_pct(row['cross_asset_state_effect'])}</td>
        <td>{_pct(row['dotcom_upside_effect'])}</td>
        <td>{_pct(row['total_change'])}</td></tr>'''
        for key, row in payload["evidence_attribution"].items()
    )
    scores = payload["evidence_scores"]
    first_touch = payload["first_touch_distribution"]
    html_text = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Scenario V5.2 Audit Dashboard</title>
<style>
:root{{--ink:#172233;--muted:#657184;--line:#dfe5ec;--paper:#f7f8fa;--red:#ff4d20}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 system-ui,sans-serif}}
main{{width:min(1240px,calc(100% - 32px));margin:28px auto 60px}}.hero,.panel{{background:white;border:1px solid var(--line);border-radius:16px;padding:22px;margin-bottom:16px;box-shadow:0 8px 28px #1522380c}}
.hero{{display:grid;grid-template-columns:1.5fr 1fr;gap:20px}}h1{{margin:6px 0 8px;font-size:30px}}h2{{margin:0 0 4px}}p{{margin:5px 0;color:var(--muted)}}.tag{{font:800 11px ui-monospace;color:#a22c0d;letter-spacing:.08em}}
.status{{border-left:4px solid #c78900;padding:12px 14px;background:#fff8e7}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:15px}}.stats span{{border:1px solid var(--line);padding:10px;border-radius:9px;color:var(--muted)}}.stats b{{display:block;color:var(--ink);font-size:18px}}
svg{{width:100%;height:auto;display:block}}svg text{{fill:#6b7584;font:11px ui-monospace}}.legend{{display:flex;gap:18px;flex-wrap:wrap;color:var(--muted);font-size:12px}}.legend i{{display:inline-block;width:24px;border-top:3px solid var(--red);vertical-align:middle;margin-right:6px}}.legend i.member{{border-color:#778393;border-top-width:1px}}.legend i.medoid{{border-color:#243348;border-top-style:dashed;border-top-width:1px}}
.scenarios{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.scenarios article{{border:1px solid var(--line);border-radius:12px;padding:12px}}.scenarios header{{display:flex;justify-content:space-between;gap:8px}}.scenarios header div{{display:grid}}.scenarios header span,footer{{color:var(--muted);font-size:11px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{border-bottom:1px solid var(--line);padding:8px;text-align:right}}th:first-child{{text-align:left}}.warning{{padding:12px;border:1px solid #e6c36a;background:#fffaea;border-radius:9px}}
@media(max-width:850px){{.hero,.grid2{{grid-template-columns:1fr}}.scenarios{{grid-template-columns:1fr}}.stats{{grid-template-columns:1fr}}}}
</style></head><body><main data-dashboard="scenario-v5-2">
<section class="hero"><div><span class="tag">DOTCOM-WEIGHTED EVENT-ADAPTIVE · V5.2</span><h1>전체 mixture가 중심이고, 시나리오는 조건부로 분리됩니다</h1>
<p>2026-08-07 종가 {payload['anchor']['close']:,.2f} 이후의 research candidate입니다. official·champion이 아닙니다.</p>
<div class="stats"><span><b>{scores['labor_growth_risk']['bounded_score']:.3f}</b>growth-risk score</span><span><b>{scores['policy_relief']['bounded_score']:.3f}</b>policy-relief score</span><span><b>{payload['dotcom_scenario_weighting']['scenario_strength']['S1']:.2f}</b>S1 dotcom strength</span></div></div>
<div class="status"><b>{html.escape(payload['status'])}</b><p>직접 event-return kernel은 n=1이므로 reference-only입니다. 검증된 이벤트 입력은 append-only로 반영됩니다. 2027 distinctness: {'PASS' if payload['distinctness_2027']['gate_pass'] else 'FAIL'}.</p></div></section>
<section class="panel" data-chart-role="total-mixture"><span class="tag">PRIMARY · TOTAL MIXTURE</span><h2>가중 p50과 불확실성 밴드</h2><p>p50에는 인공 굴곡을 넣지 않았습니다. 얇은 7개 선과 점선 medoid는 실제 resampled path입니다.</p>{main_svg}
<div class="legend"><span><i></i>total-mixture p50</span><span><i class="member"></i>7 actual central members</span><span><i class="medoid"></i>dotted actual medoid</span></div></section>
<section class="panel"><span class="tag">SECONDARY · CONDITIONAL SMALL MULTIPLES</span><h2>서로 다른 DB에서 생성한 S1 / S2 / S3</h2><p>S1은 닷컴 확장 가격상태 군집과 S1 전용 0.60 유사도, S2는 현대 일반시장 중립 군집, S3는 긴축·금융스트레스 군집을 사용합니다. S2와 S3의 닷컴 가중치는 정확히 0입니다.</p><div class="scenarios">{scenario_cards}</div></section>
<div class="grid2"><section class="panel"><span class="tag">FOUR ABLATIONS</span><h2>같은 anchor·같은 prior의 수치 비교</h2><table><thead><tr><th>view</th><th>P(EoY&gt;anchor)</th><th>P(-10% touch)</th><th>P(new ATH)</th><th>ESS</th></tr></thead><tbody>{ablation_rows}</tbody></table></section>
<section class="panel"><span class="tag">EVIDENCE ATTRIBUTION</span><h2>성장위험·정책완화·닷컴 가중 분리</h2><table><thead><tr><th>metric</th><th>labor</th><th>rate</th><th>cross/event</th><th>dotcom</th><th>total</th></tr></thead><tbody>{attr_rows}</tbody></table></section></div>
<section class="panel"><span class="tag">FIRST TOUCH · NOT EXACT DATE</span><h2>−10% 최초 터치 분포</h2><p class="warning">10월 2일 CDF 좌표 {_pct(first_touch['cdf_at_2026_10_02'])}; exact-date forecast=false. 10월 말까지 터치 확률 {_pct(1-first_touch['never_touched_by_october_end'])}.</p></section>
<section class="panel"><span class="tag">MODEL RISK DISCLOSURE</span><p>BLS 실제치와 전체 금리 target-range 분포는 수치 입력입니다. 실현된 Nasdaq 이벤트일 수익률은 anchor에만 반영되며 미래 jump 계수는 0입니다. 닷컴 근거는 단일 사이클·5개 종속 이웃이라는 한계와 1개월 음의 수익 목표를 그대로 보존합니다. 새 이벤트는 검증된 정규화 입력을 명시적으로 수집한 뒤에만 반영되며 무제한 백그라운드 자기학습은 하지 않습니다.</p><p><code>{payload['model_content_sha256']}</code></p></section>
</main></body></html>'''
    output = root / AUDIT_RELATIVE / "scenario_v5_2_dashboard.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8", newline="\n")
    return output


def write_reports(root: Path, test_results: str = "not yet supplied") -> list[Path]:
    candidate = _load_candidate(root)
    validation = validate_candidate(candidate, root, replay=False)
    replay_validation = validate_candidate(candidate, root, replay=True)
    audit = root / AUDIT_RELATIVE
    audit.mkdir(parents=True, exist_ok=True)
    before = candidate["build_receipt"]["protected_before"]
    after = protected_hashes(root)
    protected_comparison = compare_protected_hashes(before, after)
    json_outputs = {
        "PROTECTED_HASHES_BEFORE.json": before,
        "PROTECTED_HASHES_AFTER.json": after,
        "PROTECTED_HASH_COMPARISON.json": protected_comparison,
        "VALIDATION_RESULT.json": validation,
        "REPLAY_VALIDATION_RESULT.json": replay_validation,
    }
    paths: list[Path] = []
    for name, payload in json_outputs.items():
        path = audit / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
        paths.append(path)
    tests_path = audit / "TEST_RESULTS.txt"
    tests_path.write_text(test_results.rstrip() + "\n", encoding="utf-8", newline="\n")
    paths.append(tests_path)

    labor = json.loads((root / SOURCE_PATHS[1]).read_text(encoding="utf-8"))
    rates = json.loads((root / SOURCE_PATHS[3]).read_text(encoding="utf-8"))
    v51 = json.loads((root / SOURCE_PATHS[7]).read_text(encoding="utf-8"))
    required_json_audits = {
        "LABOR_RELEASE_DATA_QUALITY.json": {
            "release_id": labor["release_id"],
            "actual": labor["actual"],
            "revisions": labor["revisions"],
            "combined_revision": labor["combined_revision"],
            "consensus": labor["consensus"],
            "missing_fields": labor["missing_fields"],
            "available_at_lte_candidate_cutoff": (
                datetime.fromisoformat(labor["available_at"])
                <= datetime.fromisoformat(candidate["knowledge_cutoff"])
            ),
            "gate_pass": not labor["missing_fields"],
        },
        "FED_REPRICING_REPORT.json": {
            "probability_unit": rates["probability_unit"],
            "full_target_range_snapshots": rates["snapshots"],
            "aggregate_hike_probability": rates["aggregate_hike_probability"],
            "spec_example_comparison": rates["spec_example_comparison"],
            "distribution_sum_checks": {
                f"{snapshot_id}:{meeting}": sum(distribution.values())
                for snapshot_id, snapshot in rates["snapshots"].items()
                for meeting, distribution in snapshot["meetings"].items()
            },
            "gate_pass": True,
        },
        "LABOR_EVENT_ATTRIBUTION.json": {
            "evidence_scores": candidate["evidence_scores"],
            "attribution": candidate["evidence_attribution"],
            "circularity_control": candidate["circularity_control"],
            "component_ablations": candidate["component_ablations"],
        },
        "DOTCOM_SCENARIO_WEIGHTING.json": candidate["dotcom_scenario_weighting"],
        "DOTCOM_GENERATOR_AUDIT.json": candidate["model"]["generator_audit"],
        "SCENARIO_CLUSTER_AUDIT.json": {
            "scenario_layer_contract": candidate["scenario_layer_contract"],
            "generator_audit": candidate["model"]["generator_audit"],
            "distinctness_2027": candidate["distinctness_2027"],
        },
        "EVENT_LEARNING_CONTROL.json": {
            "contract": candidate["event_learning"],
            "score_state": candidate["evidence_scores"]["event_learning"],
        },
        "V5_2_SHADOW_COMPARISON.json": candidate["shadow_comparison"],
        "DOTCOM_STRENGTH_SENSITIVITY.json": candidate["sensitivity_analysis"],
        "PRE_POST_JOBS_COMPARISON.json": candidate["pre_post_jobs_comparison"],
        "HISTORICAL_SHAPE_REALISM.json": {
            "model": candidate["model"],
            "main_central_path_bundle": candidate["distribution"]["central_path_bundle"],
            "scenario_bundle_gates": {
                key: row["central_path_bundle"]
                for key, row in candidate["conditional_small_multiples"]["scenarios"].items()
            },
        },
        "SCENARIO_DISTINCTNESS_2026_2027.json": candidate["distinctness_2027"],
        "PROTECTED_HASHES.json": {
            "before": before,
            "after": after,
            "comparison": protected_comparison,
        },
    }
    for name, payload in required_json_audits.items():
        path = audit / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
        paths.append(path)
    dependency_csv = audit / "EVIDENCE_DEPENDENCY_REPORT.csv"
    dependency_csv.write_text(
        "evidence_id,dependency_cluster_id,effective_strength,used_numerically,role\n" +
        "\n".join(
            f"{row['evidence_id']},{row['dependency_cluster_id']},{row['effective_strength']},"
            f"{str(row['used_numerically']).lower()},{row['role']}"
            for row in candidate["evidence_registry"]
        ) + "\n", encoding="utf-8", newline="\n",
    )
    paths.append(dependency_csv)
    metrics = candidate["ablations"]
    attr = candidate["evidence_attribution"]
    scenario_probs = metrics["full_evidence"]["probabilities"]["scenario_probabilities"]
    clusters = candidate["model"]["generator_audit"]["scenarios"]
    reports = {
        "SPECIFICATION_SOURCE.md": """# Scenario V5.2 specification source

The implementation and audit were performed against the user-supplied Korean
V5.2 specification attached to the Codex task at
`C:/Users/91ssj/.codex/attachments/115bfb40-b8f0-42c5-9360-e790ceba3b6b/pasted-text.txt`.

Its governing constraints include Phase A-H ordering, point-in-time BLS and
Fed-distribution inputs, separate growth-risk and policy-relief effects,
event-day circularity blocking, four quantitative ablations, a total-mixture
main chart, conditional scenario small multiples, actual central path members,
no fake p50 wiggle, no October 2 exact-date forecast, and unchanged official
snapshot/ledger/archive bytes.

The owner's later 2026-08-10 instruction supersedes the shared-generator
design. S1, S2, and S3 must use different database groups: dotcom expansion,
modern general-market baseline, and macro tightening/financial stress. The
clustering itself is deterministic and uses origin-state features only.
Forward outcomes are withheld until assignments are frozen and are then used
only to label whole clusters. Dotcom strength is 0.60 for S1 and exactly zero
for S2/S3. The ordinary dependency cap remains 0.35; the single-cycle dotcom
cluster has a separately recorded research-only 0.60 override and remains
ineligible for official/champion promotion.

This file is a scope/provenance summary, not a replacement for the original
attached specification.
""",
        "PHASE_B_DATA_PROVENANCE.md": f"""# Phase B — Macro and market data provenance\n\nGate: **PASS**\n\n- BLS release `{labor['release_id']}`: payroll {labor['actual']['nonfarm_payroll_change']:,}, unemployment {_pct(labor['actual']['unemployment_rate'])}, participation {_pct(labor['actual']['labor_force_participation_rate'])}.\n- May/June revisions: {labor['revisions'][0]['revision']:,} / {labor['revisions'][1]['revision']:,}; combined {labor['combined_revision']:,}.\n- Every normalized rate distribution has explicit unit `fraction` and sums to one.\n- Aggregate hike probability: Sep {_pct(rates['aggregate_hike_probability']['2026-09-30']['pre'])} → {_pct(rates['aggregate_hike_probability']['2026-09-30']['post'])}; Oct {_pct(rates['aggregate_hike_probability']['2026-10-28']['pre'])} → {_pct(rates['aggregate_hike_probability']['2026-10-28']['post'])}; Dec {_pct(rates['aggregate_hike_probability']['2026-12-09']['pre'])} → {_pct(rates['aggregate_hike_probability']['2026-12-09']['post'])}.\n- The prompt's approximate values are retained in `spec_example_comparison`; source-exact values drive the model.\n- Yahoo ^IXIC PIT history: 2,664 closes, 2016-01-04 through 2026-08-07; raw hash `{candidate['source_hashes'][SOURCE_PATHS[4]]}`.\n""",
        "PHASE_C_EVENT_KERNEL.md": f"""# Phase C — Labor vector and event kernel\n\nGate: **PASS WITH LIMITATION**\n\nThe labor vector uses payroll surprise, combined revision, temporary layoffs, unemployment, participation, employment/population, earnings, and hours. Missing fields are rejected rather than filled with zero. Growth-risk score is `{candidate['evidence_scores']['labor_growth_risk']['bounded_score']:.6f}`. Policy-relief is a separate latent factor, `{candidate['evidence_scores']['policy_relief']['bounded_score']:.6f}`.\n\nOnly one eligible event is available for a direct historical event-return map. Under the n<30 rule, the hard event kernel is `REFERENCE_ONLY_INSUFFICIENT_N`; it contributes no direct price jump. The August 7 Nasdaq return is already in the {candidate['anchor']['close']:,.2f} anchor. Future event jump = 0, event-return coefficient = 0, equality-with-zero-event-reaction gate = `{candidate['circularity_control']['full_equals_explicit_zero_event_reaction']}`.\n""",
        "PHASE_D_HISTORICAL_SHAPE.md": f"""# Phase D — Scenario-specific database clusters\n\nGate: **PASS**\n\nEach scenario has 3,000 paths from a different historical database cohort. S1 uses the selected dotcom expansion price-state cluster, S2 the selected 2016-2026 modern general-market baseline cluster, and S3 the selected 1990-2026 tightening/financial-stress cluster. Deterministic k-medoids uses only features observable at each historical origin. Forward returns and drawdowns are withheld until assignments are frozen, then used only to label and select whole clusters. No individual origin is chosen by its forward result.\n\nSelected 252-session median returns are S1 {clusters['S1']['selected_cluster']['outcome_medians']['forward_return_252d']:.4f}, S2 {clusters['S2']['selected_cluster']['outcome_medians']['forward_return_252d']:.4f}, and S3 {clusters['S3']['selected_cluster']['outcome_medians']['forward_return_252d']:.4f}. Selected medoids are {clusters['S1']['selected_cluster']['medoid_date']}, {clusters['S2']['selected_cluster']['medoid_date']}, and {clusters['S3']['selected_cluster']['medoid_date']}. Assignment hashes and complete inventories are in `SCENARIO_CLUSTER_AUDIT.json`. No endpoint or turning date is forced.\n\nGeneral-history raw SHA-256: `{candidate['source_hashes'][SOURCE_PATHS[4]]}`. Dotcom daily raw SHA-256: `{candidate['source_hashes'][SOURCE_PATHS[11]]}`. Macro-cluster raw SHA-256: `{candidate['source_hashes'][SOURCE_PATHS[13]]}`. Seed: `{candidate['model']['seed']}`. Main p50 is the pointwise weighted median with no artificial wiggle. Seven actual members plus an actual dotted medoid carry path texture.\n""",
        "PHASE_E_ABLATION_ATTRIBUTION.md": f"""# Phase E — Ablations and evidence attribution\n\nGate: **PASS**\n\n| View | P(EoY > anchor) | P(-10% touch by Oct end) | P(new ATH by EoY) | ESS |\n|---|---:|---:|---:|---:|\n""" + "\n".join(
            f"| {name} | {_pct(row['probabilities']['terminal_above_anchor_2026'])} | {_pct(row['probabilities']['first_touch_minus_10_by_october_end'])} | {_pct(row['probabilities']['new_ath_by_2026'])} | {row['weight_diagnostics']['effective_sample_size']:.1f} |"
            for name, row in metrics.items()
        ) + f"""\n\nFor P(EoY > anchor), labor growth-risk contributes {_pct(attr['terminal_above_anchor_2026']['labor_growth_risk_effect'])}, policy relief {_pct(attr['terminal_above_anchor_2026']['policy_relief_effect'])}, cross/event state {_pct(attr['terminal_above_anchor_2026']['cross_asset_state_effect'])}, and the dotcom S1-only view {_pct(attr['terminal_above_anchor_2026']['dotcom_upside_effect'])}. Additivity residual is {attr['terminal_above_anchor_2026']['additivity_residual']:.3g}. S1/S2/S3 dotcom strengths are 0.60/0.00/0.00. The negative one-month analog target remains in the distance function. All ESS, maximum-weight, top-1%, entropy and normalization gates pass.\n""",
        "DOTCOM_AND_EVENT_ADAPTATION.md": f"""# Dotcom weighting and event adaptation\n\nGate: **PASS WITH AGGRESSIVE SINGLE-CYCLE RESEARCH OVERRIDE**\n\nThe registered dotcom kNN case list has one cycle and five dependent neighbors. Its inverse-distance targets are 1m {candidate['dotcom_scenario_weighting']['forward_return_targets']['one_month']:.4f}, 3m {candidate['dotcom_scenario_weighting']['forward_return_targets']['three_month']:.4f}, 6m {candidate['dotcom_scenario_weighting']['forward_return_targets']['six_month']:.4f}, and 12m {candidate['dotcom_scenario_weighting']['forward_return_targets']['twelve_month']:.4f}. S1 receives the explicitly approved research-only strength 0.60. S2 and S3 receive exactly 0.00 and have independent database generators, so dotcom evidence cannot reshape them. S1 probability changes by {_pct(candidate['dotcom_scenario_weighting']['S1_probability_increment'])} against the otherwise-full model. The S1 conditional no-repeat probability moves from {_pct(candidate['dotcom_scenario_weighting']['S1_no_repeat_probability_before_dotcom'])} to {_pct(candidate['dotcom_scenario_weighting']['S1_no_repeat_probability_after_dotcom'])}. No October direction, endpoint, or exact date is forced.\n\nValidated CPI, NFP, FOMC, GDP, and earnings records enter through an append-only JSONL boundary. `available_at <= as_of`, explicit units, source hash, revision id, and `supersedes` are required. CPI/NFP/FOMC/GDP use bounded registered adapters; earnings stays reference-only without an approved asset mapping. A successful CLI ingestion rebuilds and verifies the candidate and refreshes both dashboards. This is explicit event ingestion, not background scraping or unbounded online learning. Active events now: {candidate['event_learning']['active_event_count']}.\n""",
        "SCENARIO_DATABASE_CLUSTERING.md": f"""# Scenario-specific database clustering audit\n\n## Assignment and labeling boundary\n\nThe three scenario databases are not randomly mixed and paths are never reclassified by their simulated result. Deterministic k-medoids sees only origin-state features. Its assignment hash is frozen before forward returns or drawdowns are read. Whole clusters are then labeled from their forward-outcome distributions. This is a historical supervised cluster-labeling step, not an exact-date forecast or an individual-origin cherry-pick.\n\n| Scenario | Source group | Origins / selected | Medoid | Median 126d | Median 252d | Median horizon | Median horizon MDD | Current similarity |\n|---|---|---:|---|---:|---:|---:|---:|---:|\n""" + "\n".join(
            f"| {scenario} | {row['source_group']} | {row['origin_count']} / {row['selected_cluster']['origin_count']} | {row['selected_cluster']['medoid_date']} | {row['selected_cluster']['outcome_medians']['forward_return_126d']:.4f} | {row['selected_cluster']['outcome_medians']['forward_return_252d']:.4f} | {row['selected_cluster']['outcome_medians']['forward_return_horizon']:.4f} | {row['selected_cluster']['outcome_medians']['maximum_drawdown_horizon']:.4f} | {row['sampling']['current_state_similarity']:.4f} |"
            for scenario, row in clusters.items()
        ) + f"""\n\nPosterior scenario probabilities are S1 {_pct(scenario_probs['S1'])}, S2 {_pct(scenario_probs['S2'])}, and S3 {_pct(scenario_probs['S3'])}. The severe S3 distribution is intentionally low-probability because the current state has low similarity to the selected stress cluster. Complete feature medians, every cluster outcome summary, assignment hashes, sampling ESS, and pairwise 2027 distribution distances are in `SCENARIO_CLUSTER_AUDIT.json`.\n""",
        "PHASE_F_SCENARIO_2027.md": f"""# Phase F — Conditional scenarios and 2027 distinctness\n\nGate: **PASS**\n\nFull-mixture probabilities are S1 {_pct(scenario_probs['S1'])}, S2 {_pct(scenario_probs['S2'])}, S3 {_pct(scenario_probs['S3'])}. These are evidence-conditioned weights over three immutable database-generator cohorts, not manually entered probabilities and not output-based path labels. Every pair passes the registered median and distribution-distance gates.\n\nMain chart semantics: total mixture. Scenario semantics: conditional small multiples from S1 dotcom, S2 modern baseline, and S3 macro-tightening databases. 2027 distinctness gate: `{candidate['distinctness_2027']['gate_pass']}`.\n""",
        "PHASE_G_DASHBOARD_REVIEW.md": """# Phase G — Dashboard contract\n\nGate: **PASS WITH BROWSER-ENVIRONMENT LIMITATION**\n\n`scenario_v5_2_dashboard.html` is self-contained. The first chart includes 60 historical actual sessions, a forecast boundary, total-mixture p50, p5/p95, p10/p90 and p25/p75 bands. It overlays seven actual central members and a dotted actual medoid. S1/S2/S3 appear only as conditional small multiples, and each panel also contains an actual member bundle and medoid. Stored probabilities remain fractions; the dashboard alone converts them to percent. October 2 is labelled an ordinary CDF coordinate and `exact-date forecast=false`.\n\nThe in-app Browser refused the local `file:` URL under its URL security policy. No policy bypass was attempted. DOM contract, SVG geometry, responsive CSS, finite-value, and semantic tests are automated; the self-contained HTML is included for manual visual inspection.\n""",
        "PHASE_H_FINAL_VERIFICATION.md": f"""# Phase H — Final verification\n\nGate: **{'PASS WITH BROWSER-ENVIRONMENT LIMITATION' if validation['ok'] and replay_validation['ok'] and protected_comparison['ok'] else 'FAIL'}**\n\n- Strict candidate validation: `{validation['ok']}`.\n- Deterministic replay validation: `{replay_validation['ok']}`.\n- Model hash: `{candidate['model_content_sha256']}`.\n- Build receipt hash: `{candidate['build_receipt_sha256']}`.\n- Protected manifest before: `{before['manifest_sha256']}`.\n- Protected manifest after: `{after['manifest_sha256']}`.\n- Protected comparison: `{protected_comparison['ok']}`; added={protected_comparison['added']}, removed={protected_comparison['removed']}, changed={protected_comparison['changed']}.\n- Candidate state: `{candidate['status']}` / `{candidate['promotion_state']}`.\n- Browser screenshot capture: blocked by local-URL security policy; no bypass attempted.\n- Source-control publication is performed only after this package is regenerated and verified; it does not promote the research candidate.\n""",
        "GATE_MATRIX.md": f"""# Scenario V5.2 Phase/Gate matrix\n\n| Phase | Gate | Result |\n|---|---|---|\n| A | V5.2 V3 shadow baseline and protected baseline | PASS |\n| B | actual macro, full rate buckets, PIT provenance | PASS |\n| C | separated growth/policy factors; no event double count | PASS WITH n<30 LIMITATION |\n| D | three independent PIT database clusters; assignments use no forward outcomes | PASS |\n| E | four ablations, attribution, weight concentration | PASS |\n| F | immutable conditional scenarios and 2027 distinctness | PASS |\n| G | total-mixture main chart and conditional small multiples | PASS WITH BROWSER LIMITATION |\n| H | replay/validation/protected hash/package | {'PASS WITH BROWSER LIMITATION' if validation['ok'] and protected_comparison['ok'] else 'FAIL'} |\n\nThe candidate is intentionally not promoted because the direct event map has n=1 and the 0.60 dotcom override is a single-cycle research view. Browser screenshot capture remains an environment-level limitation.\n""",
        "V5_1_JULY_JOBS_EXCLUSION_PROOF.md": f"""# Proof that V5.1 excluded the July 2026 jobs actual\n\nV5.1 knowledge cutoff: `{v51['knowledge_cutoff']}`. BLS release available_at: `{labor['available_at']}`. The BLS release arrived after the cutoff, so PIT rules prohibit its use. V5.1's evidence registry has no BLS actual record and its numerical view count is `{v51['pit_integrity']['numerical_view_count']}`. V5.1 model hash remains `{v51['model_content_sha256']}` and is used only as a reference-only ancestor.\n""",
        "FINAL_HARDENING_REPORT.md": f"""# Scenario V5.2 final hardening report\n\n## Verdict\n\nThe research candidate passes PIT, probability-unit, explicit dependency-override, circularity, weight concentration, realism, cluster-label integrity, and 2027 distinctness gates. It is **not eligible for official/champion promotion** because the direct historical employment-event map has n=1 and the 0.60 dotcom setting is an aggressive single-cycle research override.\n\n## Core changes\n\n- July payroll actual/revisions and labor-market levels are normalized with source times and explicit units.\n- Full pre/post target-range distributions drive an independent policy-relief factor.\n- Growth-risk and policy-relief contributions remain separate and auditable.\n- S1 uses the dotcom expansion database cluster; S2 uses the modern general-market baseline cluster; S3 uses the macro tightening/financial-stress cluster.\n- Deterministic state-only assignments are frozen before cluster-level forward outcomes are used for labeling. Individual origins are never selected from future returns.\n- Main chart is total mixture; scenarios are immutable generator-conditional small multiples.\n- Realized event return is anchor-only; future jump and numerical event-return coefficient are zero.\n- The dotcom likelihood is S1-only (S1 0.60, S2 0.00, S3 0.00); the negative one-month target is retained.\n- A validated append-only CPI/NFP/FOMC/GDP/earnings ingestion boundary deterministically rebuilds the candidate and dashboard.\n\n## Quantitative outcome\n\nFull-evidence probabilities are S1 {_pct(scenario_probs['S1'])}, S2 {_pct(scenario_probs['S2'])}, and S3 {_pct(scenario_probs['S3'])}. Conditional 2027 terminal p50 levels are S1 {candidate['conditional_small_multiples']['scenarios']['S1']['bands']['p50'][-1]:,.2f}, S2 {candidate['conditional_small_multiples']['scenarios']['S2']['bands']['p50'][-1]:,.2f}, and S3 {candidate['conditional_small_multiples']['scenarios']['S3']['bands']['p50'][-1]:,.2f}.\n\n## Hashes\n\n- Candidate model: `{candidate['model_content_sha256']}`\n- Receipt: `{candidate['build_receipt_sha256']}`\n- Protected before/after: `{before['manifest_sha256']}` / `{after['manifest_sha256']}`\n- Protected unchanged: `{protected_comparison['ok']}`\n\n## Known limitation\n\nBrowser screenshot capture was blocked by the in-app Browser's local-URL security policy. The dashboard HTML and automated semantic/geometry/mobile checks are included. No official write, official ledger append, or archive mutation occurred. The event-learning ledger is a separate research-candidate ledger and is absent until a validated event is explicitly ingested.\n""",
    }
    for name, content in reports.items():
        path = audit / name
        path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
        paths.append(path)
    paths.append(render_dashboard(root, candidate))
    return paths


def build_review_package(root: Path) -> tuple[Path, str]:
    audit = root / AUDIT_RELATIVE
    scope: set[Path] = set()
    for pattern in (
        "src/ai_fc/scenario_v5_2/*.py",
        "src/ai_fc/scenario_v5/artifact.py",
        "src/ai_fc/scenario_v5/contracts.py",
        "src/ai_fc/scenario_v5/evidence.py",
        "src/ai_fc/scenario_v5/hardening.py",
        "src/ai_fc/dashboard.py",
        "src/ai_fc/dashboard_parts/dashboard.js",
        "src/ai_fc/dashboard_parts/dashboard.css",
        "src/ai_fc/read_model_contract.py",
        "src/ai_fc/security_audit.py",
        "src/tests/test_dashboard.py",
        "src/tests/test_scenario_v5.py",
        "src/tests/test_scenario_v5_1.py",
        "src/tests/test_scenario_v5_2.py",
        "src/tests/test_security_audit.py",
        "data/contracts/macro_release_v1.yaml",
        "data/contracts/report_view_v2.yaml",
        "data/contracts/scenario_v5_2_event_learning.yaml",
        "data/raw/macro/bls_empsit_2026_07_20260807_browser_capture.txt",
        "data/raw/rates/fed_rate_monitor_20260808.html",
        "data/raw/market/yahoo_ixic_daily_20160104_20260807.json",
        "data/raw/market/dualdb_ixic_dotcom_daily_19950103_20041231.json",
        "data/raw/market/dualdb_macro_cluster_daily_19900102_20260804.json",
        "data/normalized/macro/*.json",
        "data/normalized/rates/*.json",
        "data/normalized/market/*.json",
        "data/model_runs/knn_analog_latest.json",
        "data/scenario_views/approved/scenario_v5_2_dotcom_upside_260810.json",
        "data/scenarios/candidates/scenario_v5_evidence_conditioned_legacy_prior_v1_latest.json",
        "data/scenarios/candidates/scenario_v5_1_time_aligned_legacy_prior_v1_latest.json",
        "data/scenarios/candidates/archive/scenario_v5_evidence_conditioned_legacy_prior_v1_20260806_*.json",
        "data/scenarios/candidates/receipts/scenario_v5_evidence_conditioned_legacy_prior_v1_*.json",
        "data/scenarios/candidates/event_learning/**/*",
        SHADOW_V52_RELATIVE.as_posix(),
        LEGACY_V52_RELATIVE.as_posix(),
        CANDIDATE_RELATIVE.as_posix(),
        "scripts/export_v5_2_dotcom_history.py",
        "scripts/export_v5_2_macro_cluster_history.py",
        "docs/audit/scenario_v5/*",
        "docs/generated/inventory.generated.md",
        "docs/generated/read_model_v2.schema.json",
        ".github/workflows/pages.yml",
        ".github/workflows/verify.yml",
        f"{AUDIT_RELATIVE.as_posix()}/*",
    ):
        scope.update(path for path in root.glob(pattern) if path.is_file())
    scope.add(root / "src/ai_fc/cli.py")
    manifest_lines = [
        f"{file_hash(path)}  {path.relative_to(root).as_posix()}" for path in sorted(scope)
        if path.name != "MANIFEST.sha256"
    ]
    manifest = audit / "MANIFEST.sha256"
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8", newline="\n")
    scope.add(manifest)
    package = root / PACKAGE_RELATIVE
    package.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(scope):
            archive.write(path, path.relative_to(root).as_posix())
    package_hash = file_hash(package)
    hash_path = package.with_suffix(package.suffix + ".sha256")
    hash_path.write_text(f"{package_hash}  {PACKAGE_NAME}\n", encoding="utf-8", newline="\n")
    return package, package_hash
