"""추론 호출의 계약 검증 경로를 고정한다 (2026-09-11 실측 결함).

`messages.parse` 는 SDK **안에서** `TypeAdapter(ForecastResult).validate_json` 을 돌린다.
`ForecastResult` 의 `anchor_pct + Σdelta_pp == probability` 항등식은 교차 필드 제약이라
JSON Schema 로 표현할 수 없고, 따라서 **서버가 막아주지 못한다**. 위반 응답이 오면
ValidationError 가 parse 안에서 터져 `budget.add()` 에 도달하지 못하고, 응답은 이미
과금됐는데 사용량도 원문도 남지 않는다.

2026-09-11 `asml-eps-beat-2026q3` 실행이 이 경로로 죽었다 — cost_log 에 리서치 2행만
남고 추론 행이 없었다($1.564 소모, 기록 0). 여기서 그 재발을 막는다.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_fc import llm
from ai_fc.llm import PipelineBudget
from ai_fc.schemas import ForecastResult

ROOT = Path(__file__).resolve().parents[2]


def _payload(**over) -> dict:
    """항등식을 만족하는 기준 출력. 65 + 4 − 3 − 4 − 5 = 57."""
    base = {
        "question_check": "해소 가능",
        "reference_class": "ASML 분기 실적",
        "base_rates": ["4분기 중 3회 beat", "가이던스 보수적", "수주 기록"],
        "anchor_pct": 65,
        "adjustments": [
            {"evidence": "수주 강세", "direction": "up", "delta_pp": 4},
            {"evidence": "환율 역풍", "direction": "down", "delta_pp": 3},
            {"evidence": "컨센 미형성", "direction": "down", "delta_pp": 4},
            {"evidence": "EUR/USD 환산 불확실", "direction": "down", "delta_pp": 5},
        ],
        "decomposition": "분해",
        "premortem": ["a", "b", "c"],
        "probability": 57,
        "ci80_lo": 40,
        "ci80_hi": 74,
        "key_reasons": ["r1", "r2", "r3"],
        "observables": ["o1", "o2"],
        "snapshots_filled": [],
        "unverified_notes": [],
    }
    base.update(over)
    return base


class _Resp:
    """messages.create 응답 스텁."""

    def __init__(self, text: str, *, stop_reason: str = "end_turn"):
        self.content = [SimpleNamespace(type="text", text=text)]
        self.stop_reason = stop_reason
        self.usage = SimpleNamespace(input_tokens=5000, output_tokens=2000,
                                     cache_creation_input_tokens=0,
                                     cache_read_input_tokens=0)


class _Client:
    """호출 순서를 기록하는 가짜 클라이언트. 네트워크 없음."""

    def __init__(self, texts: list[str]):
        self._texts = list(texts)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp(self._texts.pop(0))


# ── 결함의 존재 자체 ─────────────────────────────────────────────────

def test_the_identity_is_not_expressible_in_the_wire_schema() -> None:
    """서버가 못 막는다는 사실이 이 설계의 전제다 — 바뀌면 알아야 한다."""
    assert llm._transform_schema is not None, "SDK 변환 함수 경로가 바뀌었다"
    wire = json.dumps(llm._transform_schema(ForecastResult), ensure_ascii=False)
    assert "anchor_pct" in wire
    # 교차 필드 항등식은 어떤 JSON Schema 키워드로도 표현되지 않는다.
    for keyword in ('"minimum"', '"maximum"', '"exclusiveMinimum"'):
        assert keyword not in wire, f"{keyword} 가 전송 스키마에 살아 있다 — 전제 재확인 필요"


def test_contract_violation_raises_inside_the_sdk_parser() -> None:
    """messages.parse 를 쓰면 budget.add 이전에 터진다 — 그래서 쓰지 않는다."""
    from anthropic.lib._parse._response import parse_text

    with pytest.raises(ValidationError, match="must equal final probability"):
        parse_text(json.dumps(_payload(probability=52)), ForecastResult)


def test_reasoning_call_does_not_use_messages_parse() -> None:
    """독스트링은 parse 를 **설명**하므로, 실제 호출 코드만 떼어 본다."""
    source = (ROOT / "src/ai_fc/llm.py").read_text(encoding="utf-8")
    start = source.index("def _reasoning_once")
    body = source[start:source.index(chr(10) + "def ", start + 1)]
    code = [line for line in body.splitlines()
            if "client.messages" in line or "_with_retries" in line]
    assert any("client.messages.create" in line for line in code)
    assert not any("client.messages.parse" in line for line in code), \
        "추론 경로가 parse 로 돌아가면 결함이 되살아난다"


# ── 고쳐진 행동 ──────────────────────────────────────────────────────

def test_cost_is_accounted_even_when_the_contract_fails(tmp_path, monkeypatch) -> None:
    """핵심 회귀: 위반 응답도 **비용은 계상**된다. 두 번(원본+교정) 모두."""
    monkeypatch.setattr(llm.config, "SCRATCH_DIR", tmp_path / "scratch")
    bad = json.dumps(_payload(probability=52))          # 합 57 ≠ 52
    client = _Client([bad, bad])                        # 교정도 실패
    budget = PipelineBudget(limit_usd=10)

    with pytest.raises(ValidationError):
        llm.reasoning_call(client, "sys", "user", budget)

    assert len(budget.calls) == 2, "두 호출 모두 계상돼야 한다"
    assert budget.spent_usd > 0
    assert len(client.calls) == 2, "교정 재시도가 정확히 한 번"


def test_raw_output_is_dumped_on_failure(tmp_path, monkeypatch) -> None:
    """원문이 안 남으면 무엇이 왜 틀렸는지 알 길이 없다."""
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(llm.config, "SCRATCH_DIR", scratch)
    bad = json.dumps(_payload(probability=52))
    with pytest.raises(ValidationError):
        llm.reasoning_call(_Client([bad, bad]), "sys", "user", PipelineBudget(limit_usd=10))

    dumps = sorted(scratch.glob("*_reasoning_attempt*.json"))
    assert len(dumps) == 2, f"시도별 원문 덤프가 있어야 한다: {dumps}"
    assert json.loads(dumps[0].read_text(encoding="utf-8"))["probability"] == 52


def test_clean_output_needs_no_retry(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(llm.config, "SCRATCH_DIR", tmp_path / "scratch")
    client = _Client([json.dumps(_payload())])
    budget = PipelineBudget(limit_usd=10)
    parsed, usage = llm.reasoning_call(client, "sys", "user", budget)
    assert parsed.probability == 57
    assert len(client.calls) == 1 and len(budget.calls) == 1
    assert usage.cost_usd > 0


def test_retry_fixes_the_record_not_the_judgement(tmp_path, monkeypatch) -> None:
    """교정은 기록을 고친다 — 확률은 그대로 57."""
    monkeypatch.setattr(llm.config, "SCRATCH_DIR", tmp_path / "scratch")
    missing = _payload(adjustments=_payload()["adjustments"][:1])      # 65+4=69 ≠ 57
    fixed = _payload()
    client = _Client([json.dumps(missing), json.dumps(fixed)])
    parsed, _ = llm.reasoning_call(client, "sys", "user", PipelineBudget(limit_usd=10))
    assert parsed.probability == 57
    assert len(client.calls) == 2
    retry_user = client.calls[1]["messages"][0]["content"]
    assert "최종 확률(probability)은 절대 바꾸지 마라" in retry_user
    assert "must equal final probability" in retry_user, "무엇이 틀렸는지 알려줘야 한다"


def test_retry_that_moves_the_probability_is_rejected(tmp_path, monkeypatch) -> None:
    """교정이 판단을 움직이면 그건 교정이 아니다."""
    monkeypatch.setattr(llm.config, "SCRATCH_DIR", tmp_path / "scratch")
    missing = _payload(adjustments=_payload()["adjustments"][:1])      # p=57, 합 69
    moved = _payload(probability=69, ci80_lo=55, ci80_hi=80,
                     adjustments=_payload()["adjustments"][:1])        # 합을 맞추려 p 를 옮김
    client = _Client([json.dumps(missing), json.dumps(moved)])
    with pytest.raises(RuntimeError, match="확률을 바꿨다"):
        llm.reasoning_call(client, "sys", "user", PipelineBudget(limit_usd=10))
    assert len(client.calls) == 2


def test_refusal_and_empty_output_still_account_cost(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(llm.config, "SCRATCH_DIR", tmp_path / "scratch")

    class _RefusalClient(_Client):
        def _create(self, **kwargs):
            self.calls.append(kwargs)
            return _Resp(self._texts.pop(0), stop_reason="refusal")

    budget = PipelineBudget(limit_usd=10)
    with pytest.raises(RuntimeError, match="refusal"):
        llm.reasoning_call(_RefusalClient([json.dumps(_payload())]), "s", "u", budget)
    assert len(budget.calls) == 1, "거부 응답도 과금된다 — 계상돼야 한다"

    budget2 = PipelineBudget(limit_usd=10)
    with pytest.raises(RuntimeError, match="비어 있다"):
        llm.reasoning_call(_Client(["   "]), "s", "u", budget2)
    assert len(budget2.calls) == 1


# ── 프롬프트가 계약을 말해주는가 ──────────────────────────────────────

def test_prompt_states_the_arithmetic_contract() -> None:
    """모델이 모르는 규칙은 지킬 수 없다."""
    from ai_fc.reasoning_core import load_system_prompt

    text = load_system_prompt(ROOT / "prompts")
    assert "anchor_pct + Σ(부호 있는 delta_pp) == probability" in text
    flat = " ".join(text.split())          # 줄바꿈·들여쓰기를 지우고 본다
    assert "그 재조정도 adjustments 에 항목으로 기록" in flat
    assert "회차 전체가 버려진다" in flat, "위반의 대가를 말해줘야 한다"


def test_v1_1_premortem_requires_recording_the_readjustment() -> None:
    """[4] 의 '재조정한다' 가 항등식과 충돌하던 지점 — 버전 파일에 명문화한다."""
    text = (ROOT / "prompts/reasoning_core_v1_1.md").read_text(encoding="utf-8")
    assert "재조정분은 반드시 `adjustments` 에 항목으로 남긴다" in text
    assert "출력 전체가 거부된다" in text


# ── 전송 바디가 parse 와 동치인가 (2026-09-11 2차 실측 결함) ──────────

def test_output_config_is_byte_identical_to_what_parse_sends() -> None:
    """`create` 로 갈아타면서 format 래퍼를 빠뜨려 400 을 받았다.

    `output_config.format` 은 `{"type": "json_schema", "schema": ...}` 여야 하는데
    스키마만 넣어 서버가 `output_config.format.type: Input should be 'json_schema'`
    로 거절했다. 리서치 비용 $2.67 을 태우고 나서야 드러났다 — 전송 바디는
    **API 없이 대조할 수 있었다.** 그래서 여기서 고정한다.
    """
    import anthropic

    captured: dict = {}
    client = anthropic.Anthropic(api_key="sk-ant-test-not-used")

    def _fake_post(path, **kwargs):
        captured["body"] = kwargs.get("body")
        raise _Intercepted

    class _Intercepted(Exception):
        pass

    client.messages._post = _fake_post
    with pytest.raises(_Intercepted):
        client.messages.parse(
            model="claude-opus-4-8", max_tokens=100,
            system=[{"type": "text", "text": "s"}], thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            messages=[{"role": "user", "content": "u"}],
            output_format=ForecastResult)

    sent = captured["body"]["output_config"]
    mine = {"effort": "high", "format": llm.json_output_format()}
    assert sent["format"]["type"] == "json_schema"
    assert json.dumps(sent, sort_keys=True, default=str) == \
        json.dumps(mine, sort_keys=True, default=str), \
        "create 경로가 parse 와 다른 바디를 보낸다 — 서버가 거절한다"


def test_reasoning_once_actually_passes_that_config() -> None:
    """헬퍼가 맞아도 호출부가 안 쓰면 소용없다."""
    import tempfile

    from pathlib import Path as _P
    client = _Client([json.dumps(_payload())])
    with tempfile.TemporaryDirectory() as tmp:
        original = llm.config.SCRATCH_DIR
        llm.config.SCRATCH_DIR = _P(tmp)
        try:
            llm.reasoning_call(client, "sys", "user", PipelineBudget(limit_usd=10))
        finally:
            llm.config.SCRATCH_DIR = original
    cfg = client.calls[0]["output_config"]
    assert cfg["effort"] == "high"
    assert cfg["format"]["type"] == "json_schema"
    assert "properties" in cfg["format"]["schema"] or "$ref" in cfg["format"]["schema"]
