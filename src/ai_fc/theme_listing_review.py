"""테마 상장 자동 검수 — 감시가 모은 새 상장을 사전등록 규칙(theme_listing_auto_review_v2)으로 판정해 기록한다.

2026-10-26 사용자 결정: 새 상장 검수도 자동화한다. 판정 근거는 거래소·공시 원천의 사업 설명 텍스트이고,
규칙은 ``data/contracts/theme_listing_auto_review_v2.yaml`` 에 있다. v1 은 전수조사 라벨 대비 정밀도 0.59 로
건수를 부풀려 기각했고, v2 는 개발 구간(2022-02~2024-12) 오류만 보고 고친 뒤 홀드아웃(2025-01~) 전에 고정했다.

* 테마로 판정 → ``theme_listing_additions.csv`` 에 출처를 단 행을 추가(note 가 ``auto_rule_v2:`` 로 시작).
* 테마 아님·첫 상장 아님 → ``theme_listing_reviews.csv`` 에 결정·이유·출처(reviewer=auto_rule_v2).
* 상장 대기 회사가 상장 → additions 로 옮기고 대기 목록에서 지운다.
* 사업 설명을 못 얻으면 판정하지 않는다(다음 실행에 재시도, ops 백로그가 7일 넘으면 알린다).

사람이 남긴 판정(reviewer=manual)은 덮어쓰지 않는다. 같은 입력이면 언제 돌려도 같은 판정이 나온다.
"""

from __future__ import annotations

import csv
import json
import re
import urllib.parse
import zlib
from pathlib import Path
from typing import Any, Callable

import yaml

from .ipo_monthly_counts import (
    THEME_LISTING_FIELDS, THEME_LISTING_RELATIVE, THEME_PIPELINE_FIELDS, THEME_PIPELINE_RELATIVE, _company_key,
    load_theme_listing_additions, load_theme_listing_pipeline,
)

RULES_RELATIVE = Path("data/contracts/theme_listing_auto_review_v2.yaml")
REVIEWER = "auto_rule_v2"
NOTE_PREFIX = "auto_rule_v2:"

EM_A_F10_URL = ("https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_F10_BASIC_ORGINFO"
                "&columns=SECUCODE,SECURITY_NAME_ABBR,ORG_NAME,LISTING_DATE,EM2016,MAIN_BUSINESS"
                "&filter={filter}&pageNumber=1&pageSize=5&source=HSF10&client=PC")
EM_HK_F10_URL = ("https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_HKF10_INFO_ORGPROFILE"
                 "&columns=SECUCODE,ORG_NAME,ORG_EN_ABBR,LISTING_DATE,BELONG_INDUSTRY,MAIN_BUSINESS,ORG_PROFILE"
                 "&filter={filter}&pageNumber=1&pageSize=5&source=F10&client=PC")
MOPS_URL = "https://mops.twse.com.tw/mops/api/t05st03"
JPX_EN_URL = "https://www.jpx.co.jp/english/listing/stocks/new/index.html"
JPX_ROOT = "https://www.jpx.co.jp"


class ThemeListingReviewError(ValueError):
    pass


# ── 규칙 ──────────────────────────────────────────────────────────────────


def load_rules(root: Path) -> dict[str, Any]:
    rules = yaml.safe_load((root / RULES_RELATIVE).read_text(encoding="utf-8"))
    if rules.get("contract_id") != "theme_listing_auto_review_v2" or rules.get("fitting") != "none":
        raise ThemeListingReviewError("auto review rules contract mismatch")
    return rules


def _pattern(term: str) -> re.Pattern[str]:
    """라틴 문자 용어는 단어 경계로, 대문자 약어(IC·AI·GPU…)는 대소문자까지 맞춘다. CJK·한글은 부분 일치."""
    escaped = re.escape(term)
    if re.fullmatch(r"[A-Za-z0-9 .\-]+", term):
        flags = 0 if term.isupper() and len(term) <= 5 else re.IGNORECASE
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", flags)
    return re.compile(escaped)


def _hits(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _pattern(term).search(text)]


