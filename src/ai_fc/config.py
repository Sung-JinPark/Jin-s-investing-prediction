"""경로·모델·예산 설정. 환경변수(.env) 우선, 그다음 기본값."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 프로젝트 루트: src/ai_fc/config.py → 2단계 위
ROOT = Path(__file__).resolve().parent.parent.parent

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


# ── LLM ──────────────────────────────────────────────────────────
REASONING_MODEL = os.environ.get("AI_FC_REASONING_MODEL", "claude-opus-4-8")
# 추론 K회 실행 중앙값 (ARCHITECTURE §2-④ — "단일 실행은 불안정" 업계 공통 결론).
# 기본 1 = SingleRun. K>1 활성화는 P2 게이트(해소 30+) 후 사용자 결정 (C9).
REASONING_RUNS = int(os.environ.get("AI_FC_REASONING_RUNS", "1"))
# 섀도 extremization 계수 (AIA/Neyman-Roughgarden α=√3) — 표시 전용, 공식 확률 아님.
# 실 보정(Platt/isotonic)은 해소 100+ ML 게이트 뒤 (섀도 열로 사전 성능 비교용).
EXTREMIZE_ALPHA = 3 ** 0.5
RESEARCH_MODEL = os.environ.get("AI_FC_RESEARCH_MODEL", "claude-opus-4-8")
PROMPT_VERSION = "reasoning_core_v1"

# 가격 ($/MTok) — 비용 추정용. 모델 변경 시 갱신.
PRICES = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
}

WEB_SEARCH_MAX_USES = int(os.environ.get("AI_FC_SEARCH_MAX_USES", "8"))
# v3 WS-B 경량(lite) 티어 — 검색량·분량만 축소 (에이전트 수·데블스·스키마 불변, 헌법 준수).
# 목표 단가 $1.2~1.8 (표준 $2.5~4). 적용: registry `tier: lite` (시리즈 E/M 질문 한정).
LITE_SEARCH_MAX_USES = int(os.environ.get("AI_FC_LITE_SEARCH_MAX_USES", "4"))
LITE_RESEARCH_WORDS = 450       # 표준 900 — profiles 공통 규칙의 분량 지시만 치환
LLM_MAX_RETRIES = 3
RESEARCH_MAX_TOKENS = 16000
REASONING_MAX_TOKENS = 16000

# ── 예산 (USD) ────────────────────────────────────────────────────
DEFAULT_PIPELINE_BUDGET = float(os.environ.get("AI_FC_PIPELINE_BUDGET", "4.00"))
# 사용자 결정 2026-07-20: 월 상한 $20 (기존 $100에서 하향).
# 함의: 월 실행 가능 예측 ~5~8회 — WS1 표본 속도 목표(월 8~12 해소)와 상충하므로
# 우선순위 규율 필수 (FACTORY_GUIDE §3 개정). 초과 시 프리플라이트 자동 차단.
MONTHLY_BUDGET = float(os.environ.get("AI_FC_MONTHLY_BUDGET", "20.00"))

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
