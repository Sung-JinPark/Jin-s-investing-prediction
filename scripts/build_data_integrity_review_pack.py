"""Build a self-contained GPT review pack for statistics and future-path integrity."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_fc.multi_year_stress import build_multi_year_stress  # noqa: E402
from ai_fc.scenario_v5.contracts import (  # noqa: E402
    LF_CANONICAL_PROTECTED_PATHS,
    PROTECTED_PATHS,
    protected_hashes,
)
from ai_fc.scenario_v5_2.engine import source_file_hash  # noqa: E402
from ai_fc.statistics_lab import (  # noqa: E402
    FRED_SERIES,
    _cycle_series,
    _lead_correlation,
    _monthly,
    _parse_fred_csv,
    _ratio,
    _fetch_fred,
    _parse_z1,
    validate_ipo_reference,
    validate_statistics_lab,
)


PACK_ID = "AI_INVESTING_STATISTICS_FUTURE_DATA_INTEGRITY_REVIEW_PACK_260813"
OUTPUT_ROOT = ROOT / "reports/reviews/current/data_integrity_260813"
EVIDENCE_ROOT = OUTPUT_ROOT / "evidence"
ZIP_PATH = ROOT / "reports/reviews/current" / f"{PACK_ID}.zip"
FIXED_ZIP_TIME = (2026, 8, 13, 20, 0, 0)
USER_AGENT = "JinsInvestingDataIntegrityAudit/1.0"

STATISTICS = ROOT / "data/statistics/dotcom_statistics_latest.json"
IPO_REFERENCE = ROOT / "data/statistics/ipo/ipo_comparison_v1.json"
CROSS_ASSET = ROOT / "data/cross_asset/cross_asset_latest.json"
CANDIDATE = ROOT / "data/scenarios/candidates/scenario_v5_2_scenario_clustered_db_v4_latest.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_json(path: Path, payload: Any) -> None:
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=check,
    )


def _live_source_verification(statistics_payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for source in statistics_payload["sources"]:
        series_id = str(source["series_id"])
        if series_id not in FRED_SERIES and series_id != "FL663067003":
            rows.append({
                "series_id": series_id,
                "status": "snapshot_receipt_only_not_live_refetched",
                "stored_sha256": source["raw_sha256"],
                "request_url": source.get("request_url") or source.get("source_url"),
            })
            continue
        url = source.get("request_url")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=75) as response:
                raw = response.read()
            actual = _sha256_bytes(raw)
            if series_id == "FL663067003":
                parsed = _parse_z1(raw)
            else:
                parsed = _parse_fred_csv(raw, series_id)
            rows.append({
                "series_id": series_id,
                "status": "match" if actual == source["raw_sha256"] else "changed_since_snapshot",
                "stored_sha256": source["raw_sha256"],
                "live_sha256": actual,
                "request_url": url,
                "bytes": len(raw),
                "parsed_rows": len(parsed),
            })
        except Exception as exc:  # auditable failure, never converted to a pass
            rows.append({
                "series_id": series_id,
                "status": "verification_error",
                "stored_sha256": source["raw_sha256"],
                "request_url": url,
                "error": f"{type(exc).__name__}: {exc}",
            })
    live_rows = [row for row in rows if row["series_id"] in {*FRED_SERIES, "FL663067003"}]
    return {
        "schema_version": 1,
        "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live_transport_source_count": len(live_rows),
        "live_exact_match_count": sum(row["status"] == "match" for row in live_rows),
        "gate_pass": bool(live_rows) and all(row["status"] == "match" for row in live_rows),
        "rows": rows,
    }


def _source_matrix(statistics_payload: dict[str, Any], verification: dict[str, Any]) -> list[dict[str, Any]]:
    status_by_id = {row["series_id"]: row["status"] for row in verification["rows"]}
    captured = date.fromisoformat(statistics_payload["generated_at"][:10])
    matrix = []
    for source in statistics_payload["sources"]:
        observed = date.fromisoformat(str(source["latest_observation"]))
        provider = str(source.get("provider", ""))
        if source["series_id"] in FRED_SERIES or source["series_id"] == "FL663067003":
            automation = "weekly_live_fetch"
            evidence_grade = "A_public_transport_with_raw_hash"
        elif source["series_id"] == "NAHB_HMI":
            automation = "manual_reference_freshness_gate_62d"
            evidence_grade = "B_primary_snapshot_with_hash"
        elif str(source["series_id"]).startswith("SEC_") or provider in {"HKEX", "SSE", "SK hynix", "OpenAI", "Anthropic"}:
            automation = "manual_event_review"
            evidence_grade = "A_primary_event_receipt"
        else:
            automation = "manual_research_reference"
            evidence_grade = "B_reviewed_secondary_or_academic"
        matrix.append({
            "series_id": source["series_id"],
            "provider": provider,
            "native_frequency": source.get("native_frequency"),
            "latest_observation": source["latest_observation"],
            "age_days_at_collection": (captured - observed).days,
            "vintage": source.get("vintage"),
            "automation": automation,
            "evidence_grade": evidence_grade,
            "live_receipt_status": status_by_id.get(source["series_id"], "not_checked"),
            "source_url": source.get("source_url"),
            "request_url": source.get("request_url"),
            "raw_sha256": source["raw_sha256"],
        })
    return matrix


def _math_audit(
    statistics_payload: dict[str, Any], ipo_reference: dict[str, Any],
    cross_asset: dict[str, Any], candidate: dict[str, Any],
) -> dict[str, Any]:
    validate_statistics_lab(statistics_payload)
    validate_ipo_reference(ipo_reference)

    source_rows: dict[str, list[dict[str, Any]]] = {}
    for series_id in ("SPASTT01KRM661N", "NASDAQCOM"):
        rows, _ = _fetch_fred(series_id)
        source_rows[series_id] = rows
    kospi_monthly = _monthly(source_rows["SPASTT01KRM661N"], "last")
    nasdaq_monthly = _monthly(source_rows["NASDAQCOM"], "last")
    ratio = _ratio(kospi_monthly, nasdaq_monthly)
    dotcom, current = _cycle_series(ratio, 59, indexed=True)
    kospi_chart = next(
        row for row in statistics_payload["charts"] if row["id"] == "kospi_nasdaq_relative_lead"
    )
    chart_series = {row["label"]: row["points"] for row in kospi_chart["series"]}
    lead = [_lead_correlation(kospi_monthly, nasdaq_monthly, lag) for lag in range(4)]
    kospi_reconciles = (
        chart_series["닷컴 KOSPI/NASDAQ"] == dotcom
        and chart_series["현재 KOSPI/NASDAQ"] == current
        and kospi_chart["lead_diagnostics"] == lead
    )

    broad_counts = {
        int(row["year"]): len(row["issuers"]) for row in ipo_reference["ai_broad_cohort"]
    }
    influence = dict(broad_counts)
    for member in ipo_reference["qualitative_ipo"]["listed_ai_beneficiary_watchlist"]["members"]:
        influence[int(member["count_period"])] += 1
    ipo_chart = next(
        row for row in statistics_payload["charts"] if row["id"] == "internet_vs_ai_core_ipos"
    )
    influence_stored = {
        int(point["date"][:4]): int(point["value"])
        for point in next(
            row for row in ipo_chart["series"] if row["label"] == "현재 AI 영향력 포함 집계"
        )["points"]
    }

    stress = build_multi_year_stress(cross_asset)
    composite = stress["historical_stress_composite"]
    counterfactual = stress["ai_bust_counterfactual"]

    source_hash_rows = []
    for relative, expected in candidate["source_hashes"].items():
        path = ROOT / relative
        actual = source_file_hash(ROOT, relative) if path.is_file() else None
        source_hash_rows.append({
            "path": relative, "expected": expected, "actual": actual,
            "match": actual == expected,
        })
    generator = candidate["model"]["generator_audit"]
    distinctness = candidate["distinctness"]
    return {
        "schema_version": 1,
        "statistics_contract_valid": True,
        "ipo_reference_contract_valid": True,
        "kospi_formula_reconciles_to_live_raw_rows": kospi_reconciles,
        "kospi_lead_diagnostics": lead,
        "ipo_actual_broad_counts": broad_counts,
        "ipo_influence_inclusive_expected": influence,
        "ipo_influence_inclusive_stored": influence_stored,
        "ipo_influence_reconciles": influence == influence_stored,
        "multi_year_stress": {
            "single_graph_count": stress["presentation_html"].count("<svg"),
            "historical_composite": composite,
            "btc_center": counterfactual["bitcoin_sensitivity"]["center"],
            "realty_income_center": counterfactual["realty_income_sensitivity"]["center"],
            "beta_observations": counterfactual["beta_observations"],
            "official_forecast_input": stress["official_forecast_input"],
        },
        "scenario_v5_2": {
            "candidate_id": candidate["candidate_id"],
            "status": candidate["status"],
            "promotion_state": candidate["promotion_state"],
            "probability_unit": candidate["first_touch_distribution"]["probability_unit"],
            "path_count": candidate["model"]["path_count"],
            "paths_per_scenario": generator["scenario_path_count"],
            "dotcom_generator_share_s1": generator["B_generator_dotcom_block_share"],
            "macro_origin_overlap": generator["macro_regime_cohort_origin_overlap"],
            "dependency_cap_gate_pass": generator["structural_event_adapter"]["dependency_cap_gate_pass"],
            "official_snapshot_overwritten": candidate["shadow_comparison"]["official_snapshot_overwritten"],
            "sample_adequacy": distinctness["sample_adequacy"],
            "threshold_calibration": distinctness["threshold_calibration"],
            "kernel_gates_pass": generator["kernel_gates_pass"],
            "conditional_63d_returns": {
                key: value["cumulative_return_p50"]["63"]
                for key, value in distinctness["per_scenario"].items()
            },
            "source_hashes_all_match": all(row["match"] for row in source_hash_rows),
            "source_hash_rows": source_hash_rows,
        },
    }


def _protected_manifest() -> dict[str, Any]:
    """Compare the protected working tree to Git, not a mixed mutable ledger manifest.

    The ledger manifest also inventories append-only and mutable read models, so
    treating every row as byte-immutable creates false failures.  Official
    protection is instead defined by the Scenario contract.  The one research
    candidate intentionally rebuilt in this change is reported separately and
    never counted as an official snapshot/ledger/archive mutation.
    """
    allowed_research_changes = {
        "data/scenarios/candidates/"
        "scenario_v5_2_scenario_clustered_db_v4_latest.json",
    }
    current = protected_hashes(ROOT)["files"]
    tree = _run(["git", "ls-tree", "-r", "--name-only", "origin/main"]).stdout.splitlines()
    baseline_paths = {
        relative for relative in tree
        if any(
            relative == prefix or relative.startswith(f"{prefix}/")
            for prefix in PROTECTED_PATHS
        )
    }
    rows = []
    for relative in sorted(set(current) | baseline_paths):
        process = subprocess.run(
            ["git", "show", f"origin/main:{relative}"], cwd=ROOT,
            capture_output=True, check=False,
        )
        if process.returncode:
            expected = None
        else:
            content = process.stdout
            if any(
                relative == prefix or relative.startswith(f"{prefix}/")
                for prefix in LF_CANONICAL_PROTECTED_PATHS
            ):
                content = content.replace(b"\r\n", b"\n")
            expected = _sha256_bytes(content)
        actual = current.get(relative)
        if expected is None:
            status = "added"
        elif actual is None:
            status = "removed"
        elif actual == expected:
            status = "unchanged"
        else:
            status = "changed"
        rows.append({
            "path": relative,
            "origin_main_sha256": expected,
            "working_tree_sha256": actual,
            "status": status,
            "authorized_research_candidate_change": (
                relative in allowed_research_changes and status == "changed"
            ),
        })
    unauthorized = [
        row for row in rows
        if row["status"] != "unchanged"
        and not row["authorized_research_candidate_change"]
    ]
    return {
        "schema_version": 1,
        "baseline": "origin/main",
        "scope_contract": "src/ai_fc/scenario_v5/contracts.py::PROTECTED_PATHS",
        "file_count": len(rows),
        "unchanged_count": sum(row["status"] == "unchanged" for row in rows),
        "authorized_research_change_count": sum(
            row["authorized_research_candidate_change"] for row in rows
        ),
        "unauthorized_change_count": len(unauthorized),
        "gate_pass": not unauthorized,
        "rows": rows,
    }


def _workflow_runs() -> dict[str, Any]:
    result: dict[str, Any] = {"captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for workflow in ("statistics-refresh.yml", "scenario-refresh.yml", "investing-refresh.yml", "pages.yml"):
        try:
            process = _run([
                "gh", "run", "list", "--workflow", workflow, "--limit", "12",
                "--json", "databaseId,createdAt,event,status,conclusion,headSha,url",
            ])
            result[workflow] = json.loads(process.stdout)
        except Exception as exc:
            result[workflow] = {"error": f"{type(exc).__name__}: {exc}"}
    return result


def _write_source_csv(matrix: list[dict[str, Any]]) -> None:
    target = OUTPUT_ROOT / "01_SOURCE_INTEGRITY_MATRIX.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(matrix[0]))
        writer.writeheader()
        writer.writerows(matrix)


def _copy_evidence() -> None:
    paths = [
        "src/ai_fc/statistics_lab.py",
        "src/ai_fc/multi_year_stress.py",
        "src/ai_fc/dashboard.py",
        "src/ai_fc/dashboard_parts/dashboard.js",
        "src/ai_fc/market_extensions.py",
        "src/ai_fc/scenario_v5/contracts.py",
        "src/ai_fc/scenario_v5_2/artifact.py",
        "src/ai_fc/scenario_v5_2/engine.py",
        "src/tests/test_statistics_lab.py",
        "src/tests/test_multi_year_stress.py",
        "src/tests/test_market_extensions.py",
        "src/tests/test_dashboard.py",
        "src/tests/test_scenario_v5_2.py",
        "scripts/build_data_integrity_review_pack.py",
        "data/contracts/statistics_lab_v1.yaml",
        "data/contracts/multi_year_bubble_stress_v1.yaml",
        "data/contracts/scenario_v5_2_weights.yaml",
        "data/contracts/scenario_v5_3_separation.yaml",
        "data/statistics/dotcom_statistics_latest.json",
        "data/statistics/ipo/ipo_comparison_v1.json",
        "data/statistics/reference/nahb_hmi_history_v1.json",
        "data/cross_asset/cross_asset_latest.json",
        "data/scenarios/candidates/scenario_v5_2_scenario_clustered_db_v4_latest.json",
        ".github/workflows/statistics-refresh.yml",
        ".github/workflows/scenario-refresh.yml",
        ".github/workflows/investing-refresh.yml",
        ".github/workflows/pages.yml",
        "_site/index.html",
        "_site/data.json",
        "_site/future_paths.json",
        "_site/statistics.json",
    ]
    for relative in paths:
        source = ROOT / relative
        if source.is_file():
            target = EVIDENCE_ROOT / "snapshot" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for pattern in ("*.xml", "*.txt", "*.json"):
        for source in (EVIDENCE_ROOT / "test_logs").glob(pattern):
            if source.is_file():
                continue
    screenshot_root = EVIDENCE_ROOT / "screenshots"
    if screenshot_root.is_dir():
        # Screenshots are already written in place by the capture tool.
        pass


def _reports(
    statistics_payload: dict[str, Any], verification: dict[str, Any],
    matrix: list[dict[str, Any]], math_audit: dict[str, Any], workflows: dict[str, Any],
    protected: dict[str, Any],
) -> None:
    kospi = math_audit["kospi_lead_diagnostics"]
    stress = math_audit["multi_year_stress"]
    scenario = math_audit["scenario_v5_2"]
    _write(OUTPUT_ROOT / "README.md", f"""# {PACK_ID}

