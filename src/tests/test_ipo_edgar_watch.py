from __future__ import annotations

import json
from pathlib import Path

from ai_fc.ipo_edgar_watch import (
    AI_KEYWORDS,
    CANDIDATES_PATH,
    FORM,
    IPO_REFERENCE_PATH,
    USER_AGENT,
    company_from_display_name,
    load_cohort_names,
    normalize_company,
    refresh_edgar_candidates,
    search_url,
)


ROOT = Path(__file__).resolve().parents[2]


def _install_reference(tmp_path: Path) -> dict:
    payload = json.loads((ROOT / IPO_REFERENCE_PATH).read_text(encoding="utf-8"))
    target = tmp_path / IPO_REFERENCE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _hit(company: str, cik: str, accession: str, filed_at: str) -> dict:
    return {
        "_id": f"{accession}:doc-{cik}.htm",
        "_source": {
            "ciks": [cik],
            "display_names": [f"{company}  (TCK)  (CIK {cik})"],
            "adsh": accession,
            "file_date": filed_at,
            "form": FORM,
        },
    }


def _page(hits: list[dict], total: int | None = None) -> bytes:
    return json.dumps({
        "hits": {"total": {"value": total if total is not None else len(hits)}, "hits": hits},
    }).encode("utf-8")


FRESH = _hit("Fresh Compute Inc", "0001234567", "0001234567-26-000012", "2026-08-14")
SECOND = _hit("Quiet Robotics Ltd", "0007654321", "0007654321-26-000044", "2026-08-20")
# ai_broad_cohort에 이미 들어가 있는 발행인 (2025년 행)
KNOWN = _hit("CoreWeave", "0001769628", "0001769628-26-000101", "2026-08-18")


def _fetcher_for(mapping: dict[str, bytes]):
    """키워드별 응답을 주입한다. 미지정 키워드는 빈 결과."""

    def fetcher(url: str) -> bytes:
        for keyword, body in mapping.items():
            if f"%22{keyword.split()[0]}" in url or keyword.replace(" ", "+") in url:
                return body
        return _page([])

    return fetcher


def test_user_agent_carries_the_contact_address_sec_fair_access_requires() -> None:
    assert USER_AGENT == "JinsInvestingIPOEdgarWatch/1.0 (91ssjj@gmail.com)"


def test_search_url_matches_the_endpoint_verified_against_live_edgar() -> None:
    from datetime import date

    url = search_url("artificial intelligence", start=date(2026, 8, 13), end=date(2026, 8, 31))
    assert url.startswith("https://efts.sec.gov/LATEST/search-index?")
    assert "q=%22artificial%20intelligence%22" in url
    assert "forms=424B4" in url
    assert "dateRange=custom" in url
    assert "startdt=2026-08-13" in url and "enddt=2026-08-31" in url
    assert "from=" not in url, "첫 페이지는 오프셋을 붙이지 않는다"
    assert "from=100" in search_url(
        "machine learning", start=date(2026, 8, 13), end=date(2026, 8, 31), offset=100)


def test_display_name_and_company_normalisation() -> None:
    assert company_from_display_name(
        "Check-Cap Ltd  (MBAI)  (CIK 0001610590)") == "Check-Cap Ltd"
    assert company_from_display_name(
        "Rainier Acquisition Corp  (CIK 0002147219)") == "Rainier Acquisition Corp"
    assert company_from_display_name(
        "Silexion Therapeutics Corp  (SLXN, SLXNW)  (CIK 0002022416)"
    ) == "Silexion Therapeutics Corp"
    # 법인 접미사 차이는 코호트 대조를 막지 않는다
    assert normalize_company("CoreWeave, Inc.") == normalize_company("CoreWeave")
    assert normalize_company("Circle Internet Group") == "circle internet"


def test_cohort_names_come_from_the_published_broad_cohort() -> None:
    names = load_cohort_names(ROOT)
    assert normalize_company("CoreWeave") in names
    assert normalize_company("Astera Labs") in names
    assert "" not in names


