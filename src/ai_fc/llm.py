"""Anthropic 래퍼: 재시도·토큰/검색 미터링·예산 중단.

- 리서치: messages.create + 서버사이드 web_search_20260209 (pause_turn 루프 처리)
- 추론: messages.create + **직접 검증** (structured outputs)
  — messages.parse 를 쓰지 않는 이유는 reasoning_call 독스트링 참조
- 모든 호출의 비용을 계산해 PipelineBudget에 가산. 초과 시 즉시 중단.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import anthropic
from pydantic import ValidationError

from . import config
from .schemas import ForecastResult

#: SDK 가 스키마를 API 로 보내기 전에 거치는 변환. 내부 모듈이라 이동에 대비해 방어한다.
try:  # pragma: no cover - SDK 배치에 따라 달라진다
    from anthropic.lib._parse._transform import transform_schema as _transform_schema
except Exception:  # noqa: BLE001
    _transform_schema = None


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    request_id: str | None = None
    cached_input_tokens: int = 0
    web_search_calls: int = 0


@dataclass
class PipelineBudget:
    limit_usd: float
    spent_usd: float = 0.0
    calls: list[Usage] = field(default_factory=list)

    def add(self, usage: Usage) -> None:
        self.calls.append(usage)
        self.spent_usd += usage.cost_usd

    def ensure_room(self, stage: str) -> None:
        if self.spent_usd >= self.limit_usd:
            raise BudgetExceeded(
                f"파이프라인 예산 초과: ${self.spent_usd:.2f} >= ${self.limit_usd:.2f} ({stage} 전 중단)")


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = config.PRICES.get(model, (5.0, 25.0))
    return input_tokens / 1e6 * in_price + output_tokens / 1e6 * out_price


def _usage_of(resp, model: str) -> Usage:
    u = resp.usage
    inp = (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) \
        + (getattr(u, "cache_read_input_tokens", 0) or 0) // 10  # 캐시 읽기는 ~0.1x
    out = u.output_tokens or 0
    return Usage(inp, out, _cost(model, inp, out))


def _with_retries(fn):
    last = None
    for attempt in range(config.LLM_MAX_RETRIES):
        try:
            return fn()
        except (anthropic.RateLimitError, anthropic.InternalServerError,
                anthropic.APIConnectionError) as exc:
            last = exc
            time.sleep(2 ** attempt * 2)
        # BadRequest 등 4xx는 재시도 없이 즉시 전파
    raise last


def research_call(client: anthropic.Anthropic, system: str, user: str,
                  budget: PipelineBudget,
                  max_search_uses: int | None = None) -> tuple[str, int, Usage]:
    """웹서치 리서치 1회. (본문 텍스트, 검색결과 블록 수, 사용량) 반환.

    max_search_uses: per-call 검색 상한 (v3 WS-B lite 티어) — None이면 전역 기본.
    검색이 전멸(성공 0건 + 오류 블록 존재 — 분당 검색 한도 초과 등)하면
    65초 냉각 후 1회 재실행한다. 재시도 비용도 예산에 정직하게 가산.
    """
    model = config.RESEARCH_MODEL
    search_limit = max_search_uses if max_search_uses is not None \
        else config.WEB_SEARCH_MAX_USES
    total = Usage()

    for search_attempt in range(2):
        budget.ensure_room("research")
        messages = [{"role": "user", "content": user}]
        text_parts: list[str] = []
        n_sources = 0
        n_search_errors = 0

        for _ in range(5):  # pause_turn 연속 재개 상한
            resp = _with_retries(lambda: client.messages.create(
                model=model,
                max_tokens=config.RESEARCH_MAX_TOKENS,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                tools=[{"type": "web_search_20260209", "name": "web_search",
                        "max_uses": search_limit}],
                messages=messages,
            ))
            u = _usage_of(resp, model)
            total = Usage(total.input_tokens + u.input_tokens,
                          total.output_tokens + u.output_tokens,
                          total.cost_usd + u.cost_usd)
            budget.add(u)

            for block in resp.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "web_search_tool_result":
                    content = block.content
                    if isinstance(content, list):  # 오류 시 객체, 성공 시 리스트
                        n_sources += len(content)
                    else:
                        n_search_errors += 1

            if resp.stop_reason == "pause_turn":
                messages = messages + [{"role": "assistant", "content": resp.content}]
                continue
            if resp.stop_reason == "refusal":
                raise RuntimeError("리서치 호출이 refusal로 종료됨")
            break

        if n_sources == 0 and n_search_errors > 0 and search_attempt == 0:
            time.sleep(65)  # 분당 검색 한도 냉각
            continue
        return "\n".join(text_parts).strip(), n_sources, total

    return "\n".join(text_parts).strip(), n_sources, total


def structured_call(client: anthropic.Anthropic, system: str, user: str,
                    budget: PipelineBudget, output_format,
                    max_tokens: int = 2000):
    """소형 구조화 호출 (WS6 divergence 사후 리뷰 등). 파싱 실패 시 예외."""
    budget.ensure_room("structured")
    model = config.REASONING_MODEL
    resp = _with_retries(lambda: client.messages.parse(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        output_format=output_format))
    usage = _usage_of(resp, model)
    budget.add(usage)
    parsed = resp.parsed_output
    if parsed is None:
        raise RuntimeError("structured 출력 파싱 실패")
    return parsed, usage


#: 계약 위반 시 **단 한 번** 붙이는 교정 지시. 확률을 바꾸라고 하지 않는다.
CONTRACT_RETRY_HINT = """

