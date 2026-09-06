#!/usr/bin/env python
"""tools/v12_s5_tables.py — 최종 보고의 표 렌더러.

표는 전부 data/timeseries_v12/reports/final_report.json 에서만 렌더한다. 사람이 수치를
옮겨 적지 않으므로 전사 오류가 구조적으로 불가능하고, tools/v12_s5_doc_check.py 가
보고서의 표가 이 출력과 **바이트 일치**하는지 대사한다.

산출: outputs/timeseries_v12/loop/_s5_1_tables.md
실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s5_tables.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/timeseries_v12/reports/final_report.json"
OUT = ROOT / "outputs/timeseries_v12/loop/_s5_1_tables.md"


def f6(x) -> str:
    return "—" if x is None else f"{x:.6f}"


def f4(x) -> str:
    return "—" if x is None else f"{x:.4f}"


def f3(x) -> str:
    return "—" if x is None else f"{x:.3f}"


def pct(x, digits: int = 2) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def ci(pair) -> str:
    if not pair:
        return "—"
    return f"[{pair[0]:+.6f}, {pair[1]:+.6f}]"


def table_A(R: dict) -> list[str]:
    out = ["### 표 A — 태스크 13종 실행 결과", "",
           "| # | 태스크 | 제목 | accept | 상태 | 산출물 | 금지 verb |",
           "|---:|---|---|---|---|---:|---:|"]
    pending = False
    for t in R["loop"]["tasks"]:
        has_result = t["result_status"] is not None
        pending = pending or not has_result
        art = str(t["artifacts"]) if has_result else "—"
        verbs = str(t["forbidden_verbs_executed"]) if has_result else "—"
        out.append(f"| {t['priority']} | `{t['id']}` | {t['title']} | {t['accept']} | "
                   f"{t['backlog_status']} | {art} | {verbs} |")
    if pending:
        out += ["",
                "> `—` 는 그 태스크의 result JSON 이 이 표를 렌더한 시점에 아직 없다는 뜻이다. "
                "각 태스크의 result JSON 은 산출물 커밋 **뒤에** 기록되므로(루프 규약), "
                "마지막 태스크는 자기 산출물을 자기 표에 실을 수 없다 — 그 값은 해당 result JSON 에 있다."]
    return out + [""]


def table_B(R: dict) -> list[str]:
    F = R["stage_findings"]
    rows = [
        ("S1", F["S1"]["question"], f"세 트랙 전부 유지 · 번복 {F['S1']['overturned']}",
         f"민감도 33셀 중 번복 {F['S1']['sensitivity']['cells_overturn']}셀(전제 붕괴형) · 정본 셀 {F['S1']['sensitivity']['canonical_cell_verdict']}"),
        ("S2", F["S2"]["question"], f"S3 진입 ({F['S2']['entry']['decision']})",
         f"R0 {F['S2']['entry']['R0']} · R1 {F['S2']['entry']['R1']} · R2 {F['S2']['entry']['R2']} · R3 {F['S2']['entry']['R3']}"),
        ("S3", F["S3"]["question"], F["S3"]["decision"],
         f"채택 {F['S3']['adopted_cells']}/{F['S3']['cells']}셀 · k_obs={F['S3']['k_obs']} · T5 통과율 {F['S3']['T5_pass_rate_pooled']} > {F['S3']['T5_threshold']}"),
        ("CKPT", "S1~S3 산출물 봉인",
         f"앵커 재현 {R['ckpt_reproduction']['checkpoint_anchor_match']}",
         f"파일 {R['ckpt_reproduction']['files_rehashed']}+{R['ckpt_reproduction']['result_files_rehashed']} 재해시 · drift 0"),
        ("S4", F["S4"]["question"], F["S4"]["contract_status"],
         f"게이트 {len(F['S4']['gates_registered'])}종 등록 · armed={F['S4']['gates_armed']} · 평가 후보 {F['S4']['evaluated_candidates']} · 금지 {F['S4']['prohibitions_total']}종"),
    ]
    out = ["### 표 B — 단계별 판정 요약", "",
           "| 단계 | 물음 | 판정 | 근거 요약 |", "|---|---|---|---|"]
    for stage, q, verdict, note in rows:
        out.append(f"| **{stage}** | {q} | **{verdict}** | {note} |")
    return out + [""]


def table_C(R: dict) -> list[str]:
    S1 = R["stage_findings"]["S1"]
    out = ["### 표 C — S1 세 동결 독립 재계산", "",
           "| 트랙 | 판정 | 핵심 수치 |", "|---|---|---|"]
    out.append(f"| V10 W3 챔피언 | {S1['verdicts']['v10']} | 쌍대 평균 Δ {f6(S1['v10']['paired_mean_delta'])} "
               f"(상대 {pct(S1['v10']['relative_improvement'])}) · CI90 {ci(S1['v10']['ci90'])} · "
               f"GFC 견인 {pct(S1['v10']['gfc_delta_share'], 1)} · 상위5% 제거 후 평균 {f6(S1['v10']['top5pct_mean_after_removal'])} "
               f"(순이득의 {pct(S1['v10']['top5pct_share_of_net'], 2)}) |")
    out.append(f"| V11 P1 전이 | {S1['verdicts']['v11']} | 조합 {S1['v11']['combos_tested']} 중 채택 요건 충족 "
               f"{S1['v11']['combos_meeting_adoption_rule']} · 순열 귀무 p={S1['v11']['permutation_null_p']} |")
    out.append(f"| V9 exog | {S1['verdicts']['v9']} | {S1['v9']['pairs']}쌍 중 평균 Δ 양수 "
               f"{S1['v9']['pairs_with_positive_mean']} · 최대 \\|Δ\\| {f6(S1['v9']['max_abs_mean_delta'])} |")
    return out + [""]


def table_D(R: dict) -> list[str]:
    S2 = R["stage_findings"]["S2"]
    r, oc, sk = S2["reflection_baseline"], S2["overconfidence"], S2["skill_vs_climatology"]
    out = ["### 표 D — S2 first_touch 실력·과신 (417 원점 · 2007-01-05~2014-12-24)", "",
           "| 지평 | BS V8 | BS 반사 | BSS(V8\\|기후) | 기후 대비 쌍대 CI90 | BSS(V8\\|반사) | 반사 대비 쌍대 CI90 | V8 상위분위 gap CI90 | 반사 상위분위 gap CI90 |",
           "|---|---:|---:|---:|---|---:|---|---|---|"]
    out.append(f"| h21 | {f6(r['h21_brier_v8'])} | {f6(r['h21_brier_reflection'])} | {f6(sk['h21_bss'])} | "
               f"{ci(sk['h21_loss_diff_ci90'])} | {f6(r['h21_bss_v8_vs_reflection'])} | {ci(r['h21_loss_diff_ci90'])} | "
               f"{ci(oc['h21_v8_top_gap_ci90'])} | {ci(oc['h21_reflection_top_gap_ci90'])} |")
    out.append(f"| h63 | {f6(r['h63_brier_v8'])} | {f6(r['h63_brier_reflection'])} | {f6(sk['h63_bss'])} | "
               f"{ci(sk['h63_loss_diff_ci90'])} | {f6(r['h63_bss_v8_vs_reflection'])} | {ci(r['h63_loss_diff_ci90'])} | "
               f"{ci(oc['h63_v8_top_gap_ci90'])} | {ci(oc['h63_reflection_top_gap_ci90'])} |")
    out += ["",
            f"- 순위상관 ρ_s(p_V8, p_반사) = {f4(r['spearman_h21'])} (h21) · {f4(r['spearman_h63'])} (h63)",
            f"- 두 모델 동시 과신 국면 셀: {oc['shared_cells']}",
            ""]
    return out


def table_E(R: dict) -> list[str]:
    S3 = R["stage_findings"]["S3"]
    out = ["### 표 E — S3 사전등록 8셀 판정 (채택 = 양방향 CI90 하한 > 0)", "",
           "| 셀 | 구속 방향 | min CI90 하한 | 미달 양상 | 부족분(창 BS 대비) | 귀무 통과율 | 귀무 성격 | A1 | A2 |",
           "|---|---|---:|---|---:|---:|---|---|---|"]
    for c in S3["cells_detail"]:
        out.append(f"| {c['cell']} | {c['binding_direction']} | {f6(c['min_ci90_lower'])} | "
                   f"{c['binding_failure_mode']} | {pct(c['shortfall_share_of_brier'])} | "
                   f"{c['null_cell_pass_rate']:.3f} | {c['null_regime']} | "
                   f"{'채택' if c['A1'] else '미달'} | {'통과' if c['A2'] else '미달'} |")
    fm = S3["failure_modes"]
    out += ["",
            f"- 방향 {S3['directions']}개의 미달 양상: 하한<0 {fm['하한<0']} · 하한=0 {fm['하한=0']} · 하한>0 {fm['하한>0']}",
            f"- |Δ| < MDE 로 '결정적 증거 없음' 인 방향: {S3['inconclusive_by_mde_directions']}/{S3['directions']}",
            f"- 순열 귀무 아래 평균 통과 셀 수 k̄ = {S3['k_mean_under_null']} (실측 k_obs = {S3['k_obs']})",
            f"- T5 음성 대조: 통과율 {S3['T5_pass_rate_pooled']} > 문턱 {S3['T5_threshold']} → 실패 ({S3['governing_branch']})",
            ""]
    return out


def table_F(R: dict) -> list[str]:
    S4 = R["stage_findings"]["S4"]
    th, fe = S4["thresholds"], S4["feasibility"]
    out = ["### 표 F — S4 게이트 문턱과 재보정 도달 가능성", "",
           "| 지평 | 기후 BS | V8 BS | BSS(V8\\|기후) | 구속 기준선(BGK) 요구 BSS | 병기(2Φ) 요구 BSS | 완전 재보정 상한 | BGK 여유 | 재보정으로 도달 |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for h in ("h21", "h63"):
        out.append(f"| {h} | {f6(th[h]['climatology_brier'])} | {f6(th[h]['brier_v8'])} | "
                   f"{f6(th[h]['bss_v8_vs_climatology'])} | {f6(th[h]['bgk_required_bss'])} | "
                   f"{f6(th[h]['2phi_required_bss'])} | {f6(fe[h]['ceiling_fixed_bins'])} | "
                   f"{f6(th[h]['bgk_headroom_vs_ceiling'])} | {'가능' if fe[h]['bgk_reachable'] else '불가'} |")
    cur = S4["current_v8_position"]
    out += ["",
            "| 지평 | 오늘의 V8 원값 G1(기후) CI90 하한 | G2(BGK) CI90 하한 | 과신 유의 |",
            "|---|---:|---:|---|"]
    for h in ("h21", "h63"):
        out.append(f"| {h} | {f6(cur[h]['G1_ci90_lower'])} | {f6(cur[h]['G2_bgk_ci90_lower'])} | "
                   f"{cur[h]['G4_overconfidence_significant']} |")
    b = S4["budget"]
    out += ["",
            f"- 다중검정 예산 — 셀별 귀무 통과율 평균 {b['per_cell_null_pass_rate']} (명목 5% 의 {b['inflation_vs_nominal']:.2f}배) · "
            f"지평별 h21 {b['per_cell_mean_h21']} vs h63 {b['per_cell_mean_h63']}",
            f"- 데이터 예산 n* — h21×BGK 정의되지 않음(Δ̂≤0) · h63×BGK "
            f"{b['data_budget']['h63|vs_reflection_bgk']['n_star_origins']:.0f} 원점(+{b['data_budget']['h63|vs_reflection_bgk']['extra_years']:.0f}년)",
            f"- 개발 예산 상한 {b['maximum_development_evaluations']} · S3 소모 계상 시 잔여 {b['remaining_if_s3_counted']:.0f}",
            ""]
    return out


def table_G(R: dict) -> list[str]:
    out = ["### 표 G — 사용자 결정표 (V12-D1~D5)", "",
           "| ID | 결정 | 현재 상태 | 권고 | 되돌릴 수 없는 것 |", "|---|---|---|---|---|"]
    for d in R["decisions"]:
        out.append(f"| **{d['id']}** | {d['title']} | {d['state']} | "
                   f"{d['recommendation_short']} | {d['irreversible']} |")
    return out + [""]


def table_H(R: dict) -> list[str]:
    inc = R["incomplete"]
    out = ["### 표 H — 미완 항목 분류 (12 태스크 not_done 전량 수집)", "",
           "| 분류 | 건수 | 뜻 |", "|---|---:|---|"]
    meaning = {
        "후속 태스크 소관": "그 단계에서는 미완이었고 루프 안의 다음 태스크가 실제로 냈다",
        "의도적 보존": "설계상 하지 않기로 한 것 — 하지 않은 것이 산출물이다",
        "규약 승계 미산출": "상류 단계가 정한 규약을 그대로 물려받아 계산하지 않은 것",
        "자원·범위 밖": "할 수 있었으나 이 루프의 규율·시간·권한 밖이었던 것",
        "기타": "위 넷에 들어가지 않는 것",
    }
    order = ["후속 태스크 소관", "의도적 보존", "규약 승계 미산출", "자원·범위 밖", "기타"]
    counts = inc["not_done_by_category"]
    for cat in order:
        if cat in counts:
            out.append(f"| {cat} | {counts[cat]} | {meaning[cat]} |")
    out.append(f"| **합계** | **{inc['not_done_total']}** | 12 태스크 전량 |")
    fu = inc["followup"]
    out += ["",
            f"- '후속 태스크 소관' {fu['total']}건 중 {fu['named_paths_exist_now_true']}건은 항목이 이름 붙인 "
            f"산출물 경로가 지금 실재함을 기계로 확인했고, {fu['no_named_path']}건은 경로를 이름 붙이지 않아 "
            f"해당 후속 태스크의 accept 충족으로만 확인된다(경로 유실 {fu['named_paths_missing']}건). "
            f"이 분류를 빼면 루프 밖으로 나가는 미완은 {inc['not_done_total'] - fu['total']}건이다.",
            f"- 미결 질문(open_questions) 총 {inc['open_questions_total']}건 · 중복 이월을 접으면 "
            f"{inc['open_questions_distinct']}건 · 그중 `[미검증]`/`[미확정]` 표기 {inc['unverified_flagged']}건",
            ""]
    return out


def table_I(R: dict) -> list[str]:
    inv, ck = R["artifact_inventory"], R["ckpt_reproduction"]
    seal = R["seal_state"]
    out = ["### 표 I — 루프 산출물 무결성 재대사", "",
           "| 항목 | 값 |", "|---|---|"]
    rows = [
        ("선언 산출물 (12 태스크 result JSON 의 artifacts 합)", str(inv["declared_artifacts"])),
        ("고유 산출물 경로", str(inv["unique_artifact_paths"])),
        ("result JSON", str(inv["result_json_count"])),
        ("재해시 대상 파일 합계", str(inv["files_total"])),
        ("선언 해시와 불일치(drift)", str(len(inv["drifted"]))),
        ("유실(missing)", str(len(inv["missing"]))),
        ("산출물 앵커", f"`{inv['anchors']['artifacts_anchor']}`"),
        ("result 앵커", f"`{inv['anchors']['results_anchor']}`"),
        ("**루프 앵커**", f"`{inv['anchors']['loop_anchor']}`"),
        ("CKPT 체크포인트 앵커 재현", f"{ck['checkpoint_anchor_match']} (`{ck['checkpoint_anchor_declared']}`)"),
        ("V8/V2 봉인 해시", f"`{seal['sealed_sha256']}` · BOOT 기준선 일치 {seal['sealed_matches_baseline']}"),
        ("V8 원장 해시", f"`{seal['ledger_sha256']}` · 기준선 일치 {seal['ledger_matches_baseline']}"),
        ("불변 경로 워킹트리 변경", str(len(seal["immutable_paths_dirty"]))),
    ]
    for k, v in rows:
        out.append(f"| {k} | {v} |")
    return out + [""]


def table_J(R: dict) -> list[str]:
    inv = R.get("inventory")
    if not inv:
        return ["### 표 J — inventory 재생성", "", "미실행.", ""]
    snap = inv["snapshot"]
    out = ["### 표 J — inventory 재생성 (`ai-fc inventory` 등가)", "",
           "| 항목 | 값 |", "|---|---|"]
    rows = [
        ("source fingerprint", f"`{snap['source_fingerprint']}`"),
        ("등록 질문 / 예측 파일 / 근거 파일", f"{snap['questions']} / {snap['forecast_files']} / {snap['evidence_files']}"),
        ("해소 원장 행 / 고유 이벤트", f"{snap['resolution_rows']} / {snap['tables']['resolution_event']}"),
        ("원천 계약 수", str(snap["contracts"])),
        ("실행 전 최신 상태였는가", str(inv["was_current_before_run"])),
        ("갱신된 파일", ", ".join(f"`{p}`" for p in inv["files_changed"]) or "없음"),
        ("실행 후 최신 상태", str(inv["is_current_after_run"])),
        ("불변 경로 오염", str(len(inv["immutable_paths"]["dirty_after"]))),
    ]
    for k, v in rows:
        out.append(f"| {k} | {v} |")
    return out + [""]


def table_K(R: dict) -> list[str]:
    pr = R["pr"]
    out = ["### 표 K — PR 준비 상태 (push 없음)", "",
           "| 항목 | 값 |", "|---|---|"]
    rows = [
        ("브랜치", f"`{pr['branch']}` → `{pr['base_branch']}`"),
        ("HEAD", f"`{pr['head'][:8]}`"),
        ("루프 커밋 범위", f"`{pr['loop_range']}`"),
        ("루프 커밋 수", str(pr["loop_commits"])),
        ("루프 변경 파일", str(pr["loop_files_changed"])),
        ("루프 diff", pr["loop_shortstat"]),
        ("브랜치 전체가 main 보다 앞선 커밋", str(pr["branch_commits_ahead_of_main"])),
        ("원격 푸시", pr["push"]),
        ("불변 경로 오염", str(len(pr["immutable_paths_dirty"]))),
    ]
    for k, v in rows:
        out.append(f"| {k} | {v} |")
    return out + [""]


def render(R: dict) -> str:
    parts: list[str] = [
        "<!-- 자동 생성: tools/v12_s5_tables.py — 수기 편집 금지. "
        "원천: data/timeseries_v12/reports/final_report.json -->", "",
    ]
    for fn in (table_A, table_B, table_C, table_D, table_E,
               table_F, table_G, table_H, table_I, table_J, table_K):
        parts.extend(fn(R))
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    R = json.loads(SRC.read_text(encoding="utf-8"))
    text = render(R)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
