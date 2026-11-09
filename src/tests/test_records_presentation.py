"""기록 화면의 쉬운 표현과 원본 보존 계약을 실제 공개 기록으로 검증한다.

No database is opened here.  The JavaScript display adapters run in an isolated
Node VM against copies of the registry, forecast files and append-only journal.
"""

from __future__ import annotations

import collections
import html
import json
import re
import subprocess
from decimal import Decimal
from pathlib import Path

import frontmatter
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
PARTS = ROOT / "src" / "ai_fc" / "dashboard_parts"


@pytest.fixture(scope="module")
def records_corpus() -> dict:
    registry = yaml.safe_load((ROOT / "questions" / "registry.yaml").read_text(encoding="utf-8"))
    questions = [
        {**row, "resolution": row.get("resolution", "").strip()}
        for row in registry["questions"]
    ]
    forecasts = []
    for path in sorted((ROOT / "forecasts").rglob("*.md")):
        if path.stem.endswith("_evidence") or path.stem.upper() == "TEMPLATE" or "retro" in path.parts:
            continue
        post = frontmatter.load(str(path))
        forecasts.append({
            **post.metadata,
            "body": post.content.strip(),
            "source_uri": path.relative_to(ROOT).as_posix(),
        })
    changes = [
        json.loads(line)
        for line in (ROOT / "data" / "method_changes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # A shrinking audit corpus must be deliberate; new public records are
    # automatically included without maintaining a second copy of their text.
    assert len(questions) >= 79
    assert len(forecasts) >= 61
    assert len(changes) >= 50
    return {"questions": questions, "forecasts": forecasts, "method_changes": changes}


@pytest.fixture(scope="module")
def rendered_records(records_corpus: dict) -> dict:
    program = r"""
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const context={console,URL,TextEncoder};context.window=context;context.globalThis=context;
vm.createContext(context);
for(const filename of input.scripts)vm.runInContext(fs.readFileSync(filename,'utf8'),context,{filename});
const corpus=input.corpus,before=JSON.stringify(corpus);
context.RecordsCopy.configure({questions:corpus.questions});
const questions=corpus.questions.map(q=>({
 id:q.id,title:context.RecordsCopy.title(q),criteria:context.RecordsCopy.criteria(q),
 domain:context.RecordsCopy.text(q.domain),
 drivers:(q.drivers||[]).map(d=>context.RecordsCopy.text(d)),
 source:context.RecordsCopy.text(q.resolution_source)
}));
const forecasts=corpus.forecasts.map(f=>({
 id:f.forecast_id,body:context.RecordsCopy.text(f.body,{forecast:f}),
 html:context.RecordsCopy.html(context.RecordsCopy.text(f.body,{forecast:f})),
 method:context.RecordsCopy.method(f)
}));
const methodCopy=vm.runInContext('RecordsMethodCopy',context);
const changes=corpus.method_changes.map(item=>methodCopy.get(item));
const altered={...corpus.method_changes[0],reason:corpus.method_changes[0].reason+' 원문 변경'};
const unreviewed=methodCopy.get(altered);
const unknownMethod=context.RecordsCopy.method({method:'unreviewed_internal_method_v99'});
const unknownTitle=context.RecordsCopy.title({id:'new-question',title:'unreviewed_internal_title_v99'});
const reviewIssues=context.RecordsCopy.issues();
const moneyProbes={
 koreanBillions:context.RecordsCopy.text('$70억'),
 dated:context.RecordsCopy.text('$240, 2026-07-21'),
 falling:context.RecordsCopy.text('$1,400→$1,150'),
 taiwan:context.RecordsCopy.text('NT$467.90')
};
const semanticProbes={
 btc:context.RecordsCopy.text('P(a)=1%; P(b|a)=65%; P(b | a)=65%; P(b)=50%',{forecast:{question_id:'btc-alt-mania-90d'}}),
 conditional:context.RecordsCopy.text('P(YES|A)=70%; P(YES|B)=15%',{forecast:{question_id:'nfp-jul2026-below100k'}}),
 voting:context.RecordsCopy.text('X – Y vote; Y≥1이면 YES',{forecast:{question_id:'fomc-2026-09-16-nonunanimous'}})
};
const probes=[
 '<img src=x onerror=alert(1)>',
 '[위험한 링크](javascript:alert(1))',
 '[대소문자 우회](JaVaScRiPt:alert(1))',
 '[데이터 링크](data:text/html,unsafe)',
 '[근거](https://example.org/source?a=1&b=2)',
 '## 근거 제목\n\n첫 문단입니다.\n\n- 관찰 하나\n- 관찰 둘\n\n| 기준 | 값 |\n|---|---|\n| 확률 | 25% |'
].map(value=>context.RecordsCopy.html(value));
console.log(JSON.stringify({questions,forecasts,changes,probes,moneyProbes,semanticProbes,unreviewed,altered,unknownMethod,unknownTitle,reviewIssues,unchanged:before===JSON.stringify(corpus)}));
"""
    completed = subprocess.run(
        ["node", "-e", program],
        input=json.dumps({
            "scripts": [str(PARTS / "records_copy.js"), str(PARTS / "records_method_copy.js")],
            "corpus": records_corpus,
        }, ensure_ascii=False, default=str),
        check=False, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _visible_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(value)


def _strip_source_codes(value: str, corpus: dict) -> str:
    """Remove identifiers, citations and markup numbering, never market values."""
    for row in corpus["questions"]:
        value = value.replace(row["id"], " ")
    value = re.sub(r"https?://[^\s)>]+", " ", value)
    value = re.sub(r"\b(?:reports|data|forecasts|src|docs)/[^\s`)]+", " ", value)
    value = re.sub(r"\b[\w.-]+\.(?:md|jsonl?|yaml|csv|py)\b", " ", value)
    value = re.sub(r"\b[\w.-]*_[\w.-]+\b", " ", value)
    value = re.sub(r"(?<![A-Za-z\d])(?:v\d+(?:\.\d+)*|r\d+|P[0-3]|C[1-5]|R[1-9])(?![A-Za-z\d])", " ", value, flags=re.I)
    value = re.sub(r"\b(?:10-[QK]|[68]-K|Ex-99\.1|424B\d?|144A|S-1|Z\.1|T-11)(?![A-Za-z\d])", " ", value, flags=re.I)
    value = re.sub(r"\bExhibit\s+99\.1\b", " ", value, flags=re.I)
    value = re.sub(r"\b[\w-]*[A-Za-z][\w-]*-\d[A-Za-z\d.-]*\b", " ", value)
    value = re.sub(r"(?:PR\s*)?#\d+|\bHTTP\s+\d+|\bDECISIONS\s+\d+-\d+|\b12-6\b", " ", value)
    value = re.sub(r"\b\d[a-fA-F\d]{7,}\b", " ", value)
    value = re.sub(r"\b(?:CIK\s*\d+|[A-Z]{2,}\d+[A-Z\d]*)\b", " ", value)
    value = re.sub(r"(?m)^\s*(?:#{1,6}\s*)?\[\d+\]\s*", " ", value)
    value = re.sub(r"(?m)^\s*\d+\.\s+", " ", value)
    value = re.sub(r"\[\d+\]", " ", value)
    return value


def _numeric_facts(value: str, corpus: dict) -> set[Decimal]:
    value = _strip_source_codes(value, corpus)
    korean_numbers = {"한": "1", "두": "2", "세": "3", "네": "4", "첫째": "1", "둘째": "2", "셋째": "3", "넷째": "4"}
    for word, number in korean_numbers.items():
        value = re.sub(rf"(?<![가-힣]){word}(?=\s*(?:개|번|회|가지|전망|계열|항목|곳|기간|번째|,))", number, value)
    return {
        Decimal(token.replace(",", ""))
        for token in re.findall(r"(?<![A-Za-z\d])\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?", value, flags=re.I)
    }


def _missing_numeric_facts(original: str, rendered: str, corpus: dict) -> set[Decimal]:
    before = _numeric_facts(original, corpus)
    after = _numeric_facts(rendered, corpus)
    # A basis point is 0.01 percentage points.  Readable titles may use the
    # latter unit, but the financial magnitude must stay identical.
    for token in re.findall(r"(\d+(?:\.\d+)?)\s*(?:bp|bps)\b", original, flags=re.I):
        basis_points = Decimal(token)
        if re.search(r"\d+(?:\.\d+)?\s*%\s*포인트", rendered) and basis_points / 100 in after:
            after.add(basis_points)
    # FY27 becomes 2027 회계연도; neither representation may change the year.
    for token in re.findall(r"\bFY(\d{2})\b|\bF?Q\d['’](\d{2})\b", original):
        token = next(part for part in token if part)
        if Decimal("20" + token) in after:
            after.add(Decimal(token))
    # End-of-year wording retains the same final calendar day.
    if re.search(r"(?:연|년\s*)말", rendered) and re.search(r"\d{4}-12-31", original):
        after.update({Decimal(12), Decimal(31)})
    for token in re.findall(r"\$?(\d+(?:\.\d+)?)B\b", original):
        if Decimal(token) * 10 in after and "억" in rendered:
            after.add(Decimal(token))
    return before - after


def test_records_adapters_leave_every_raw_record_unchanged(rendered_records: dict) -> None:
    assert rendered_records["unchanged"] is True


def test_all_question_titles_and_resolution_criteria_keep_their_numbers(
    records_corpus: dict, rendered_records: dict,
) -> None:
    failures = []
    for raw, shown in zip(records_corpus["questions"], rendered_records["questions"], strict=True):
        assert shown["title"].strip(), raw["id"]
        assert shown["criteria"].strip(), raw["id"]
        for field in ("title", "resolution"):
            missing = _missing_numeric_facts(raw.get(field, ""), shown["criteria" if field == "resolution" else field], records_corpus)
            if missing:
                failures.append((raw["id"], field, sorted(str(value) for value in missing)))
    assert not failures, f"판정 기준 또는 질문 제목에서 수치가 사라짐: {failures}"


def test_every_forecast_body_preserves_numeric_facts_and_source_links(
    records_corpus: dict, rendered_records: dict,
) -> None:
    failures = []
    for raw, shown in zip(records_corpus["forecasts"], rendered_records["forecasts"], strict=True):
        missing = _missing_numeric_facts(raw["body"], shown["body"], records_corpus)
        if missing:
            failures.append((raw["forecast_id"], sorted(str(value) for value in missing)))
        assert len(shown["body"]) >= len(raw["body"]) * 0.75, raw["forecast_id"]
        for url in re.findall(r"https?://[^\s)>]+", raw["body"]):
            assert url in shown["body"], (raw["forecast_id"], url)
        # Preserve the complete reasoning structure as well as values: no table
        # row, list observation or paragraph can disappear behind a short summary.
        for pattern in (r"(?m)^\s*\|.+\|\s*$", r"(?m)^\s*(?:[-*+] |\d+\. )"):
            assert len(re.findall(pattern, shown["body"])) >= len(re.findall(pattern, raw["body"])), raw["forecast_id"]
        assert len(re.split(r"\n\s*\n", shown["body"])) >= len(re.split(r"\n\s*\n", raw["body"])), raw["forecast_id"]
        def signed_percentages(text: str) -> collections.Counter:
            return collections.Counter(
                ("-" if sign in "−-" else "+", Decimal(number))
                for sign, number in re.findall(r"(?<![\w\d])([+−-])\s*(\d+(?:\.\d+)?)\s*%", text)
            )
        assert not (signed_percentages(raw["body"]) - signed_percentages(shown["body"])), raw["forecast_id"]
    assert not failures, f"예측 근거 전문에서 수치가 사라짐: {failures}"


def test_method_changes_have_titles_and_preserve_numeric_facts(
    records_corpus: dict, rendered_records: dict,
) -> None:
    failures = []
    for raw, shown in zip(records_corpus["method_changes"], rendered_records["changes"], strict=True):
        assert shown["title"].strip(), raw.get("event_id")
        assert shown["reason"].strip(), raw.get("event_id")
        assert shown["reviewed"] is True, raw.get("event_id")
        original = raw.get("title", "") + " " + raw.get("reason", "")
        presented = shown["title"] + " " + shown["reason"] + " " + str(raw.get("date", ""))
        missing = _missing_numeric_facts(original, presented, records_corpus)
        if missing:
            failures.append((raw.get("event_id"), sorted(str(value) for value in missing)))
    assert not failures, f"예측 방식 변경 설명에서 수치가 사라짐: {failures}"


def test_a_changed_method_source_requires_review_without_exposing_raw_copy(rendered_records: dict) -> None:
    changed = rendered_records["unreviewed"]
    assert changed["reviewed"] is False
    assert "원문 변경" not in changed["reason"]
    assert rendered_records["altered"]["reason"] not in changed["reason"]
    assert re.search(r"검토|준비|확인", changed["reason"])


def test_unknown_technical_copy_is_reported_for_review(rendered_records: dict) -> None:
    assert "unreviewed_internal" not in rendered_records["unknownMethod"]
    assert "unreviewed_internal" not in rendered_records["unknownTitle"]
    assert re.search(r"검토|확인", rendered_records["unknownMethod"])
    assert re.search(r"검토|확인", rendered_records["unknownTitle"])
    assert {issue["field"] for issue in rendered_records["reviewIssues"]} >= {"forecast.method", "question.title"}


def test_currency_copy_keeps_the_currency_unit_attached_to_its_amount(rendered_records: dict) -> None:
    money = rendered_records["moneyProbes"]
    assert re.search(r"70\s*억\s*달러", money["koreanBillions"])
    assert "달러억" not in money["koreanBillions"]
    assert re.search(r"240\s*달러\s*,\s*2026-07-21", money["dated"])
    assert re.search(r"1,400\s*달러\s*→\s*1,150\s*달러", money["falling"])
    assert re.search(r"467\.90\s*대만\s*달러", money["taiwan"])
    assert "미국 달러" not in money["taiwan"]


def test_conditional_probability_and_vote_notation_explains_the_actual_events(rendered_records: dict) -> None:
    probes = rendered_records["semanticProbes"]
    for value in probes.values():
        assert not re.search(r"\b[abABPXY]\b|\bvote\b|\bYES\b", value), value
    btc = probes["btc"]
    assert re.search(r"비트코인.*최고점.*때.*가상자산.*50%.*확률", btc)
    assert "1%" in btc and btc.count("65%") == 2 and "50%" in btc
    assert re.search(r"첫째 조건일 때.*70%", probes["conditional"])
    assert re.search(r"둘째 조건일 때.*15%", probes["conditional"])
    assert re.search(r"찬성.*반대.*표결", probes["voting"])
    assert re.search(r"반대.*1명 이상", probes["voting"])
    actual = next(row["body"] for row in rendered_records["forecasts"] if "fomc-2026-09-16-nonunanimous" in row["id"])
    assert not re.search(r"\b[XY]\b|\bvote\b", re.sub(r"https?://[^\s)>]+", " ", actual))


def test_resolution_copy_preserves_conjunction_boundaries_and_data_vintage(rendered_records: dict) -> None:
    criteria = {row["id"]: row["criteria"] for row in rendered_records["questions"]}
    conjunction = criteria["btc-alt-mania-90d"]
    assert re.search(r"두 조건.*모두|모두.*두 조건|동시에", conjunction)
    assert "1.5" in conjunction
    assert re.search(r"종가|장 마감", conjunction)
    margins = criteria["mu-margin-qoq-next"]
    assert re.search(r"직전 분기|이전 분기|전분기", margins)
    assert re.search(r"하락|낮|미만|<", margins)
    assert re.search(r"실제|보고치|발표치", margins)
    assert re.search(r"가이던스|전망|예상", margins)
    for question_id in (
        "cpi-aug2026-core-below-24", "unemployment-44-nov2026",
        "hy-oas-500bp-2026q4-2027q1", "t10y2y-100bp-by-2027-01-15",
    ):
        text = criteria[question_id]
        assert re.search(r"최초|처음|첫 공표|첫 발표", text), question_id
    credit = criteria["hy-oas-500bp-2026q4-2027q1"]
    assert "2026-09-10" in credit and "2027-01-31" in credit
    assert re.search(r"결측|누락|발표되지|없는 날|미공표|자료가 없는", credit)
    assert re.search(r"개정|수정", credit)
    boundary = criteria["adbe-eps-above-guide-top-fq4-2026"]
    assert re.search(r"상단|최고|최댓값", boundary)
    assert re.search(r"초과|높|넘|>", boundary)
    assert re.search(r"정확히|같|동일|경계", boundary)
    assert re.search(r"미실현|미발생|미충족|아니오|아님|아니다|불발|발생하지|충족하지|NO", boundary)


def test_records_do_not_expose_identifiers_revisions_or_developer_fields(
    records_corpus: dict, rendered_records: dict,
) -> None:
    opaque = re.compile(
        r"\b(?:r\d+|v\d+(?:\.\d+)*|P[0-3]|[A-Za-z]+_[A-Za-z_\d]+)\b",
        re.I,
    )
    failures = []
    surfaces = [
        *[(row["id"], " ".join(str(row[key]) for key in ("title", "criteria", "domain", "drivers", "source"))) for row in rendered_records["questions"]],
        *[(row["id"], row["body"] + " " + row["method"]) for row in rendered_records["forecasts"]],
        *[(str(index), row["title"] + " " + row["reason"]) for index, row in enumerate(rendered_records["changes"])],
    ]
    question_ids = [row["id"] for row in records_corpus["questions"]]
    for record_id, surface in surfaces:
        text = re.sub(r"https?://[^\s)>]+", " ", _visible_text(surface))
        leaks = opaque.findall(text)
        leaks.extend(identifier for identifier in question_ids if identifier in text)
        if leaks:
            failures.append((record_id, sorted(set(leaks))))
    assert not failures, f"사용자용 기록 문구에 내부 코드가 노출됨: {failures}"


def test_reasoning_html_escapes_markup_and_rejects_unsafe_links(rendered_records: dict) -> None:
    image, javascript, mixed_case, data_link, safe_link, structured = rendered_records["probes"]
    assert "<img" not in image.lower()
    assert "&lt;img" in image
    for rendered in (javascript, mixed_case, data_link):
        assert not re.search(r"href\s*=\s*[\"']\s*(?:javascript|data):", rendered, re.I)
    assert 'href="https://example.org/source?a=1&amp;b=2"' in safe_link
    assert "<h" in structured
    assert "<p>" in structured
    assert "<ul>" in structured and "<li>" in structured
    assert "<table>" in structured and "25%" in structured
