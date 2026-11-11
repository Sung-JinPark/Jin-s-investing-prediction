"""닷컴 대비 과열도 v6 — 그림자 검증: 편입 시험·게이트 판정·v5 대조를 한 원장 스냅샷에서 재현한다.

읽기 전용이다(원천 호출 없음, 원장·스냅샷 무수정). 쓰는 것은 검토 산출물뿐이다:
  * ``--report`` 로 준 Markdown 보고서와 같은 이름의 JSON
  * ``--write-frozen`` 을 주면 그 계약 파일 끝의 ``frozen`` 블록(편입·기준값·가중·판정)

판정 기준일(``--as-of``)을 고정해 '오늘' 기준 게이트(V9~V12)가 실행 날짜에 따라 달라지지 않게 한다.

    python tools/verify_overheat_v6_shadow.py --contract data/contracts/dotcom_overheat_index_v6.yaml \
        --as-of 2026-11-09 --report docs/audit/overheat_v6_0_validation_20261111.md --write-frozen
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc import dotcom_overheat_v6 as v6  # noqa: E402

PROTECTED = (
    "data/statistics/official_store/ledgers/normalized_observations.jsonl",
    "data/statistics/dotcom_statistics_latest.json",
    "data/statistics/ipo/ritter_ipoall_monthly.json",
    "data/contracts/dotcom_overheat_index_v5.yaml",
)
KEY_DATES = ("1996-12-31", "1998-12-31", "1999-12-31", "2000-03-10", "2000-03-31", "2002-10-09", "2007-10-31",
             "2009-03-09", "2011-02-28", "2021-02-08", "2021-11-19", "2022-12-28", "2025-12-31")
FROZEN_MARKER = "\nfrozen:"


def file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def protected_digests(root: Path) -> dict[str, str | None]:
    return {relative: file_digest(root / relative) for relative in PROTECTED}


def input_digest(inp: v6.Inputs, as_of: date) -> str:
    """판정에 쓴 입력의 지문 — 기준일까지의 NASDAQ 종가와 월·분기·Ritter 행 전체."""
    last = inp.session_index(as_of)
    body = {
        "nasdaq": [[d.isoformat(), v] for d, v in zip(inp.sessions[:last + 1], inp.close[:last + 1])],
        "series": {sid: [[a.isoformat(), v] for a, _, v in rows] for sid, rows in sorted(inp.series.items())},
        "ritter": {m: inp.ritter[m] for m in inp.ritter_months},
    }
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(root: Path, contract_relative: Path, as_of: date) -> dict[str, Any]:
    before = protected_digests(root)
    contract = v6.load_contract(root, contract_relative)
    inp = v6.load_inputs(root)
    registered = contract.get("frozen") or {}
    computed = v6.admission(inp, contract)
    contract["frozen"] = computed
    cache: dict[Any, Any] = {}
    history = v6.replay(inp, contract, end=as_of, cache=cache)
    gates = v6.evaluate_gates(inp, contract, history, cache)
    today = v6.evaluate(inp, contract, history[-1]["index"], cache=cache, detail=True)

    from ai_fc.dotcom_overheat import compute_index as v5_index

    v5 = v5_index(root)
    rows = []
    for family, ids in today["setup"]["members"].items():
        for key in ids:
            if key not in today["scores"]:
                continue
            rows.append({"family": family, "id": key, "score": round(today["scores"][key], 1),
                         "weight": round(today["indicator_weights"][key], 2),
                         "contribution": round(today["contributions"][key], 2),
                         "period": today["rows"][key]["period"], "basis": today["rows"][key]["basis"]})
    gates["construction_checks"]["C5"] = {
        "value": {"v5": v5.get("index"), "v6": None if today["composite"] is None else round(today["composite"], 1)},
        "passed": today["composite"] is not None and v5.get("status") == "ok",
    }
    key_values = {d: (None if (v := v6._value_on(history, date.fromisoformat(d))) is None else round(v, 1))
                  for d in KEY_DATES}
    key_values[as_of.isoformat()] = None if today["composite"] is None else round(today["composite"], 1)
    after = protected_digests(root)
    verdict = "passed" if gates["all_falsifiable_passed"] and gates["construction_c1_c4_passed"] else "failed"
    same_as_registered = None
    if registered.get("members"):
        same_as_registered = {
            "members": registered.get("members") == computed["members"],
            "weights": registered.get("weights") == computed["weights"],
            "anchors": all(
                abs(float(registered["anchors"][k][f]) - float(computed["anchors"][k][f]))
                <= 1e-6 * max(1.0, abs(float(computed["anchors"][k][f])))
                for k in computed["anchors"] if k in (registered.get("anchors") or {}) for f in ("zero", "peak")),
        }
    return {
        "contract": str(contract_relative).replace("\\", "/"),
        "contract_id": contract["contract_id"], "contract_version": contract["version"],
        "rules_fixed_at": contract.get("rules_fixed_at"),
        "gate_as_of": as_of.isoformat(), "ledger_through": inp.sessions[-1].isoformat(),
        "input_sha256": input_digest(inp, as_of),
        "admission": computed, "gates": gates, "verdict": verdict,
        "latest_rows": rows, "families_today": {k: round(v, 1) for k, v in today["families"].items()},
        "effective_weights": {k: round(v, 2) for k, v in (today.get("effective_weights") or {}).items()},
        "key_values": key_values, "v5": {"status": v5.get("status"), "index": v5.get("index")},
        "frozen_matches_recomputation": same_as_registered,
        "protected_unchanged": before == after, "protected_sha256": after,
    }


def frozen_block(report: dict[str, Any], stamp: str) -> dict[str, Any]:
    gates = report["gates"]
    return {
        **report["admission"],
        "frozen_at": stamp, "gate_as_of": report["gate_as_of"], "input_sha256": report["input_sha256"],
        "verdict": report["verdict"], "failed_gates": gates["failed"],
        "gate_values": {k: g.get("value") for k, g in gates["falsifiable"].items()},
        "construction_values": {k: c.get("value") for k, c in gates["construction_checks"].items()},
    }


def write_frozen(path: Path, block: dict[str, Any]) -> None:
    text = path.read_text(encoding="utf-8")
    cut = text.rfind(FROZEN_MARKER)
    if cut < 0:
        raise SystemExit(f"{path}: no trailing 'frozen:' block to replace")
    head = text[:cut].rstrip("\n") + "\n\n"
    body = yaml.safe_dump({"frozen": block}, allow_unicode=True, sort_keys=False, width=110)
    path.write_bytes((head + body).encode("utf-8"))


def _mark(passed: Any) -> str:
    return "—" if passed is None else ("통과" if passed else "실패")


def markdown(report: dict[str, Any], rules: dict[str, str]) -> str:
    adm, gates = report["admission"], report["gates"]
    lines = [
        f"# 닷컴 대비 과열도 {report['contract_id'].replace('dotcom_overheat_index_', '')} 그림자 검증",
        "",
        f"- 계약: `{report['contract']}` (판 `{report['contract_version']}`, 규칙 고정 {report['rules_fixed_at']})",
        f"- 판정 기준일: {report['gate_as_of']} · 원장 최신 거래일 {report['ledger_through']}",
        f"- 입력 지문(sha256): `{report['input_sha256']}`",
        f"- **판정: {'통과' if report['verdict'] == 'passed' else '탈락'}**"
        + ("" if not gates["failed"] else f" — 실패 게이트 {', '.join(gates['failed'])}"),
        f"- 보호 경로 무변경: {'예' if report['protected_unchanged'] else '아니오'}",
        "",
        "참고 지표다. 확률이 아니며 매매 신호가 아니다. 과거 구간은 최신 개정 자료에 고정 발표 지연을 적용한 소급 재계산이다.",
        "",
        "## 편입 시험",
        "",
        "| 지표 | A3 (D≥2) | A4 저점 3곳 ≤50 | A4 월말 최고 ≤80 | A5 p95 ≤25 | A6 | 편입 |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, row in adm["tests"].items():
        if "A3" not in row:
            lines.append(f"| {key} | — | — | — | — | — | 탈락({row.get('reason')}) |")
            continue
        a6 = row.get("A6")
        a6_text = "—" if not a6 else f"{a6.get('mae_estimate')} / {a6.get('mae_carry')} {_mark(a6.get('passed'))}"
        a5 = row["A5"]
        a5_text = "일간" if "p95_step" not in a5 else f"{a5['p95_step']} {_mark(a5['passed'])}"
        lines.append(
            f"| {key} | {row['A3']['D']} {_mark(row['A3']['passed'])} | {row['A4']['bear_lows']} | "
            f"{row['A4']['max_2001_2022']} {_mark(row['A4']['passed'])} | {a5_text} | {a6_text} | "
            f"{'편입' if row['admitted'] else '탈락'} |")
    lines += ["", "편입 결과: " + "; ".join(f"{f} = {', '.join(ids) or '없음'}" for f, ids in adm["members"].items()),
              "", "부문 가중: " + ", ".join(f"{f} {w}" for f, w in adm["weights"].items()),
              "", "## 구성 확인 (정의상 성립 — 검증이 아니다)", "", "| 항목 | 규칙 | 값 | 결과 |", "|---|---|---|---|"]
    for key, row in gates["construction_checks"].items():
        lines.append(f"| {key} | {rules.get(key, '')} | {row.get('value')} | {_mark(row.get('passed'))} |")
    lines += ["", "## 게이트 (틀릴 수 있는 검증 — 임계값은 v6.0 등록값 그대로)", "",
              "| 게이트 | 규칙 | 값 | 결과 |", "|---|---|---|---|"]
    for key, row in gates["falsifiable"].items():
        note = " (해당 없음 — 대상 0개)" if row.get("not_applicable") else ""
        reason = f" · {row['reason']}" if row.get("reason") else ""
        lines.append(f"| {key} | {rules.get(key, '')} | {row.get('value')}{reason} | {_mark(row.get('passed'))}{note} |")
    band = gates["band_today"]
    lines += ["", "## 기준일의 값", "",
              f"- 지수 {report['key_values'][report['gate_as_of']]} · 가정 범위 "
              f"{None if band['lo'] is None else round(band['lo'], 1)} ({band.get('lo_variant')}) ~ "
              f"{None if band['hi'] is None else round(band['hi'], 1)} ({band.get('hi_variant')})"
              f" · 본 사양과 다른 변형 {band.get('distinct_from_base')}개 / {len(band['variants']) - 1}개",
              f"- v5(현재 대표값) {report['v5']['index']}",
              "", "| 부문 | 지표 | 점수 | 가중 | 기여 | 기간 | 근거 |", "|---|---|---|---|---|---|---|"]
    for row in report["latest_rows"]:
        lines.append(f"| {row['family']} | {row['id']} | {row['score']} | {row['weight']} | {row['contribution']} | "
                     f"{row['period']} | {row['basis']} |")
    lines += ["", "변형별 값: " + ", ".join(f"{k} {v}" for k, v in band["variants"].items()),
              "", "## 주요 시점 (당시 화면 재현)", "", "| 날짜 | 지수 |", "|---|---|"]
    lines += [f"| {d} | {v} |" for d, v in report["key_values"].items()]
    reported = gates["reported_not_gated"]
    lines += ["", "## 게이트가 아닌 공시 수치", "",
              f"- 일간 지수 변화의 NASDAQ 수익률 R²: 최근 252거래일 {reported['daily_r2_last_252']}, 전체 {reported['daily_r2_all']}"
              f" · 월간 {reported['monthly_r2']}",
              f"- NASDAQ 가격 항이 들어간 가중 {reported['price_term_weight']} · 단일 지표 최대 가중 {reported['max_indicator_weight']}",
              f"- 재현 구간의 보류 일수 {gates['hold_days_in_replay']}", ""]
    return "\n".join(lines)


def gate_rules(contract: dict[str, Any]) -> dict[str, str]:
    rules = {}
    for group in ("construction_checks", "falsifiable"):
        for row in contract["gates"][group]:
            rules[row["id"]] = str(row["rule"]).replace("|", "/")
    return rules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--contract", default=str(v6.CONTRACT_RELATIVE))
    parser.add_argument("--as-of", default=None, help="gate date (default: contract gate_as_of, else latest session)")
    parser.add_argument("--report", default=None, help="Markdown report path (a .json twin is written beside it)")
    parser.add_argument("--write-frozen", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    relative = Path(args.contract)
    contract = v6.load_contract(root, relative)
    as_of_text = args.as_of or contract.get("gate_as_of") or (contract.get("frozen") or {}).get("gate_as_of")
    as_of = date.fromisoformat(str(as_of_text)) if as_of_text else v6.load_inputs(root).sessions[-1]
    report = run(root, relative, as_of)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["generated_at"] = stamp
    if args.report:
        out = root / args.report
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown(report, gate_rules(contract)), encoding="utf-8", newline="\n")
        out.with_suffix(".json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    if args.write_frozen:
        write_frozen(root / relative, frozen_block(report, stamp))
    summary = {"verdict": report["verdict"], "failed": report["gates"]["failed"],
               "value": report["key_values"][report["gate_as_of"]],
               "weights": report["admission"]["weights"],
               "frozen_matches_recomputation": report["frozen_matches_recomputation"],
               "protected_unchanged": report["protected_unchanged"]}
    sys.stdout.buffer.write((json.dumps(summary, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0 if report["protected_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