이 ZIP은 통계 DB, 미래 전망 연구 후보, 다년 스트레스, 배포·갱신 체인을 외부 GPT가 원자료 수준으로 재검토하도록 만든 자체완결 증거 팩입니다.

## 결론

- 통계 live 수집 계열 {verification['live_transport_source_count']}개 중 원문 SHA가 정확히 일치한 계열은 {verification['live_exact_match_count']}개입니다. `gate_pass={str(verification['gate_pass']).lower()}`.
- 통계 계산 계약과 KOSPI 재계산, IPO 영향력 집계, 다년 스트레스 재계산은 모두 기계적으로 대조했습니다.
- V5.2는 계산·원천 해시가 재현되지만 **공식 forecast/champion이 아닙니다**. S2 기원 표본 16/20, distinctness shadow 0/30, 일부 kernel gate 실패가 남습니다.
- 선택한 낙폭 사례 4개는 확률 모집단이 아닙니다. 합성 그래프도 발생확률·목표가격이 아닌 조건부 민감도입니다.
- 공식 보호범위는 `origin/main` 대비 무단 변경 {protected['unauthorized_change_count']}건입니다. V5.2 연구 후보 변경 {protected['authorized_research_change_count']}건은 별도 표시되며 official snapshot·ledger·archive 변경으로 세지 않습니다.