def test_watch_writes_only_its_own_queue_and_never_the_published_reference(
    tmp_path: Path,
) -> None:
    _install_reference(tmp_path)
    before = (tmp_path / IPO_REFERENCE_PATH).read_bytes()

    _, payload, pending = refresh_edgar_candidates(
        tmp_path,
        checked_at="2026-08-31T00:00:00+00:00",
        fetcher=_fetcher_for({"artificial intelligence": _page([FRESH, SECOND])}),
        keywords=("artificial intelligence",),
    )

    assert (tmp_path / IPO_REFERENCE_PATH).read_bytes() == before, "게시 파일은 무접촉"
    assert (tmp_path / CANDIDATES_PATH).is_file()
    assert sorted(
        path.name for path in (tmp_path / "data/statistics/ipo").iterdir()
    ) == ["edgar_candidates.json", "ipo_comparison_v1.json"], "출력 파일은 하나뿐"

    assert payload["dataset_id"] == "ipo_edgar_424b4_candidates_v1"
    assert payload["schema_version"] == 1
    assert payload["cadence"] == "biweekly"
    assert payload["checked_at"] == "2026-08-31T00:00:00+00:00"
    assert payload["reviewed_through"] == "2026-08-12"
    assert payload["window_start"] == "2026-08-13", "검토 완료일 다음 날부터 묻는다"
    assert payload["window_end"] == "2026-08-31"
    assert payload["status"] == "current"
    assert payload["applies_to_published_counts"] is False
    assert pending == 2

    first = payload["candidates"][0]
    assert set(first) == {
        "company", "cik", "accession", "filed_at", "form", "filing_url",
        "matched_keywords", "already_in_cohort", "review_status",
    }
    assert first["company"] == "Fresh Compute Inc"
    assert first["cik"] == "0001234567"
    assert first["accession"] == "0001234567-26-000012"
    assert first["filed_at"] == "2026-08-14"
    assert first["form"] == "424B4"
    assert first["matched_keywords"] == ["artificial intelligence"]
    assert first["already_in_cohort"] is False
    assert first["review_status"] == "pending"
    assert first["filing_url"] == (
        "https://www.sec.gov/Archives/edgar/data/1234567/"
        "000123456726000012/doc-0001234567.htm"
    )


def test_issuers_already_in_the_cohort_are_flagged_not_dropped(tmp_path: Path) -> None:
    _install_reference(tmp_path)
    _, payload, pending = refresh_edgar_candidates(
        tmp_path,
        checked_at="2026-08-31T00:00:00+00:00",
        fetcher=_fetcher_for({"artificial intelligence": _page([FRESH, KNOWN])}),
        keywords=("artificial intelligence",),
    )
    by_company = {row["company"]: row for row in payload["candidates"]}
    assert by_company["CoreWeave"]["already_in_cohort"] is True
    assert by_company["Fresh Compute Inc"]["already_in_cohort"] is False
    assert payload["counts"] == {
        "candidates": 2, "already_in_cohort": 1, "pending_review": 1,
    }
    assert pending == 1, "이미 반영된 발행인은 검토 대기에서 빠진다"


def test_the_same_filing_collects_every_keyword_that_matched(tmp_path: Path) -> None:
    _install_reference(tmp_path)
    _, payload, _ = refresh_edgar_candidates(
        tmp_path,
        checked_at="2026-08-31T00:00:00+00:00",
        fetcher=_fetcher_for({
            "artificial intelligence": _page([FRESH]),
            "machine learning": _page([FRESH]),
        }),
        keywords=("artificial intelligence", "machine learning", "deep learning"),
    )
    assert len(payload["candidates"]) == 1, "중복 accession은 한 건으로 합쳐진다"
    assert payload["candidates"][0]["matched_keywords"] == [
        "artificial intelligence", "machine learning",
    ]
    assert payload["keywords"] == [
        "artificial intelligence", "machine learning", "deep learning",
    ]


def test_paging_walks_until_the_reported_total_is_covered(tmp_path: Path) -> None:
    _install_reference(tmp_path)
    first_page = [
        _hit(f"Issuer {index}", f"{index:010d}", f"{index:010d}-26-000001", "2026-08-15")
        for index in range(1, 101)
    ]
    seen: list[str] = []

    def fetcher(url: str) -> bytes:
        seen.append(url)
        if "from=100" in url:
            return _page([SECOND], total=101)
        return _page(first_page, total=101)

    _, payload, _ = refresh_edgar_candidates(
        tmp_path,
        checked_at="2026-08-31T00:00:00+00:00",
        fetcher=fetcher,
        keywords=("artificial intelligence",),
    )
    assert len(seen) == 2 and "from=100" in seen[1]
    assert len(payload["candidates"]) == 101


def test_search_failure_degrades_the_queue_without_losing_the_run(tmp_path: Path) -> None:
    _install_reference(tmp_path)

    def broken(url: str) -> bytes:
        raise TimeoutError("edgar down")

    _, payload, pending = refresh_edgar_candidates(
        tmp_path,
        checked_at="2026-08-31T00:00:00+00:00",
        fetcher=broken,
        keywords=("artificial intelligence", "machine learning"),
    )
    assert payload["status"] == "degraded"
    assert [row["error"] for row in payload["errors"]] == ["TimeoutError"] * 2
    assert payload["candidates"] == [] and pending == 0


def test_default_keyword_set_is_explicit_and_recorded(tmp_path: Path) -> None:
    _install_reference(tmp_path)
    _, payload, _ = refresh_edgar_candidates(
        tmp_path,
        checked_at="2026-08-31T00:00:00+00:00",
        fetcher=_fetcher_for({}),
    )
    assert payload["keywords"] == list(AI_KEYWORDS)
    assert "artificial intelligence" in AI_KEYWORDS
    assert payload["candidates"] == []