def lead_text(fields: list[str], rules: dict[str, Any]) -> list[str]:
    """필드마다 첫 문장 — 부차 표지(以及·此外…) 뒤는 버린다. 소개문 뒤쪽의 부업·고객 산업 언급을 세지 않기 위해서다."""
    leads = []
    for field in fields:
        text = str(field or "").strip()
        cut = len(text)
        for mark in rules["sentence_breaks"]:
            index = text.find(mark)
            if 0 < index < cut:
                cut = index
        text = text[:cut]
        for mark in rules["secondary_markers"]:
            index = text.find(mark)
            if index > 0:
                text = text[:index]
        if text.strip():
            leads.append(text.strip())
    return leads


def _clauses(leads: list[str], rules: dict[str, Any]) -> list[str]:
    pattern = "|".join(re.escape(mark) for mark in rules["clause_breaks"])
    return [part.strip() for lead in leads for part in re.split(pattern, lead) if part.strip()]


def first_item(clause: str, rules: dict[str, Any]) -> str:
    """절의 첫 항목 — '研发、生产和销售' 같은 동사 연쇄를 지운 뒤 나열 구분자(、及和与)로 나눈다. 뒤쪽 항목은 부업이다."""
    verbs = "|".join(re.escape(verb) for verb in rules["verb_chain_terms"])
    joints = "".join(re.escape(mark) for mark in rules["item_breaks"]) + "并並"
    stripped = re.sub(rf"的?(?:(?:{verbs})[{joints}]?){{2,}}", " ", clause)
    parts = re.split("|".join(re.escape(mark) for mark in rules["item_breaks"]), stripped)
    return next((part for part in parts if part.strip()), stripped)


def decide(fields: list[str], industry: str, rules: dict[str, Any]) -> dict[str, Any]:
    """사업 설명 필드 + 산업 분류 → {decision: counted|not_theme, theme, evidence}. 계약 procedure 의 lead_text~default."""
    leads = lead_text(fields, rules)
    clauses = _clauses(leads, rules)
    joined = " ".join(leads)
    service = _hits(f"{industry} {joined}", rules["service_exclusions"])
    if service:
        return {"decision": "not_theme", "theme": None, "evidence": f"고객 대상 서비스·유통 {', '.join(service)}"}
    industry_semi = _hits(industry, rules["industry_semiconductor"])
    semi: list[str] = []
    for clause in clauses:
        head = first_item(clause, rules)
        found = _hits(head, rules["semiconductor_terms"]) + _hits(head, rules["semiconductor_core"])
        if not found:
            continue
        if _hits(clause, rules["application_markers"]) and not _hits(clause, rules["semiconductor_supply_nouns"]):
            continue  # 반도체가 고객 산업으로만 나온다
        semi += found
    if industry_semi or semi:
        excluded = _hits(joined, rules["semiconductor_exclusions"])
        if excluded and not _hits(joined, rules["semiconductor_core"]):
            return {"decision": "not_theme", "theme": None,
                    "evidence": f"반도체 후보이나 제외 업종 {', '.join(excluded)}"}
        return {"decision": "counted", "theme": "semiconductor",
                "evidence": ("산업 분류 " + industry.strip()) if industry_semi
                else "사업 설명 " + ", ".join(sorted(set(semi)))}
    ai: list[str] = []
    for clause in clauses:
        found = _hits(first_item(clause, rules), rules["ai_terms"])
        if not found:
            continue
        if (_hits(clause, rules["application_markers"]) or _hits(clause, rules["enabling_tech"])
                or _hits(clause, rules["ai_hardware_exclusions"])):
            continue
        ai += found
    if ai:
        return {"decision": "counted", "theme": "ai", "evidence": "사업 설명 " + ", ".join(sorted(set(ai)))}
    return {"decision": "not_theme", "theme": None, "evidence": "사업 설명 첫 문장에 AI·반도체 제품 없음"}


# ── 사업 설명 수집 (네트워크) ───────────────────────────────────────────────


def _em_rows(url_template: str, field: str, value: str, get: Callable[..., bytes]) -> list[dict[str, Any]]:
    flt = urllib.parse.quote(f'({field}="{value}")')
    payload = json.loads(get(url_template.format(filter=flt)).decode("utf-8"))
    result = payload.get("result") if isinstance(payload, dict) else None
    return list((result or {}).get("data") or [])