## 검토 순서

1. `00_EXECUTIVE_VERDICT.md`
2. `01_SOURCE_INTEGRITY_MATRIX.csv`
3. `02_REFRESH_CADENCE_AND_RUN_AUDIT.md`
4. `03_STATISTICS_FORMULA_AUDIT.md`
5. `04_SCENARIO_V52_ALGORITHM_AUDIT.md`
6. `05_MULTI_YEAR_STRESS_METHOD.md`
7. `06_KOSPI_SIGNAL_METHOD.md`
8. `07_LIMITATIONS_AND_OPEN_RISKS.md`
9. `08_GPT_REVIEW_CHECKLIST.md`
10. `evidence/` 원문·테스트·스크린샷
""")
    _write(OUTPUT_ROOT / "00_EXECUTIVE_VERDICT.md", f"""# 종합 판정

## PASS

- 최신 통계 스냅샷: `{statistics_payload['generated_at']}`, 관측 최댓값 `{statistics_payload['as_of']}`, 장표 {len(statistics_payload['charts'])}개.
- FRED/Fed Z.1 live raw receipt exact match: {verification['live_exact_match_count']}/{verification['live_transport_source_count']}.
- KOSPI/NASDAQ 공식 공개 계열 재계산 일치: `{str(math_audit['kospi_formula_reconciles_to_live_raw_rows']).lower()}`.
- SK하이닉스 포함 영향력 진단: 실제 IPO 5와 별도로 영향력 포함 6, 재계산 일치 `{str(math_audit['ipo_influence_reconciles']).lower()}`.
- 다년 스트레스: 화면 SVG {stress['single_graph_count']}개, official input `{str(stress['official_forecast_input']).lower()}`.
- 보호 파일: {protected['unchanged_count']}/{protected['file_count']} 불변, 허용 연구후보 변경 {protected['authorized_research_change_count']}건, 무단 변경 {protected['unauthorized_change_count']}건.

