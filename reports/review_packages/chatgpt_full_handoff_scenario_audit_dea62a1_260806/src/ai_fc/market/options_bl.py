"""옵션 내재 디지털 확률 — CBOE 무인증 지연시세 → IV 스마일 보간 → N(d2).

Breeden-Litzenberger의 디지털 근사 P(S_T > K) ≈ −∂C/∂K를, 희소 호가에 강건하도록
IV 공간에서 계산한다: 행사가별 IV를 선형 보간해 스마일 조건부 Black-Scholes
N(d2)로 평가 (BL 직접 미분과 달리 지저분한 호가에 덜 민감).

정직 고지: 산출 확률은 **risk-neutral 측도** — 변동성 프리미엄 때문에 실제(physical)
확률과 체계적으로 다르다 (하방 사건은 과대, 상방은 과소 평가 경향). 참조 지위로만.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date

from ..quant.feed import _get

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
RISK_FREE = 0.04  # 근사 무위험금리 — detail에 기록
# 옵션 심볼: ROOT + YYMMDD + C/P + strike*1000 (8자리)
OSI_RE = re.compile(r"^([A-Z^]+)(\d{6})([CP])(\d{8})$")


@dataclass
class OptionChain:
    symbol: str
    spot: float
    # (expiry, strike) → iv (콜 기준, 유효 호가만)
    call_ivs: dict[tuple[date, float], float] = field(default_factory=dict)

    def expiries(self) -> list[date]:
        return sorted({e for e, _ in self.call_ivs})


def fetch_chain_cboe(symbol: str = "QQQ") -> OptionChain:
    """CBOE 지연시세 JSON → 콜 IV 체인. 유효 IV(>0)와 양방 호가만 채택."""
    data = json.loads(_get(CBOE_URL.format(symbol=symbol), timeout=45, retries=2))
    d = data["data"]
    chain = OptionChain(symbol=symbol, spot=float(d["close"]))
    for o in d.get("options", []):
        m = OSI_RE.match(o.get("option", "").replace(" ", ""))
        if not m or m.group(3) != "C":
            continue
        iv = float(o.get("iv") or 0)
        bid, ask = float(o.get("bid") or 0), float(o.get("ask") or 0)
        if iv <= 0 or bid <= 0 or ask <= 0:
            continue
        yy, mm, dd = int(m.group(2)[:2]), int(m.group(2)[2:4]), int(m.group(2)[4:])
        expiry = date(2000 + yy, mm, dd)
        strike = int(m.group(4)) / 1000.0
        chain.call_ivs[(expiry, strike)] = iv
    return chain


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _interp_iv(chain: OptionChain, expiry: date, strike: float) -> float | None:
    pts = sorted((k, v) for (e, k), v in chain.call_ivs.items() if e == expiry)
    if len(pts) < 2:
        return None
    strikes = [k for k, _ in pts]
    if strike <= strikes[0]:
        return pts[0][1]
    if strike >= strikes[-1]:
        return pts[-1][1]
    for (k0, v0), (k1, v1) in zip(pts, pts[1:]):
        if k0 <= strike <= k1:
            w = (strike - k0) / (k1 - k0) if k1 > k0 else 0.0
            return v0 + w * (v1 - v0)
    return None


@dataclass
class BlResult:
    prob_above: float
    iv: float
    t_years: float
    detail: dict = field(default_factory=dict)


def prob_above(chain: OptionChain, expiry: date, strike: float,
               asof: date | None = None) -> BlResult | None:
    """risk-neutral P(S_T > K) = N(d2), IV는 스마일 보간값. 데이터 부족 시 None."""
    asof = asof or date.today()
    t = max((expiry - asof).days, 1) / 365.0
    iv = _interp_iv(chain, expiry, strike)
    if iv is None or iv <= 0:
        return None
    d2 = ((math.log(chain.spot / strike) + (RISK_FREE - 0.5 * iv ** 2) * t)
          / (iv * math.sqrt(t)))
    return BlResult(
        prob_above=_norm_cdf(d2), iv=iv, t_years=round(t, 4),
        detail={"spot": chain.spot, "strike": strike, "expiry": expiry.isoformat(),
                "risk_free": RISK_FREE, "measure": "risk-neutral",
                "method": "iv-interp N(d2) (BL 디지털 근사)"})


def nearest_expiry(chain: OptionChain, target: date) -> date | None:
    """target 이후 가장 가까운 만기 (없으면 마지막 만기)."""
    exps = chain.expiries()
    if not exps:
        return None
    later = [e for e in exps if e >= target]
    return later[0] if later else exps[-1]


def proxy_strike(index_threshold: float, index_spot: float, proxy_spot: float) -> float:
    """지수 임계값 → 프록시(QQQ 등) 등가 행사가 — 단순 비율 매핑 (가정 명시 기록)."""
    return index_threshold / index_spot * proxy_spot