def _earlier_listing(rows: list[dict[str, Any]], listing_date: str) -> str | None:
    """같은 법인의 다른 시장 상장 중 이번 상장보다 먼저인 것. Eastmoney 는 신청만 한 회사에 임시 코드
    (H2491.HK·A18091.SH)와 빈 상장일을 준다 — 실제 숫자 코드와 상장일이 있는 행만 상장으로 본다."""
    for item in rows:
        code = str(item.get("SECUCODE") or "")
        listed = str(item.get("LISTING_DATE") or "")[:10]
        real_code = re.fullmatch(r"\d{4,6}\.(HK|SH|SZ|BJ)", code)
        if real_code and re.fullmatch(r"\d{4}-\d{2}-\d{2}", listed) and listed < listing_date:
            return code
    return None


def _pdf_text(raw: bytes) -> str:
    """표준 라이브러리만으로 PDF 텍스트를 뽑는다(Flate 스트림 + ToUnicode CMap). JPX 영문 개요 전용."""
    streams = []
    for match in re.finditer(rb"(<<(?:(?!>>).)*?>>)\s*stream\r?\n", raw, re.S):
        start = match.end()
        body = raw[start:raw.find(b"endstream", start)]
        if b"/FlateDecode" in match.group(1):
            try:
                body = zlib.decompressobj().decompress(body)
            except zlib.error:
                continue
        streams.append(body)
    cmap: dict[int, str] = {}
    for body in streams:
        for block in re.findall(rb"beginbfchar(.*?)endbfchar", body, re.S):
            for code, uni in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                cmap[int(code, 16)] = bytes.fromhex(uni.decode()).decode("utf-16-be", "ignore")
        for block in re.findall(rb"beginbfrange(.*?)endbfrange", body, re.S):
            for low, high, uni in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                for offset, code in enumerate(range(int(low, 16), int(high, 16) + 1)):
                    cmap[code] = chr(int(uni, 16) + offset)
    parts = []
    for body in streams:
        if b"BT" not in body:
            continue
        for literal in re.findall(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]+>", body):
            if literal.startswith(b"("):
                parts.append(literal[1:-1].decode("latin-1"))
            else:
                hexes = re.sub(rb"\s", b"", literal[1:-1]).decode()
                step = 4 if len(hexes) % 4 == 0 else 2
                parts.append("".join(cmap.get(int(hexes[i:i + step], 16), "") for i in range(0, len(hexes), step)))
    return re.sub(r"\s+", " ", re.sub(r"en-(GB|US)", "", "".join(parts)))


def parse_jpx_outline(text: str) -> dict[str, str]:
    business = re.search(r"Description of Business\s+(.*?)\s+Category of Industry", text)
    listed = re.search(r"Current Listed Market\s+(.*?)\s+Name", text)
    company = re.search(r"Company Name\s+(.*?)\s+Scheduled Listing Date", text)
    return {"business": business.group(1).strip() if business else "",
            "current_listed_market": listed.group(1).strip() if listed else "",
            "company_en": company.group(1).strip() if company else ""}


def jpx_outline_links(html: str) -> dict[str, str]:
    """JPX 영문 신규상장 표 — 코드 → 영문 개요 PDF 경로."""
    links: dict[str, str] = {}
    for match in re.finditer(r'<span id="([0-9A-Z]{4})"></span>(.*?)</tr>', html, re.S):
        pdf = re.search(r'href="([^"]*OutlineEN\.pdf)"', match.group(2))
        if pdf:
            links[match.group(1)] = JPX_ROOT + pdf.group(1)
    return links