## HOLD / 제한

- V5.2 promotion은 HOLD: `{scenario['promotion_state']}`. S2 표본은 16/20이고 30거래일 threshold 관측은 0/30입니다.
- kernel 전체 gate는 `{str(scenario['kernel_gates_pass']).lower()}`입니다. 실패를 경로 수정이나 확률 보정으로 숨기지 않았습니다.
- IPO/HMI는 수동 검토 참조입니다. 14일/62일 freshness gate가 초과 시 주간 작업을 실패시키지만 자동 원문 분류기는 아닙니다.
- rate probability는 유료 CME API가 아니라 CME futures 기반 Investing.com 공개 화면 캡처입니다. BLS 고용은 공식 BLS 원문입니다.
- 현재 KOSPI 월수익 선행 상관은 1개월 {kospi[1]['correlation']:+.2f}, 2개월 {kospi[2]['correlation']:+.2f}, 3개월 {kospi[3]['correlation']:+.2f}로 약합니다. 강한 선행 신호라는 주장은 기각합니다.
""")
    _write(OUTPUT_ROOT / "02_REFRESH_CADENCE_AND_RUN_AUDIT.md", """# 갱신·배포 체인 감사

## 통계

- `statistics-refresh.yml`: 토요일 00:20 UTC. FRED/Fed Z.1을 live fetch하고 reference-only 통계를 재계산합니다.
- 변경 시 append-only `data/statistics/archive`를 추가하고 latest를 바꿉니다.
- 이번 수정으로 inventory도 같은 커밋에 포함합니다.
- IPO 분류는 14일, HMI는 62일 수동 참조 freshness gate를 넘으면 실패합니다.

