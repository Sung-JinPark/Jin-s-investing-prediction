#!/usr/bin/env python
"""tools/v12_prereg_check.py — S3-0 사전등록 파일의 기계 검증 (읽기 전용, 파일 미기록).

사전등록의 가치는 "결과를 본 뒤 바뀌지 않았다" 는 것 하나다. 그래서 사람의 서술을 믿지 않고
아래 아홉 가지를 기계로 대사한다.

  C1 스키마      — 필수 최상위 키·필수 하위 키 존재, JSON 파싱 성공
  C2 설계도 대사 — 각 가설의 design_literal·prior_expectation_design 이 설계도 §2 표의
                   바이트 부분문자열인지. (등록부가 원문에서 표류하면 여기서 걸린다)
  C3 상수 대사   — ℓ=13·B=2000·seed=20260902·분할 2010-12-31·EWMA λ=0.97 이
                   tools 모듈의 실제 상수와 일치하는지
  C4 심볼 존재   — S3-1 이 호출할 함수가 실제로 존재하는지 (등록만 하고 못 돌리면 무의미)
  C5 데이터 사실 — 417 원점·209/208 분할·창 경계·지평 집합이 run 과 일치하는지
  C6 입력 해시   — S2-1/S2-2/S2-3 산출물 sha256 이 등록된 값과 일치하는지
  C7 무결과 증명 — p′ 를 만드는 코드가 저장소에 아직 없는지 (사전등록의 핵심 주장)
  C8 금지 필드   — 등록부에 결과성 수치 필드(delta·ci90·pass·적합값)가 섞여 있지 않은지
  C9 해시        — 사전등록 파일 자체의 sha256 (커밋 로그 앵커)

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_prereg_check.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

PREREG = ROOT / "data/timeseries_v12/prereg/hypotheses.json"
DESIGN = ROOT / "docs/design/V12_EVENT_TRACK_SUNDAY_OPUS_LOOP_DESIGN_260904.md"

REQUIRED_TOP = [
    "schema", "task_id", "authority", "results_seen", "results_seen_statement",
    "target", "holdout", "split", "estimation_protocol", "uncertainty",
    "adoption", "multiplicity", "hypotheses", "prohibitions",
    "reporting_contract", "pre_committed_interpretation", "inputs_anchored",
]

# C8 — 등록부에 있으면 "결과를 이미 봤다" 는 뜻이 되는 키 이름.
FORBIDDEN_KEYS = {
    "delta", "delta_obs", "ci90_lower", "ci90_upper", "bootstrap_se",
    "lambda_hat", "w_hat", "lambda_star", "brier_p_prime", "a1_pass", "a2_pass",
    "k_obs", "p_value", "pass_rate", "adopted_cells", "transfer_results",
}
# 위 이름이 "무엇을 보고할지" 목록 안에서 문자열로 등장하는 것은 허용된다 (계약이므로).
# 금지되는 것은 그 이름이 **키**로 쓰이면서 수치를 담는 경우다.

# C7 — p′ 를 만드는 코드의 지문. 하나라도 걸리면 "결과 보기 전" 주장이 깨진다.
#
# 주석·문자열은 제외하고 **실행되는 토큰**만 스캔한다. S2 산출물은 산문으로 "T3 의 w 탐색은
# S3-1 소관(미계산)" 이라고 적어 두었고, 그런 문장이 검사를 걸어 넘어뜨리면 검사가 주장하는 것
# (p′ 를 만드는 코드의 부재)과 검사하는 것(글자 'p′' 의 부재)이 어긋난다. 산문은 C7-b 로 따로 센다.
PRIME_CODE_PATTERNS = [
    r"\bp_prime\b", r"\bp_recal\b", r"\bfirst_touch_recal\w*", r"\bshrink_map\b",
    r"\bfit_lambda\b", r"\bfit_w\b", r"\btransfer_cell\b",
    r"1 - w \) \* p", r"p - lam\w* \* \( p -",
]
PRIME_PROSE_PATTERNS = [r"p′", r"p_prime"]
PRIME_SCAN_DIRS = ["tools", "src"]
PRIME_SCAN_EXEMPT = {"tools/v12_prereg_check.py"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Checks:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def add(self, cid: str, ok: bool, detail: str) -> None:
        self.rows.append((cid, bool(ok), detail))

    @property
    def failed(self) -> int:
        return sum(0 if ok else 1 for _, ok, _ in self.rows)


def c1_schema(reg: dict, ck: Checks) -> None:
    missing = [k for k in REQUIRED_TOP if k not in reg]
    ck.add("C1-a", not missing, f"필수 최상위 키 {len(REQUIRED_TOP)}개 — 누락 {missing or '없음'}")
    ck.add("C1-b", reg.get("schema") == "v12_s3_prereg_v1", f"schema={reg.get('schema')!r}")
    ck.add("C1-c", reg.get("task_id") == "S3-0", f"task_id={reg.get('task_id')!r}")
    ck.add("C1-d", reg.get("results_seen") is False, f"results_seen={reg.get('results_seen')!r}")

    ids = [h["id"] for h in reg["hypotheses"]]
    ck.add("C1-e", ids == ["T1", "T2", "T3", "T4", "T5"], f"가설 id 순서 {ids}")
    eligible = [h["id"] for h in reg["hypotheses"] if h["adoption_eligible"]]
    ck.add("C1-f", eligible == ["T1", "T2", "T3", "T4"],
           f"채택 대상 {eligible} (T5 는 음성대조라 제외)")

    fam = reg["multiplicity"]["family_size"]
    ck.add("C1-g", fam == len(eligible) * len(reg["target"]["horizons"]),
           f"family_size={fam} = 채택가설 {len(eligible)} × 지평 {len(reg['target']['horizons'])}")

    per_cell = reg["reporting_contract"]["mandatory_fields_per_cell"]
    need = {"delta", "ci90_lower", "mde_1645se", "A1_pass", "A2_pass",
            "sign_after_top5pct_drop", "delta_vs_reflection"}
    ck.add("C1-h", need <= set(per_cell), f"셀 보고 의무 필드 {len(per_cell)}개, 핵심 누락 {sorted(need - set(per_cell)) or '없음'}")


def c2_design(reg: dict, ck: Checks) -> None:
    text = DESIGN.read_text(encoding="utf-8")
    for h in reg["hypotheses"]:
        lit = h["design_literal"]
        ck.add(f"C2-{h['id']}-식", lit in text, f"design_literal 바이트 일치: {lit[:46]}…")
        exp = h.get("prior_expectation_design")
        ck.add(f"C2-{h['id']}-기대", isinstance(exp, str) and exp in text,
               f"prior_expectation_design 바이트 일치: {exp!r}")
    # 공통 규약 문장 자체도 원문에 있는지
    for probe in ["stationary block bootstrap(ℓ=13, B=2000) CI90 + 순열 귀무 1000회",
                  "채택 = 양방향 모두 CI90 하한 > 0",
                  "사후 가설 추가 금지"]:
        ck.add("C2-공통", probe in text, f"설계도 원문 확인: {probe[:44]}…")
    # 원문에 없는 가설을 발명하지 않았는가 — §2 표의 ID 집합과 대조
    table_ids = re.findall(r"^\|\s*(T\d)", text, flags=re.M)
    ck.add("C2-집합", sorted(set(table_ids)) == ["T1", "T2", "T3", "T4", "T5"],
           f"설계도 §2 표의 가설 ID = {sorted(set(table_ids))}")


def c3_constants(reg: dict, ck: Checks) -> None:
    import v12_first_touch_diag as ft
    import v12_reflect_baseline as rb

    boot = reg["uncertainty"]["bootstrap"]
    ck.add("C3-a", boot["block_length"] == ft.BLOCK, f"ℓ: 등록 {boot['block_length']} vs 코드 {ft.BLOCK}")
    ck.add("C3-b", boot["replicates"] == ft.REPLICATES, f"B: 등록 {boot['replicates']} vs 코드 {ft.REPLICATES}")
    ck.add("C3-c", boot["seed"] == ft.SEED, f"seed: 등록 {boot['seed']} vs 코드 {ft.SEED}")
    ck.add("C3-d", reg["split"]["boundary"] == ft.S3_SPLIT[0],
           f"분할: 등록 {reg['split']['boundary']} vs 코드 {ft.S3_SPLIT[0]}")

    t3 = next(h for h in reg["hypotheses"] if h["id"] == "T3")
    ck.add("C3-e", "0.97" in t3["p_reflect_spec"]["sigma"] and rb.LAMBDA == 0.97,
           f"EWMA λ: 등록 0.97 vs 코드 {rb.LAMBDA}")
    ck.add("C3-f", abs(rb.LOG_BARRIER - float(np.log(0.90))) < 1e-15,
           f"장벽 ln(0.90): 코드 {rb.LOG_BARRIER:.12f}")

    grid = reg["estimation_protocol"]["grid"]
    ck.add("C3-g", grid["support"] == [0.0, 1.0] and abs(grid["step"] - 0.01) < 1e-12
           and grid["points"] == 101, f"그리드 {grid['support']} step {grid['step']} → {grid['points']}점")
    ck.add("C3-h", reg["multiplicity"]["null"]["replicates"] == 1000,
           f"순열 {reg['multiplicity']['null']['replicates']}회 (설계도 문자)")

    t1 = next(h for h in reg["hypotheses"] if h["id"] == "T1")
    ck.add("C3-i", "80" in t1["fixed_from_training_window"]["tau"], "τ = 학습창 80분위 고정")
    counts = {h["id"]: len(h.get("free_parameters", {})) for h in reg["hypotheses"]}
    ck.add("C3-j", counts["T1"] == 1 and counts["T2"] == 1 and counts["T3"] == 1 and counts["T4"] == 0,
           f"자유도 {counts} — 설계도 표(1/1/1/0)와 일치")


def c4_symbols(ck: Checks) -> None:
    import v12_first_touch_diag as ft
    import v12_reflect_baseline as rb

    for mod, name in [(ft, "load_first_touch"), (ft, "block_index_draws"), (ft, "ci90"),
                      (ft, "brier"), (ft, "S3_SPLIT"), (rb, "sigma_at_origins"),
                      (rb, "p_reflect"), (rb, "load_returns"), (rb, "LAMBDA"), (rb, "LOG_BARRIER")]:
        ck.add("C4", hasattr(mod, name), f"{mod.__name__}::{name} 존재")


def c5_data(reg: dict, ck: Checks) -> dict:
    import v12_first_touch_diag as ft

    data = ft.load_first_touch()
    tgt = reg["target"]
    ck.add("C5-a", data["experiment_label"] == tgt["experiment_label"],
           f"run label {data['experiment_label']}")
    ck.add("C5-b", data["run_path"] == tgt["run_path"], f"run path {data['run_path']}")
    ck.add("C5-c", data["run_sha256"] == tgt["run_sha256"],
           f"run sha256 {data['run_sha256'][:16]}… = 등록 {str(tgt['run_sha256'])[:16]}…")

    facts: dict = {"run_sha256": data["run_sha256"], "per_horizon": {}}
    boundary = reg["split"]["boundary"]
    for h in tgt["horizons"]:
        blk = data["per_horizon"][int(h)]
        dates = blk["dates"]
        n = len(dates)
        early = sum(1 for d in dates if d <= boundary)
        late = n - early
        gaps = np.diff(np.array([np.datetime64(d) for d in dates]).astype("datetime64[D]").astype(int))
        facts["per_horizon"][f"h{h}"] = {
            "n": n, "early": early, "late": late,
            "first": dates[0], "last": dates[-1],
            "median_gap_days": float(np.median(gaps)),
            "touch_rate": float(blk["y"].mean()),
            "p_min": float(blk["p"].min()), "p_max": float(blk["p"].max()),
        }
        ck.add(f"C5-h{h}-n", n == tgt["n_origins"], f"원점 {n} = 등록 {tgt['n_origins']}")
        ck.add(f"C5-h{h}-분할", early == reg["split"]["early"]["n_expected"]
               and late == reg["split"]["late"]["n_expected"],
               f"전반 {early} / 후반 {late} = 등록 {reg['split']['early']['n_expected']}/{reg['split']['late']['n_expected']}")
        ck.add(f"C5-h{h}-창", [dates[0], dates[-1]] == tgt["window"],
               f"창 [{dates[0]}, {dates[-1]}] = 등록 {tgt['window']}")

    # T4 의 지평 교집합이 실제로 존재하는지 (등록만 하고 정의 불가면 곤란)
    d21 = set(data["per_horizon"][21]["dates"])
    d63 = set(data["per_horizon"][63]["dates"])
    facts["h21_h63_intersection"] = len(d21 & d63)
    ck.add("C5-T4", len(d21 & d63) == tgt["n_origins"],
           f"h21∩h63 원점 {len(d21 & d63)} — T4 정의 가능")

    # 2015+ 원점이 표본에 섞여 있지 않은지 (홀드아웃 보존의 기계 확인)
    beyond = [d for d in data["per_horizon"][21]["dates"] if d >= "2015-01-01"]
    ck.add("C5-홀드아웃", not beyond, f"2015+ 원점 {len(beyond)}건 (0이어야 함)")
    return facts


def c6_inputs(reg: dict, ck: Checks) -> None:
    for rel, expect in reg["inputs_anchored"].items():
        if not rel.endswith(".json"):
            continue
        path = ROOT / rel
        got = sha256(path) if path.exists() else "<없음>"
        ck.add("C6", got == expect, f"{rel} sha256 {got[:16]}… = 등록 {expect[:16]}…")


def _code_only(body: str) -> str:
    """주석·문자열·독스트링을 버리고 실행 토큰만 공백으로 이어 붙인다."""
    import io
    import tokenize

    keep = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(body).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                            tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                continue
            if tok.string.strip():
                keep.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return body          # 토큰화 실패 시 원문으로 — 놓치느니 과탐지
    return " ".join(keep)


def c7_no_prime_code(ck: Checks) -> None:
    code_hits: list[str] = []
    prose_hits: list[str] = []
    scanned = 0
    for d in PRIME_SCAN_DIRS:
        for path in sorted((ROOT / d).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel in PRIME_SCAN_EXEMPT:
                continue
            scanned += 1
            body = path.read_text(encoding="utf-8", errors="replace")
            code = _code_only(body)
            for pat in PRIME_CODE_PATTERNS:
                if re.search(pat, code):
                    code_hits.append(f"{rel} ~ /{pat}/")
            for i, line in enumerate(body.splitlines(), 1):
                if any(re.search(p, line) for p in PRIME_PROSE_PATTERNS):
                    prose_hits.append(f"{rel}:{i}")

    ck.add("C7-a", not code_hits,
           f"실행 토큰에서 p′ 생성 지문 {len(code_hits)}건 / {scanned}파일"
           + (f" — {code_hits[:4]}" if code_hits else " (0 = 결과 보기 전 확정)"))
    ck.add("C7-b", True,
           f"산문 언급 {len(prose_hits)}건(정보) — {prose_hits or '없음'}")


def c8_forbidden(reg: dict, ck: Checks) -> None:
    offenders: list[str] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                here = f"{path}.{k}"
                if k.lower() in FORBIDDEN_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                    offenders.append(f"{here}={v}")
                walk(v, here)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(reg, "$")
    ck.add("C8-a", not offenders, f"결과성 수치 필드 {len(offenders)}건" + (f" — {offenders[:4]}" if offenders else ""))

    # power_notice 는 '표본의 성질'만 담아야 한다 — Brier·Δ·CI 수치가 있으면 오염
    pn = json.dumps(reg.get("power_notice_inherited", {}), ensure_ascii=False)
    bad = [w for w in ("ci90", "delta", "brier_", "skill") if w in pn.lower()]
    ck.add("C8-b", not bad, f"power_notice 안의 결과 어휘 {bad or '없음'} (표본 성질만 허용)")

    # 채택 규칙 문자열이 §2 원문 그대로인지 (완화 방지)
    ck.add("C8-c", reg["adoption"]["primary"]["rule"].count("모두") >= 1
           and "CI90 하한 > 0" in reg["adoption"]["primary"]["rule"],
           "1차 채택 규칙에 '양방향 모두 · CI90 하한 > 0' 유지")


def main() -> int:
    ck = Checks()
    raw = PREREG.read_bytes()
    reg = json.loads(raw.decode("utf-8"))

    c1_schema(reg, ck)
    c2_design(reg, ck)
    c3_constants(reg, ck)
    c4_symbols(ck)
    facts = c5_data(reg, ck)
    c6_inputs(reg, ck)
    c7_no_prime_code(ck)
    c8_forbidden(reg, ck)

    digest = hashlib.sha256(raw).hexdigest()
    for cid, ok, detail in ck.rows:
        print(f"{'PASS' if ok else 'FAIL'} {cid:14s} {detail}")
    print()
    print(f"검사 {len(ck.rows)}항목 · 실패 {ck.failed}")
    print(f"C9 prereg sha256 = {digest}")
    print(f"C9 prereg bytes  = {len(raw)}")
    print("표본 사실(참고, 등록부 미기재): " + json.dumps(facts, ensure_ascii=False))
    return 1 if ck.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