---
[계약 교정 — 직전 출력이 산술 계약을 위반했다]
위반 내용: {error}

**최종 확률(probability)은 절대 바꾸지 마라.** 고쳐야 하는 것은 판단이 아니라 **기록**이다.
절차 [4] 프리모템에서 확률을 재조정했다면, 그 재조정을 `adjustments` 에 항목으로 **추가**해
`anchor_pct + Σ(부호 있는 delta_pp) == probability` 가 성립하게 만들어라.
같은 확률 그대로, 조정 항목만 빠짐없이 채워 다시 출력하라."""


def _dump_reasoning_raw(attempt: int, text: str) -> None:
    """추론 원문을 스크래치에 남긴다. 실패해도 파이프라인을 막지 않는다.

    이 덤프가 없으면 계약 위반으로 죽었을 때 **무엇이 왜 틀렸는지 알 길이 없다** —
    2026-09-11 실측에서 정확히 그 상태였다.
    """
    try:
        scratch = config.SCRATCH_DIR
        scratch.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (scratch / f"{stamp}_reasoning_attempt{attempt}.json").write_text(text, encoding="utf-8")
    except Exception:  # noqa: BLE001 - 진단 보조는 파이프라인을 막지 않는다
        pass


def json_output_format() -> dict | None:
    """`messages.parse` 가 서버로 보내는 것과 **동일한** `output_config.format` 객체.

    parse 의 구성(resources/messages/messages.py)을 그대로 따른다:
        schema = TypeAdapter(output_format).json_schema()
        JSONOutputFormatParam(schema=transform_schema(schema), type="json_schema")

    래퍼(`type: json_schema`)를 빼먹으면 서버가 400 으로 거절한다
    (`output_config.format.type: Input should be 'json_schema'`) — 2026-09-11 실측.
    그래서 이 구성은 테스트에서 parse 의 실제 전송 바디와 대조해 고정한다.
    """
    if _transform_schema is None:
        return None
    from pydantic import TypeAdapter

    schema = TypeAdapter(ForecastResult).json_schema()
    return {"type": "json_schema", "schema": _transform_schema(schema)}


def _reasoning_once(client: anthropic.Anthropic, system: str, user: str,
                    budget: PipelineBudget, model: str, attempt: int) -> tuple[str, Usage]:
    """추론 API 1회. **응답을 받으면 무엇이 실패하든 비용을 먼저 계상한다.**"""
    output_config: dict = {"effort": "high"}
    fmt = json_output_format()
    if fmt is not None:
        output_config["format"] = fmt

    resp = _with_retries(lambda: client.messages.create(
        model=model,
        max_tokens=config.REASONING_MAX_TOKENS,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],  # 다질문 연속 실행 시 캐시
        thinking={"type": "adaptive"},
        output_config=output_config,
        messages=[{"role": "user", "content": user}],
    ))
    usage = _usage_of(resp, model)
    budget.add(usage)          # ← 검증보다 먼저. 응답은 이미 과금됐다.

    text = "".join(block.text for block in (resp.content or [])
                   if getattr(block, "type", None) == "text")
    _dump_reasoning_raw(attempt, text)

    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("추론 호출이 refusal로 종료됨")
    if not text.strip():
        raise RuntimeError("추론 출력이 비어 있다 — 기록하지 않고 중단")
    return text, usage


def _peek_probability(text: str) -> int | None:
    """계약 검증 **전에** 확률만 훔쳐본다 — 교정 재시도가 판단을 바꿨는지 감시하려고."""
    try:
        value = json.loads(text).get("probability")
    except Exception:  # noqa: BLE001
        return None
    return value if isinstance(value, int) else None


def reasoning_call(client: anthropic.Anthropic, system: str, user: str,
                   budget: PipelineBudget) -> tuple[ForecastResult, Usage]:
    """추론 코어 1회 — structured output 강제. 파싱 실패 시 예외 (숫자 추측 금지).

    ## 왜 `messages.parse` 를 쓰지 않는가 (2026-09-11 실측 결함)

    SDK 의 `messages.parse` 는 HTTP 응답을 받은 뒤 **post-parser 안에서**
    `TypeAdapter(ForecastResult).validate_json` 을 돌린다. 그런데 `ForecastResult` 는
    `@model_validator` 로 `anchor_pct + Σ(부호 있는 delta_pp) == probability` 항등식을
    강제하고, 이 **교차 필드 항등식은 JSON Schema 로 표현할 수 없어 서버가 막아주지
    못한다** (SDK 의 `transform_schema` 는 `minimum`/`maximum` 조차 description 문자열로
    강등한다). 즉 계약 전량이 클라이언트 전용이다.

    결과: 위반 응답이 오면 `ValidationError` 가 `messages.parse` **안에서** 터져
    `budget.add()` 에 도달하지 못한다. 응답은 이미 과금됐는데 **사용량도 원문도 남지
    않아** 사후 진단이 불가능하다. 2026-09-11 `asml-eps-beat-2026q3` 실행이 정확히 이
    경로로 죽었다 — `cost_log.csv` 에 리서치 2행만 남고 추론 행이 없었다($1.564 소모,
    기록 0). OpenAI 경로는 `budget.add` 가 `model_validate` 보다 먼저라 같은 위반이
    3행을 남기므로, 이 비대칭 때문에 결함이 두 달간 드러나지 않았다.

    그래서 `create` 로 받아 **먼저 계상하고 원문을 남긴 뒤** 검증한다.

    ## 교정 재시도는 기록을 고치지 판단을 고치지 않는다

    항등식 위반은 대개 **기록 누락**이다 — 절차 [4] 프리모템에서 확률을 재조정하고도
    그 재조정을 `adjustments` 에 적지 않으면 합이 안 맞는다. 그래서 한 번만, 확률을
    바꾸지 말라고 명시해 재요청한다. 재시도가 확률을 바꾸면 **그 자체를 실패로 본다** —
    교정이 판단을 움직이면 그건 교정이 아니다.
    """
    budget.ensure_room("reasoning")
    model = config.REASONING_MODEL

    text, usage = _reasoning_once(client, system, user, budget, model, attempt=1)
    try:
        parsed = ForecastResult.model_validate_json(text)
    except ValidationError as exc:
        first_probability = _peek_probability(text)
        budget.ensure_room("reasoning:contract-retry")
        retry_user = user + CONTRACT_RETRY_HINT.format(error=str(exc)[:500])
        text, usage = _reasoning_once(client, system, retry_user, budget, model, attempt=2)
        parsed = ForecastResult.model_validate_json(text)   # 또 터지면 그대로 전파
        if first_probability is not None and parsed.probability != first_probability:
            raise RuntimeError(
                f"계약 교정 재시도가 확률을 바꿨다: {first_probability} → {parsed.probability}. "
                "교정은 기록을 고치는 것이지 판단을 고치는 것이 아니다 — 기록하지 않고 중단"
            ) from exc

    if not (1 <= parsed.probability <= 99) or parsed.ci80_lo > parsed.ci80_hi:
        raise RuntimeError(f"추론 출력 검증 실패: p={parsed.probability}, "
                           f"ci=[{parsed.ci80_lo},{parsed.ci80_hi}]")
    return parsed, usage