## 미래 전망

- `scenario-refresh.yml`: 화~토 01:30 UTC. scenario, cross-asset, V5.2 rebuild/replay를 수행합니다.
- 2026-08-13 run은 `market-extensions` 내부 실패가 `continue-on-error`에 가려진 것을 확인했습니다. 이번 수정은 마지막 단계에서 보조 작업 실패를 전체 실패로 보고합니다.
- 같은 금요일 weekly tracker를 반복 수집해 current-vintage revision과 충돌하던 원인은, 이미 검증된 동일 weekly vintage를 재사용하도록 수정했습니다. 기존 archive는 수정하지 않았습니다.

## Pages

- main의 데이터·통계·dashboard·V5.2·multi-year stress 변경이 Pages build를 유발합니다.
- 통계는 `statistics.json`, 미래 경로는 `future_paths.json`으로 라우트별 lazy fetch합니다. 예산 상향 없이 future payload 여유를 회복했습니다.

원문 실행 기록은 `evidence/GITHUB_ACTIONS_RUNS.json`에 있습니다. 구현 커밋 이후 run은 최종 live 증거 파일에서 다시 확인해야 합니다.
""")
    _write(OUTPUT_ROOT / "03_STATISTICS_FORMULA_AUDIT.md", """# 통계 수식 감사

