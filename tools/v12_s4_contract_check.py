#!/usr/bin/env python
"""S4-1 — V12 계약 draft 독립 검증 (읽기 전용, 파일 쓰기 0).

계약 파일을 **읽어서** 원천(S2/S3 JSON·V8/V10 계약·봉인 해시)과 대사한다. 생성기의 롤업을
믿지 않고 원본 필드에서 다시 유도하며, 불일치는 전부 FAIL 이다.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s4_contract_check.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v12.draft.yaml"
GEN = ROOT / "tools/v12_s4_contract.py"

RESULTS: list[tuple[str, bool, str]] = []


def check(cid: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((cid, bool(ok), detail))


def load_json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_generator():
    """생성기를 모듈로 적재한다 (__main__ 가드 때문에 main() 은 실행되지 않는다)."""
    spec = importlib.util.spec_from_file_location("v12_s4_contract_mod", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TEXT = CONTRACT.read_text(encoding="utf-8")
C = yaml.safe_load(TEXT)

FT = load_json("data/timeseries_v12/diagnostics/first_touch_diagnostic.json")
RB = load_json("data/timeseries_v12/diagnostics/reflection_baseline.json")
S2 = load_json("data/timeseries_v12/diagnostics/s2_entry_verdict.json")
S3 = load_json("data/timeseries_v12/diagnostics/s3_verdict.json")
PRE = load_json("data/timeseries_v12/prereg/hypotheses.json")
CKPT = load_json("outputs/timeseries_v12/loop/checkpoint_monday.json")
V8 = yaml.safe_load((ROOT / "data/contracts/multivariate_timeseries_v8.yaml").read_text("utf-8"))
V10 = yaml.safe_load((ROOT / "data/contracts/multivariate_timeseries_v10.yaml").read_text("utf-8"))

HS = ["21", "63"]


def eq6(a, b) -> bool:
    return a is not None and b is not None and abs(float(a) - round(float(b), 6)) < 1e-12


# ── V1 봉인 ─────────────────────────────────────────────────────────────────
def v1_seal() -> None:
    spec = importlib.util.spec_from_file_location(
        "v12_seal_check_mod", ROOT / "tools/v12_seal_check.py")
    seal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seal)
    loop = ROOT / "outputs/timeseries_v12/loop"
    sealed = seal.sealed_hash()
    ledger = seal.ledger_hash()
    base = (loop / "sealed_baseline.hash").read_text().strip()
    lbase = (loop / "ledger_baseline.hash").read_text().strip()
    check("V1-a 봉인 해시 = BOOT baseline", sealed == base, sealed[:12])
    check("V1-b v8 원장 해시 = baseline", ledger == lbase, ledger[:12])
    check("V1-c 봉인 해시가 계약 핀과 일치",
          C["predecessor_immutability"]["sealed_source_hash"] == sealed)
    check("V1-d 원장 해시가 계약 핀과 일치",
          C["predecessor_immutability"]["v8_ledger_hash"] == ledger)


# ── V2 입력 무변경 ──────────────────────────────────────────────────────────
def v2_inputs() -> None:
    declared = {f["path"]: f["declared"] for f in CKPT["files"]}
    for rel, digest in C["provenance"]["inputs_sha256"].items():
        actual = sha256_file(ROOT / rel)
        check(f"V2 입력 sha256 일치 · {rel}", actual == digest, actual[:12])
        if rel in declared:
            check(f"V2-b CKPT 선언과 일치 · {rel}", declared[rel] == digest)


# ── V3 계약 성격 ────────────────────────────────────────────────────────────
def v3_character() -> None:
    check("V3-a status=negative_result_draft", C["status"] == "negative_result_draft")
    check("V3-b gates.armed=false", C["gates"]["armed"] is False)
    check("V3-c 평가된 후보 0", C["gates"]["evaluated_candidates"] == 0)
    check("V3-d 채택 0", C["negative_result"]["adopted_count"] == 0
          and C["negative_result"]["adopted_cells"] == [])
    check("V3-e decision_code=NEGATIVE_RESULT",
          C["negative_result"]["decision_code"] == "NEGATIVE_RESULT")
    check("V3-f 트랙 미개시", C["development_protocol"]["track_open"] is False
          and C["development_protocol"]["evaluations_spent"] == 0)
    check("V3-g 미공개 상태", C["probability_contract"]["publication_status"] == "not_published")
    check("V3-h contract_character.kind", C["contract_character"]["kind"] == "negative_result_contract")


# ── V4 판정 전재 (요약·완화 없음) ────────────────────────────────────────────
def v4_verdict() -> None:
    v, der, fa = S3["verdict"], S3["derivation"], S3["failure_analysis"]
    nr = C["negative_result"]
    pairs = [
        ("decision", nr["decision"], v["decision"]),
        ("decision_code", nr["decision_code"], v["decision_code"]),
        ("adopted_count", nr["adopted_count"], v["adopted_count"]),
        ("k_obs", nr["k_obs"], v["k_obs"]),
        ("directions_evaluated", nr["directions_evaluated"], der["directions"]),
        ("governing_branch", nr["governing_branch"], v["governing_branch"]),
        ("branches_fired", nr["branches_fired"], v["branches_fired"]),
        ("branch_precedence", nr["branch_precedence"], v["branch_precedence"]),
        ("s4_contract_mandate", nr["s4_contract_mandate"], v["s4_contract"]),
        ("s4_contract_source", nr["s4_contract_source"], v["s4_contract_source"]),
        ("T5_failed", nr["negative_control_T5"]["failed"], v["T5_failed"]),
        ("T5_threshold", nr["negative_control_T5"]["threshold"], v["T5_threshold"]),
        ("family_claim_supported", nr["permutation_null"]["family_claim_supported"],
         v["family_claim_supported"]),
        ("lower<0", nr["failure_modes"]["ci90_lower_below_zero"], fa["by_failure_mode"]["하한<0"]),
        ("lower=0", nr["failure_modes"]["ci90_lower_equal_zero_map_inert"],
         fa["by_failure_mode"]["하한=0"]),
        ("lower>0", nr["directions_with_ci90_lower_gt_0"], fa["by_failure_mode"]["하한>0"]),
        ("family_cells", nr["family_cells"], PRE["multiplicity"]["family_size"]),
        ("null_replicates", nr["permutation_null"]["replicates"],
         PRE["multiplicity"]["null"]["replicates"]),
        ("T5_limit", nr["negative_control_T5"]["interpretation_limit"],
         S3["rule"]["T5_interpretation_limit"]),
    ]
    for name, got, want in pairs:
        check(f"V4 판정 전재 · {name}", got == want, f"{got!r} vs {want!r}")
    check("V4-b T5 통과율", eq6(nr["negative_control_T5"]["pass_rate_pooled"],
                              round(v["T5_pass_rate_pooled"], 4)))
    check("V4-c k_mean", eq6(nr["permutation_null"]["k_mean_under_null"],
                             round(S3["multiplicity"]["k_mean"], 3)))
    check("V4-d T5 문구가 실측 통과율을 인용",
          f"{v['T5_pass_rate_pooled'] * 100:.1f}%" in nr["negative_control_T5"]["meaning"])


# ── V5 게이트 문턱 재유도 ────────────────────────────────────────────────────
def v5_thresholds() -> None:
    th = C["gates"]["G2_skill_vs_reflection"]["thresholds"]
    for h in HS:
        ga = S2["gate_arithmetic"][f"h{h}"]
        row = th[f"h{h}"]
        check(f"V5 기후 Brier h{h}", eq6(row["climatology_brier"], ga["climatology_brier"]))
        for name in ("reflection_2phi", "reflection_bgk"):
            key = f"vs_{name}"
            src = ga[name]
            check(f"V5 {key} 기준선 Brier h{h}",
                  eq6(row[key]["baseline_brier"], src["baseline_brier"]))
            check(f"V5 {key} MDE h{h}", eq6(row[key]["mde_1645se"], src["mde_1645se"]))
            check(f"V5 {key} 요구 Brier h{h}",
                  eq6(row[key]["required_candidate_brier_max"], src["required_candidate_brier"]))
            check(f"V5 {key} 요구 BSS h{h}",
                  eq6(row[key]["required_brier_skill_vs_climatology_min"],
                      src["required_bss_vs_climatology"]))
            # 요구 Brier = 기준선 − MDE 를 원본 값으로 재계산
            check(f"V5-b {key} 요구 Brier 산술 h{h}",
                  abs(src["required_candidate_brier"]
                      - (src["baseline_brier"] - src["mde_1645se"])) < 1e-12)
    check("V5-c 구속 기준선 = BGK",
          C["gates"]["G2_skill_vs_reflection"]["binding_baseline"] == "reflection_bgk")
    check("V5-d BGK 가 2Φ 보다 엄격 (요구 Brier 가 더 낮다)",
          all(S2["gate_arithmetic"][f"h{h}"]["reflection_bgk"]["required_candidate_brier"]
              < S2["gate_arithmetic"][f"h{h}"]["reflection_2phi"]["required_candidate_brier"]
              for h in HS))


# ── V6 도달 가능성 재계산 ────────────────────────────────────────────────────
def v6_feasibility() -> None:
    fb = C["gate_feasibility_arithmetic"]["by_horizon"]
    for h in HS:
        ga = S2["gate_arithmetic"][f"h{h}"]
        prc = ga["perfect_recalibration_ceiling"]
        cf = prc["murphy_fixed_bins"]["bss_if_rel_zero"]
        cq = prc["murphy_quantile_bins"]["bss_if_rel_zero"]
        row = fb[f"h{h}"]
        check(f"V6 상한 fixed h{h}", eq6(row["recalibration_ceiling_bss"]["fixed_bins"], cf))
        check(f"V6 상한 quantile h{h}", eq6(row["recalibration_ceiling_bss"]["quantile_bins"], cq))
        check(f"V6 상한 max h{h}", eq6(row["recalibration_ceiling_bss"]["max"],
                                      ga["ceiling_max_bss"]))
        check(f"V6-b max = 두 binning 최대 h{h}",
              abs(ga["ceiling_max_bss"] - max(cf, cq)) < 1e-12)
        for name in ("reflection_2phi", "reflection_bgk"):
            req = ga[name]["required_bss_vs_climatology"]
            got = row["verdict_by_baseline"][name]
            check(f"V6 도달 fixed h{h}/{name}",
                  got["reachable_under_fixed_bin_ceiling"] == bool(req <= cf))
            check(f"V6 도달 quantile h{h}/{name}",
                  got["reachable_under_quantile_bin_ceiling"] == bool(req <= cq))
            check(f"V6 도달 any h{h}/{name}",
                  got["reachable_under_any_binning"] == bool(req <= max(cf, cq)))
            check(f"V6 여유 h{h}/{name}",
                  eq6(got["headroom_vs_max_ceiling"], max(cf, cq) - req))
    # 계약 서술이 실제 산술과 같은 방향인지 — h21/BGK 는 도달 불가여야 한다
    check("V6-c h21 BGK 도달 불가가 실제 산술",
          fb["h21"]["verdict_by_baseline"]["reflection_bgk"]["reachable_under_any_binning"] is False)
    check("V6-d reading 이 h21 도달 불가를 말한다",
          "h21" in C["gate_feasibility_arithmetic"]["reading"]
          and "도달할 수 없다" in C["gate_feasibility_arithmetic"]["reading"])


# ── V7 CRPS 게이트 무손상 ───────────────────────────────────────────────────
def v7_crps() -> None:
    v8_dev = {k: v for k, v in V8["dev_gate_proxy"].items() if k != "revision_history"}
    got_dev = C["crps_gate_intact"]["dev_gate_proxy"]
    check("V7-a dev_gate_proxy 키 집합 동일", set(got_dev) == set(v8_dev),
          f"{sorted(set(got_dev) ^ set(v8_dev))}")
    check("V7-b dev_gate_proxy 값 동일", got_dev == v8_dev)
    check("V7-c publication_gate 동일", C["crps_gate_intact"]["publication_gate"]
          == V8["publication_gate"])
    check("V7-d operational_gate 동일", C["crps_gate_intact"]["operational_gate"]
          == V8["operational_gate"])
    check("V7-e V10 도 같은 CRPS proxy 를 쓴다 (복제 일관)",
          {k: v for k, v in V10["dev_gate_proxy"].items() if k != "revision_history"} == v8_dev)
    check("V7-f 완화 금지 조항 존재",
          C["prohibitions"]["v12_specific"]["crps_gate_threshold_relaxation"] is True)
    check("V7-g V8 계약 sha256 핀",
          C["predecessor_immutability"]["v8_contract_sha256"]
          == sha256_file(ROOT / "data/contracts/multivariate_timeseries_v8.yaml"))
    check("V7-h V8 계약 파일 무변경 (git)", "data/contracts/multivariate_timeseries_v8.yaml"
          not in _dirty_paths())


def _dirty_paths() -> set:
    import subprocess
    out = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    return {ln[3:].strip() for ln in out.splitlines() if ln.strip()}


# ── V8 실측값 대사 ──────────────────────────────────────────────────────────
def v8_measured() -> None:
    for h in HS:
        ph, rh = FT["per_horizon"][h], RB["per_horizon"][h]
        m = C["measured_state_v8_first_touch"][f"h{h}"]
        check(f"V8 n h{h}", m["n"] == ph["n"])
        check(f"V8 touches h{h}", m["touches"] == ph["touches"])
        check(f"V8 base_rate h{h}", eq6(m["base_rate"], ph["base_rate"]))
        check(f"V8 brier h{h}", eq6(m["brier_v8_first_touch"], ph["brier"]))
        check(f"V8 기후 Brier h{h}",
              eq6(m["climatology_brier_insample"], ph["climatology_brier_insample"]))
        check(f"V8 BSS h{h}", eq6(m["brier_skill_vs_insample_climatology"],
                                  ph["brier_skill_vs_insample_climatology"]))
        ec = ph["expanding_climatology"]
        check(f"V8 expanding n h{h}", m["expanding_climatology"]["eligible_n"] == ec["eligible_n"])
        check(f"V8 expanding BSS h{h}",
              eq6(m["expanding_climatology"]["brier_skill"], ec["bss_vs_expanding"]))
        for binning, src in (("quantile_bins", "murphy_quantile_bins"),
                             ("fixed_bins", "murphy_fixed_bins")):
            for field in ("reliability", "resolution", "uncertainty", "binning_residual"):
                check(f"V8 murphy {binning}.{field} h{h}",
                      eq6(m["murphy_decomposition"][binning][field], ph[src][field]))
        tq = m["top_quintile_overconfidence"]
        check(f"V8 v8_gap h{h}", eq6(tq["v8_gap"], S2["rules"]["horizons"][f"h{h}"]["v8_top_gap"]))
        check(f"V8 v8_gap 하한 h{h}",
              eq6(tq["v8_gap_ci90_lower"], S2["rules"]["R1"]["ci90_lower"][f"h{h}"]))
        check(f"V8 reflection_gap 하한 h{h}",
              eq6(tq["reflection_gap_ci90_lower"], S2["rules"]["R2"]["ci90_lower"][f"h{h}"]))
        for key, node in (("paired_v8_vs_climatology", rh["paired"]["v8_vs_climatology"]),
                          ("paired_v8_vs_reflection_2phi", rh["paired"]["v8_vs_reflection"]),
                          ("paired_v8_vs_reflection_bgk",
                           rh["variants"]["discrete_monitoring_bgk"]["paired_v8_vs_variant"])):
            check(f"V8 {key}.loss_diff h{h}", eq6(m[key]["loss_diff"], node["loss_diff"]))
            check(f"V8 {key}.ci90_lower h{h}",
                  eq6(m[key]["ci90_lower"], node["ci90"]["ci90_lower"]))
            check(f"V8 {key}.mde50 h{h}", eq6(m[key]["mde50"], node["ci90"]["mde50"]))
            check(f"V8 {key}.n h{h}", m[key]["n"] == node["n"])


# ── V9 등록부 원문 대사 ─────────────────────────────────────────────────────
def v9_prereg_quotes() -> None:
    g3 = C["gates"]["G3_bidirectional_transfer"]
    quotes = [
        ("A1 rule", g3["rule"], PRE["adoption"]["primary"]["rule"]),
        ("A1 source", g3["source"], PRE["adoption"]["primary"]["source"]),
        ("A1 frozen", g3["frozen"], PRE["adoption"]["primary"]["frozen"]),
        ("fit_objective", g3["fit_objective"], PRE["estimation_protocol"]["fit_objective"]),
        ("frozen_nuisance", g3["frozen_nuisance"], PRE["estimation_protocol"]["frozen_nuisance"]),
        ("test_statistic", g3["test_statistic"], PRE["estimation_protocol"]["test_statistic"]),
        ("MDE", C["gates"]["G5_reporting_obligations"]["mde"],
         PRE["uncertainty"]["mde_obligation"]["rule"]),
        ("concentration", C["gates"]["G5_reporting_obligations"]["concentration"],
         PRE["uncertainty"]["concentration_obligation"]["rule"]),
        ("multiplicity", C["gates"]["G5_reporting_obligations"]["multiplicity"],
         PRE["multiplicity"]["family_claim_threshold"]),
        ("A2 rationale", C["gates"]["G2_skill_vs_reflection"]["rationale"],
         PRE["adoption"]["secondary"]["rationale"]),
        ("derived_layer", C["probability_contract"]["derived_layer_constraint"],
         PRE["target"]["derived_layer_constraint"]),
        ("split frozen", C["target"]["split"]["frozen"], PRE["split"]["frozen"]),
        ("y", C["target"]["y"], PRE["target"]["y"]),
        ("p", C["target"]["p"], PRE["target"]["p"]),
    ]
    for name, got, want in quotes:
        check(f"V9 등록부 원문 · {name}", got == want, f"{got!r}")
    check("V9-b 부트스트랩 상수", (g3["uncertainty"]["block_length"],
                              g3["uncertainty"]["replicates"], g3["uncertainty"]["seed"])
          == (PRE["uncertainty"]["bootstrap"]["block_length"],
              PRE["uncertainty"]["bootstrap"]["replicates"],
              PRE["uncertainty"]["bootstrap"]["seed"]))
    check("V9-c run 핀", C["target"]["sample"]["run_sha256"] == PRE["target"]["run_sha256"])
    check("V9-d 원점수·창", (C["target"]["sample"]["n_origins"], C["target"]["sample"]["window"])
          == (PRE["target"]["n_origins"], PRE["target"]["window"]))
    check("V9-e 분할", (C["target"]["split"]["boundary"], C["target"]["split"]["early_n"],
                      C["target"]["split"]["late_n"])
          == (PRE["split"]["boundary"], PRE["split"]["early"]["n_expected"],
              PRE["split"]["late"]["n_expected"]))


# ── V10 금지 서술 스캔 ──────────────────────────────────────────────────────
def v10_banned() -> None:
    mod = load_generator()
    violations, exempted = mod.scan_banned(TEXT)
    check("V10-a 금지 서술이 부정문 밖에 0건", violations == [], f"{violations}")
    check("V10-b 면제는 전부 부정·금지문", all(
        any(m in e["text"] for m in mod.NEGATION_MARKERS) for e in exempted),
          f"면제 {len(exempted)}건 공시")
    # 되살리기 조항이 실제로 본문에 있는가
    check("V10-c C-S4-contract 조항 존재",
          "C-S4-contract" in C["negative_result"]["carryover_clauses_from_s3"])
    check("V10-d 되살리기 금지 조항",
          C["prohibitions"]["v12_specific"]["revive_negative_result_as_conditional_pass"] is True)


# ── V11 정지점·금지 승계 ────────────────────────────────────────────────────
def v11_stops() -> None:
    sp = C["stopping_points"]
    check("V11-a 정지점 2", sp["count"] == 2)
    check("V11-b 홀드아웃 창 = V8", sp["holdout"]["window"]
          == [str(x) for x in V8["model"]["windows"]["holdout"]])
    check("V11-c 봉인 창 = V8", sp["sealed"]["window"]
          == [str(x) for x in V8["model"]["windows"]["sealed"]])
    check("V11-d 봉인 공개 상한 = V8", sp["sealed"]["maximum_disclosures_per_model_version"]
          == V8["model"]["sealed_evaluation"]["maximum_disclosures_per_model_version"])
    check("V11-e retune 금지 = V8", sp["sealed"]["retune_after_failure"]
          == V8["model"]["sealed_evaluation"]["retune_after_failure"] == "prohibited")
    check("V11-f 승인 필수", sp["holdout"]["requires_explicit_user_approval"] is True
          and sp["sealed"]["requires_explicit_user_signoff"] is True)
    check("V11-g 루프 실행 기록 전부 0",
          all(v == 0 for v in sp["loop_execution_record"].values()),
          f"{sp['loop_execution_record']}")
    inh = C["prohibitions"]["inherited_from_v8_and_v10"]
    missing = (set(V8["prohibitions"]) | set(V10["prohibitions"])) - set(inh)
    check("V11-h V8·V10 금지 키 승계 누락 0", not missing, f"missing={sorted(missing)}")
    check("V11-i 승계 값 전부 true", all(v is True for v in inh.values()))
    check("V11-j retune 금지 3종", all(inh[k] is True for k in
                                    ("retune_v2", "retune_v8", "mutate_v8")))


# ── V12 홀드아웃 무접촉 ─────────────────────────────────────────────────────
def _walk_strings(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def v12_holdout() -> None:
    # 원문 줄 스캔은 YAML 블록 시퀀스에서 맥락(키)이 앞줄로 밀려 오판한다.
    # 그래서 파싱된 구조를 경로째 걷는다 — 2015+ 연도가 어디에 실렸는지가 판정 대상.
    # 2015~2025 = 설계창(~2014) 밖의 데이터 시대. 루프 자신의 집필 시각(2026)은 데이터
    # 주장이 아니므로 범위에서 빼고, 대신 V12-a3 이 2026 문자열의 경로를 따로 못박는다.
    year = re.compile(r"\b20(1[5-9]|2[0-5])\b")
    window_paths = ("stopping_points.holdout.window", "stopping_points.sealed.window")
    ok_words = ("미소모", "미계산", "미실행", "latest", "홀드아웃을 열지", "봉인 실행 0회")
    bad = []
    for path, value in _walk_strings(C):
        if not year.search(value):
            continue
        if path.startswith(window_paths):
            continue
        if any(w in value for w in ok_words):
            continue
        bad.append((path, value[:80]))
    check("V12-a 2015+ 언급은 정지점 창 또는 미소모·미계산 서술뿐", not bad, f"{bad[:3]}")
    check("V12-a2 홀드아웃/봉인 창이 정확히 그 경로에만",
          all(any(year.search(x) for x in C["stopping_points"][k]["window"])
              for k in ("holdout", "sealed")))
    authorship = ("drafted_during.", "provenance.prereg_committed_kst",
                  "predecessor_immutability.v8_frozen_on", "provenance.design_doc",
                  "contract_character.authority_order")
    stray = [(p, v[:60]) for p, v in _walk_strings(C)
             if "2026" in v and not p.startswith(authorship)]
    check("V12-a3 2026 문자열은 집필 시각·문서명 경로에만", not stray, f"{stray[:3]}")
    check("V12-b 홀드아웃 미소모 명시", "미소모" in C["stopping_points"]["holdout"]["current_state"])
    check("V12-c C-holdout 조항", "C-holdout" in C["negative_result"]["carryover_clauses_from_s3"])
    # 이 태스크가 홀드아웃 산출물을 만들지 않았는지
    hold = list((ROOT / "data/timeseries_v12").rglob("*holdout*"))
    check("V12-d 홀드아웃 산출물 0", not hold, f"{[p.name for p in hold]}")


# ── V13 결정론 재생성 ───────────────────────────────────────────────────────
def v13_deterministic() -> None:
    mod = load_generator()
    regenerated = mod.render(mod.build())
    check("V13-a 생성기 재실행 바이트 동일", regenerated == TEXT,
          f"len {len(regenerated)} vs {len(TEXT)}")
    check("V13-b 계약이 유효 YAML", isinstance(yaml.safe_load(regenerated), dict))


# ── V14 MDE 규약 공시 ───────────────────────────────────────────────────────
def v14_mde() -> None:
    mc = C["mde_convention"]["worked_example_h21_reflection_2phi"]
    se = RB["per_horizon"]["21"]["paired"]["v8_vs_reflection"]["ci90"]["bootstrap_se"]
    diag = RB["per_horizon"]["21"]["paired"]["v8_vs_reflection"]["ci90"]["mde50"]
    gate = S2["gate_arithmetic"]["h21"]["reflection_2phi"]["mde_1645se"]
    check("V14-a 진단 MDE = 1.645·se", abs(diag - 1.645 * se) < 1e-12)
    check("V14-b 게이트 MDE 승수 ≠ 1.645", abs(gate / se - 1.645) > 1e-9)
    check("V14-c 게이트 승수 = z(0.95)", abs(gate / se - 1.6448536269514722) < 1e-9)
    check("V14-d 차이 계량 일치", abs(mc["absolute_difference"] - round(abs(diag - gate), 9)) < 1e-12)
    check("V14-e 차이가 6째 자리 이하", abs(diag - gate) < 1e-6)
    check("V14-f 한계 대장에 등재",
          any("mde_convention" in s for s in C["known_limits"]))


# ── V15 accept 대사 ─────────────────────────────────────────────────────────
def v15_accept() -> None:
    check("V15-a 계약 파일 존재", CONTRACT.is_file())
    check("V15-b 파일명이 spec 과 일치",
          CONTRACT.name == "multivariate_timeseries_v12.draft.yaml")
    check("V15-c contract_id/version", C["contract_id"] == "multivariate_timeseries_v12"
          and C["model_version"] == 12)
    required = ["target", "gates", "crps_gate_intact", "stopping_points", "prohibitions",
                "negative_result", "reopen_protocol"]
    check("V15-d spec 요구 절 전부 존재", all(k in C for k in required),
          f"{[k for k in required if k not in C]}")
    check("V15-e 표적이 first_touch h21/h63", C["target"]["horizons_sessions"] == [21, 63]
          and "first_touch" in C["target"]["event"])
    gate_ids = [k for k in C["gates"] if re.match(r"^G\d_", k)]
    check("V15-f 게이트 5종 이상 등록", len(gate_ids) >= 5, f"{gate_ids}")


def main() -> int:
    for fn in (v1_seal, v2_inputs, v3_character, v4_verdict, v5_thresholds, v6_feasibility,
               v7_crps, v8_measured, v9_prereg_quotes, v10_banned, v11_stops, v12_holdout,
               v13_deterministic, v14_mde, v15_accept):
        fn()
    failed = [(cid, d) for cid, ok, d in RESULTS if not ok]
    for cid, ok, d in RESULTS:
        if not ok:
            print(f"FAIL  {cid}  {d}")
    print(json.dumps({
        "checks_total": len(RESULTS),
        "checks_failed": len(failed),
        "contract_sha256": sha256_file(CONTRACT),
        "failed_ids": [c for c, _ in failed],
    }, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
