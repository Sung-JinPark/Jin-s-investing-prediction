"""경로·모델·예산 설정. 환경변수(.env) 우선, 그다음 기본값."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# 프로젝트 루트: src/ai_fc/config.py → 2단계 위
ROOT = Path(__file__).resolve().parent.parent.parent
PUBLIC_REPOSITORY_URL = os.getenv(
    "AI_FC_PUBLIC_REPOSITORY_URL",
    "https://github.com/sung-jinpark/Jin-s-investing-prediction",
)

FORECASTS_DIR = ROOT / "forecasts"
QUESTIONS_REGISTRY = ROOT / "questions" / "registry.yaml"
LEDGER_CSV = ROOT / "calibration" / "ledger.csv"
PROMPTS_DIR = ROOT / "prompts"
BASE_RATES_DIR = ROOT / "data" / "base_rates"
REPORTS_DIR = ROOT / "reports"
DB_PATH = ROOT / "db" / "index.db"
SCRATCH_DIR = ROOT / "db" / "scratch"  # dry-run·부분 증거 덤프 (gitignore)
LOCKFILE = ROOT / "db" / ".ai_fc.lock"

TZ_NAME = "Asia/Seoul"  # 모든 타임스탬프는 KST

# ── API 키 (환경변수 → DPAPI 암호화 파일 순) ──────────────────────
# 저장: PowerShell에서 ProtectedData::Protect(CurrentUser)로 1회 암호화.
# 사용자 계정에 바운드 — 평문 파일·레지스트리에 키가 남지 않는다.
API_KEY_FILE = Path.home() / ".ai_fc" / "anthropic_key.dpapi"


def _dpapi_decrypt(data: bytes) -> bytes:
    import ctypes
    import ctypes.wintypes as wt

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI 복호화 실패 — 다른 사용자 계정이거나 파일 손상")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def get_api_key() -> str | None:
    """ANTHROPIC_API_KEY 환경변수 우선, 없으면 DPAPI 파일 복호화."""
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env:
        return env
    import sys
    if sys.platform == "win32" and API_KEY_FILE.exists():
        return _dpapi_decrypt(API_KEY_FILE.read_bytes()).decode("utf-8").strip()
    return None


def get_openai_api_key() -> str | None:
    """Return the OpenAI key from the environment without persisting or printing it."""
    return os.environ.get("OPENAI_API_KEY") or None


# ── LLM ──────────────────────────────────────────────────────────
REASONING_MODEL = os.environ.get("AI_FC_REASONING_MODEL", "claude-opus-4-8")
# 추론 K회 실행 중앙값 (ARCHITECTURE §2-④ — "단일 실행은 불안정" 업계 공통 결론).
# 기본 1 = SingleRun. K>1 활성화는 P2 게이트(해소 30+) 후 사용자 결정 (C9).
REASONING_RUNS = int(os.environ.get("AI_FC_REASONING_RUNS", "1"))
# 섀도 extremization 계수 (AIA/Neyman-Roughgarden α=√3) — 표시 전용, 공식 확률 아님.
# 실 보정(Platt/isotonic)은 해소 100+ ML 게이트 뒤 (섀도 열로 사전 성능 비교용).
EXTREMIZE_ALPHA = 3 ** 0.5
RESEARCH_MODEL = os.environ.get("AI_FC_RESEARCH_MODEL", "claude-opus-4-8")
# T07-3 (2026-09-11) — 추론 코어 v1.1. 프리모템에 필수 3항(전제 개정 취약성·컨센 유무·임계 z)을
# 추가했다. **가중 학습 아님** — 프롬프트 절차 변경이고 ML 게이트와 무관하다.
# 예측 파일 frontmatter 의 prompt_version 이 v1 코호트와 v1.1 코호트를 구별해 준다.
PROMPT_VERSION = os.environ.get("AI_FC_PROMPT_VERSION", "reasoning_core_v1_1")

# 가격 ($/MTok) — 비용 추정용. 모델 변경 시 갱신.
PRICES = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    # OpenAI list prices verified from official model cards on 2026-08-01.
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-luna": (0.20, 1.20),
}

# A live OpenAI shadow is opt-in. Explicit Sol/Terra/Luna tier ids and verified
# dated snapshots are accepted; moving family aliases such as gpt-5.6 are rejected.
OPENAI_SHADOW_MODEL = os.environ.get("AI_FC_OPENAI_SHADOW_MODEL", "").strip()
OPENAI_SHADOW_PIPELINE_BUDGET = float(
    os.environ.get("AI_FC_OPENAI_SHADOW_PIPELINE_BUDGET", "2.00")
)
OPENAI_REASONING_EFFORT = os.environ.get("AI_FC_OPENAI_REASONING_EFFORT", "medium")
OPENAI_SHADOW_QUESTION_IDS = frozenset(
    q.strip()
    for q in os.environ.get("AI_FC_OPENAI_SHADOW_QUESTIONS", "").split(",")
    if q.strip()
)
OFFICIAL_LLM_PROVIDER = os.environ.get("AI_FC_OFFICIAL_LLM_PROVIDER", "anthropic").strip()
OPENAI_OFFICIAL_MODEL = os.environ.get("AI_FC_OPENAI_OFFICIAL_MODEL", "").strip()

WEB_SEARCH_MAX_USES = int(os.environ.get("AI_FC_SEARCH_MAX_USES", "8"))
# v3 WS-B 경량(lite) 티어 — 검색량·분량만 축소 (에이전트 수·데블스·스키마 불변, 헌법 준수).
# 목표 단가 $1.2~1.8 (표준 $2.5~4). 적용: registry `tier: lite` (시리즈 E/M 질문 한정).
LITE_SEARCH_MAX_USES = int(os.environ.get("AI_FC_LITE_SEARCH_MAX_USES", "4"))
LITE_RESEARCH_WORDS = 450       # 표준 900 — profiles 공통 규칙의 분량 지시만 치환

# T05 (2026-09-11, 사용자 확정) — **lite 티어 은퇴.**
#
# 실측: `pipeline_tier: lite` 로 태그된 회차 4건이 전부 degraded(2) 또는 failed(2)였다.
# 같은 기간 과금 기록이 있는 cli/api 회차 4건은 4/4 가 ok. Fisher 정확검정 p=0.029.
#
# **주의 — 이 증거는 티어와 제공자를 분리하지 못한다.** lite 4건은 전부
# `openai:gpt-5.6-terra`(DECISIONS 10-4 의 자동 생산자 전환 기간, 2026-08-03~08-29)이고
# 비교군 4건은 전부 `anthropic:claude-opus-4-8` 이다. 두 축이 표본에서 완전히 겹쳐 있어
# "lite 가 나빴다"와 "openai 경로가 나빴다"를 구별할 수 없다. 그래서 은퇴 사유를
# '검색량 축소가 원인'이라고 적지 않는다 — **그 조합이 게이트급 회차를 내지 못했다**는
# 사실만 적는다. openai 경로는 이미 config 기본값에서 내려와 있다.
#
# 은퇴 방식: 레지스트리의 `tier: lite` 값은 **역사 기록으로 보존**하고, 실행 시점에
# `registry.effective_tier()` 가 standard 로 승격시킨다. 40문항을 일괄 수정하면
# "그때 무엇으로 등록했는가"가 지워진다.
LITE_TIER_RETIRED_AT = date(2026, 9, 11)
LLM_MAX_RETRIES = 3
RESEARCH_MAX_TOKENS = int(os.environ.get("AI_FC_RESEARCH_MAX_TOKENS", "16000"))
REASONING_MAX_TOKENS = int(os.environ.get("AI_FC_REASONING_MAX_TOKENS", "16000"))

# ── 예산 (USD) ────────────────────────────────────────────────────
# 회차당 상한. 실측 표준 회차 $1.92~$2.75(n=5, 2026-09-11)이므로 $4 는 상단 대비
# 45% 여유다. 내리면 회차가 중간에 끊겨 **돈만 쓰고 기록이 안 남는다** — 같은 모양의
# 손실(원인은 다른 계약 사고였다)이 2026-09-11 에 $4.24 였다. 여유는 남겨 둔다.
DEFAULT_PIPELINE_BUDGET = float(os.environ.get("AI_FC_PIPELINE_BUDGET", "4.00"))
# 사용자 결정 2026-07-20: 월 상한 $20 (기존 $100에서 하향).
# 사용자 결정 2026-09-09 (C5-A2): $20 -> $40.
# 사용자 결정 2026-09-11 (C5-A4): **$40 -> $50**. 실측 단가가 $1.7197(n=4) 에서
# $2.303(n=5) 으로 올라 주 3건(13회차/월) 케이던스가 $29.9 를 쓰는데, $40 체제에서는
# 실패·재시도 여유가 $10 뿐이었다. 상한은 **전체 지출**에 걸리며 실패분(stage=failed)도
# 포함해 센다 — 실패를 예산 밖으로 빼면 상한이 거짓말이 된다.
MONTHLY_BUDGET = float(os.environ.get("AI_FC_MONTHLY_BUDGET", "50.00"))
# 생산 경로(anthropic cli/api)는 전역 상한과 같다. **일부러 같게 둔다**: 게이트급
# 회차를 내는 생산자가 하나뿐인데 그 하나에 전역보다 낮은 캡을 걸면, 남는 금액은
# 아무도 쓸 수 없어 사용자가 정한 $50 이 사실상 그 캡으로 내려앉는다.
# 생산을 실제로 조이는 것은 아래 예비 구간 규칙과 케이던스(주 3건)다.
ANTHROPIC_MONTHLY_BUDGET = float(
    os.environ.get("AI_FC_ANTHROPIC_MONTHLY_BUDGET", str(MONTHLY_BUDGET))
)
# 자동 경로(GitHub Actions)의 openai sub-cap. $25 -> $2.
# 이 캡은 2026-09-11 까지 **아무것도 묶지 않았다** — openai 경로의 9월 지출은 $0 이고
# 마지막 생산은 2026-08-29 다. T05 가 그 조합(openai:gpt-5.6-terra + 축소 핀)을
# "게이트급 회차를 하나도 내지 못했다"(0/4 ok)로 은퇴시켰으므로, 자동 경로에서
# **유료 예측 생산을 뺐다**(investing-refresh.yml). 남은 유료 호출은 키 생존 확인용
# smoke($0.01 미만)뿐이라 캡도 거기에 맞춘다. 되살리려면 이 값과 워크플로 두 곳을
# 함께 올려야 한다 — 한 곳만 고쳐서는 다시 돌지 않는다.
OPENAI_MONTHLY_BUDGET = float(os.environ.get("AI_FC_OPENAI_MONTHLY_BUDGET", "2.00"))

# 예비 구간 — 월 상한의 마지막 20%($40~$50)는 **마감 임박 질문 전용**이다.
# 사문화된 '예비비'(쓸 수 없게 캡으로 떼어 둔 돈)가 아니라 우선순위 가드다:
# 이 구간에 들어가면 마감이 D-30 이내인 질문만 새 회차를 받는다. 막으려는 실패는
# 실측된 것이다 — `cpi-jun2026-accel` 은 예산이 앞선 질문들에 먼저 쓰여
# **첫 예측 없이 만료**했고(처리량 소실 11.1%), 무예측 만료는 게이트 분자에 0 을 더한다.
MONTHLY_BUDGET_RESERVE_RATIO = float(
    os.environ.get("AI_FC_MONTHLY_BUDGET_RESERVE_RATIO", "0.20")
)
# 예비 구간에서 통과시키는 마감 임박 기준(일). deadline 이 없는 질문(rolling·tbd)은
# 임박으로 보지 않는다 — 페일클로즈.
RESERVE_DEADLINE_DAYS = int(os.environ.get("AI_FC_RESERVE_DEADLINE_DAYS", "30"))
# 케이던스(운영 규칙, 기계 강제 아님): 주 3건 = 13회차/월 x $2.303 = $29.9 (상한의 60%).
# 근거는 docs/P1_OPERATIONS.md '비용·처리량 규율'.
WEEKLY_FORECAST_CADENCE = 3

# ── 알림 (선택) ───────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── 오픈웨이트 ML 레이어 (P1.7) ───────────────────────────────────
ML_DIVERGENCE_PP = 15          # LLM vs ML앙상블 괴리 임계 (%p) — due 표시만, 자동 실행 없음
ML_DISAGREEMENT_PP = 20        # 모델 간 불일치 임계 (%p) — 초과 시 divergence 트리거 제외
ML_REF_MAX_AGE_DAYS = 7        # ML 참조 확률 신선도 (주 1회 실행 cadence와 정합)
MARKET_REF_MAX_AGE_DAYS = 3    # 시장내재확률 신선도
BASE_RATES_DIGEST_MAX_CHARS = 1500  # 프롬프트 주입 다이제스트 하드 컷
# 수동 base rate 빈티지 경고 임계 (일) — 잠정값, 확정은 사용자 결정 AUDIT-260715 8-4.
# 경고 전용 — 차단하지 않는다.
BASE_RATE_VINTAGE_WARN_DAYS = 7
ML_HISTORY_DIR = ROOT / "data" / "ml_history"

# ── 게이트 (CLAUDE.md와 동기) ─────────────────────────────────────
GATE_P2 = {"n": 30, "brier": 0.20}
GATE_P3 = {"n": 50, "brier": 0.18}
DOMAIN_BLOCK = {"n": 10, "brier": 0.22}
STALE_DAYS = 14  # 활성 질문이 이 일수 이상 무예측이면 스테일 경보


@dataclass
class Paths:
    """테스트에서 루트를 바꿔치기할 수 있도록 경로 묶음."""

    root: Path = ROOT

    forecasts: Path = field(init=False)
    registry: Path = field(init=False)
    ledger: Path = field(init=False)
    prompts: Path = field(init=False)
    reports: Path = field(init=False)
    db: Path = field(init=False)
    scratch: Path = field(init=False)
    lockfile: Path = field(init=False)

    def __post_init__(self) -> None:
        self.forecasts = self.root / "forecasts"
        self.registry = self.root / "questions" / "registry.yaml"
        self.ledger = self.root / "calibration" / "ledger.csv"
        self.prompts = self.root / "prompts"
        self.reports = self.root / "reports"
        self.db = self.root / "db" / "index.db"
        self.scratch = self.root / "db" / "scratch"
        self.lockfile = self.root / "db" / ".ai_fc.lock"