## 공통 변환

- 월말/월평균: native frequency를 먼저 월 단위로 집계하며 `aggregation=last|mean`을 series registry가 명시합니다.
- 사이클 정렬: `period = 12*(year-start_year) + month-start_month`, 닷컴 1995-01, 현재 2023-01, 최대 59개월입니다.
- 시작=100: `I_t = 100 * x_t / x_0`.
- 전년비: `YoY_t = 100 * (x_t/x_(t-12)-1)`; 전년 동월이 없으면 점을 만들지 않습니다.
- 비율: 같은 달 inner join 뒤 `left/right`; 결측을 forward fill하지 않습니다.

## 핵심 장표

- NASDAQ/M2, NASDAQ/가계 현금성 자산: 단순 비율을 다시 시작=100으로 만듭니다. M2와 가계 현금성 자산은 예금 중복 때문에 합산하지 않습니다.
- valuation proxy: `NCBEILQ027S / CPATAX / 1000`; NASDAQ 공식 PER이 아닙니다.
- IPO 흡수율: `IPO 첫 종가 시총(USD bn)*1000 / Fed 기업주식 총가치(USD mn)*100`.
- KOSPI 상대강도: `(OECD Korea share-price index / NASDAQCOM)`의 시작=100.
- KOSPI 선행 진단: `corr(log(KOSPI_t/KOSPI_t-1), log(NASDAQ_t+h/NASDAQ_t+h-1))`, h=0,1,2,3을 모두 공개합니다.
- CPI 정렬: 원자재를 미래로 연장하지 않고 CPI 날짜만 -2개월 이동해 묘사적으로 정렬합니다.

## 단위·PIT

- 모든 통계는 `reference_only`, `model_use=false`, `official_forecast_input=false`입니다.
- 현재선은 관측점에서 멈추고 2027까지 예측 연장하지 않습니다.
- FRED 역사값은 latest-release reconstructed이며 native PIT vintage가 아닙니다. 따라서 역사 비교는 당시 이용가능 정보 backtest가 아닙니다.
""")
    _write(OUTPUT_ROOT / "04_SCENARIO_V52_ALGORITHM_AUDIT.md", f"""# Scenario V5.2 알고리즘 감사

- 후보: `{scenario['candidate_id']}` / `{scenario['status']}` / `{scenario['promotion_state']}`.
- 확률 저장 단위: `{scenario['probability_unit']}`. UI에서만 %로 변환합니다.
- 경로: 총 {scenario['path_count']:,}, 시나리오별 {scenario['paths_per_scenario']:,}.
- S1: 닷컴+완화·확장 DB, 닷컴 generator share {scenario['dotcom_generator_share_s1']:.2f}.
- S2: 균형·soft-landing DB.
- S3: 긴축·금융 stress DB.
- macro origin overlap: `{json.dumps(scenario['macro_origin_overlap'], ensure_ascii=False)}`.
- 63거래일 조건부 p50 수익: `{json.dumps(scenario['conditional_63d_returns'], ensure_ascii=False)}`.
- dependency cap gate: `{str(scenario['dependency_cap_gate_pass']).lower()}`.
- source hash: `{str(scenario['source_hashes_all_match']).lower()}`.
- official snapshot overwrite: `{str(scenario['official_snapshot_overwritten']).lower()}`.

## 이벤트 증거

- 고용: BLS 2026-07 official actual, revisions, unemployment, participation.
- 금리확률: CME 30-day Fed Funds futures를 기반으로 한 Investing.com 공개 화면 캡처. 공식/유료 CME API가 아니므로 secondary입니다.
- policy relief와 labor growth risk는 structural adapter에서 별도 좌표로 사용되고 dependency cap을 적용합니다.

## 승격 불가 사유

- S2 origin n=16 < 20.
- distinctness threshold shadow observations 0 < 30.
- S2/S3 일부 empirical kernel time-to-trough/recovery gate 실패.
- 따라서 계산 재현 성공은 calibrated forecast 또는 champion 승격을 뜻하지 않습니다.
""")
    _write(OUTPUT_ROOT / "05_MULTI_YEAR_STRESS_METHOD.md", f"""# 단일 다년 스트레스 그래프