def enrich(row: dict[str, Any], *, get: Callable[..., bytes], jpx_links: dict[str, str] | None = None) -> dict[str, Any]:
    """상장 1건의 사업 설명·산업 분류·첫 상장 여부 단서를 원천에서 모은다. 실패는 text='' 로 남긴다."""
    venue, code = row["venue"], row["code"]
    out: dict[str, Any] = {"text": "", "industry": "", "prior_listing": None, "company_en": "", "text_source": None,
                           "fields": []}
    if venue == "cn_a":
        suffix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(row["exchange"], "")
        rows = _em_rows(EM_A_F10_URL, "SECUCODE", f"{code}.{suffix}", get)
        info = rows[0] if rows else {}
        out["industry"] = " ".join(filter(None, [row.get("industry"), info.get("EM2016")]))
        out["fields"] = [field for field in (row.get("business"), info.get("MAIN_BUSINESS")) if field]
        out["text_source"] = row.get("source_url")
        if info.get("ORG_NAME"):
            earlier = _earlier_listing(_em_rows(EM_HK_F10_URL, "ORG_NAME", info["ORG_NAME"], get), row["listing_date"])
            out["prior_listing"] = f"HKEX {earlier}" if earlier else None
    elif venue == "hk_main":
        rows = _em_rows(EM_HK_F10_URL, "SECUCODE", f"{code}.HK", get)
        info = rows[0] if rows else {}
        out["industry"] = str(info.get("BELONG_INDUSTRY") or "")
        out["fields"] = [field for field in (info.get("MAIN_BUSINESS"), str(info.get("ORG_PROFILE") or "")[:600]) if field]
        out["company_en"] = str(info.get("ORG_EN_ABBR") or "")
        out["text_source"] = f"https://emweb.securities.eastmoney.com/PC_HKF10/pages/home/index.html?code={code}"
        if info.get("ORG_NAME"):
            earlier = _earlier_listing(_em_rows(EM_A_F10_URL, "ORG_NAME", info["ORG_NAME"], get), row["listing_date"])
            out["prior_listing"] = f"A주 {earlier}" if earlier else None
    elif venue == "kr":
        out["industry"] = row.get("industry") or ""
        out["fields"] = [row["business"]] if row.get("business") else []
        out["text_source"] = row.get("source_url")
    elif venue in {"tw_twse", "tw_tpex"}:
        body = json.dumps({"companyId": code}).encode()
        payload = json.loads(get(MOPS_URL, data=body, content_type="application/json").decode("utf-8"))
        result = payload.get("result") or {}
        out["industry"] = str((result.get("industryCategory") or {}).get("value") or "")
        main = str((result.get("mainBusiness") or {}).get("value") or "")
        out["fields"] = [main] if main else []
        out["company_en"] = str((result.get("companyEnglishName") or {}).get("value") or "")
        out["text_source"] = f"https://mops.twse.com.tw/mops/#/web/t05st03?companyId={code}"
    elif venue == "jp":
        link = (jpx_links or {}).get(code)
        if link:
            outline = parse_jpx_outline(_pdf_text(get(link)))
            out["fields"] = [outline["business"]] if outline["business"] else []
            out["company_en"] = outline["company_en"]
            out["text_source"] = link
            market = outline["current_listed_market"]
            out["prior_listing"] = market if market and market.upper() not in {"N/A", "NA", "-"} else None
    out["text"] = " ".join(out["fields"])
    return out


# ── 판정 기록 ────────────────────────────────────────────────────────────


def _pipeline_match(row: dict[str, Any], pipeline: list[dict[str, str]]) -> dict[str, str] | None:
    from .theme_listing_watch import _name_keys

    names = _name_keys(row["company"]) | (_name_keys(row["company_en"]) if row.get("company_en") else set())
    for item in pipeline:
        keys = {key for key in _name_keys(item["company"])
                if len(key) >= (2 if re.search(r"[㐀-鿿]", key) else 5)}
        if any(key in name for key in keys for name in names):
            return item
    return None


def _ticker(row: dict[str, Any]) -> str:
    if row["venue"] == "hk_main":
        return f"{row['code']}.HK"
    if row["venue"] == "kr" and len(row["code"]) == 5:
        return row["code"] + "0"
    return row["code"]


def plan_decision(row: dict[str, Any], enriched: dict[str, Any], rules: dict[str, Any],
                  pipeline: list[dict[str, str]]) -> dict[str, Any]:
    """절차 2~7단계 — 기록하지 않고 판정만 돌려준다(시험·일치도 측정이 같은 함수를 쓴다)."""
    if enriched.get("prior_listing"):
        return {"decision": "not_first_listing", "theme": None, "evidence": f"먼저 상장: {enriched['prior_listing']}"}
    if row["venue"] in {"tw_twse", "tw_tpex"} and re.search(r"投控|投資控股", row["company"]):
        return {"decision": "no_offering", "theme": None, "evidence": "지주사 전환 상장(投控)"}
    matched = _pipeline_match({**row, "company_en": enriched.get("company_en", "")}, pipeline)
    if matched:
        return {"decision": "counted", "theme": matched["theme"], "evidence": f"상장 대기 목록 {matched['company']}",
                "pipeline": matched["company"]}
    if not str(enriched.get("text") or "").strip() and not str(enriched.get("industry") or "").strip():
        return {"decision": "no_text", "theme": None, "evidence": "사업 설명을 얻지 못함"}
    names = [name for name in (row["company"], enriched.get("company_en")) if name]
    return decide([*names, *(enriched.get("fields") or [])], str(enriched.get("industry") or ""), rules)