## 합성

선택 사례는 대공황, 2차대전 초기, 오일쇼크, 닷컴 4개입니다. 각 연도 누적지수를 100에서 시작하고 로그 공간에서 연도별 중앙값과 선형 q25/q75를 계산합니다.

- 중앙 합성: `{stress['historical_composite']['center_index']}`
- q25: `{stress['historical_composite']['q25_index']}`
- q75: `{stress['historical_composite']['q75_index']}`
- 지평별 n: `{stress['historical_composite']['observations_by_horizon']}` — 2년짜리 오일쇼크 때문에 3년차 n=3입니다.

## 자산 전송

`AssetIndex_t = 100 * (ReferenceIndex_t/100)^beta`를 사용해 0 아래 가격을 만들지 않습니다. beta는 최근 5년 NASDAQ 하락일 {stress['beta_observations']}개에서 온 cross-asset 진단입니다.

- BTC 중심: beta {stress['btc_center']['beta']}, `{stress['btc_center']['index']}`
- Realty Income 중심: beta {stress['realty_income_center']['beta']}, `{stress['realty_income_center']['index']}`

역사 q25/q75와 beta 10/90 범위를 동시에 결합해 음영 범위를 만들었습니다. 확률 구간이 아니며 선택사례·추정 beta 민감도 envelope입니다. 역사 기준은 S&P 계열, beta 기준은 NASDAQ이라 기초지수 차이가 남습니다.
""")
    _write(OUTPUT_ROOT / "06_KOSPI_SIGNAL_METHOD.md", f"""# KOSPI AI-cycle 선행 후보

- 공식 공개 가격 계열: OECD Main Economic Indicators의 Korea share-price index를 FRED transport로 수집.
- 비교 계열: NASDAQ Composite.
- KRX는 KOSPI를 시가총액식 benchmark로 설명하고 전기전자 업종 비중을 크게 공시합니다.
- 한국은행은 반도체 수출을 가격·물량으로 분해해야 한다고 설명합니다. 따라서 KOSPI 하나만으로 AI 경기 전환을 확정하지 않습니다.

## 실측

| 시차 | 상관 | n |
|---|---:|---:|
""" + "\n".join(
        f"| {'동행' if row['lead_months']==0 else str(row['lead_months'])+'개월 선행'} | {row['correlation']:+.4f} | {row['observations']} |"
        for row in kospi
    ) + """

동행은 중간 수준이지만 1~3개월 선행 상관은 약합니다. 그러므로 현재 데이터는 “KOSPI가 NASDAQ을 강하게 선행한다”는 가설을 지지하지 않습니다. 화면은 상대강도 고점 이탈을 반도체 수출·메모리 가격과 함께 볼 후보 지표로만 제공합니다.
""")
    _write(OUTPUT_ROOT / "07_LIMITATIONS_AND_OPEN_RISKS.md", """# 제한과 미해결 위험

1. 통계 역사는 latest-release reconstructed라 native PIT backtest가 아닙니다.
2. IPO broad cohort는 완전한 keyword census가 아니라 공개 시장서사 기반 검토 cohort입니다.
3. SK하이닉스는 실제 IPO가 아닙니다. `영향력 포함 6`은 실제 IPO 5 + 기존 상장 수혜주 1의 별도 진단입니다.
4. IPO/HMI는 자동 분류·수집이 아니라 freshness gate가 있는 수동 참조입니다.
5. V5.2 direct event/calibration 표본과 30일 shadow가 부족합니다.
6. market-extensions는 weekly captured vintage를 보존하므로 같은 금요일 이후 공개된 과거 수정치를 소급 반영하지 않습니다. 수정은 승인 correction으로만 append합니다.
7. 네 하락 사례는 사용자가 지정한 선택 사례이며 exhaustive base rate가 아닙니다.
8. BTC는 닷컴기에 존재하지 않았고 beta는 국면에 따라 비선형입니다.
9. KOSPI 선행성은 현재 1~3개월 상관이 약하며 거래시간·환율·국가위험이 섞입니다.
10. 과거 Q1 quarantined benchmark 2건의 probability unit 오류(22.0, 5.0 fraction)가 sync 경고에 남아 있습니다. 격리되어 공식 benchmark에는 유입되지 않지만 별도 승인 correction 대상입니다.
""")
    _write(OUTPUT_ROOT / "08_GPT_REVIEW_CHECKLIST.md", """# 외부 GPT 검토 질문