def _append_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        for row in rows:
            writer.writerow(row)


def apply_auto_review(root: Path, listings: list[dict[str, Any]], *, get: Callable[..., bytes],
                      reviewed_at: str, jpx_links: dict[str, str] | None = None) -> dict[str, Any]:
    """pending_review 상장마다 판정을 기록한다. 원천 실패는 그 상장만 다음 실행으로 미룬다."""
    from .theme_listing_watch import REVIEW_FIELDS, REVIEWS_RELATIVE, _FETCH_ERRORS

    rules = load_rules(root)
    pipeline = load_theme_listing_pipeline(root)
    additions = load_theme_listing_additions(root)
    taken = {(row["era"], _company_key(row["company"])) for row in additions}
    new_additions: list[dict[str, str]] = []
    new_reviews: list[dict[str, str]] = []
    removed_pipeline: list[str] = []
    outcomes: dict[str, int] = {}
    for row in listings:
        if row.get("status") != "pending_review":
            continue
        try:
            enriched = enrich(row, get=get, jpx_links=jpx_links)
        except _FETCH_ERRORS as exc:
            row["auto_review"] = {"decision": "no_text", "evidence": f"원천 실패 {type(exc).__name__}"}
            outcomes["no_text"] = outcomes.get("no_text", 0) + 1
            continue
        verdict = plan_decision(row, enriched, rules, pipeline)
        row["auto_review"] = {**verdict, "text": str(enriched.get("text") or "")[:240],
                              "industry": enriched.get("industry"), "text_source": enriched.get("text_source")}
        outcomes[verdict["decision"]] = outcomes.get(verdict["decision"], 0) + 1
        source = enriched.get("text_source") or row["source_url"]
        if verdict["decision"] == "counted":
            company = row["company"] if not enriched.get("company_en") else f"{enriched['company_en']} ({row['company']})"
            key = ("ai", _company_key(company))
            if key in taken:
                # 다른 회사와 이름 키가 겹치면 이중 계상 위험 — 규칙대로 불분명 처리(세지 않는다).
                new_reviews.append({"venue": row["venue"], "code": row["code"], "company": row["company"],
                                    "listing_date": row["listing_date"], "decision": "unclear",
                                    "reason": f"{NOTE_PREFIX} 명단의 다른 회사와 이름 키 충돌 — 세지 않음",
                                    "source_url": source, "reviewed_at": reviewed_at, "reviewer": REVIEWER})
                continue
            taken.add(key)
            new_additions.append({
                "month": row["listing_date"][:7], "era": "ai", "theme": verdict["theme"], "subtheme": "auto",
                "company": company, "ticker": _ticker(row), "exchange": row["exchange"], "board": row["board"],
                "market_country": row["country"], "instrument": "ordinary", "listing_scope": "foreign_primary",
                "proceeds_usd_m": "", "source_url": source,
                "note": f"{NOTE_PREFIX} {verdict['evidence']}; listed {row['listing_date']}",
            })
            if verdict.get("pipeline"):
                removed_pipeline.append(verdict["pipeline"])
        elif verdict["decision"] != "no_text":
            new_reviews.append({"venue": row["venue"], "code": row["code"], "company": row["company"],
                                "listing_date": row["listing_date"], "decision": verdict["decision"],
                                "reason": f"{NOTE_PREFIX} {verdict['evidence']}"[:300], "source_url": source,
                                "reviewed_at": reviewed_at, "reviewer": REVIEWER})
    _append_csv(root / THEME_LISTING_RELATIVE, THEME_LISTING_FIELDS, new_additions)
    _append_csv(root / REVIEWS_RELATIVE, REVIEW_FIELDS, new_reviews)
    if removed_pipeline:
        kept = [row for row in pipeline if row["company"] not in removed_pipeline]
        with (root / THEME_PIPELINE_RELATIVE).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=THEME_PIPELINE_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(kept)
    # 기록 직후 로더 규칙으로 다시 읽는다 — 자동 행이 명단 규칙을 깨면 여기서 멈춘다.
    load_theme_listing_additions(root)
    return {"rules": RULES_RELATIVE.as_posix(), "reviewer": REVIEWER, "outcomes": dict(sorted(outcomes.items())),
            "added": len(new_additions), "reviewed": len(new_reviews), "pipeline_moved": removed_pipeline}