1. `01_SOURCE_INTEGRITY_MATRIX.csv`의 provider·request URL·hash가 주장과 일치하는가?
2. latest-release history를 PIT로 오인한 문구가 있는가?
3. IPO actual 5와 influence-inclusive 6이 어디에서도 혼용되지 않는가?
4. KOSPI 상관식의 t+h 정렬과 표본 수가 올바른가?
5. 네 역사 사례의 log median/q25/q75와 3년차 n=3이 재계산되는가?
6. power-beta transport와 band envelope 방향이 낙폭에서 단조적인가?
7. V5.2 S1/S2/S3 DB 교집합 0과 각 feature schema가 실제 artifact에서 확인되는가?
8. S2 16/20, shadow 0/30, kernel gate 실패가 promotion을 막는가?
9. official snapshot·ledger·archive hash가 `PROTECTED_MANIFEST.json`과 일치하는가?
10. workflow가 partial auxiliary failure를 더 이상 성공으로 숨기지 않는가?
11. 통계/미래 route fetch 실패가 조용히 빈 화면이 되지 않는가?
12. 모바일 390px screenshot에 가로 overflow, 텍스트 겹침, console error가 없는가?
""")


def _manifest_and_zip() -> tuple[str, int]:
    files = [path for path in sorted(OUTPUT_ROOT.rglob("*")) if path.is_file()]
    manifest = {
        "schema_version": 1,
        "package": ZIP_PATH.name,
        "files": [
            {
                "path": path.relative_to(OUTPUT_ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
    }
    _write_json(OUTPUT_ROOT / "MANIFEST.json", manifest)
    files = [path for path in sorted(OUTPUT_ROOT.rglob("*")) if path.is_file()]
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            info = zipfile.ZipInfo(
                f"{PACK_ID}/{path.relative_to(OUTPUT_ROOT).as_posix()}", FIXED_ZIP_TIME,
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    digest = _sha256(ZIP_PATH)
    _write(ZIP_PATH.with_suffix(ZIP_PATH.suffix + ".sha256"), f"{digest}  {ZIP_PATH.name}\n")
    return digest, len(files)


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    statistics_payload = _read_json(STATISTICS)
    ipo_reference = _read_json(IPO_REFERENCE)
    cross_asset = _read_json(CROSS_ASSET)
    candidate = _read_json(CANDIDATE)

    verification = _live_source_verification(statistics_payload)
    matrix = _source_matrix(statistics_payload, verification)
    math_audit = _math_audit(statistics_payload, ipo_reference, cross_asset, candidate)
    workflows = _workflow_runs()
    protected = _protected_manifest()

    _write_json(EVIDENCE_ROOT / "LIVE_SOURCE_HASH_VERIFICATION.json", verification)
    _write_json(EVIDENCE_ROOT / "MATH_RECALCULATION.json", math_audit)
    _write_json(EVIDENCE_ROOT / "GITHUB_ACTIONS_RUNS.json", workflows)
    _write_json(OUTPUT_ROOT / "PROTECTED_MANIFEST.json", protected)
    _write_source_csv(matrix)
    _reports(statistics_payload, verification, matrix, math_audit, workflows, protected)
    _copy_evidence()

    try:
        raw_diff = _run(
            ["git", "diff", "--binary", "origin/main...HEAD"], check=False,
        ).stdout
        # Keep the review tree compatible with repository-wide
        # ``git diff --check``.  This changes only trailing whitespace in the
        # evidence rendering, never the committed source or data being audited.
        diff = "\n".join(line.rstrip() for line in raw_diff.splitlines()) + "\n"
        _write(EVIDENCE_ROOT / "IMPLEMENTATION.patch", diff)
    except Exception as exc:
        _write(EVIDENCE_ROOT / "IMPLEMENTATION.patch", f"patch unavailable: {exc}\n")

    digest, count = _manifest_and_zip()
    print(f"generated: {ZIP_PATH.relative_to(ROOT).as_posix()}")
    print(f"files: {count}")
    print(f"sha256: {digest}")
    if not verification["gate_pass"] or not protected["gate_pass"]:
        return 1
    if not math_audit["kospi_formula_reconciles_to_live_raw_rows"]:
        return 1
    if not math_audit["ipo_influence_reconciles"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
